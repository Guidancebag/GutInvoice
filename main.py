"""
GutInvoice — Every Invoice has a Voice
v16.1 — FIXED: TwiML responses | Threading | Hi greeting | Supabase resilience
===================================================================================
SINGLE FILE — no pdf_generators.py needed.

ALL PDF FORMATS UNCHANGED from v16.
FIXES IN v16.1:
  ✅ TwiML used for all text responses (works even if Twilio REST API fails)
  ✅ Background threading for voice note processing (no webhook timeout)
  ✅ "Hi / Hello / Hey" greeting handler restored (shows full menu)
  ✅ Supabase errors non-fatal — never cause silent failure
  ✅ Error handler always returns TwiML (user ALWAYS gets a response)
  ✅ save_invoice gracefully skips unknown columns

SAME ENV VARS AS v16:
  TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER
  SARVAM_API_KEY, CLAUDE_API_KEY (or ANTHROPIC_API_KEY)
  SUPABASE_URL, SUPABASE_KEY

SUPABASE SQL (run once if new columns missing):
  ALTER TABLE invoices ADD COLUMN IF NOT EXISTS is_cancelled BOOLEAN DEFAULT FALSE;
  ALTER TABLE invoices ADD COLUMN IF NOT EXISTS credit_note_for TEXT;
  ALTER TABLE invoices ADD COLUMN IF NOT EXISTS taxable_value NUMERIC DEFAULT 0;
  ALTER TABLE invoices ADD COLUMN IF NOT EXISTS cgst NUMERIC DEFAULT 0;
  ALTER TABLE invoices ADD COLUMN IF NOT EXISTS sgst NUMERIC DEFAULT 0;
  ALTER TABLE invoices ADD COLUMN IF NOT EXISTS igst NUMERIC DEFAULT 0;
  ALTER TABLE invoices ADD COLUMN IF NOT EXISTS cgst_rate NUMERIC DEFAULT 0;
  ALTER TABLE invoices ADD COLUMN IF NOT EXISTS sgst_rate NUMERIC DEFAULT 0;
  ALTER TABLE invoices ADD COLUMN IF NOT EXISTS igst_rate NUMERIC DEFAULT 0;
  ALTER TABLE invoices ADD COLUMN IF NOT EXISTS invoice_date TEXT;
"""

# ═══════════════════════════════════════════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════════════════════════════════════════
import os, io, json, logging, re, requests, threading
from urllib.parse import quote as url_quote
from datetime import datetime
from flask import Flask, request, Response, render_template_string
from twilio.rest import Client as TwilioClient
from twilio.twiml.messaging_response import MessagingResponse
import anthropic

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)
app = Flask(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# BASIC HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def env(key, default=""):
    return os.environ.get(key, default)

def get_twilio():
    return TwilioClient(env("TWILIO_ACCOUNT_SID"), env("TWILIO_AUTH_TOKEN"))

def get_claude():
    return anthropic.Anthropic(api_key=env("CLAUDE_API_KEY") or env("ANTHROPIC_API_KEY"))

def safe_json(response, label):
    """Parse JSON — returns None on failure (never raises)"""
    raw = (response.text or "").strip()
    log.info(f"[{label}] HTTP {response.status_code} | {raw[:120]}")
    if not raw:
        log.warning(f"[{label}] empty response")
        return None
    try:
        return json.loads(raw)
    except Exception:
        log.warning(f"[{label}] non-JSON: {raw[:120]}")
        return None

def fmt(val):
    try:   return f"{float(val):,.2f}"
    except: return "0.00"

def fmt_i(val):
    try:
        v = float(val)
        return str(int(v)) if v == int(v) else str(v)
    except: return "0"

# ═══════════════════════════════════════════════════════════════════════════════
# TWIML + REST HELPERS  ← KEY FIX: TwiML needs no credentials, always works
# ═══════════════════════════════════════════════════════════════════════════════

def twiml_reply(text):
    """HTTP response back to Twilio — most reliable, no REST API credentials needed"""
    r = MessagingResponse()
    r.message(str(text))
    return str(r), 200, {"Content-Type": "text/xml"}

def twiml_empty():
    """Empty TwiML — real response sent via send_rest() in background"""
    return str(MessagingResponse()), 200, {"Content-Type": "text/xml"}

def send_rest(to, body, pdf_url=None):
    """Send via Twilio REST API — only required when attaching a PDF"""
    try:
        kw = {"from_": env("TWILIO_FROM_NUMBER"), "to": to, "body": str(body)}
        if pdf_url:
            kw["media_url"] = [pdf_url]
        get_twilio().messages.create(**kw)
        log.info(f"REST send OK → {to}")
        return True
    except Exception as e:
        log.error(f"REST send FAILED → {to}: {e}")
        if pdf_url:
            try:
                get_twilio().messages.create(
                    from_=env("TWILIO_FROM_NUMBER"), to=to,
                    body=str(body) + f"\n\n📎 PDF: {pdf_url}"
                )
            except Exception as e2:
                log.error(f"REST fallback also failed: {e2}")
        return False

# ═══════════════════════════════════════════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════════════════════════════════════════
import os, io, json, logging, re, requests
from datetime import datetime
from flask import Flask, request, Response, render_template_string
from twilio.rest import Client as TwilioClient
import anthropic

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)
app = Flask(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# BASIC HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def env(key, default=""):
    return os.environ.get(key, default)

def get_twilio():
    return TwilioClient(env("TWILIO_ACCOUNT_SID"), env("TWILIO_AUTH_TOKEN"))

def get_claude():
    api_key = env("CLAUDE_API_KEY") or env("ANTHROPIC_API_KEY")
    return anthropic.Anthropic(api_key=api_key)

def safe_json(response, label):
    raw = response.text.strip()
    log.info(f"[{label}] HTTP {response.status_code} | {raw[:200]}")
    if not raw:
        raise Exception(f"{label} empty response (HTTP {response.status_code})")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise Exception(f"{label} non-JSON (HTTP {response.status_code}): {raw[:200]} | {e}")

def fmt(val):
    try:
        return f"{float(val):,.2f}"
    except Exception:
        return "0.00"

def fmt_i(val):
    try:
        v = float(val)
        return str(int(v)) if v == int(v) else str(v)
    except Exception:
        return "0"

# ═══════════════════════════════════════════════════════════════════════════════
# PDF STYLES & CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

M      = 15 * mm
PAGE_W = A4[0] - 2 * M
TEAL   = colors.HexColor("#006B6B")
ORANGE = colors.HexColor("#FF6B35")
DARK   = colors.HexColor("#1A1A2E")
LGRAY  = colors.HexColor("#F5F5F5")
RED    = colors.HexColor("#CC0000")
WHITE  = colors.white
SS     = getSampleStyleSheet()

def _s(name, **kw):
    return ParagraphStyle(name=name, parent=SS["Normal"], **kw)

ST = {
    "doc_title": _s("doc_title", fontSize=15, fontName="Helvetica-Bold",
                    textColor=WHITE, alignment=TA_CENTER),
    "sec_hdr":   _s("sec_hdr",  fontSize=8,  fontName="Helvetica-Bold",
                    textColor=WHITE, alignment=TA_CENTER),
    "body":      _s("body",     fontSize=8,  textColor=DARK, leading=12),
    "body_b":    _s("body_b",   fontSize=8,  fontName="Helvetica-Bold", textColor=DARK),
    "body_r":    _s("body_r",   fontSize=8,  textColor=DARK, alignment=TA_RIGHT, leading=12),
    "grand_l":   _s("grand_l",  fontSize=9,  fontName="Helvetica-Bold", textColor=DARK),
    "grand_r":   _s("grand_r",  fontSize=9,  fontName="Helvetica-Bold", textColor=DARK,
                    alignment=TA_RIGHT),
    "th":        _s("th",       fontSize=8,  fontName="Helvetica-Bold",
                    textColor=WHITE, alignment=TA_CENTER),
    "td_c":      _s("td_c",     fontSize=8,  textColor=DARK, alignment=TA_CENTER, leading=11),
    "td_l":      _s("td_l",     fontSize=8,  textColor=DARK, alignment=TA_LEFT,   leading=11),
    "td_r":      _s("td_r",     fontSize=8,  textColor=DARK, alignment=TA_RIGHT,  leading=11),
    "fn1":       _s("fn1",      fontSize=7,  textColor=WHITE, alignment=TA_CENTER, leading=10),
    "fn2":       _s("fn2",      fontSize=6,  textColor=ORANGE, alignment=TA_CENTER,
                    leading=9, fontName="Helvetica-Oblique"),
    "red_b":     _s("red_b",    fontSize=8,  fontName="Helvetica-Bold", textColor=RED),
    "red_r":     _s("red_r",    fontSize=8,  fontName="Helvetica-Bold", textColor=RED,
                    alignment=TA_RIGHT),
    "small_c":   _s("small_c",  fontSize=7,  textColor=colors.grey,
                    alignment=TA_CENTER, leading=9),
}

def p(text, style="body"):
    return Paragraph(str(text) if text is not None else "", ST[style])

def sp(h=4):
    return Spacer(1, h * mm)

# ═══════════════════════════════════════════════════════════════════════════════
# PDF SHARED COMPONENTS
# ═══════════════════════════════════════════════════════════════════════════════

def doc_header(title):
    """Full-width teal header — centered bold title"""
    t = Table([[p(title, "doc_title")]], colWidths=[PAGE_W], rowHeights=[11 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), TEAL),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t

def _inner_box(rows, width):
    t = Table(rows, colWidths=[width])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), TEAL),
        ("BACKGROUND",    (0, 1), (-1, -1), LGRAY),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("BOX",           (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("INNERGRID",     (0, 1), (-1, -1), 0.2, colors.lightgrey),
    ]))
    return t

def seller_invoice_section(d, show_gstin=True, show_reverse=True,
                            right_lbl="INVOICE DETAILS", no_lbl="Invoice No"):
    """
    Two-column block matching all docx templates:
    Left  = SELLER DETAILS
    Right = INVOICE DETAILS (or CREDIT NOTE DETAILS)
    """
    LW = PAGE_W * 0.52
    RW = PAGE_W * 0.48

    left_rows = [
        [p("SELLER DETAILS", "sec_hdr")],
        [p(f"<b>Business Name:</b> {d.get('seller_name','')}", "body")],
        [p(f"<b>Address:</b> {d.get('seller_address','')}", "body")],
    ]
    if show_gstin:
        left_rows.append([p(f"<b>GSTIN:</b> {d.get('seller_gstin','')}", "body")])

    inv_date_lbl = "Credit Note Date" if "CREDIT" in right_lbl.upper() else "Invoice Date"
    right_rows = [
        [p(right_lbl, "sec_hdr")],
        [p(f"<b>{no_lbl}:</b> {d.get('invoice_number','')}", "body")],
        [p(f"<b>{inv_date_lbl}:</b> {d.get('invoice_date', datetime.now().strftime('%d/%m/%Y'))}", "body")],
        [p(f"<b>Place of Supply:</b> {d.get('place_of_supply','')}", "body")],
    ]
    if show_reverse:
        right_rows.append([p(f"<b>Reverse Charge:</b> {d.get('reverse_charge','No')}", "body")])

    outer = Table(
        [[_inner_box(left_rows, LW - 3), _inner_box(right_rows, RW - 3)]],
        colWidths=[LW, RW]
    )
    outer.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return outer

def bill_to_section(d, show_gstin=True):
    """Full-width BILL TO box"""
    rows = [
        [p("BILL TO (CUSTOMER DETAILS)", "sec_hdr")],
        [p(f"<b>Name:</b> {d.get('customer_name','')}", "body")],
        [p(f"<b>Address:</b> {d.get('customer_address','')}", "body")],
    ]
    if show_gstin and d.get("customer_gstin"):
        rows.append([p(f"<b>GSTIN:</b> {d.get('customer_gstin','')}", "body")])
    t = Table(rows, colWidths=[PAGE_W])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), TEAL),
        ("BACKGROUND",    (0, 1), (-1, -1), LGRAY),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("BOX",           (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("INNERGRID",     (0, 1), (-1, -1), 0.2, colors.lightgrey),
    ]))
    return t

def items_table_7col(items):
    """
    7-column items table matching all 3 docx templates:
    # | Description | HSN/SAC | Qty | Unit | Rate (₹) | Amount (₹)
    """
    CW = [PAGE_W * w for w in [0.05, 0.33, 0.12, 0.08, 0.08, 0.16, 0.18]]
    data = [[p("#","th"), p("Description","th"), p("HSN/SAC","th"),
             p("Qty","th"), p("Unit","th"), p("Rate (₹)","th"), p("Amount (₹)","th")]]
    for it in items:
        data.append([
            p(str(it.get("sno","1")),          "td_c"),
            p(str(it.get("description","")),    "td_l"),
            p(str(it.get("hsn_sac","")),        "td_c"),
            p(fmt(it.get("qty", 0)),             "td_r"),
            p(str(it.get("unit","Nos")),         "td_c"),
            p(f"₹ {fmt(it.get('rate',0))}",      "td_r"),
            p(f"₹ {fmt(it.get('amount',0))}",    "td_r"),
        ])
    t = Table(data, colWidths=CW, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), TEAL),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, LGRAY]),
        ("BOX",           (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t

def totals_box(rows):
    """Right-aligned totals block with grand total highlighted"""
    t = Table(rows, colWidths=[PAGE_W * 0.70, PAGE_W * 0.30])
    t.setStyle(TableStyle([
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
        ("ALIGN",         (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE",     (0, -1), (-1, -1), 1.2, TEAL),
        ("LINEBELOW",     (0, -1), (-1, -1), 1.5, TEAL),
        ("BACKGROUND",    (0, -1), (-1, -1), LGRAY),
    ]))
    return t

def declaration_two_col(declaration, payment_terms):
    """Two-column DECLARATION | PAYMENT TERMS — used in Tax Invoice"""
    t = Table(
        [[p("<b>DECLARATION</b>", "body_b"), p("<b>PAYMENT TERMS</b>", "body_b")],
         [p(declaration, "body"),            p(payment_terms, "body")]],
        colWidths=[PAGE_W * 0.60, PAGE_W * 0.40]
    )
    t.setStyle(TableStyle([
        ("BOX",           (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("BACKGROUND",    (0, 0), (-1, 0), LGRAY),
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    return t

def declaration_single(title, declaration, payment_terms):
    """Single-box declaration — used in Bill of Supply and Non-GST Invoice"""
    t = Table(
        [[p(title, "body_b")],
         [p(declaration, "body")],
         [p(f"<b>Payment Terms:</b> {payment_terms}", "body")]],
        colWidths=[PAGE_W]
    )
    t.setStyle(TableStyle([
        ("BOX",           (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("BACKGROUND",    (0, 0), (-1, 0), LGRAY),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
    ]))
    return t

def signatory_block(seller_name):
    """For {seller} / Authorised Signatory — right aligned"""
    t1 = Table(
        [[p(""), p(f"<b>For {seller_name}</b>", "body")]],
        colWidths=[PAGE_W * 0.55, PAGE_W * 0.45]
    )
    t1.setStyle(TableStyle([
        ("TOPPADDING",    (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("ALIGN",         (1, 0), (1, 0), "RIGHT"),
    ]))
    t2 = Table(
        [[p(""), p("Authorised Signatory", "body")]],
        colWidths=[PAGE_W * 0.55, PAGE_W * 0.45]
    )
    t2.setStyle(TableStyle([
        ("TOPPADDING",    (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ALIGN",         (1, 0), (1, 0), "RIGHT"),
        ("LINEABOVE",     (1, 0), (1, 0), 0.5, colors.lightgrey),
    ]))
    return [t1, t2]

def footer_elems():
    t = Table(
        [[p("Powered by GutInvoice, Every Invoice has a voice !!", "fn1")],
         [p("Developed by Tallbag Advisory and Tech Solutions Private Limited  |  Contact: +91 7702424946", "fn1")],
         [p("Disclaimer: Double check the Invoice details generated before sharing to anyone. GutInvoice is not responsible for any errors.", "fn2")]],
        colWidths=[PAGE_W]
    )
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (0, 1), TEAL),
        ("BACKGROUND",    (0, 2), (0, 2), colors.HexColor("#FFF3EE")),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("BOX",           (0, 2), (-1, 2), 0.3, ORANGE),
    ]))
    return [sp(5), t]

def num_words(amount):
    ones = ["","One","Two","Three","Four","Five","Six","Seven","Eight","Nine",
            "Ten","Eleven","Twelve","Thirteen","Fourteen","Fifteen","Sixteen",
            "Seventeen","Eighteen","Nineteen"]
    tens = ["","","Twenty","Thirty","Forty","Fifty","Sixty","Seventy","Eighty","Ninety"]
    def _w(n):
        if n < 20:    return ones[n]
        elif n < 100: return tens[n//10] + (" " + ones[n%10] if n%10 else "")
        elif n < 1000:  return ones[n//100]+" Hundred"+(" and "+_w(n%100) if n%100 else "")
        elif n < 100000: return _w(n//1000)+" Thousand"+(" "+_w(n%1000) if n%1000 else "")
        elif n < 10000000: return _w(n//100000)+" Lakh"+(" "+_w(n%100000) if n%100000 else "")
        else: return _w(n//10000000)+" Crore"+(" "+_w(n%10000000) if n%10000000 else "")
    try:
        n = int(float(amount))
        return "Zero Rupees Only" if n==0 else _w(n)+" Rupees Only"
    except Exception:
        return ""

def _new_doc(buf):
    return SimpleDocTemplate(buf, pagesize=A4,
                             leftMargin=M, rightMargin=M,
                             topMargin=M, bottomMargin=M)

# ═══════════════════════════════════════════════════════════════════════════════
# BUILDER 1: TAX INVOICE  (matches 438394e... docx template)
# ═══════════════════════════════════════════════════════════════════════════════

def build_tax_invoice(d: dict) -> bytes:
    buf = io.BytesIO()
    doc = _new_doc(buf)
    el  = []

    el.append(doc_header("TAX INVOICE"))
    el.append(sp(2))
    el.append(seller_invoice_section(d, show_gstin=True, show_reverse=True))
    el.append(sp(2))
    el.append(bill_to_section(d, show_gstin=True))
    el.append(sp(3))
    el.append(items_table_7col(d.get("items", [])))
    el.append(sp(2))

    cr  = float(d.get("cgst_rate", 0))
    sr  = float(d.get("sgst_rate", 0))
    ir  = float(d.get("igst_rate", 0))
    inter = str(d.get("is_interstate","false")).lower() == "true"
    tr = [[p("Taxable Value","body"), p(f"₹ {fmt(d.get('taxable_value',0))}","body_r")]]
    if inter:
        tr.append([p(f"IGST @ {fmt_i(ir)}%","body"), p(f"₹ {fmt(d.get('igst',0))}","body_r")])
    else:
        tr.append([p(f"CGST @ {fmt_i(cr)}%","body"), p(f"₹ {fmt(d.get('cgst',0))}","body_r")])
        tr.append([p(f"SGST @ {fmt_i(sr)}%","body"), p(f"₹ {fmt(d.get('sgst',0))}","body_r")])
    tr.append([p("GRAND TOTAL","grand_l"), p(f"₹ {fmt(d.get('total_amount',0))}","grand_r")])
    el.append(totals_box(tr))
    el.append(sp(2))
    el.append(p(f"<b>Amount in Words:</b> {num_words(d.get('total_amount',0))}", "body"))
    el.append(sp(3))
    el.append(declaration_two_col(
        d.get("declaration","We declare that this invoice shows the actual price of the goods/services described and all particulars are true and correct."),
        d.get("payment_terms","Pay within 30 days")
    ))
    el.append(sp(2))
    el.extend(signatory_block(d.get("seller_name","")))
    el.extend(footer_elems())
    doc.build(el)
    return buf.getvalue()

# ═══════════════════════════════════════════════════════════════════════════════
# BUILDER 2: BILL OF SUPPLY  (matches 84a93a7... docx template)
# ═══════════════════════════════════════════════════════════════════════════════

def build_bill_of_supply(d: dict) -> bytes:
    buf = io.BytesIO()
    doc = _new_doc(buf)
    el  = []

    el.append(doc_header("BILL OF SUPPLY"))
    el.append(sp(2))
    el.append(seller_invoice_section(d, show_gstin=True, show_reverse=True))
    el.append(sp(2))
    el.append(bill_to_section(d, show_gstin=False))   # No GSTIN for BOS customer
    el.append(sp(3))
    el.append(items_table_7col(d.get("items", [])))
    el.append(sp(2))
    tr = [
        [p("Sub Total","body"),    p(f"₹ {fmt(d.get('taxable_value',0))}","body_r")],
        [p("GRAND TOTAL","grand_l"), p(f"₹ {fmt(d.get('total_amount',0))}","grand_r")],
    ]
    el.append(totals_box(tr))
    el.append(sp(2))
    el.append(p(f"<b>Amount in Words:</b> {num_words(d.get('total_amount',0))}", "body"))
    el.append(sp(3))
    el.append(declaration_single(
        "DECLARATION (MANDATORY FOR COMPOSITION DEALERS)",
        d.get("declaration","Composition taxable person, not eligible to collect tax on supplies."),
        d.get("payment_terms","Pay within 15 days")
    ))
    el.append(sp(2))
    el.extend(signatory_block(d.get("seller_name","")))
    el.extend(footer_elems())
    doc.build(el)
    return buf.getvalue()

# ═══════════════════════════════════════════════════════════════════════════════
# BUILDER 3: INVOICE (Non-GST)  (matches 94ecfd8... docx template)
# ═══════════════════════════════════════════════════════════════════════════════

def build_nongst_invoice(d: dict) -> bytes:
    buf = io.BytesIO()
    doc = _new_doc(buf)
    el  = []

    el.append(doc_header("INVOICE"))
    el.append(sp(2))
    el.append(seller_invoice_section(d, show_gstin=False, show_reverse=False))  # No GSTIN/RC
    el.append(sp(2))
    el.append(bill_to_section(d, show_gstin=False))
    el.append(sp(3))
    el.append(items_table_7col(d.get("items", [])))
    el.append(sp(2))
    tr = [
        [p("Sub Total","body"),       p(f"₹ {fmt(d.get('taxable_value',0))}","body_r")],
        [p("TOTAL AMOUNT","grand_l"), p(f"₹ {fmt(d.get('total_amount',0))}","grand_r")],
    ]
    el.append(totals_box(tr))
    el.append(sp(2))
    el.append(p(f"<b>Amount in Words:</b> {num_words(d.get('total_amount',0))}", "body"))
    el.append(sp(3))
    el.append(declaration_single(
        "DECLARATION",
        d.get("declaration","This is not a tax invoice. No GST has been charged."),
        d.get("payment_terms","Pay within 30 days")
    ))
    el.append(sp(2))
    el.extend(signatory_block(d.get("seller_name","")))
    el.extend(footer_elems())
    doc.build(el)
    return buf.getvalue()

# ═══════════════════════════════════════════════════════════════════════════════
# BUILDER 4: CREDIT NOTE  (matches sample_credit_note_v13.pdf)
# ═══════════════════════════════════════════════════════════════════════════════

def build_credit_note(d: dict) -> bytes:
    buf = io.BytesIO()
    doc = _new_doc(buf)
    el  = []

    el.append(doc_header("CREDIT NOTE"))
    el.append(sp(2))

    # Reference block (top summary — unique to credit notes)
    cn_no     = d.get("invoice_number") or d.get("credit_note_number","")
    cn_date   = d.get("invoice_date", datetime.now().strftime("%d/%m/%Y"))
    orig_no   = d.get("original_invoice_number","")
    orig_date = d.get("original_invoice_date","")
    reason    = d.get("reason") or d.get("credit_reason","Cancellation of invoice as requested by seller")

    ref = Table(
        [[p(f"<b>Credit Note No:</b> {cn_no}",    "body"),
          p(f"<b>Credit Note Date:</b> {cn_date}", "body")],
         [p(f"<b>Against Invoice No:</b> {orig_no}",       "body"),
          p(f"<b>Original Invoice Date:</b> {orig_date}",  "body")],
         [p(f"<b>Reason:</b> {reason}", "body"), p("","body")]],
        colWidths=[PAGE_W * 0.55, PAGE_W * 0.45]
    )
    ref.setStyle(TableStyle([
        ("BOX",           (0, 0), (-1, -1), 0.8, TEAL),
        ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#E8F5F5")),
        ("INNERGRID",     (0, 0), (-1, -1), 0.2, colors.lightgrey),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
    ]))
    el.append(ref)
    el.append(sp(2))

    el.append(seller_invoice_section(
        d, show_gstin=True, show_reverse=False,
        right_lbl="CREDIT NOTE DETAILS", no_lbl="Credit Note No"
    ))
    el.append(sp(2))
    el.append(bill_to_section(d, show_gstin=True))
    el.append(sp(3))
    el.append(items_table_7col(d.get("items", [])))
    el.append(sp(2))

    cr    = float(d.get("cgst_rate", 0))
    sr    = float(d.get("sgst_rate", 0))
    ir    = float(d.get("igst_rate", 0))
    inter = str(d.get("is_interstate","false")).lower() == "true"
    tr    = [[p("Taxable Value Reversed","body"),
              p(f"₹ {fmt(d.get('taxable_value',0))}","body_r")]]
    if inter:
        tr.append([p(f"IGST @ {fmt_i(ir)}% (Reversed)","red_b"),
                   p(f"(₹ {fmt(d.get('igst',0))})","red_r")])
    else:
        tr.append([p(f"CGST @ {fmt_i(cr)}% (Reversed)","red_b"),
                   p(f"(₹ {fmt(d.get('cgst',0))})","red_r")])
        tr.append([p(f"SGST @ {fmt_i(sr)}% (Reversed)","red_b"),
                   p(f"(₹ {fmt(d.get('sgst',0))})","red_r")])
    tr.append([p("TOTAL CREDIT AMOUNT","grand_l"),
               p(f"₹ {fmt(d.get('total_amount',0))}","grand_r")])
    el.append(totals_box(tr))
    el.append(sp(2))
    el.append(p(f"<b>Amount in Words:</b> {num_words(d.get('total_amount',0))}", "body"))
    el.append(sp(3))

    decl_text = d.get("declaration",
        "This Credit Note cancels and fully reverses the above mentioned invoice. "
        "The tax liability has been reduced accordingly. This document is valid for "
        "GST credit note purposes under Section 34 of CGST Act 2017.")
    decl_t = Table(
        [[p("DECLARATION","body_b")],
         [p(decl_text,"body")],
         [p(f"<b>Original Invoice:</b> {orig_no}  |  <b>Reason:</b> {reason}","body")]],
        colWidths=[PAGE_W]
    )
    decl_t.setStyle(TableStyle([
        ("BOX",           (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("BACKGROUND",    (0, 0), (-1, 0), LGRAY),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
    ]))
    el.append(decl_t)
    el.append(sp(2))
    el.extend(signatory_block(d.get("seller_name","")))
    el.extend(footer_elems())
    doc.build(el)
    return buf.getvalue()

# ═══════════════════════════════════════════════════════════════════════════════
# BUILDER 5: MONTHLY REPORT  (matches sample_monthly_report_v13.pdf)
# 5 Sections + Final Tax Liability Summary
# ═══════════════════════════════════════════════════════════════════════════════

def build_monthly_report(rep: dict) -> bytes:
    buf = io.BytesIO()
    doc = _new_doc(buf)
    el  = []

    month = rep.get("report_month","")
    year  = rep.get("report_year", datetime.now().year)
    el.append(doc_header(f"Invoice & Tax Liability Report — {month} {year}"))
    el.append(sp(2))

    # Seller header line
    sname  = rep.get("seller_name","")
    sgstin = rep.get("seller_gstin","")
    saddr  = rep.get("seller_address","")
    gdate  = datetime.now().strftime("%d/%m/%Y")
    el.append(Table(
        [[p(f"<b>{sname}</b>  |  {saddr}","body"),
          p(f"<b>GSTIN:</b> {sgstin}  |  <b>Generated:</b> {gdate}","body_r")]],
        colWidths=[PAGE_W*0.6, PAGE_W*0.4]
    ))
    el.append(sp(2))

    # KPI Summary box
    s = rep.get("summary",{})
    kpi = Table(
        [[p("Total Invoices","sec_hdr"),
          p("Total Taxable Value","sec_hdr"),
          p("Total GST Payable","sec_hdr")],
         [p(str(s.get("total_invoices",0)),"grand_l"),
          p(f"Rs. {fmt(s.get('taxable_value',0))}","grand_l"),
          p(f"Rs. {fmt(s.get('total_gst',0))}","grand_l")]],
        colWidths=[PAGE_W/3]*3
    )
    kpi.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,0), TEAL),
        ("BACKGROUND",    (0,1),(-1,1), LGRAY),
        ("BOX",           (0,0),(-1,-1), 0.8, TEAL),
        ("INNERGRID",     (0,0),(-1,-1), 0.5, colors.lightgrey),
        ("TOPPADDING",    (0,0),(-1,-1), 5),
        ("BOTTOMPADDING", (0,0),(-1,-1), 5),
        ("LEFTPADDING",   (0,0),(-1,-1), 8),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
    ]))
    el.append(kpi)
    el.append(sp(4))

    # Reusable section renderer for A/B/C/E
    def render_section(section_title, inv_list):
        el.append(p(f"<b>{section_title}</b>","body_b"))
        el.append(sp(1))
        if not inv_list:
            el.append(Table([[p("No invoices in this category.","body")]],
                            colWidths=[PAGE_W]))
            el.append(sp(3))
            return
        CW = [PAGE_W*w for w in [0.18,0.10,0.17,0.22,0.12,0.07,0.07,0.07]]
        hdr = [p("Invoice No","th"), p("Date","th"), p("Customer","th"),
               p("Description","th"), p("Taxable Rs.","th"),
               p("CGST Rs.","th"),   p("SGST Rs.","th"), p("IGST Rs.","th")]
        rows = [hdr]
        tot = {"tax":0,"cgst":0,"sgst":0,"igst":0}
        for inv in inv_list:
            d_   = inv.get("_data",{})
            desc = d_.get("items",[{}])[0].get("description","") if d_.get("items") else ""
            rows.append([
                p(inv.get("invoice_number",""),"td_l"),
                p(inv.get("invoice_date",""),  "td_c"),
                p(inv.get("customer_name",""), "td_l"),
                p(desc,                        "td_l"),
                p(fmt(inv.get("taxable_value",0)),"td_r"),
                p(fmt(inv.get("cgst",0)),         "td_r"),
                p(fmt(inv.get("sgst",0)),         "td_r"),
                p(fmt(inv.get("igst",0)),         "td_r"),
            ])
            tot["tax"]  += float(inv.get("taxable_value",0))
            tot["cgst"] += float(inv.get("cgst",0))
            tot["sgst"] += float(inv.get("sgst",0))
            tot["igst"] += float(inv.get("igst",0))
        rows.append([
            p(f"TOTAL ({len(inv_list)} invoices)","td_l"),
            p("","td_c"),p("","td_l"),p("","td_l"),
            p(fmt(tot["tax"]),"td_r"),
            p(fmt(tot["cgst"]),"td_r"),
            p(fmt(tot["sgst"]),"td_r"),
            p(fmt(tot["igst"]),"td_r"),
        ])
        t = Table(rows, colWidths=CW, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,0),  TEAL),
            ("BACKGROUND",    (0,-1),(-1,-1), LGRAY),
            ("ROWBACKGROUNDS",(0,1),(-1,-2), [WHITE, colors.HexColor("#F9F9F9")]),
            ("BOX",           (0,0),(-1,-1),  0.5, colors.lightgrey),
            ("INNERGRID",     (0,0),(-1,-1),  0.3, colors.lightgrey),
            ("FONTNAME",      (0,-1),(-1,-1), "Helvetica-Bold"),
            ("TOPPADDING",    (0,0),(-1,-1),  3),
            ("BOTTOMPADDING", (0,0),(-1,-1),  3),
            ("VALIGN",        (0,0),(-1,-1),  "MIDDLE"),
        ]))
        el.append(t)
        el.append(sp(3))

    render_section("SECTION A — TAX INVOICES (GST Registered)",      rep.get("tax_invoices",[]))
    render_section("SECTION B — BILL OF SUPPLY (Composition / Exempt)", rep.get("bos_invoices",[]))
    render_section("SECTION C — NON-GST INVOICES (Unregistered)",    rep.get("nongst_invoices",[]))

    # Section D — HSN-WISE TAX SUMMARY
    el.append(p("<b>SECTION D — HSN-WISE TAX SUMMARY</b>","body_b"))
    el.append(sp(1))
    hsn_list = rep.get("hsn_summary",[])
    if hsn_list:
        CW2 = [PAGE_W*w for w in [0.12,0.26,0.15,0.12,0.12,0.12,0.11]]
        hdr2 = [p("HSN Code","th"), p("Description","th"), p("Taxable Rs.","th"),
                p("CGST Rs.","th"), p("SGST Rs.","th"), p("IGST Rs.","th"),
                p("Total Tax Rs.","th")]
        rows2 = [hdr2]
        gt = {"tax":0,"cgst":0,"sgst":0,"igst":0,"taxable":0}
        for h in hsn_list:
            ttax = float(h.get("cgst",0))+float(h.get("sgst",0))+float(h.get("igst",0))
            rows2.append([
                p(str(h.get("hsn","")),"td_c"),
                p(str(h.get("description","")),"td_l"),
                p(fmt(h.get("taxable",0)),"td_r"),
                p(fmt(h.get("cgst",0)),"td_r"),
                p(fmt(h.get("sgst",0)),"td_r"),
                p(fmt(h.get("igst",0)),"td_r"),
                p(fmt(ttax),"td_r"),
            ])
            gt["taxable"] += float(h.get("taxable",0))
            gt["cgst"]    += float(h.get("cgst",0))
            gt["sgst"]    += float(h.get("sgst",0))
            gt["igst"]    += float(h.get("igst",0))
            gt["tax"]     += ttax
        rows2.append([
            p("GRAND TOTAL","td_l"), p("","td_l"),
            p(fmt(gt["taxable"]),"td_r"), p(fmt(gt["cgst"]),"td_r"),
            p(fmt(gt["sgst"]),"td_r"),   p(fmt(gt["igst"]),"td_r"),
            p(fmt(gt["tax"]),"td_r")
        ])
        ht = Table(rows2, colWidths=CW2, repeatRows=1)
        ht.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,0),  TEAL),
            ("BACKGROUND",    (0,-1),(-1,-1), LGRAY),
            ("ROWBACKGROUNDS",(0,1),(-1,-2), [WHITE, colors.HexColor("#F9F9F9")]),
            ("BOX",           (0,0),(-1,-1),  0.5, colors.lightgrey),
            ("INNERGRID",     (0,0),(-1,-1),  0.3, colors.lightgrey),
            ("FONTNAME",      (0,-1),(-1,-1), "Helvetica-Bold"),
            ("TOPPADDING",    (0,0),(-1,-1),  3),
            ("BOTTOMPADDING", (0,0),(-1,-1),  3),
            ("VALIGN",        (0,0),(-1,-1),  "MIDDLE"),
        ]))
        el.append(ht)
    else:
        el.append(Table([[p("No HSN/SAC data available.","body")]],colWidths=[PAGE_W]))
    el.append(sp(3))

    render_section("SECTION E — CREDIT NOTES (Cancelled Invoices)", rep.get("credit_notes",[]))

    # FINAL TAX LIABILITY SUMMARY
    el.append(p("<b>FINAL TAX LIABILITY SUMMARY</b>","body_b"))
    el.append(sp(1))
    fs = rep.get("final_summary",{})
    fs_rows = [
        [p("Gross Taxable Value (all invoices)","body"),
         p(f"Rs. {fmt(fs.get('gross_taxable',0))}","body_r")],
        [p("Gross CGST Collected","body"),
         p(f"Rs. {fmt(fs.get('gross_cgst',0))}","body_r")],
        [p("Gross SGST Collected","body"),
         p(f"Rs. {fmt(fs.get('gross_sgst',0))}","body_r")],
        [p("Gross IGST Collected","body"),
         p(f"Rs. {fmt(fs.get('gross_igst',0))}","body_r")],
        [p("Less: CGST Reversed (Credit Notes)","red_b"),
         p(f"(Rs. {fmt(fs.get('reversed_cgst',0))})","red_r")],
        [p("Less: SGST Reversed (Credit Notes)","red_b"),
         p(f"(Rs. {fmt(fs.get('reversed_sgst',0))})","red_r")],
        [p("Less: IGST Reversed (Credit Notes)","red_b"),
         p(f"(Rs. {fmt(fs.get('reversed_igst',0))})","red_r")],
        [p("NET GST PAYABLE TO GOVERNMENT ★","grand_l"),
         p(f"Rs. {fmt(fs.get('net_gst',0))}","grand_r")],
    ]
    ft = Table(fs_rows, colWidths=[PAGE_W*0.72, PAGE_W*0.28])
    ft.setStyle(TableStyle([
        ("BOX",           (0,0),(-1,-1), 0.8, TEAL),
        ("BACKGROUND",    (0,-1),(-1,-1), colors.HexColor("#E8F5F5")),
        ("LINEABOVE",     (0,-1),(-1,-1), 1.5, TEAL),
        ("INNERGRID",     (0,0),(-1,-2), 0.3, colors.lightgrey),
        ("TOPPADDING",    (0,0),(-1,-1), 4),
        ("BOTTOMPADDING", (0,0),(-1,-1), 4),
        ("LEFTPADDING",   (0,0),(-1,-1), 6),
        ("RIGHTPADDING",  (0,0),(-1,-1), 6),
        ("ALIGN",         (1,0),(1,-1),  "RIGHT"),
    ]))
    el.append(ft)
    el.append(sp(3))
    el.append(p("Use this report to prepare your GSTR-1 filing. "
                "Verify all amounts with your Chartered Accountant before submission.","small_c"))
    el.extend(footer_elems())
    doc.build(el)
    return buf.getvalue()

# ═══════════════════════════════════════════════════════════════════════════════
# PDF ENTRY POINTS (with Supabase Storage upload)
# ═══════════════════════════════════════════════════════════════════════════════

def upload_pdf_to_supabase(pdf_bytes, file_path):
    url = f"{env('SUPABASE_URL')}/storage/v1/object/invoices/{file_path}"
    h   = {"apikey": env("SUPABASE_KEY"),
           "Authorization": f"Bearer {env('SUPABASE_KEY')}",
           "Content-Type": "application/pdf",
           "x-upsert": "true"}
    r = requests.post(url, headers=h, data=pdf_bytes, timeout=30)
    if r.status_code not in (200, 201):
        raise Exception(f"Supabase upload {r.status_code}: {r.text[:200]}")
    return f"{env('SUPABASE_URL')}/storage/v1/object/public/invoices/{file_path}"

def _clean_phone(phone):
    return phone.replace("whatsapp:+","").replace("+","").replace(" ","")

def select_and_generate_pdf(invoice_data, seller_phone):
    itype  = (invoice_data.get("invoice_type") or "").upper()
    inv_no = invoice_data.get("invoice_number") or f"GUT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    if   "CREDIT" in itype: pdf_bytes, sub = build_credit_note(invoice_data),    "credit_notes"
    elif "BILL"   in itype: pdf_bytes, sub = build_bill_of_supply(invoice_data), "invoices"
    elif "TAX"    in itype: pdf_bytes, sub = build_tax_invoice(invoice_data),    "invoices"
    else:                   pdf_bytes, sub = build_nongst_invoice(invoice_data), "invoices"
    phone = _clean_phone(seller_phone)
    return upload_pdf_to_supabase(pdf_bytes, f"{phone}/{sub}/{inv_no}.pdf")

def generate_report_pdf_and_upload(report_data, seller_phone):
    month = report_data.get("report_month","Report")
    year  = report_data.get("report_year", datetime.now().year)
    phone = _clean_phone(seller_phone)
    return upload_pdf_to_supabase(build_monthly_report(report_data),
                                  f"{phone}/reports/{month}_{year}.pdf")

# ═══════════════════════════════════════════════════════════════════════════════
# SUPABASE HELPERS — ALL wrapped in try/except, never crash the webhook
# ═══════════════════════════════════════════════════════════════════════════════

def sb_h():
    return {"apikey": env("SUPABASE_KEY"),
            "Authorization": f"Bearer {env('SUPABASE_KEY')}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"}

def sb_url(table, q=""):
    return f"{env('SUPABASE_URL')}/rest/v1/{table}{q}"

def get_seller(phone):
    try:
        ph = url_quote(phone, safe='')
        r = requests.get(sb_url("sellers", f"?phone_number=eq.{ph}&limit=1"),
                         headers=sb_h(), timeout=10)
        d = safe_json(r, "get_seller")
        return d[0] if isinstance(d, list) and d else None
    except Exception as e:
        log.error(f"get_seller failed: {e}")
        return None

def create_seller(phone):
    try:
        r = requests.post(sb_url("sellers"), headers=sb_h(),
                          json={"phone_number": phone, "onboarding_step": "language_asked",
                                "language": "english", "created_at": datetime.utcnow().isoformat()},
                          timeout=10)
        d = safe_json(r, "create_seller")
        if isinstance(d, list) and d:
            return d[0]
        return {"phone_number": phone, "onboarding_step": "language_asked", "language": "english"}
    except Exception as e:
        log.error(f"create_seller failed: {e}")
        return {"phone_number": phone, "onboarding_step": "language_asked", "language": "english"}

def update_seller(phone, updates):
    try:
        ph = url_quote(phone, safe='')
        r = requests.patch(sb_url("sellers", f"?phone_number=eq.{ph}"),
                           headers=sb_h(), json=updates, timeout=10)
        log.info(f"update_seller {updates} → {r.status_code}")
        return safe_json(r, "update_seller")
    except Exception as e:
        log.error(f"update_seller failed: {e}")
        return None

def save_invoice(phone, inv_data, pdf_url):
    d = inv_data
    core = {
        "seller_phone": phone,
        "invoice_type": d.get("invoice_type", "TAX INVOICE"),
        "invoice_number": d.get("invoice_number", ""),
        "customer_name": d.get("customer_name", ""),
        "total_amount": d.get("total_amount", 0),
        "invoice_data": json.dumps(d),
        "pdf_url": pdf_url,
        "created_at": datetime.utcnow().isoformat(),
        "invoice_month": datetime.utcnow().month,
        "invoice_year": datetime.utcnow().year,
    }
    extra = {
        "taxable_value": d.get("taxable_value", 0),
        "cgst": d.get("cgst", 0), "sgst": d.get("sgst", 0), "igst": d.get("igst", 0),
        "cgst_rate": d.get("cgst_rate", 0), "sgst_rate": d.get("sgst_rate", 0),
        "igst_rate": d.get("igst_rate", 0),
        "invoice_date": d.get("invoice_date", ""),
        "is_cancelled": False,
        "credit_note_for": d.get("original_invoice_number", ""),
    }
    try:
        r = requests.post(sb_url("invoices"), headers=sb_h(),
                          json={**core, **extra}, timeout=10)
        if r.status_code in (200, 201):
            log.info(f"save_invoice OK: {d.get('invoice_number')}")
            return safe_json(r, "save_invoice")
        log.warning(f"save_invoice full failed {r.status_code}, trying core only")
        r2 = requests.post(sb_url("invoices"), headers=sb_h(), json=core, timeout=10)
        log.info(f"save_invoice core: {r2.status_code}")
        return safe_json(r2, "save_invoice_core")
    except Exception as e:
        log.error(f"save_invoice failed: {e}")
        return None

def cancel_invoice_in_db(phone, invoice_number):
    try:
        ph  = url_quote(phone, safe='')
        inv = url_quote(invoice_number, safe='')
        r = requests.patch(
            sb_url("invoices", f"?seller_phone=eq.{ph}&invoice_number=eq.{inv}"),
            headers=sb_h(), json={"is_cancelled": True}, timeout=10)
        return safe_json(r, "cancel_invoice")
    except Exception as e:
        log.error(f"cancel_invoice failed: {e}")
        return None

def get_invoice_by_number(phone, invoice_number):
    try:
        ph  = url_quote(phone, safe='')
        inv = url_quote(invoice_number, safe='')
        r = requests.get(
            sb_url("invoices", f"?seller_phone=eq.{ph}&invoice_number=eq.{inv}&limit=1"),
            headers=sb_h(), timeout=10)
        d = safe_json(r, "get_invoice")
        return d[0] if isinstance(d, list) and d else None
    except Exception as e:
        log.error(f"get_invoice failed: {e}")
        return None

def get_all_monthly_invoices(phone, month, year):
    try:
        ph = url_quote(phone, safe='')
        r = requests.get(
            sb_url("invoices", f"?seller_phone=eq.{ph}&invoice_month=eq.{month}&invoice_year=eq.{year}"),
            headers=sb_h(), timeout=15)
        d = safe_json(r, "monthly_invoices")
        return d if isinstance(d, list) else []
    except Exception as e:
        log.error(f"monthly_invoices failed: {e}")
        return []

# ═══════════════════════════════════════════════════════════════════════════════
# SEQUENTIAL INVOICE NUMBERING
# ═══════════════════════════════════════════════════════════════════════════════

def get_invoice_prefix(seller):
    biz     = (seller.get("business_name") or seller.get("seller_name") or "GUT").upper()
    cleaned = re.sub(r"[^A-Z0-9]", "", biz)
    return (cleaned + "GUT")[:3]

def get_next_seq(phone, month, year, is_credit=False):
    type_q = "eq.CREDIT NOTE" if is_credit else "neq.CREDIT NOTE"
    ph = url_quote(phone, safe='')
    q  = f"?seller_phone=eq.{ph}&invoice_month=eq.{month}&invoice_year=eq.{year}&invoice_type={type_q}&select=id"
    try:
        r = requests.get(sb_url("invoices", q), headers=sb_h(), timeout=10)
        d = safe_json(r, "seq")
        return (len(d) if isinstance(d, list) else 0) + 1
    except Exception:
        return 1

def generate_invoice_number(phone, seller, month, year):
    return f"{get_invoice_prefix(seller)}{get_next_seq(phone,month,year,False):03d}-{month:02d}{year}"

def generate_credit_note_number(phone, seller, month, year):
    return f"CN-{get_invoice_prefix(seller)}{get_next_seq(phone,month,year,True):03d}-{month:02d}{year}"


# ═══════════════════════════════════════════════════════════════════════════════
# INVOICE PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

def download_audio(media_url):
    r = requests.get(media_url, auth=(env("TWILIO_ACCOUNT_SID"), env("TWILIO_AUTH_TOKEN")), timeout=30)
    if r.status_code != 200:
        raise Exception(f"Audio download failed {r.status_code}")
    log.info(f"Audio: {len(r.content)} bytes")
    return r.content

def transcribe_audio(audio_bytes, language="telugu"):
    lang_map = {"telugu": "te-IN", "english": "en-IN", "both": "te-IN"}
    r = requests.post(
        "https://api.sarvam.ai/speech-to-text",
        files={"file": ("audio.ogg", audio_bytes, "audio/ogg")},
        data={"model": "saaras:v2.5", "language_code": lang_map.get(language, "te-IN"),
              "with_disfluencies": "false"},
        headers={"api-subscription-key": env("SARVAM_API_KEY")},
        timeout=60
    )
    result = safe_json(r, "Sarvam")
    tr = (result or {}).get("transcript", "")
    log.info(f"Transcript: {tr}")
    return tr

def extract_invoice_data(transcript, seller, phone, month, year):
    sname  = seller.get("business_name") or seller.get("seller_name") or ""
    saddr  = seller.get("address") or seller.get("seller_address") or ""
    sgstin = seller.get("gstin") or seller.get("seller_gstin") or ""
    inv_no = generate_invoice_number(phone, seller, month, year)
    today  = datetime.now().strftime("%d/%m/%Y")
    system = (
        "You are a GST invoice data extractor for Indian businesses. "
        "Extract invoice details from the voice transcription and return ONLY valid JSON. "
        "Rules: amounts as numbers only; dates DD/MM/YYYY; "
        "invoice_type = \"TAX INVOICE\" (GST), \"BILL OF SUPPLY\" (composition/exempt), "
        "\"INVOICE\" (no GSTIN); cgst_rate=sgst_rate=gst_rate/2 intrastate; "
        "igst_rate=full interstate; reverse_charge=\"No\" by default."
    )
    prompt = (
        f'Transcription: "{transcript}"\n\n'
        f'Pre-filled seller:\n'
        f'  seller_name: {sname}\n  seller_address: {saddr}\n'
        f'  seller_gstin: {sgstin}\n  invoice_number: {inv_no}\n  invoice_date: {today}\n\n'
        f'Return ONLY this JSON:\n{{\n'
        f'  "invoice_type": "TAX INVOICE",\n'
        f'  "invoice_number": "{inv_no}",\n'
        f'  "invoice_date": "{today}",\n'
        f'  "seller_name": "{sname}",\n'
        f'  "seller_address": "{saddr}",\n'
        f'  "seller_gstin": "{sgstin}",\n'
        f'  "reverse_charge": "No",\n'
        f'  "customer_name": "",\n'
        f'  "customer_address": "",\n'
        f'  "customer_gstin": "",\n'
        f'  "place_of_supply": "",\n'
        f'  "is_interstate": false,\n'
        f'  "items": [{{"sno":"1","description":"","hsn_sac":"","qty":1,"unit":"Nos","rate":0,"amount":0}}],\n'
        f'  "taxable_value": 0,\n'
        f'  "cgst_rate": 9, "sgst_rate": 9, "igst_rate": 0,\n'
        f'  "cgst": 0, "sgst": 0, "igst": 0,\n'
        f'  "total_amount": 0,\n'
        f'  "declaration": "We declare this invoice shows the actual price of goods/services.",\n'
        f'  "payment_terms": "Pay within 30 days"\n}}' 
    )
    msg  = get_claude().messages.create(
        model="claude-haiku-4-5-20251001", max_tokens=1500,
        system=system, messages=[{"role": "user", "content": prompt}]
    )
    text = msg.content[0].text.strip()
    if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
    elif "```"   in text: text = text.split("```")[1].split("```")[0].strip()
    s = text.find("{"); e = text.rfind("}") + 1
    if s == -1 or e == 0:
        raise Exception(f"No JSON from Claude: {text[:200]}")
    data = json.loads(text[s:e])
    itype2 = data.get("invoice_type",""); ino2 = data.get("invoice_number",""); cname2 = data.get("customer_name","")
    log.info(f"Invoice: {itype2} #{ino2} | {cname2}")
    return data

# ═══════════════════════════════════════════════════════════════════════════════
# CANCEL / CREDIT NOTE
# ═══════════════════════════════════════════════════════════════════════════════

def is_cancel_request(text):
    return any(k in text.lower() for k in ["cancel","void","రద్దు","wrong invoice","delete invoice","reverse invoice"])

def parse_invoice_ref(text):
    m = re.search(r"([A-Z]{2,6}\d{3}-\d{6})", text.upper())
    if m: return m.group(1)
    m = re.search(r"(\d{3}-\d{6})", text)
    if m: return m.group(1)
    return None

def handle_cancel_request(from_num, text, seller, lang):
    ref = parse_invoice_ref(text)
    if not ref:
        send_rest(from_num, "⚠️ Please specify the invoice number.\nExample: *cancel TEJ001-022026*"
                  if lang=="english" else "⚠️ Invoice number చెప్పండి.\nExample: *cancel TEJ001-022026*")
        return
    orig = get_invoice_by_number(from_num, ref)
    if not orig:
        orig = get_invoice_by_number(from_num, f"{get_invoice_prefix(seller)}{ref}")
    if not orig:
        send_rest(from_num, f"⚠️ Invoice *{ref}* not found." if lang=="english"
                  else f"⚠️ Invoice *{ref}* మీ records లో కనుగొనబడలేదు.")
        return
    if orig.get("is_cancelled"):
        send_rest(from_num, f"⚠️ Invoice *{orig['invoice_number']}* is already cancelled."
                  if lang=="english" else f"⚠️ ఇప్పటికే రద్దు చేయబడింది.")
        return
    if orig.get("invoice_type") == "CREDIT NOTE":
        send_rest(from_num, "⚠️ Credit notes cannot be cancelled.")
        return
    cancel_invoice_in_db(from_num, orig["invoice_number"])
    try:    orig_data = json.loads(orig.get("invoice_data","{}"))
    except: orig_data = orig
    now   = datetime.utcnow()
    cn_no = generate_credit_note_number(from_num, seller, now.month, now.year)
    credit = {
        **orig_data,
        "invoice_type": "CREDIT NOTE", "invoice_number": cn_no,
        "credit_note_number": cn_no, "invoice_date": now.strftime("%d/%m/%Y"),
        "original_invoice_number": orig["invoice_number"],
        "original_invoice_date": orig_data.get("invoice_date",""),
        "reason": "Cancellation of invoice as requested by seller",
    }
    pdf_url = select_and_generate_pdf(credit, from_num)
    save_invoice(from_num, credit, pdf_url)
    total = fmt(orig_data.get("total_amount",0))
    body = (f"✅ *Invoice {orig['invoice_number']} Cancelled*\n\n📋 Credit Note: {cn_no}\n💰 Credit Amount: ₹ {total}\n\nCredit Note PDF attached ↓"
            if lang=="english"
            else f"✅ *Invoice {orig['invoice_number']} రద్దు*\n\n📋 Credit Note: {cn_no}\n💰 Amount: ₹ {total}\n\nCredit Note PDF పంపబడింది ↓")
    send_rest(from_num, body, pdf_url)

# ═══════════════════════════════════════════════════════════════════════════════
# MONTHLY REPORT
# ═══════════════════════════════════════════════════════════════════════════════

MONTH_MAP = {
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
    "జనవరి":1,"ఫిబ్రవరి":2,"మార్చి":3,"ఏప్రిల్":4,"మే":5,"జూన్":6,
    "జులై":7,"ఆగస్టు":8,"సెప్టెంబర్":9,"అక్టోబర్":10,"నవంబర్":11,"డిసెంబర్":12
}
MNAMES = {v: k.capitalize() for k, v in MONTH_MAP.items() if k.isascii()}

def is_report_request(text):
    return any(k in text.lower() for k in ["report","summary","రిపోర్ట్","సమరీ","monthly","నెల","last month","tax summary","invoices summary","గత నెల"])

def parse_month_year(text):
    tl=text.lower(); year=datetime.now().year
    m=re.search(r"20\d{2}",text)
    if m: year=int(m.group())
    for name,num in MONTH_MAP.items():
        if name in tl: return num, year
    return datetime.now().month, year

def _parse_row(raw):
    try:    d = json.loads(raw.get("invoice_data","{}"))
    except: d = {}
    return {
        "invoice_number": raw.get("invoice_number",""),
        "invoice_date":   d.get("invoice_date", raw.get("invoice_date","")),
        "customer_name":  raw.get("customer_name",""),
        "invoice_type":   raw.get("invoice_type",""),
        "taxable_value":  float(raw.get("taxable_value",0) or 0),
        "cgst":           float(raw.get("cgst",0) or 0),
        "sgst":           float(raw.get("sgst",0) or 0),
        "igst":           float(raw.get("igst",0) or 0),
        "total_amount":   float(raw.get("total_amount",0) or 0),
        "_data": d, "_cancelled": raw.get("is_cancelled",False),
    }

def _build_hsn(inv_list):
    hsn = {}
    for inv in inv_list:
        d=inv.get("_data",{}); cr=float(d.get("cgst_rate",0)); sr=float(d.get("sgst_rate",0))
        ir=float(d.get("igst_rate",0)); inter=str(d.get("is_interstate","false")).lower()=="true"
        for item in d.get("items",[]):
            key=str(item.get("hsn_sac","")).strip()
            if not key: continue
            amt=float(item.get("amount",0))
            if key not in hsn: hsn[key]={"hsn":key,"description":item.get("description",""),"taxable":0,"cgst":0,"sgst":0,"igst":0}
            hsn[key]["taxable"]+=amt
            if inter: hsn[key]["igst"]+=round(amt*ir/100,2)
            else: hsn[key]["cgst"]+=round(amt*cr/100,2); hsn[key]["sgst"]+=round(amt*sr/100,2)
    return list(hsn.values())

def handle_report_request(from_num, text, seller, lang):
    month_num, year = parse_month_year(text)
    mname = MNAMES.get(month_num, str(month_num))
    all_raw = get_all_monthly_invoices(from_num, month_num, year)
    if not all_raw:
        send_rest(from_num, f"📊 No invoices found for {mname} {year}." if lang=="english"
                  else f"📊 {mname} {year} కి invoices లేవు.")
        return
    parsed = [_parse_row(r) for r in all_raw]
    credit_ns = [p for p in parsed if p["invoice_type"]=="CREDIT NOTE"]
    regular   = [p for p in parsed if p["invoice_type"]!="CREDIT NOTE"]
    active    = [p for p in regular if not p.get("_cancelled")]
    tax_inv    = [i for i in active if "TAX"  in i["invoice_type"].upper()]
    bos_inv    = [i for i in active if "BILL" in i["invoice_type"].upper()]
    nongst_inv = [i for i in active if i["invoice_type"].upper() in ("INVOICE","NON-GST","NONGST")]
    gt = sum(i["taxable_value"] for i in regular)
    gc = sum(i["cgst"] for i in regular); gs = sum(i["sgst"] for i in regular)
    gi = sum(i["igst"] for i in regular)
    rc = sum(i["cgst"] for i in credit_ns); rs = sum(i["sgst"] for i in credit_ns)
    ri = sum(i["igst"] for i in credit_ns)
    net = (gc+gs+gi)-(rc+rs+ri)
    report = {
        "report_month": mname, "report_year": year,
        "seller_name":  seller.get("business_name") or seller.get("seller_name",""),
        "seller_address": seller.get("address") or seller.get("seller_address",""),
        "seller_gstin": seller.get("gstin") or seller.get("seller_gstin",""),
        "summary": {"total_invoices":len(regular),"taxable_value":gt,"total_gst":net},
        "tax_invoices":tax_inv,"bos_invoices":bos_inv,"nongst_invoices":nongst_inv,
        "hsn_summary":_build_hsn(active),"credit_notes":credit_ns,
        "final_summary":{"gross_taxable":gt,"gross_cgst":gc,"gross_sgst":gs,"gross_igst":gi,
                         "reversed_cgst":rc,"reversed_sgst":rs,"reversed_igst":ri,"net_gst":net}
    }
    pdf_url = generate_report_pdf_and_upload(report, from_num)
    body = (f"📊 *{mname} {year} Report Ready!*\n\n🧾 Total: {len(regular)}\n💰 Taxable: ₹ {fmt(gt)}\n🏷️ Net GST: ₹ {fmt(net)}"
            + (f"\n📋 Credit Notes: {len(credit_ns)}" if credit_ns else ""))
    send_rest(from_num, body, pdf_url)

# ═══════════════════════════════════════════════════════════════════════════════
# ONBOARDING FLOW
# ═══════════════════════════════════════════════════════════════════════════════

def handle_onboarding(from_num, body, seller):
    step = seller.get("onboarding_step","language_asked")
    lang = seller.get("language","english")
    tl   = (body or "").strip().lower()
    if step == "language_asked":
        if any(x in tl for x in ["1","english"]):
            update_seller(from_num,{"language":"english","onboarding_step":"registration_asked"})
            send_rest(from_num,"Great! You chose English 🇬🇧\n\nWould you like to register your business?\nType *YES* to register  |  *SKIP* to start invoicing directly")
        elif any(x in tl for x in ["2","telugu","తెలుగు"]):
            update_seller(from_num,{"language":"telugu","onboarding_step":"registration_asked"})
            send_rest(from_num,"బాగుంది! తెలుగు ఎంచుకున్నారు 🙏\n\nవ్యాపార వివరాలు నమోదు చేయాలా?\n*YES* type చేయండి  |  *SKIP* నేరుగా invoice చేయండి")
        else:
            send_rest(from_num,"Welcome to *GutInvoice* 🎙️\n_Every Invoice has a Voice_\n\nChoose language:\n1️⃣ English\n2️⃣ Telugu / తెలుగు")
        return True
    if step == "registration_asked":
        if any(x in tl for x in ["yes","అవున"]):
            update_seller(from_num,{"onboarding_step":"reg_name"})
            send_rest(from_num,"Enter your *Business Name*:" if lang=="english" else "మీ *వ్యాపార పేరు* enter చేయండి:")
        else:
            update_seller(from_num,{"onboarding_step":"complete"})
            send_rest(from_num,"✅ Setup complete! Send a voice note to create your first invoice. 🎙️"
                      if lang=="english" else "✅ Setup పూర్తయింది! Voice note పంపి invoice చేయండి. 🎙️")
        return True
    if step == "reg_name":
        update_seller(from_num,{"business_name":body.strip(),"onboarding_step":"reg_address"})
        send_rest(from_num,"Enter your *Business Address*:" if lang=="english" else "మీ *వ్యాపార చిరునామా* enter చేయండి:")
        return True
    if step == "reg_address":
        update_seller(from_num,{"address":body.strip(),"onboarding_step":"reg_gstin"})
        send_rest(from_num,"Enter your *GSTIN* (or *SKIP* if unregistered):" if lang=="english" else "మీ *GSTIN* enter చేయండి (లేకుంటే *SKIP*):")
        return True
    if step == "reg_gstin":
        gstin = "" if "skip" in tl else body.strip().upper()
        update_seller(from_num,{"gstin":gstin,"onboarding_step":"complete"})
        name = seller.get("business_name","")
        send_rest(from_num,f"✅ *Registration Complete!*\nWelcome, {name}!\n\nSend a voice note to create your first invoice. 🎙️\nType *HELP* for commands."
                  if lang=="english"
                  else f"✅ *నమోదు పూర్తయింది!*\n{name} కి స్వాగతం!\n\nVoice note పంపి invoice చేయండి. 🎙️\n*HELP* type చేయండి.")
        return True
    return False

# ═══════════════════════════════════════════════════════════════════════════════
# VOICE NOTE BACKGROUND PROCESSOR
# Runs in a daemon thread — TwiML ack returned immediately, no timeout risk
# ═══════════════════════════════════════════════════════════════════════════════

def process_voice_note(from_num, media_url, seller, lang):
    try:
        audio = download_audio(media_url)
        tr    = transcribe_audio(audio, lang)
        if not tr.strip():
            send_rest(from_num,"⚠️ Could not understand audio. Please speak clearly and try again."
                      if lang=="english" else "⚠️ Audio అర్థం కాలేదు. Clearly చెప్పి మళ్ళీ try చేయండి.")
            return
        if is_cancel_request(tr):
            handle_cancel_request(from_num, tr, seller, lang)
            return
        if is_report_request(tr):
            handle_report_request(from_num, tr, seller, lang)
            return
        send_rest(from_num,"⏳ Generating your invoice... (Ready in ~30 seconds)"
                  if lang=="english" else "⏳ మీ invoice తయారవుతుంది... (~30 seconds)")
        now = datetime.utcnow()
        inv = extract_invoice_data(tr, seller, from_num, now.month, now.year)
        url = select_and_generate_pdf(inv, from_num)
        save_invoice(from_num, inv, url)
        itype=inv.get("invoice_type","Invoice"); inv_no=inv.get("invoice_number","")
        cname=inv.get("customer_name",""); total=fmt(inv.get("total_amount",0))
        body = (f"✅ *Your {itype} is Ready!*\n\n📋 Invoice No: {inv_no}\n👤 Customer: {cname}\n💰 Total: ₹ {total}\n\nPowered by *GutInvoice* 🎙️"
                if lang=="english"
                else f"✅ *మీ {itype} Ready!*\n\n📋 Invoice No: {inv_no}\n👤 Customer: {cname}\n💰 Total: ₹ {total}\n\nPowered by *GutInvoice* 🎙️")
        send_rest(from_num, body, url)
        log.info(f"✅ Invoice done | {inv_no} | {from_num}")
    except Exception as e:
        log.error(f"process_voice_note error: {e}", exc_info=True)
        send_rest(from_num,"⚠️ Something went wrong. Please try again."
                  if lang=="english" else "⚠️ Error వచ్చింది. మళ్ళీ try చేయండి.")

# ═══════════════════════════════════════════════════════════════════════════════
# TWILIO WEBHOOK — FIXED VERSION
# ═══════════════════════════════════════════════════════════════════════════════

GREETINGS = {"hi","hello","hey","hii","helo","start","హలో","నమస్కారం","namaste","నమస్తే","ola","yo"}

@app.route("/webhook", methods=["POST"])
def webhook():
    from_num  = request.form.get("From","")
    body      = request.form.get("Body","") or ""
    media_url = request.form.get("MediaUrl0","")
    num_media = int(request.form.get("NumMedia",0))
    log.info(f"─── Webhook | From:{from_num} | Body:{body[:50]!r} | Media:{num_media}")
    try:
        seller = get_seller(from_num)
        if not seller:
            seller = create_seller(from_num)
            return twiml_reply("Welcome to *GutInvoice* 🎙️\n_Every Invoice has a Voice_\n\nChoose your language:\n1️⃣ English\n2️⃣ Telugu / తెలుగు")

        lang = seller.get("language","english")
        step = seller.get("onboarding_step","complete")

        if step not in ("complete", None, ""):
            handle_onboarding(from_num, body, seller)
            return twiml_empty()

        tl = (body or "").strip().lower()

        # GREETING — restored from working version ✅
        if tl in GREETINGS:
            name = seller.get("business_name") or "there"
            return twiml_reply(
                f"👋 Hey {name}! Welcome to *GutInvoice* 🎙️\n\n"
                f"🎙️ *Send a voice note* → Auto-generate invoice\n"
                f"📊 *\'January 2026 summary\'* → Monthly PDF report\n"
                f"❌ *\'cancel TEJ001-022026\'* → Cancel + credit note\n"
                f"✏️ *UPDATE* → Update your business profile\n"
                f"📋 *HELP* → See profile & all commands\n\n"
                f"Example: _\"Customer Suresh, 50 rods, 800 each, 18% GST\"_"
                if lang=="english"
                else f"👋 నమస్కారం {name}! *GutInvoice* కి స్వాగతం 🎙️\n\n"
                     f"🎙️ *Voice note పంపండి* → Invoice auto-generate\n"
                     f"📊 *\'January 2026 summary\'* → Monthly report\n"
                     f"❌ *\'cancel TEJ001-022026\'* → Invoice cancel + credit note\n"
                     f"✏️ *UPDATE* → Profile update\n"
                     f"📋 *HELP* → Profile & commands"
            )

        # HELP
        if tl in ("help","హెల్ప్","status"):
            name = seller.get("business_name") or from_num
            gstin = seller.get("gstin") or "Not set"
            addr  = seller.get("address") or "Not set"
            return twiml_reply(
                f"📋 *GutInvoice — Your Profile*\n\n"
                f"👤 {name}\n📍 {addr}\n🔑 GSTIN: {gstin}\n\n"
                f"🎙️ *Voice note* → Create invoice\n"
                f"📊 *report feb 2026* → Monthly report\n"
                f"❌ *cancel TEJ001-022026* → Cancel + credit note\n"
                f"✏️ *UPDATE* → Update profile"
            )

        # UPDATE
        if tl in ("update","register"):
            update_seller(from_num,{"onboarding_step":"reg_name"})
            return twiml_reply("Enter your *Business Name*:" if lang=="english" else "మీ *వ్యాపార పేరు* enter చేయండి:")

        # CANCEL (text)
        if is_cancel_request(body) and not num_media:
            t = threading.Thread(target=handle_cancel_request, args=(from_num,body,seller,lang), daemon=True)
            t.start()
            return twiml_reply("⏳ Processing cancellation..." if lang=="english" else "⏳ Cancellation process అవుతుంది...")

        # REPORT (text)
        if is_report_request(body) and not num_media:
            t = threading.Thread(target=handle_report_request, args=(from_num,body,seller,lang), daemon=True)
            t.start()
            return twiml_reply("📊 Generating your report... (30-60 seconds)" if lang=="english" else "📊 Report తయారవుతుంది... (30-60 seconds)")

        # VOICE NOTE — thread + immediate TwiML ack ✅
        if num_media and media_url:
            t = threading.Thread(target=process_voice_note, args=(from_num,media_url,seller,lang), daemon=True)
            t.start()
            return twiml_reply("🎙️ Voice note received! Processing...\n⏳ Your invoice will arrive in ~30 seconds."
                               if lang=="english"
                               else "🎙️ Voice note అందింది! Process అవుతుంది...\n⏳ Invoice ~30 seconds లో వస్తుంది.")

        # UNKNOWN
        return twiml_reply("🎙️ Send a *voice note* to create an invoice.\nType *HI* for the full menu."
                           if lang=="english" else "🎙️ Invoice కోసం *voice note* పంపండి.\nFull menu కోసం *HI* type చేయండి.")

    except Exception as e:
        log.error(f"Webhook FATAL: {e}", exc_info=True)
        # TwiML fallback — ALWAYS responds, no credentials needed ✅
        return twiml_reply("⚠️ Something went wrong. Please try again in a moment.")

# ═══════════════════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/health")
def health():
    keys = ["TWILIO_ACCOUNT_SID","TWILIO_AUTH_TOKEN","TWILIO_FROM_NUMBER","SARVAM_API_KEY","SUPABASE_URL","SUPABASE_KEY"]
    checks = {k: bool(env(k)) for k in keys}
    checks["CLAUDE_API_KEY"] = bool(env("CLAUDE_API_KEY") or env("ANTHROPIC_API_KEY"))
    try:
        r = requests.get(sb_url("sellers","?limit=1"), headers=sb_h(), timeout=5)
        checks["supabase_connection"] = (r.status_code==200)
    except Exception:
        checks["supabase_connection"] = False
    ok = all(checks.values())
    return {"status":"healthy" if ok else "missing_config","version":"v16.1",
            "checks":checks,"timestamp":datetime.now().isoformat()}, 200 if ok else 500

HOME_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"/><title>GutInvoice</title>
<style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Segoe UI',sans-serif;background:#0A0F1E;color:#fff;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:40px 20px}h1{font-size:48px;font-weight:900;color:#FF6B35;margin-bottom:8px}h2{font-size:18px;color:#94a3b8;margin-bottom:30px}.pill{display:inline-flex;align-items:center;gap:8px;background:rgba(16,185,129,.1);border:1px solid rgba(16,185,129,.3);padding:8px 20px;border-radius:50px;font-size:13px;color:#10B981;font-weight:700;margin-bottom:30px}.dot{width:8px;height:8px;background:#10B981;border-radius:50%;animation:blink 2s infinite}@keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}.grid{display:flex;gap:20px;flex-wrap:wrap;justify-content:center;max-width:950px}.card{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:16px;padding:24px;width:210px}.card h3{font-size:28px;margin-bottom:8px}.card p{font-size:13px;color:#94a3b8;line-height:1.5}footer{margin-top:50px;font-size:12px;color:#475569;line-height:1.8}</style>
</head><body>
<div class="pill"><div class="dot"></div>LIVE — v16.1</div>
<h1>GutInvoice</h1><h2>Every Invoice has a Voice 🎙️</h2>
<div class="grid">
  <div class="card"><h3>🎙️</h3><p>Voice note → Invoice in 30 seconds</p></div>
  <div class="card"><h3>🤖</h3><p>AI transcription in Telugu + English</p></div>
  <div class="card"><h3>📄</h3><p>GST-compliant PDF, sequential numbers</p></div>
  <div class="card"><h3>❌</h3><p>Cancel any invoice → auto credit note</p></div>
</div>
<footer>Powered by Tallbag Advisory and Tech Solutions Private Limited · +91 7702424946</footer>
</body></html>"""

@app.route("/")
def home():
    return render_template_string(HOME_HTML)

# ═══════════════════════════════════════════════════════════════════════════════
# DEBUG ENDPOINT — visit https://your-app.railway.app/debug to diagnose
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/debug")
def debug():
    """
    Visit this URL in browser to see exactly what's configured.
    Safe — shows only presence of keys, not values.
    """
    import sys
    results = {}

    # 1. Env vars
    for k in ["TWILIO_ACCOUNT_SID","TWILIO_AUTH_TOKEN","TWILIO_FROM_NUMBER",
              "SARVAM_API_KEY","SUPABASE_URL","SUPABASE_KEY"]:
        val = env(k)
        results[k] = f"SET ({len(val)} chars)" if val else "❌ MISSING"
    results["CLAUDE_API_KEY"] = f"SET" if (env("CLAUDE_API_KEY") or env("ANTHROPIC_API_KEY")) else "❌ MISSING"

    # 2. Twilio test
    try:
        c = get_twilio()
        acc = c.api.accounts(env("TWILIO_ACCOUNT_SID")).fetch()
        results["twilio_test"] = f"✅ OK — {acc.friendly_name}"
    except Exception as e:
        results["twilio_test"] = f"❌ {e}"

    # 3. Supabase sellers table
    try:
        r = requests.get(sb_url("sellers","?limit=3"), headers=sb_h(), timeout=5)
        results["supabase_sellers"] = f"✅ HTTP {r.status_code} — {r.text[:80]}"
    except Exception as e:
        results["supabase_sellers"] = f"❌ {e}"

    # 4. Supabase invoices table
    try:
        r = requests.get(sb_url("invoices","?limit=1"), headers=sb_h(), timeout=5)
        results["supabase_invoices"] = f"✅ HTTP {r.status_code} — {r.text[:80]}"
    except Exception as e:
        results["supabase_invoices"] = f"❌ {e}"

    # 5. Sarvam API reachability
    try:
        r = requests.get("https://api.sarvam.ai", timeout=5)
        results["sarvam_reachable"] = f"✅ HTTP {r.status_code}"
    except Exception as e:
        results["sarvam_reachable"] = f"❌ {e}"

    # 6. TWILIO_FROM_NUMBER format
    fnum = env("TWILIO_FROM_NUMBER","")
    if fnum.startswith("whatsapp:"):
        results["from_number_format"] = f"✅ Correct format: {fnum}"
    elif fnum:
        results["from_number_format"] = f"⚠️ Missing 'whatsapp:' prefix — got: {fnum}"
    else:
        results["from_number_format"] = "❌ MISSING"

    results["python_version"] = sys.version
    results["app_version"]    = "v16.1"

    # Return as plain text for easy reading
    lines = [f"GutInvoice v16.1 — Debug Report",
             f"Time: {datetime.now().isoformat()}", ""]
    for k, v in results.items():
        lines.append(f"  {k}: {v}")
    return "\n".join(lines), 200, {"Content-Type": "text/plain"}

@app.route("/test-whatsapp")
def test_whatsapp():
    """Send a test message to yourself — visit this URL to verify Twilio is working"""
    test_to = request.args.get("to","")
    if not test_to:
        return "Add ?to=whatsapp:+91XXXXXXXXXX to the URL", 400
    try:
        get_twilio().messages.create(
            from_=env("TWILIO_FROM_NUMBER"),
            to=test_to,
            body="✅ GutInvoice v16.1 is live and working! Your webhook is connected correctly."
        )
        return f"✅ Test message sent to {test_to}", 200
    except Exception as e:
        return f"❌ Failed: {e}", 500

if __name__ == "__main__":
    port = int(env("PORT",5000))
    log.info(f"🚀 GutInvoice v16.1 starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
