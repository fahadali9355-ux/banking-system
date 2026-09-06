# Digital Banking Backend + Ops Automation

## Local Setup

1. Create a virtual environment:
   ```bash
   python -m venv venv
   venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Create a `.env` file based on `.env.example`:
   ```bash
   DATABASE_URL=postgresql://user:pass@host:port/dbname
   ```

4. Run the server:
   ```bash
   uvicorn app.main:app --reload
   ```

## Mapping to n8n
Set the `PYTHON_SERVICES_BASE_URL` variable in your n8n environment to point to this service's base URL (e.g. `http://localhost:8000`). n8n will append the paths defined in the contract (e.g. `/auth/verify-password`).
