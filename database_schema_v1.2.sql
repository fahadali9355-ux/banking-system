-- ============================================================================
-- Digital Banking Backend + Ops Automation — Database Schema (Postgres)
-- SMIT Hackathon Capstone | Version 1.2
-- v1.1 adds: account_closure_requests, interest_accrual_log,
-- fraud_pattern_matches, accounts.interest_rate, INTEREST transaction type
-- — closing gaps found against the 32-item capstone feature checklist.
--
-- v1.2 adds (closing a second round of 7 gaps found in cross-document review):
--   1. transaction_password_hash moves from accounts to account_holders, so a
--      JOINT_SIGNATURE transaction can attribute which holder approved it,
--      instead of every holder sharing one account-level secret.
--   2. transaction_challenge_codes — a short-lived, single-use code required
--      alongside the password on every transaction-execution request, so a
--      password captured from the customer's own Sent folder/forwarding
--      cannot be replayed on its own.
--   3. transaction_approval_requests — the same approval-record pattern as
--      account_closure_requests / holder_removal_requests, applied to a
--      single JOINT_SIGNATURE transaction's second-holder approval.
--   4. reactivation_requests — makes the previously-undefined "KYC-equivalent
--      re-verification" an explicit, auditable multi-step record.
--   5. users.phone is now the documented delivery channel for step-up OTPs
--      (fraud confirm-it-was-me, closure/removal approval, reactivation) —
--      independent of the email channel that carries the original request.
--   6. interest_accrual_log.skip_reason semantics clarified to run-time-only
--      evaluation (see TRD v1.2 Sec. 5); no column change, wording only.
--   7. Multi-account-per-sender disambiguation is handled by an n8n query
--      against account_holders, not a schema change; no new column here.
--
-- Design principles:
--   1. This schema is the single ledger of truth. Pinecone/LLM layers never
--      write here directly — only Python services and n8n-triggered writes do.
--   2. Money fields use NUMERIC(18,2), never FLOAT, to avoid rounding drift.
--   3. balance is intentionally NOT constrained to >= 0 (see FR-2.5: reversal
--      after funds are spent must still be allowed to go negative).
--   4. Every table that matters for compliance/audit has created_at as a
--      minimum, and several have full audit trails (see email_audit_log,
--      password_verification_log).
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------------------------------------------------------------------------
-- ENUM TYPES
-- ---------------------------------------------------------------------------
CREATE TYPE account_type_enum       AS ENUM ('SINGLE', 'JOINT', 'MINOR');
CREATE TYPE authority_type_enum     AS ENUM ('EITHER_OR', 'JOINT_SIGNATURE', 'MAJORITY_VOTE');
CREATE TYPE account_status_enum     AS ENUM ('ACTIVE', 'SUSPENDED', 'PENDING_VERIFICATION', 'CLOSED');
CREATE TYPE holder_role_enum        AS ENUM ('PRIMARY', 'SECONDARY', 'GUARDIAN', 'MINOR');
CREATE TYPE holder_permission_enum  AS ENUM ('FULL', 'VIEW_ONLY');
CREATE TYPE holder_status_enum      AS ENUM ('ACTIVE', 'PENDING_DISCLOSURE');
CREATE TYPE transaction_type_enum   AS ENUM ('DEBIT', 'CREDIT', 'TRANSFER_IN', 'TRANSFER_OUT', 'REVERSAL', 'INTEREST');
CREATE TYPE transaction_status_enum AS ENUM ('PENDING', 'COMPLETED', 'ROLLED_BACK', 'FAILED');
CREATE TYPE standing_order_status_enum AS ENUM ('ACTIVE', 'PAUSED', 'PERMANENTLY_FAILED', 'CANCELLED');
CREATE TYPE attempt_result_enum    AS ENUM ('SUCCESS', 'INSUFFICIENT_FUNDS', 'ERROR');
CREATE TYPE reconciliation_cause_enum AS ENUM ('DUPLICATE_ENTRY', 'ROUNDING_ERROR', 'TIMING_GAP', 'ORPHANED_ENTRY', 'UNKNOWN');
CREATE TYPE fraud_status_enum      AS ENUM ('HELD', 'CONFIRMED_LEGIT', 'CONFIRMED_FRAUD');
CREATE TYPE dispute_status_enum    AS ENUM ('OPEN', 'RESOLVED_UNANIMOUS', 'ESCALATED');
CREATE TYPE draft_status_enum      AS ENUM ('PENDING_APPROVAL', 'APPROVED', 'REJECTED');
CREATE TYPE removal_status_enum    AS ENUM ('PENDING', 'APPROVED', 'EXPIRED');
CREATE TYPE password_action_enum   AS ENUM ('TRANSACTION', 'STATEMENT');
CREATE TYPE password_result_enum   AS ENUM ('SUCCESS', 'FAILURE');
CREATE TYPE closure_status_enum    AS ENUM ('PENDING', 'APPROVED', 'ESCALATED', 'EXPIRED');
CREATE TYPE interest_skip_reason_enum AS ENUM ('NONE', 'NEGATIVE_BALANCE', 'SUSPENDED', 'ACCOUNT_CLOSED');
CREATE TYPE reactivation_status_enum AS ENUM ('PENDING_CHALLENGE', 'PENDING_STAFF_REVIEW', 'APPROVED', 'REJECTED');

-- ---------------------------------------------------------------------------
-- USERS — real people who can hold accounts
-- ---------------------------------------------------------------------------
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name       TEXT NOT NULL,
    email           TEXT NOT NULL UNIQUE,
    phone           TEXT,                                          -- step-up OTP delivery channel (fraud confirm, closure/removal approval, reactivation) — independent of email
    date_of_birth   DATE NOT NULL,
    kyc_verified    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- ACCOUNTS — the ledger of truth for account-level state
-- ---------------------------------------------------------------------------
CREATE TABLE accounts (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_type                account_type_enum NOT NULL,
    authority_type              authority_type_enum NOT NULL DEFAULT 'EITHER_OR',
    balance                     NUMERIC(18,2) NOT NULL DEFAULT 0,   -- may go negative, see FR-2.5
    status                      account_status_enum NOT NULL DEFAULT 'ACTIVE',
    statement_pdf_password_hash TEXT NOT NULL,                     -- distinct secret; account-level (statement delivery has one destination, not per-holder attribution)
    failed_password_attempts   INT NOT NULL DEFAULT 0,
    last_failed_attempt_at     TIMESTAMPTZ,
    transaction_threshold      NUMERIC(18,2),                      -- amount above which extra approval kicks in
    interest_rate              NUMERIC(6,4) NOT NULL DEFAULT 0,     -- annual rate, e.g. 0.0350 = 3.5%; 0 for MINOR by policy
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_accounts_status ON accounts(status);

-- ---------------------------------------------------------------------------
-- ACCOUNT_HOLDERS — junction table; even single-holder accounts use this
-- ---------------------------------------------------------------------------
CREATE TABLE account_holders (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id                  UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    user_id                     UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    role                        holder_role_enum NOT NULL,
    permission                  holder_permission_enum NOT NULL DEFAULT 'FULL',
    transaction_password_hash   TEXT NOT NULL,                      -- v1.2: moved from accounts — per-holder secret, so a JOINT_SIGNATURE request is attributable to the holder who sent it (bcrypt/argon2; never logged in plaintext)
    debt_disclosure_accepted_at TIMESTAMPTZ,                        -- required before rights activate on debt-carrying accounts
    status                      holder_status_enum NOT NULL DEFAULT 'ACTIVE',
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(account_id, user_id)
);
CREATE INDEX idx_account_holders_account ON account_holders(account_id);
CREATE INDEX idx_account_holders_user ON account_holders(user_id);

-- ---------------------------------------------------------------------------
-- TRANSACTIONS — append-only ledger; source of truth for balance
-- ---------------------------------------------------------------------------
CREATE TABLE transactions (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id            UUID NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    related_transaction_id UUID REFERENCES transactions(id),        -- links a reversal to its original
    amount                NUMERIC(18,2) NOT NULL,
    type                  transaction_type_enum NOT NULL,
    status                transaction_status_enum NOT NULL DEFAULT 'PENDING',
    idempotency_key       TEXT NOT NULL UNIQUE,
    description           TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_transactions_account ON transactions(account_id);
CREATE INDEX idx_transactions_created ON transactions(created_at);

-- ---------------------------------------------------------------------------
-- IDEMPOTENCY_KEYS — supports FR-2.1 (duplicate submission protection)
-- ---------------------------------------------------------------------------
CREATE TABLE idempotency_keys (
    key             TEXT PRIMARY KEY,
    request_hash    TEXT NOT NULL,
    response_payload JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- STANDING_ORDERS — scheduled payments, with optimistic locking
-- ---------------------------------------------------------------------------
CREATE TABLE standing_orders (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id            UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    beneficiary_account_id UUID REFERENCES accounts(id),
    amount                NUMERIC(18,2) NOT NULL,
    schedule_day          INT NOT NULL,                             -- day-of-month, adjusted for weekends/holidays at runtime
    status                standing_order_status_enum NOT NULL DEFAULT 'ACTIVE',
    version               INT NOT NULL DEFAULT 0,                   -- optimistic lock, see FR-3.4
    retry_count           INT NOT NULL DEFAULT 0,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE standing_order_attempts (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    standing_order_id UUID NOT NULL REFERENCES standing_orders(id) ON DELETE CASCADE,
    attempted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    result            attempt_result_enum NOT NULL
);

-- ---------------------------------------------------------------------------
-- RECONCILIATION_FLAGS — nightly ledger vs. balance mismatches (never auto-fixed)
-- ---------------------------------------------------------------------------
CREATE TABLE reconciliation_flags (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id        UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    ledger_sum        NUMERIC(18,2) NOT NULL,
    reported_balance  NUMERIC(18,2) NOT NULL,
    discrepancy       NUMERIC(18,2) GENERATED ALWAYS AS (reported_balance - ledger_sum) STORED,
    likely_cause      reconciliation_cause_enum NOT NULL DEFAULT 'UNKNOWN',
    resolved          BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_by       UUID REFERENCES users(id),
    resolved_at       TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- FRAUD_FLAGS — holds + explainability
-- ---------------------------------------------------------------------------
CREATE TABLE fraud_flags (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id  UUID NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    score           NUMERIC(6,3) NOT NULL,
    status          fraud_status_enum NOT NULL DEFAULT 'HELD',
    explanation     TEXT,                                           -- plain-language reason (LLM-generated, redacted input)
    otp_confirmed_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- DISPUTES — joint-account disputes require unanimous holder input
-- ---------------------------------------------------------------------------
CREATE TABLE disputes (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id       UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    transaction_id   UUID NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    holder_responses JSONB NOT NULL DEFAULT '{}',                   -- { holder_id: "accept"|"reject" }
    status           dispute_status_enum NOT NULL DEFAULT 'OPEN',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at      TIMESTAMPTZ
);

-- ---------------------------------------------------------------------------
-- DRAFT_RESPONSES — RAG output; never sent without human approval
-- ---------------------------------------------------------------------------
CREATE TABLE draft_responses (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id    TEXT NOT NULL,
    account_id   UUID REFERENCES accounts(id),
    draft_text   TEXT NOT NULL,
    explanation  TEXT,                                              -- why the model drafted this reply
    status       draft_status_enum NOT NULL DEFAULT 'PENDING_APPROVAL',
    reviewed_by  UUID REFERENCES users(id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- HOLDER_REMOVAL_REQUESTS — mutual consent workflow (FR-1.4)
-- ---------------------------------------------------------------------------
CREATE TABLE holder_removal_requests (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id        UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    target_holder_id  UUID NOT NULL REFERENCES account_holders(id) ON DELETE CASCADE,
    approvals         JSONB NOT NULL DEFAULT '{}',                  -- { holder_id: true/false }
    status            removal_status_enum NOT NULL DEFAULT 'PENDING',
    expires_at        TIMESTAMPTZ NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- ACCOUNT_CLOSURE_REQUESTS — mirrors holder_removal_requests pattern; used
-- for FR-1.9 (unanimous consent required, disputed closure escalates)
-- ---------------------------------------------------------------------------
CREATE TABLE account_closure_requests (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id    UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    initiated_by  UUID NOT NULL REFERENCES users(id),
    approvals     JSONB NOT NULL DEFAULT '{}',                     -- { holder_id: true/false }
    status        closure_status_enum NOT NULL DEFAULT 'PENDING',
    expires_at    TIMESTAMPTZ NOT NULL,                            -- decision window; unresolved-at-expiry escalates
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at   TIMESTAMPTZ
);
CREATE INDEX idx_closure_requests_account ON account_closure_requests(account_id);

-- ---------------------------------------------------------------------------
-- TRANSACTION_APPROVAL_REQUESTS — v1.2: second-holder sign-off for a single
-- transaction on a JOINT_SIGNATURE account. Same approval-record pattern as
-- account_closure_requests / holder_removal_requests (design principle in
-- Sec. 1), reused rather than reinvented (FR-1.11).
-- ---------------------------------------------------------------------------
CREATE TABLE transaction_approval_requests (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id        UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    idempotency_key   TEXT NOT NULL,                               -- ties this approval to the pending transaction request
    initiated_by      UUID NOT NULL REFERENCES account_holders(id),
    approvals         JSONB NOT NULL DEFAULT '{}',                 -- { holder_id: true/false }
    status            closure_status_enum NOT NULL DEFAULT 'PENDING', -- reuses PENDING/APPROVED/ESCALATED/EXPIRED
    expires_at        TIMESTAMPTZ NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at       TIMESTAMPTZ
);
CREATE INDEX idx_txn_approval_account ON transaction_approval_requests(account_id);

-- ---------------------------------------------------------------------------
-- TRANSACTION_CHALLENGE_CODES — v1.2: short-lived single-use code required
-- alongside the transaction password on every sensitive-action email, so a
-- password alone (captured from the customer's own Sent folder/forwarding)
-- cannot be replayed (FR-6.10). Issued per-thread, not per-account, so a
-- captured code cannot be reused on a different request.
-- ---------------------------------------------------------------------------
CREATE TABLE transaction_challenge_codes (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id    UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    thread_id     TEXT NOT NULL,                                   -- Gmail thread the code was issued into
    code_hash     TEXT NOT NULL,
    expires_at    TIMESTAMPTZ NOT NULL,                            -- 5-minute validity window
    used_at       TIMESTAMPTZ,                                     -- NULL until consumed; single-use
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_challenge_codes_account ON transaction_challenge_codes(account_id, thread_id);

-- ---------------------------------------------------------------------------
-- REACTIVATION_REQUESTS — v1.2: makes the previously-unspecified "KYC-
-- equivalent re-verification" (FR-6.6) an explicit, auditable record —
-- identity-challenge answers plus a phone OTP, both required before the
-- request even reaches the staff review queue (FR-6.11).
-- ---------------------------------------------------------------------------
CREATE TABLE reactivation_requests (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id              UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    identity_challenge_passed BOOLEAN NOT NULL DEFAULT FALSE,      -- name/DOB/last-transaction-amount knowledge check
    phone_otp_verified_at   TIMESTAMPTZ,                           -- NULL until the phone OTP step succeeds
    status                  reactivation_status_enum NOT NULL DEFAULT 'PENDING_CHALLENGE',
    reviewed_by             UUID REFERENCES users(id),             -- staff member; only a human sets APPROVED/REJECTED
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at             TIMESTAMPTZ
);
CREATE INDEX idx_reactivation_account ON reactivation_requests(account_id);

-- ---------------------------------------------------------------------------
-- INTEREST_ACCRUAL_LOG — one row per account per accrual run, incl. skips
-- (Core Infra: "Python services for interest calculation")
-- ---------------------------------------------------------------------------
CREATE TABLE interest_accrual_log (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id       UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    period_start     DATE NOT NULL,
    period_end       DATE NOT NULL,
    rate_applied     NUMERIC(6,4) NOT NULL,
    amount_credited  NUMERIC(18,2) NOT NULL DEFAULT 0,
    transaction_id   UUID REFERENCES transactions(id),             -- NULL when skipped
    skipped          BOOLEAN NOT NULL DEFAULT FALSE,
    skip_reason      interest_skip_reason_enum NOT NULL DEFAULT 'NONE',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_interest_log_account ON interest_accrual_log(account_id, period_start);

-- ---------------------------------------------------------------------------
-- FRAUD_PATTERN_MATCHES — links a fraud_flags row to the Pinecone
-- fraud-pattern lookup that contributed to (or was checked for) its score
-- (Core Infra: "Pinecone index for ... fraud-pattern semantic search")
-- ---------------------------------------------------------------------------
CREATE TABLE fraud_pattern_matches (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fraud_flag_id          UUID NOT NULL REFERENCES fraud_flags(id) ON DELETE CASCADE,
    pinecone_match_id      TEXT NOT NULL,
    similarity_score       NUMERIC(5,4) NOT NULL,
    matched_pattern_summary TEXT,                                  -- plain-language summary of the matched historical case
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_fraud_pattern_flag ON fraud_pattern_matches(fraud_flag_id);

-- ---------------------------------------------------------------------------
-- PASSWORD_VERIFICATION_LOG — every password check, pass or fail
-- ---------------------------------------------------------------------------
CREATE TABLE password_verification_log (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id        UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    account_holder_id UUID REFERENCES account_holders(id),         -- v1.2: which holder's password was checked (per-holder secrets); NULL for statement_pdf_password_hash checks, which remain account-level
    action_type       password_action_enum NOT NULL,
    result            password_result_enum NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_pw_log_account ON password_verification_log(account_id, created_at);

-- ---------------------------------------------------------------------------
-- EMAIL_AUDIT_LOG — every inbound/outbound email event
-- ---------------------------------------------------------------------------
CREATE TABLE email_audit_log (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id         TEXT NOT NULL,
    sender_email      TEXT NOT NULL,
    account_id        UUID REFERENCES accounts(id),
    intent            TEXT,
    action_taken      TEXT,
    redaction_applied BOOLEAN NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_email_audit_thread ON email_audit_log(thread_id);

-- ============================================================================
-- End of schema
-- ============================================================================
