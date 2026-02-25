"""
GutInvoice — Every Invoice has a Voice
v16 — Template-Exact PDFs | Sequential Invoice Numbers | Cancel/Credit Note Flow
==================================================================================
SINGLE FILE DEPLOYMENT — no pdf_generators.py needed.

KEY CHANGES FROM v15:
  ✅ All 5 PDF templates rebuilt to match approved layouts exactly
  ✅ ₹ symbol used throughout (not Rs.)
  ✅ Sequential invoice numbers: {PREFIX}{SEQ:03d}-{MM}{YYYY} e.g. TEJ001-022026
  ✅ Invoice numbers never reused (cancelled invoices keep their number voided)
  ✅ Cancel command: "cancel TEJ001-022026" → auto credit note → sent to WhatsApp
  ✅ Monthly report: 5 sections (A: Tax, B: BOS, C: NonGST, D: HSN, E: Credit Notes)
  ✅ Monthly report includes FINAL TAX LIABILITY SUMMARY with credit note deductions

ENV VARS REQUIRED (Railway → Variables):
  TWILIO_ACCOUNT_SID
  TWILIO_AUTH_TOKEN
  TWILIO_FROM_NUMBER   (e.g. whatsapp:+14155238886)
  SARVAM_API_KEY
  CLAUDE_API_KEY       (or ANTHROPIC_API_KEY)
  SUPABASE_URL         (e.g. https://xxxx.supabase.co)
  SUPABASE_KEY         (service_role key)

SUPABASE SQL (run once in SQL editor if upgrading from older version):
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

def select_and_generate_pdf(invoice_data: dict, seller_phone: str) -> str:
    itype = (invoice_data.get("invoice_type") or "").upper()
    inv_no = invoice_data.get("invoice_number") or f"GUT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    if   "CREDIT" in itype: pdf_bytes, sub = build_credit_note(invoice_data),     "credit_notes"
    elif "BILL"   in itype: pdf_bytes, sub = build_bill_of_supply(invoice_data),  "invoices"
    elif "TAX"    in itype: pdf_bytes, sub = build_tax_invoice(invoice_data),     "invoices"
    else:                   pdf_bytes, sub = build_nongst_invoice(invoice_data),  "invoices"
    phone = _clean_phone(seller_phone)
    return upload_pdf_to_supabase(pdf_bytes, f"{phone}/{sub}/{inv_no}.pdf")

def generate_report_pdf_and_upload(report_data: dict, seller_phone: str) -> str:
    month = report_data.get("report_month","Report")
    year  = report_data.get("report_year", datetime.now().year)
    phone = _clean_phone(seller_phone)
    return upload_pdf_to_supabase(build_monthly_report(report_data),
                                  f"{phone}/reports/{month}_{year}.pdf")

# ═══════════════════════════════════════════════════════════════════════════════
# SUPABASE HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def sb_h():
    return {"apikey": env("SUPABASE_KEY"),
            "Authorization": f"Bearer {env('SUPABASE_KEY')}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"}

def sb_url(table, q=""):
    return f"{env('SUPABASE_URL')}/rest/v1/{table}{q}"

def get_seller(phone):
    r = requests.get(sb_url("sellers",f"?phone_number=eq.{phone}&limit=1"),
                     headers=sb_h(), timeout=10)
    d = safe_json(r,"get_seller")
    return d[0] if isinstance(d,list) and d else None

def create_seller(phone):
    r = requests.post(sb_url("sellers"), headers=sb_h(),
                      json={"phone_number":phone,"onboarding_step":"language_asked",
                            "language":"english","created_at":datetime.utcnow().isoformat()},
                      timeout=10)
    d = safe_json(r,"create_seller")
    return d[0] if isinstance(d,list) and d else d

def update_seller(phone, updates):
    r = requests.patch(sb_url("sellers",f"?phone_number=eq.{phone}"),
                       headers=sb_h(), json=updates, timeout=10)
    return safe_json(r,"update_seller")

def save_invoice(phone, inv_data, pdf_url):
    d = inv_data
    payload = {
        "seller_phone":   phone,
        "invoice_type":   d.get("invoice_type","TAX INVOICE"),
        "invoice_number": d.get("invoice_number",""),
        "customer_name":  d.get("customer_name",""),
        "total_amount":   d.get("total_amount",0),
        "taxable_value":  d.get("taxable_value",0),
        "cgst":           d.get("cgst",0),
        "sgst":           d.get("sgst",0),
        "igst":           d.get("igst",0),
        "cgst_rate":      d.get("cgst_rate",0),
        "sgst_rate":      d.get("sgst_rate",0),
        "igst_rate":      d.get("igst_rate",0),
        "invoice_data":   json.dumps(d),
        "pdf_url":        pdf_url,
        "created_at":     datetime.utcnow().isoformat(),
        "invoice_month":  datetime.utcnow().month,
        "invoice_year":   datetime.utcnow().year,
        "invoice_date":   d.get("invoice_date",""),
        "is_cancelled":   False,
        "credit_note_for": d.get("original_invoice_number",""),
    }
    r = requests.post(sb_url("invoices"), headers=sb_h(), json=payload, timeout=10)
    return safe_json(r,"save_invoice")

def cancel_invoice_in_db(phone, invoice_number):
    r = requests.patch(
        sb_url("invoices",f"?seller_phone=eq.{phone}&invoice_number=eq.{invoice_number}"),
        headers=sb_h(), json={"is_cancelled": True}, timeout=10
    )
    return safe_json(r,"cancel_invoice")

def get_invoice_by_number(phone, invoice_number):
    r = requests.get(
        sb_url("invoices",f"?seller_phone=eq.{phone}&invoice_number=eq.{invoice_number}&limit=1"),
        headers=sb_h(), timeout=10
    )
    d = safe_json(r,"get_invoice")
    return d[0] if isinstance(d,list) and d else None

def get_all_monthly_invoices(phone, month, year):
    r = requests.get(
        sb_url("invoices",f"?seller_phone=eq.{phone}&invoice_month=eq.{month}&invoice_year=eq.{year}"),
        headers=sb_h(), timeout=15
    )
    return safe_json(r,"monthly_invoices")

# ═══════════════════════════════════════════════════════════════════════════════
# SEQUENTIAL INVOICE NUMBERING
# ═══════════════════════════════════════════════════════════════════════════════

def get_invoice_prefix(seller):
    biz     = (seller.get("business_name") or seller.get("seller_name") or "GUT").upper()
    cleaned = re.sub(r"[^A-Z0-9]","",biz)
    return (cleaned + "GUT")[:3]

def get_next_seq(phone, month, year, is_credit=False):
    q = (f"?seller_phone=eq.{phone}&invoice_month=eq.{month}&invoice_year=eq.{year}"
         f"&invoice_type={'eq.CREDIT NOTE' if is_credit else 'neq.CREDIT NOTE'}&select=id")
    try:
        r = requests.get(sb_url("invoices",q), headers=sb_h(), timeout=10)
        return len(safe_json(r,"seq")) + 1
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
    r = requests.get(media_url, auth=(env("TWILIO_ACCOUNT_SID"),env("TWILIO_AUTH_TOKEN")),
                     timeout=30)
    if r.status_code != 200:
        raise Exception(f"Audio download failed {r.status_code}")
    log.info(f"Audio: {len(r.content)} bytes")
    return r.content

def transcribe_audio(audio_bytes, language="telugu"):
    lang_map = {"telugu":"te-IN","english":"en-IN","both":"te-IN"}
    r = requests.post(
        "https://api.sarvam.ai/speech-to-text",
        files={"file":("audio.ogg",audio_bytes,"audio/ogg")},
        data={"model":"saaras:v2.5","language_code":lang_map.get(language,"te-IN"),
              "with_disfluencies":"false"},
        headers={"api-subscription-key":env("SARVAM_API_KEY")},
        timeout=60
    )
    tr = safe_json(r,"Sarvam").get("transcript","")
    log.info(f"Transcript: {tr}")
    return tr

def extract_invoice_data(transcript, seller, phone, month, year):
    sname  = seller.get("business_name") or seller.get("seller_name") or ""
    saddr  = seller.get("address") or seller.get("seller_address") or ""
    sgstin = seller.get("gstin") or seller.get("seller_gstin") or ""
    inv_no = generate_invoice_number(phone, seller, month, year)
    today  = datetime.now().strftime("%d/%m/%Y")

    system = (
        'You are a GST invoice data extractor for Indian businesses. '
        'Extract invoice details from the voice transcription and return ONLY valid JSON. '
        'Rules: amounts as numbers only; dates as DD/MM/YYYY; '
        'invoice_type = "TAX INVOICE" (GST mentioned), "BILL OF SUPPLY" (composition/exempt), '
        '"INVOICE" (no GSTIN for seller); '
        'cgst_rate=sgst_rate=gst_rate/2 for intrastate; igst_rate=full for interstate; '
        'calculate all totals correctly; reverse_charge="No" by default.'
    )
    prompt = (
        f'Transcription: "{transcript}"\n\n'
        f'Pre-filled seller (use as-is):\n'
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
        f'  "declaration": "We declare this invoice shows the actual price of goods/services described.",\n'
        f'  "payment_terms": "Pay within 30 days"\n}}'
    )
    msg  = get_claude().messages.create(
        model="claude-haiku-4-5-20251001", max_tokens=1500,
        system=system, messages=[{"role":"user","content":prompt}]
    )
    text = msg.content[0].text.strip()
    if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
    elif "```"   in text: text = text.split("```")[1].split("```")[0].strip()
    s = text.find("{"); e = text.rfind("}")+1
    if s==-1 or e==0: raise Exception(f"No JSON from Claude: {text[:200]}")
    data = json.loads(text[s:e])
    log.info(f"Invoice: {data.get('invoice_type')} #{data.get('invoice_number')} | {data.get('customer_name')}")
    return data

def send_invoice_whatsapp(twilio, to, pdf_url, inv, lang="english"):
    total = fmt(inv.get("total_amount",0))
    itype = inv.get("invoice_type","Invoice")
    inv_no = inv.get("invoice_number","")
    cname  = inv.get("customer_name","")
    if lang == "telugu":
        body = (f"✅ *మీ {itype} Ready!*\n\n📋 Invoice No: {inv_no}\n"
                f"👤 Customer: {cname}\n💰 Total: ₹ {total}\n\n"
                f"Powered by *GutInvoice* 🎙️\n_మీ గొంతే మీ Invoice_")
    else:
        body = (f"✅ *Your {itype} is Ready!*\n\n📋 Invoice No: {inv_no}\n"
                f"👤 Customer: {cname}\n💰 Total: ₹ {total}\n\n"
                f"Powered by *GutInvoice* 🎙️\n_Your voice. Your invoice._")
    twilio.messages.create(from_=env("TWILIO_FROM_NUMBER"),to=to,body=body,media_url=[pdf_url])
    log.info(f"Invoice sent to {to}")

# ═══════════════════════════════════════════════════════════════════════════════
# CANCEL / CREDIT NOTE FLOW
# ═══════════════════════════════════════════════════════════════════════════════

def is_cancel_request(text):
    kw = ["cancel","void","రద్దు","wrong invoice","delete invoice","reverse invoice"]
    return any(k in text.lower() for k in kw)

def parse_invoice_ref(text):
    """Extract invoice number like TEJ001-022026 from cancel text"""
    m = re.search(r"([A-Z]{2,6}\d{3}-\d{6})", text.upper())
    if m: return m.group(1)
    m = re.search(r"(\d{3}-\d{6})", text)
    if m: return m.group(1)
    return None

def handle_cancel_request(from_num, text, seller, twilio, lang):
    ref = parse_invoice_ref(text)
    if not ref:
        msg = ("⚠️ Please specify the invoice number.\nExample: *cancel TEJ001-022026*"
               if lang=="english"
               else "⚠️ Invoice number చెప్పండి.\nExample: *cancel TEJ001-022026*")
        twilio.messages.create(from_=env("TWILIO_FROM_NUMBER"),to=from_num,body=msg)
        return

    orig = get_invoice_by_number(from_num, ref)
    if not orig:
        # Try prepending prefix if user gave only seq-mmyyyy
        prefix = get_invoice_prefix(seller)
        orig = get_invoice_by_number(from_num, f"{prefix}{ref}")

    if not orig:
        msg = (f"⚠️ Invoice *{ref}* not found in your records."
               if lang=="english"
               else f"⚠️ Invoice *{ref}* మీ records లో కనుగొనబడలేదు.")
        twilio.messages.create(from_=env("TWILIO_FROM_NUMBER"),to=from_num,body=msg)
        return

    if orig.get("is_cancelled"):
        msg = (f"⚠️ Invoice *{orig['invoice_number']}* is already cancelled."
               if lang=="english"
               else f"⚠️ Invoice *{orig['invoice_number']}* ఇప్పటికే రద్దు చేయబడింది.")
        twilio.messages.create(from_=env("TWILIO_FROM_NUMBER"),to=from_num,body=msg)
        return

    if orig.get("invoice_type") == "CREDIT NOTE":
        twilio.messages.create(from_=env("TWILIO_FROM_NUMBER"),to=from_num,
                               body="⚠️ Credit notes cannot be cancelled.")
        return

    # Mark original as cancelled (number never reused)
    cancel_invoice_in_db(from_num, orig["invoice_number"])
    log.info(f"Cancelled: {orig['invoice_number']} for {from_num}")

    # Build credit note from original
    try:
        orig_data = json.loads(orig.get("invoice_data","{}"))
    except Exception:
        orig_data = orig
    now    = datetime.utcnow()
    cn_no  = generate_credit_note_number(from_num, seller, now.month, now.year)
    credit = {
        **orig_data,
        "invoice_type":           "CREDIT NOTE",
        "invoice_number":         cn_no,
        "credit_note_number":     cn_no,
        "invoice_date":           now.strftime("%d/%m/%Y"),
        "original_invoice_number": orig["invoice_number"],
        "original_invoice_date":   orig_data.get("invoice_date",""),
        "reason":                 "Cancellation of invoice as requested by seller",
        "credit_reason":          f"Cancellation of invoice {orig['invoice_number']}",
    }
    pdf_url = select_and_generate_pdf(credit, from_num)
    save_invoice(from_num, credit, pdf_url)

    total = fmt(orig_data.get("total_amount",0))
    if lang=="telugu":
        body = (f"✅ *Invoice {orig['invoice_number']} రద్దు చేయబడింది*\n\n"
                f"📋 Credit Note: {cn_no}\n💰 Credit Amount: ₹ {total}\n\n"
                f"Credit Note PDF పంపబడింది.")
    else:
        body = (f"✅ *Invoice {orig['invoice_number']} Cancelled*\n\n"
                f"📋 Credit Note No: {cn_no}\n💰 Credit Amount: ₹ {total}\n\n"
                f"Credit Note PDF has been generated and attached.")
    twilio.messages.create(from_=env("TWILIO_FROM_NUMBER"),to=from_num,
                           body=body, media_url=[pdf_url])
    log.info(f"Credit note {cn_no} sent to {from_num}")

# ═══════════════════════════════════════════════════════════════════════════════
# MONTHLY REPORT HANDLER
# ═══════════════════════════════════════════════════════════════════════════════

MONTH_MAP = {
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
    "జనవరి":1,"ఫిబ్రవరి":2,"మార్చి":3,"ఏప్రిల్":4,"మే":5,"జూన్":6,
    "జులై":7,"ఆగస్టు":8,"సెప్టెంబర్":9,"అక్టోబర్":10,"నవంబర్":11,"డిసెంబర్":12
}
MNAMES = {v:k.capitalize() for k,v in MONTH_MAP.items() if k.isascii()}

def is_report_request(text):
    kw = ["report","summary","రిపోర్ట్","సమరీ","monthly","నెల","last month",
          "tax summary","invoices summary","గత నెల"]
    return any(k in text.lower() for k in kw)

def parse_month_year(text):
    tl = text.lower()
    year = datetime.now().year
    m = re.search(r"20\d{2}",text)
    if m: year = int(m.group())
    for name,num in MONTH_MAP.items():
        if name in tl: return num, year
    return datetime.now().month, year

def _parse_row(raw):
    try: d = json.loads(raw.get("invoice_data","{}"))
    except Exception: d = {}
    return {
        "invoice_number": raw.get("invoice_number",""),
        "invoice_date":   d.get("invoice_date", raw.get("invoice_date","")),
        "customer_name":  raw.get("customer_name",""),
        "invoice_type":   raw.get("invoice_type",""),
        "taxable_value":  float(raw.get("taxable_value",0)),
        "cgst":           float(raw.get("cgst",0)),
        "sgst":           float(raw.get("sgst",0)),
        "igst":           float(raw.get("igst",0)),
        "total_amount":   float(raw.get("total_amount",0)),
        "_data":          d,
        "_cancelled":     raw.get("is_cancelled",False),
    }

def _build_hsn(inv_list):
    hsn = {}
    for inv in inv_list:
        d = inv.get("_data",{})
        cr = float(d.get("cgst_rate",0))
        sr = float(d.get("sgst_rate",0))
        ir = float(d.get("igst_rate",0))
        inter = str(d.get("is_interstate","false")).lower()=="true"
        for item in d.get("items",[]):
            key = str(item.get("hsn_sac","")).strip()
            if not key: continue
            amt = float(item.get("amount",0))
            if key not in hsn:
                hsn[key] = {"hsn":key,"description":item.get("description",""),
                            "taxable":0,"cgst":0,"sgst":0,"igst":0}
            hsn[key]["taxable"] += amt
            if inter: hsn[key]["igst"] += round(amt*ir/100,2)
            else:
                hsn[key]["cgst"] += round(amt*cr/100,2)
                hsn[key]["sgst"] += round(amt*sr/100,2)
    return list(hsn.values())

def handle_report_request(from_num, text, seller, twilio, lang):
    month_num, year = parse_month_year(text)
    mname = MNAMES.get(month_num, str(month_num))
    all_raw = get_all_monthly_invoices(from_num, month_num, year)

    if not all_raw:
        msg = (f"No invoices found for {mname} {year}."
               if lang=="english" else f"{mname} {year} కి invoices లేవు.")
        twilio.messages.create(from_=env("TWILIO_FROM_NUMBER"),to=from_num,body=msg)
        return

    parsed    = [_parse_row(r) for r in all_raw]
    credit_ns = [p for p in parsed if p["invoice_type"]=="CREDIT NOTE"]
    regular   = [p for p in parsed if p["invoice_type"]!="CREDIT NOTE"]
    active    = [p for p in regular if not p.get("_cancelled")]

    tax_inv    = [i for i in active if "TAX"  in i["invoice_type"].upper()]
    bos_inv    = [i for i in active if "BILL" in i["invoice_type"].upper()]
    nongst_inv = [i for i in active if i["invoice_type"].upper() in ("INVOICE","NON-GST","NONGST")]

    gross_tax  = sum(i["taxable_value"] for i in regular)
    gross_cgst = sum(i["cgst"]          for i in regular)
    gross_sgst = sum(i["sgst"]          for i in regular)
    gross_igst = sum(i["igst"]          for i in regular)
    rev_cgst   = sum(i["cgst"]          for i in credit_ns)
    rev_sgst   = sum(i["sgst"]          for i in credit_ns)
    rev_igst   = sum(i["igst"]          for i in credit_ns)
    net_gst    = (gross_cgst+gross_sgst+gross_igst) - (rev_cgst+rev_sgst+rev_igst)

    report = {
        "report_month": mname, "report_year": year,
        "seller_name":  seller.get("business_name") or seller.get("seller_name",""),
        "seller_address": seller.get("address") or seller.get("seller_address",""),
        "seller_gstin": seller.get("gstin") or seller.get("seller_gstin",""),
        "summary": {"total_invoices":len(regular),
                    "taxable_value":gross_tax, "total_gst":net_gst},
        "tax_invoices":    tax_inv,
        "bos_invoices":    bos_inv,
        "nongst_invoices": nongst_inv,
        "hsn_summary":     _build_hsn(active),
        "credit_notes":    credit_ns,
        "final_summary": {
            "gross_taxable":gross_tax, "gross_cgst":gross_cgst,
            "gross_sgst":gross_sgst,   "gross_igst":gross_igst,
            "reversed_cgst":rev_cgst,  "reversed_sgst":rev_sgst,
            "reversed_igst":rev_igst,  "net_gst":net_gst,
        }
    }
    pdf_url = generate_report_pdf_and_upload(report, from_num)
    msg = (f"📊 *{mname} {year} Report Ready!*\n\n"
           f"🧾 Total Invoices: {len(regular)}\n"
           f"💰 Gross Taxable: ₹ {fmt(gross_tax)}\n"
           f"🏷️ Net GST Payable: ₹ {fmt(net_gst)}"
           + (f"\n📋 Credit Notes: {len(credit_ns)}" if credit_ns else ""))
    twilio.messages.create(from_=env("TWILIO_FROM_NUMBER"),to=from_num,
                           body=msg, media_url=[pdf_url])
    log.info(f"Report sent to {from_num}")

# ═══════════════════════════════════════════════════════════════════════════════
# ONBOARDING FLOW
# ═══════════════════════════════════════════════════════════════════════════════

def handle_onboarding(from_num, body, seller, twilio):
    step = seller.get("onboarding_step","language_asked")
    lang = seller.get("language","english")
    tl   = (body or "").strip().lower()

    if step == "language_asked":
        if any(x in tl for x in ["1","english"]):
            update_seller(from_num,{"language":"english","onboarding_step":"registration_asked"})
            msg = ("Great! You chose English 🇬🇧\n\n"
                   "Would you like to register your business details?\n"
                   "Type *YES* to register  |  Type *SKIP* to start invoicing directly")
        elif any(x in tl for x in ["2","telugu","తెలుగు"]):
            update_seller(from_num,{"language":"telugu","onboarding_step":"registration_asked"})
            msg = ("బాగుంది! తెలుగు ఎంచుకున్నారు 🙏\n\n"
                   "మీ వ్యాపార వివరాలు నమోదు చేయాలా?\n"
                   "*YES* type చేయండి  |  *SKIP* type చేస్తే నేరుగా invoice చేయవచ్చు")
        else:
            msg = ("Welcome to *GutInvoice* 🎙️\n_Every Invoice has a Voice_\n\n"
                   "Choose your language:\n1️⃣ English\n2️⃣ Telugu / తెలుగు")
        twilio.messages.create(from_=env("TWILIO_FROM_NUMBER"),to=from_num,body=msg)
        return True

    if step == "registration_asked":
        if any(x in tl for x in ["yes","అవున"]):
            update_seller(from_num,{"onboarding_step":"reg_name"})
            msg = ("Please enter your *Business Name*:" if lang=="english"
                   else "మీ *వ్యాపార పేరు* enter చేయండి:")
        else:
            update_seller(from_num,{"onboarding_step":"complete"})
            msg = ("✅ Setup complete! Send a voice note to create your first invoice. 🎙️"
                   if lang=="english"
                   else "✅ Setup పూర్తయింది! Voice note పంపి invoice చేయండి. 🎙️")
        twilio.messages.create(from_=env("TWILIO_FROM_NUMBER"),to=from_num,body=msg)
        return True

    if step == "reg_name":
        update_seller(from_num,{"business_name":body.strip(),"onboarding_step":"reg_address"})
        msg = ("Enter your *Business Address*:" if lang=="english"
               else "మీ *వ్యాపార చిరునామా* enter చేయండి:")
        twilio.messages.create(from_=env("TWILIO_FROM_NUMBER"),to=from_num,body=msg)
        return True

    if step == "reg_address":
        update_seller(from_num,{"address":body.strip(),"onboarding_step":"reg_gstin"})
        msg = ("Enter your *GSTIN* (or type *SKIP* if unregistered):" if lang=="english"
               else "మీ *GSTIN* enter చేయండి (లేకుంటే *SKIP* type చేయండి):")
        twilio.messages.create(from_=env("TWILIO_FROM_NUMBER"),to=from_num,body=msg)
        return True

    if step == "reg_gstin":
        gstin = "" if "skip" in tl else body.strip().upper()
        update_seller(from_num,{"gstin":gstin,"onboarding_step":"complete"})
        name = seller.get("business_name","")
        msg  = (f"✅ *Registration Complete!*\nWelcome, {name}!\n\n"
                f"Send a voice note to create your first invoice. 🎙️\n"
                f"Type *HELP* for all commands."
                if lang=="english"
                else f"✅ *నమోదు పూర్తయింది!*\n{name} కి స్వాగతం!\n\n"
                     f"Voice note పంపి invoice చేయండి. 🎙️\n"
                     f"Commands కోసం *HELP* type చేయండి.")
        twilio.messages.create(from_=env("TWILIO_FROM_NUMBER"),to=from_num,body=msg)
        return True

    return False

# ═══════════════════════════════════════════════════════════════════════════════
# TWILIO WEBHOOK
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/webhook", methods=["POST"])
def webhook():
    from_num  = request.form.get("From","")
    body      = request.form.get("Body","") or ""
    media_url = request.form.get("MediaUrl0","")
    num_media = int(request.form.get("NumMedia",0))
    log.info(f"Webhook | From:{from_num} | Body:{body[:60]} | Media:{num_media}")

    try:
        twilio = get_twilio()
        seller = get_seller(from_num)

        if not seller:
            seller = create_seller(from_num)
            twilio.messages.create(
                from_=env("TWILIO_FROM_NUMBER"), to=from_num,
                body=("Welcome to *GutInvoice* 🎙️\n_Every Invoice has a Voice_\n\n"
                      "Choose your language:\n1️⃣ English\n2️⃣ Telugu / తెలుగు")
            )
            return Response("",status=200)

        lang = seller.get("language","english")
        step = seller.get("onboarding_step","complete")

        if step != "complete":
            handle_onboarding(from_num,body,seller,twilio)
            return Response("",status=200)

        tl = (body or "").strip().lower()

        # Commands
        if tl in ("help","హెల్ప్","status"):
            name  = seller.get("business_name") or from_num
            gstin = seller.get("gstin") or "Not set"
            addr  = seller.get("address") or "Not set"
            twilio.messages.create(
                from_=env("TWILIO_FROM_NUMBER"), to=from_num,
                body=(f"📋 *GutInvoice — Your Profile*\n\n"
                      f"👤 {name}\n📍 {addr}\n🔑 GSTIN: {gstin}\n\n"
                      f"🎙️ *Voice note* → Create invoice\n"
                      f"📊 *report feb 2026* → Monthly report\n"
                      f"❌ *cancel TEJ001-022026* → Cancel + credit note\n"
                      f"✏️ *update* → Update profile")
            )
            return Response("",status=200)

        if tl in ("update","register"):
            update_seller(from_num,{"onboarding_step":"reg_name"})
            twilio.messages.create(
                from_=env("TWILIO_FROM_NUMBER"), to=from_num,
                body=("Enter your *Business Name*:" if lang=="english"
                      else "మీ *వ్యాపార పేరు* enter చేయండి:")
            )
            return Response("",status=200)

        if is_cancel_request(body) and not num_media:
            handle_cancel_request(from_num,body,seller,twilio,lang)
            return Response("",status=200)

        if is_report_request(body) and not num_media:
            handle_report_request(from_num,body,seller,twilio,lang)
            return Response("",status=200)

        if num_media and media_url:
            twilio.messages.create(
                from_=env("TWILIO_FROM_NUMBER"), to=from_num,
                body=("🎙️ Processing your voice note... ~20 seconds." if lang=="english"
                      else "🎙️ Voice note process అవుతుంది... ~20 seconds.")
            )
            audio = download_audio(media_url)
            tr    = transcribe_audio(audio, lang)
            if not tr.strip():
                twilio.messages.create(
                    from_=env("TWILIO_FROM_NUMBER"), to=from_num,
                    body=("⚠️ Could not understand audio. Please try again clearly."
                          if lang=="english"
                          else "⚠️ Audio అర్థం కాలేదు. మళ్ళీ clearly చెప్పండి.")
                )
                return Response("",status=200)

            if is_cancel_request(tr):
                handle_cancel_request(from_num,tr,seller,twilio,lang)
                return Response("",status=200)
            if is_report_request(tr):
                handle_report_request(from_num,tr,seller,twilio,lang)
                return Response("",status=200)

            now = datetime.utcnow()
            inv = extract_invoice_data(tr, seller, from_num, now.month, now.year)
            url = select_and_generate_pdf(inv, from_num)
            save_invoice(from_num, inv, url)
            send_invoice_whatsapp(twilio, from_num, url, inv, lang)
            log.info(f"✅ Done | {inv.get('invoice_number')} | {from_num}")
            return Response("",status=200)

        twilio.messages.create(
            from_=env("TWILIO_FROM_NUMBER"), to=from_num,
            body=("🎙️ Send a *voice note* to create an invoice.\nType *HELP* for commands."
                  if lang=="english"
                  else "🎙️ Invoice కోసం voice note పంపండి.\nCommands కోసం *HELP* type చేయండి.")
        )
        return Response("",status=200)

    except Exception as e:
        log.error(f"Webhook error: {e}", exc_info=True)
        try:
            twilio = get_twilio()
            lang = "english"
            try:
                s = get_seller(from_num)
                lang = (s or {}).get("language","english")
            except Exception: pass
            twilio.messages.create(
                from_=env("TWILIO_FROM_NUMBER"), to=from_num,
                body=("⚠️ Something went wrong. Please try again."
                      if lang=="english"
                      else "⚠️ ఏదో తప్పు జరిగింది. మళ్ళీ try చేయండి.")
            )
        except Exception: pass
        return Response("",status=200)

# ═══════════════════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/health")
def health():
    keys = ["TWILIO_ACCOUNT_SID","TWILIO_AUTH_TOKEN","TWILIO_FROM_NUMBER",
            "SARVAM_API_KEY","SUPABASE_URL","SUPABASE_KEY"]
    checks = {k: bool(env(k)) for k in keys}
    checks["CLAUDE_API_KEY"] = bool(env("CLAUDE_API_KEY") or env("ANTHROPIC_API_KEY"))
    try:
        r = requests.get(sb_url("sellers","?limit=1"), headers=sb_h(), timeout=5)
        checks["supabase_connection"] = (r.status_code == 200)
    except Exception:
        checks["supabase_connection"] = False
    ok = all(checks.values())
    return {"status":"healthy" if ok else "missing_config",
            "version":"v16","checks":checks,
            "timestamp":datetime.now().isoformat()}, 200 if ok else 500

# ═══════════════════════════════════════════════════════════════════════════════
# HOME PAGE
# ═══════════════════════════════════════════════════════════════════════════════

HOME_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>GutInvoice — Every Invoice has a Voice</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0A0F1E;color:#fff;
     min-height:100vh;display:flex;flex-direction:column;align-items:center;
     justify-content:center;text-align:center;padding:40px 20px}
h1{font-size:48px;font-weight:900;color:#FF6B35;margin-bottom:8px}
h2{font-size:18px;color:#94a3b8;margin-bottom:30px}
.pill{display:inline-flex;align-items:center;gap:8px;background:rgba(16,185,129,.1);
      border:1px solid rgba(16,185,129,.3);padding:8px 20px;border-radius:50px;
      font-size:13px;color:#10B981;font-weight:700;margin-bottom:30px}
.dot{width:8px;height:8px;background:#10B981;border-radius:50%;animation:blink 2s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}
.grid{display:flex;gap:20px;flex-wrap:wrap;justify-content:center;max-width:950px}
.card{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);
      border-radius:16px;padding:24px;width:210px}
.card h3{font-size:28px;margin-bottom:8px}
.card p{font-size:13px;color:#94a3b8;line-height:1.5}
footer{margin-top:50px;font-size:12px;color:#475569;line-height:1.8}
</style>
</head>
<body>
<div class="pill"><div class="dot"></div>LIVE — v16</div>
<h1>GutInvoice</h1>
<h2>Every Invoice has a Voice 🎙️</h2>
<div class="grid">
  <div class="card"><h3>🎙️</h3><p>Send a voice note in Telugu or English on WhatsApp</p></div>
  <div class="card"><h3>🤖</h3><p>AI transcribes speech and extracts all invoice details</p></div>
  <div class="card"><h3>📄</h3><p>GST-compliant PDF with sequential invoice number in 30 sec</p></div>
  <div class="card"><h3>❌</h3><p>Say "cancel TEJ001-022026" → credit note auto-generated</p></div>
</div>
<footer>
  Built for Telugu-speaking MSMEs · Hyderabad, India<br>
  Powered by Tallbag Advisory and Tech Solutions Private Limited · +91 7702424946
</footer>
</body></html>"""

@app.route("/")
def home():
    return render_template_string(HOME_HTML)

if __name__ == "__main__":
    port = int(env("PORT",5000))
    log.info(f"🚀 GutInvoice v16 starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
