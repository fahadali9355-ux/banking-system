import uuid
import base64
import io
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from app.db import db

async def generate_statement(req):
    req_id = str(uuid.uuid4())
    
    start_date = datetime.strptime(req.period_start, "%Y-%m-%d")
    end_date = datetime.strptime(req.period_end, "%Y-%m-%d")
    
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT created_at, type, amount, description FROM transactions
            WHERE account_id = $1::uuid AND created_at >= $2 AND created_at <= $3
            ORDER BY created_at ASC
        """, req.account_id, start_date, end_date)
        
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, 750, f"Account Statement: {req.account_id}")
    c.setFont("Helvetica", 12)
    c.drawString(50, 730, f"Period: {req.period_start} to {req.period_end}")
    
    if not rows:
        c.drawString(50, 690, "No activity in this period")
    else:
        y = 690
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y, "Date")
        c.drawString(150, y, "Type")
        c.drawString(250, y, "Amount")
        c.drawString(350, y, "Description")
        c.setFont("Helvetica", 12)
        y -= 20
        
        for row in rows:
            c.drawString(50, y, str(row['created_at'].date()))
            c.drawString(150, y, row['type'])
            c.drawString(250, y, str(row['amount']))
            desc = row['description'] or ""
            c.drawString(350, y, desc[:30])
            y -= 20
            if y < 50:
                c.showPage()
                y = 750
                
    c.save()
    pdf_bytes = buffer.getvalue()
    pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
    
    # TODO: Encrypt the PDF with a password. 
    # In production this needs its own secure secret store, not derived from the hash.
    # For now, we are simplifying by NOT encrypting yet per hackathon instructions.
    
    period_str = req.period_start[:7] # YYYY-MM
    filename = f"statement_{period_str}.pdf"
    
    return {
        "request_id": req_id,
        "pdf_base64": pdf_base64,
        "filename": filename
    }
