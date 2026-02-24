"""
GutInvoice v12 — pdf_generators.py
====================================
Pure Python ReportLab PDF generation. Replaces Carbone.io entirely.
4 document types, all matching the approved template layouts exactly.

Entry points (called from main.py):
    select_and_generate_pdf(invoice_data, seller_phone)   → public URL
    generate_report_pdf_local(report_data, seller_phone)  → public URL
"""

import os
import io
import requests
import logging
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle,
    Paragraph, Spacer, HRFlowable
)

log = logging.getLogger(__name__)

# ─── BRAND PALETTE ────────────────────────────────────────────────────────────
TEAL       = colors.HexColor("#028090")
TEAL_LIGHT = colors.HexColor("#E0F4F6")
TEAL_MID   = colors.HexColor("#B2DFE5")
DARK       = colors.HexColor("#1A1A2E")
DARK2      = colors.HexColor("#333333")
GREY       = colors.HexColor("#666666")
LGREY      = colors.HexColor("#F5F5F5")
WHITE      = colors.white
ORANGE     = colors.HexColor("#FF6B35")
GREEN      = colors.HexColor("#10B981")

PAGE_W, PAGE_H = A4
M = 14 * mm          # left/right margin
W = PAGE_W - 2 * M   # usable width

# ─── MANDATORY FOOTER TEXT (as per spec) ─────────────────────────────────────
FOOTER_BRAND = "Powered by GutInvoice, Every Invoice has a voice !!"
FOOTER_DEV   = "Developed by Tallbag Advisory and Tech Solutions Private Limited  |  Contact: +91 7702424946"
FOOTER_DISC  = "Disclaimer: Double check the Invoice details generated before sharing to anyone"


# ═══════════════════════════════════════════════════════════════════════════════
# STYLE FACTORY
# ═══════════════════════════════════════════════════════════════════════════════
def S(name, **kwargs):
    """Quick ParagraphStyle factory."""
    defaults = dict(fontSize=9, textColor=DARK2, fontName="Helvetica",
                    alignment=TA_LEFT, leading=12)
    defaults.update(kwargs)
    return ParagraphStyle(name, **defaults)


STYLES = {
    "hdr_brand":  S("hdr_brand",  fontSize=13, textColor=WHITE, fontName="Helvetica-Bold", alignment=TA_LEFT),
    "hdr_type":   S("hdr_type",   fontSize=16, textColor=WHITE, fontName="Helvetica-Bold", alignment=TA_CENTER),
    "lbl":        S("lbl",        fontSize=7.5, textColor=TEAL,  fontName="Helvetica-Bold"),
    "val":        S("val",        fontSize=9,   textColor=DARK2,  fontName="Helvetica-Bold"),
    "body":       S("body",       fontSize=9,   textColor=DARK2),
    "body_r":     S("body_r",     fontSize=9,   textColor=DARK2,  alignment=TA_RIGHT),
    "bold":       S("bold",       fontSize=9,   textColor=DARK,   fontName="Helvetica-Bold"),
    "bold_r":     S("bold_r",     fontSize=9,   textColor=DARK,   fontName="Helvetica-Bold", alignment=TA_RIGHT),
    "bold_w":     S("bold_w",     fontSize=9,   textColor=WHITE,  fontName="Helvetica-Bold"),
    "bold_wr":    S("bold_wr",    fontSize=9,   textColor=WHITE,  fontName="Helvetica-Bold", alignment=TA_RIGHT),
    "tbl_hdr":    S("tbl_hdr",    fontSize=8,   textColor=WHITE,  fontName="Helvetica-Bold", alignment=TA_CENTER),
    "tbl_c":      S("tbl_c",      fontSize=8,   textColor=DARK2,  alignment=TA_CENTER),
    "tbl_r":      S("tbl_r",      fontSize=8,   textColor=DARK2,  alignment=TA_RIGHT),
    "tbl_l":      S("tbl_l",      fontSize=8,   textColor=DARK2),
    "small":      S("small",      fontSize=7.5, textColor=GREY),
    "small_r":    S("small_r",    fontSize=7.5, textColor=DARK2,  alignment=TA_RIGHT),
    "footer":     S("footer",     fontSize=7,   textColor=GREY,   fontName="Helvetica-Oblique", alignment=TA_CENTER, leading=10),
    "footer_disc":S("footer_disc",fontSize=6.8, textColor=colors.HexColor("#CC4400"), fontName="Helvetica-Oblique", alignment=TA_CENTER, leading=10),
    "grand_l":    S("grand_l",    fontSize=10,  textColor=WHITE,  fontName="Helvetica-Bold"),
    "grand_r":    S("grand_r",    fontSize=10,  textColor=WHITE,  fontName="Helvetica-Bold", alignment=TA_RIGHT),
    "sec_hdr":    S("sec_hdr",    fontSize=9,   textColor=WHITE,  fontName="Helvetica-Bold"),
    "sum_c":      S("sum_c",      fontSize=9,   textColor=WHITE,  alignment=TA_CENTER, leading=14),
}


# ═══════════════════════════════════════════════════════════════════════════════
# SHARED UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════
def p(text, style="body"):
    """Create Paragraph with style name or ParagraphStyle object."""
    st = STYLES[style] if isinstance(style, str) else style
    return Paragraph(str(text) if text is not None else "", st)


def fmt(val):
    """Format number as Indian currency."""
    try:
        return f"{float(str(val).replace(',', '')):,.2f}"
    except:
        return str(val) if val else "0.00"


def num_words(n):
    """Convert number to Indian words."""
    try:
        n = int(float(str(n).replace(",", "")))
    except:
        return "Zero"
    if n == 0:
        return "Zero"
    ones  = ["","One","Two","Three","Four","Five","Six","Seven","Eight","Nine",
             "Ten","Eleven","Twelve","Thirteen","Fourteen","Fifteen","Sixteen",
             "Seventeen","Eighteen","Nineteen"]
    tens  = ["","","Twenty","Thirty","Forty","Fifty","Sixty","Seventy","Eighty","Ninety"]
    def bh(x):
        return ones[x] if x < 20 else tens[x//10] + (" " + ones[x%10] if x%10 else "")
    def bt(x):
        return ones[x//100] + " Hundred" + (" " + bh(x%100) if x%100 else "") if x >= 100 else bh(x)
    r = ""
    cr, n = divmod(n, 10_000_000)
    la, n = divmod(n, 100_000)
    th, n = divmod(n, 1_000)
    if cr: r += bt(cr) + " Crore "
    if la: r += bt(la) + " Lakh "
    if th: r += bt(th) + " Thousand "
    if n:  r += bt(n)
    return r.strip() + " Rupees Only"


def footer_block():
    """Return list of footer flowables — 3 distinct lines."""
    return [
        Spacer(1, 4*mm),
        HRFlowable(width="100%", thickness=0.5, color=TEAL_MID),
        Spacer(1, 1.5*mm),
        p(FOOTER_BRAND, "footer"),
        Spacer(1, 0.8*mm),
        p(FOOTER_DEV, "footer"),
        Spacer(1, 1*mm),
        p(FOOTER_DISC, "footer_disc"),
    ]


def doc_header(doc_type_label):
    """Full-width centered document type header bar (teal background)."""
    data = [[p(doc_type_label, "hdr_type")]]
    t = Table(data, colWidths=[W])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), TEAL),
        ("TOPPADDING",    (0,0),(-1,-1), 11),
        ("BOTTOMPADDING", (0,0),(-1,-1), 11),
        ("LEFTPADDING",   (0,0),(-1,-1), 10),
        ("RIGHTPADDING",  (0,0),(-1,-1), 10),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
    ]))
    return t


def two_box(left_rows, right_rows, lw=0.55, rw=0.45):
    """Two-column box with teal header styling."""
    rows = []
    max_r = max(len(left_rows), len(right_rows))
    for i in range(max_r):
        lc = left_rows[i]  if i < len(left_rows)  else p("")
        rc = right_rows[i] if i < len(right_rows) else p("")
        rows.append([lc, rc])
    t = Table(rows, colWidths=[W*lw, W*rw])
    t.setStyle(TableStyle([
        ("BOX",           (0,0),(-1,-1), 0.8, TEAL_MID),
        ("INNERGRID",     (0,0),(-1,-1), 0.4, TEAL_MID),
        ("BACKGROUND",    (0,0),(-1,0),  TEAL_LIGHT),
        ("TOPPADDING",    (0,0),(-1,-1), 4),
        ("BOTTOMPADDING", (0,0),(-1,-1), 4),
        ("LEFTPADDING",   (0,0),(-1,-1), 7),
        ("VALIGN",        (0,0),(-1,-1), "TOP"),
    ]))
    return t


def full_box(rows):
    """Single full-width box."""
    t = Table([[r] for r in rows], colWidths=[W])
    t.setStyle(TableStyle([
        ("BOX",           (0,0),(-1,-1), 0.8, TEAL_MID),
        ("INNERGRID",     (0,0),(-1,-1), 0.4, TEAL_MID),
        ("BACKGROUND",    (0,0),(0,0),   TEAL_LIGHT),
        ("TOPPADDING",    (0,0),(-1,-1), 4),
        ("BOTTOMPADDING", (0,0),(-1,-1), 4),
        ("LEFTPADDING",   (0,0),(-1,-1), 7),
    ]))
    return t


def items_table(items, col_widths, headers, row_builder):
    """Generic items table with teal header + alternating rows."""
    data = [[p(h, "tbl_hdr") for h in headers]]
    for it in items:
        data.append(row_builder(it))
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BOX",           (0,0),(-1,-1), 0.8, TEAL_MID),
        ("INNERGRID",     (0,0),(-1,-1), 0.3, LGREY),
        ("BACKGROUND",    (0,0),(-1,0),  TEAL),
        ("FONTNAME",      (0,0),(-1,0),  "Helvetica-Bold"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [WHITE, TEAL_LIGHT]),
        ("TOPPADDING",    (0,0),(-1,-1), 4),
        ("BOTTOMPADDING", (0,0),(-1,-1), 4),
        ("LEFTPADDING",   (0,0),(-1,-1), 5),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ("FONTSIZE",      (0,1),(-1,-1), 8),
    ]))
    return t


def totals_table(rows_data):
    """Right-aligned totals table — last row is GRAND TOTAL (teal bg)."""
    t = Table(rows_data, colWidths=[W*0.72, W*0.28])
    n = len(rows_data)
    t.setStyle(TableStyle([
        ("BOX",           (0,0),(-1,-1), 0.8, TEAL_MID),
        ("INNERGRID",     (0,0),(-1,-1), 0.4, LGREY),
        ("TOPPADDING",    (0,0),(-1,-1), 5),
        ("BOTTOMPADDING", (0,0),(-1,-1), 5),
        ("LEFTPADDING",   (0,0),(-1,-1), 8),
        ("BACKGROUND",    (0,n-1),(-1,n-1), TEAL),
    ]))
    return t


def signatory_box(seller_name):
    data = [[p(f"<b>For {seller_name}</b>", "body")],
            [p("", "body")],
            [p("", "body")],
            [p("Authorised Signatory", "body")]]
    t = Table(data, colWidths=[W])
    t.setStyle(TableStyle([
        ("BOX",           (0,0),(-1,-1), 0.8, TEAL_MID),
        ("TOPPADDING",    (0,0),(-1,-1), 5),
        ("BOTTOMPADDING", (0,0),(-1,-1), 5),
        ("LEFTPADDING",   (0,0),(-1,-1), 8),
    ]))
    return t


def decl_box(declaration, payment_terms, show_split=False):
    """Declaration box. show_split=True puts decl left, payment right (TAX INVOICE style)."""
    if show_split:
        data = [[
            p(f"<b>DECLARATION</b><br/>{declaration}", "body"),
            p(f"<b>PAYMENT TERMS</b><br/>{payment_terms}", "body"),
        ]]
        t = Table(data, colWidths=[W*0.6, W*0.4])
        t.setStyle(TableStyle([
            ("BOX",           (0,0),(-1,-1), 0.8, TEAL_MID),
            ("INNERGRID",     (0,0),(-1,-1), 0.5, TEAL_MID),
            ("TOPPADDING",    (0,0),(-1,-1), 6),
            ("BOTTOMPADDING", (0,0),(-1,-1), 6),
            ("LEFTPADDING",   (0,0),(-1,-1), 8),
            ("VALIGN",        (0,0),(-1,-1), "TOP"),
        ]))
    else:
        data = [[p(f"<b>DECLARATION (MANDATORY FOR COMPOSITION DEALERS)</b><br/>"
                   f"{declaration}<br/><br/>"
                   f"<b>Payment Terms:</b> {payment_terms}", "body")]]
        t = Table(data, colWidths=[W])
        t.setStyle(TableStyle([
            ("BOX",           (0,0),(-1,-1), 0.8, TEAL_MID),
            ("TOPPADDING",    (0,0),(-1,-1), 6),
            ("BOTTOMPADDING", (0,0),(-1,-1), 6),
            ("LEFTPADDING",   (0,0),(-1,-1), 8),
        ]))
    return t


def sp(h=2):
    return Spacer(1, h*mm)


# ═══════════════════════════════════════════════════════════════════════════════
# SUPABASE STORAGE UPLOAD
# ═══════════════════════════════════════════════════════════════════════════════
def upload_pdf_to_supabase(pdf_bytes: bytes, file_path: str) -> str:
    supabase_url = os.environ.get("SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_KEY", "")
    upload_url   = f"{supabase_url}/storage/v1/object/invoices/{file_path}"
    r = requests.post(
        upload_url,
        headers={
            "Authorization": f"Bearer {supabase_key}",
            "apikey":         supabase_key,
            "Content-Type":   "application/pdf",
            "x-upsert":       "true",
        },
        data=pdf_bytes,
        timeout=30
    )
    if r.status_code not in (200, 201):
        raise Exception(f"Supabase upload failed {r.status_code}: {r.text[:300]}")
    public_url = f"{supabase_url}/storage/v1/object/public/invoices/{file_path}"
    log.info(f"PDF uploaded → {public_url}")
    return public_url


# ═══════════════════════════════════════════════════════════════════════════════
# BUILD TAX INVOICE
# ═══════════════════════════════════════════════════════════════════════════════
def build_tax_invoice(d: dict) -> bytes:
    """
    Template (from spec):
      Header: GutInvoice | TAX INVOICE
      Seller: Business Name, Address, GSTIN | Invoice No, Date, Place of Supply, Reverse Charge
      Bill To: Name, Address, GSTIN
      Items: # | Description | HSN/SAC | Qty | Unit | Rate | Amount
      Tax: Taxable Value | CGST@% | SGST@% | IGST@% | GRAND TOTAL
      Declaration (left) | Payment Terms (right)
      Authorised Signatory
      Footer
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=M, rightMargin=M,
                            topMargin=M, bottomMargin=M)
    el = []

    # ── Header ────────────────────────────────────────────────────────────────
    el.append(doc_header("TAX INVOICE"))
    el.append(sp(3))

    # ── Seller Details | Invoice Details ─────────────────────────────────────
    el.append(two_box(
        left_rows=[
            p("SELLER DETAILS", "lbl"),
            p(f"<b>Business Name:</b> {d.get('seller_name','')}", "body"),
            p(f"<b>Address:</b> {d.get('seller_address','')}", "body"),
            p(f"<b>GSTIN:</b> {d.get('seller_gstin','N/A')}", "body"),
        ],
        right_rows=[
            p("INVOICE DETAILS", "lbl"),
            p(f"<b>Invoice No:</b> {d.get('invoice_number','')}", "body"),
            p(f"<b>Invoice Date:</b> {d.get('invoice_date','')}", "body"),
            p(f"<b>Place of Supply:</b> {d.get('place_of_supply','')}", "body"),
            p(f"<b>Reverse Charge:</b> {d.get('reverse_charge','No')}", "body"),
        ]
    ))
    el.append(sp(2))

    # ── Bill To ───────────────────────────────────────────────────────────────
    el.append(full_box([
        p("BILL TO (CUSTOMER DETAILS)", "lbl"),
        p(f"<b>Name:</b> {d.get('customer_name','')}", "body"),
        p(f"<b>Address:</b> {d.get('customer_address','')}", "body"),
        p(f"<b>GSTIN:</b> {d.get('customer_gstin','') or 'Unregistered'}", "body"),
    ]))
    el.append(sp(2))

    # ── Line Items ────────────────────────────────────────────────────────────
    cw = [W*0.05, W*0.30, W*0.10, W*0.07, W*0.08, W*0.18, W*0.22]
    hdrs = ["#", "Description", "HSN/SAC", "Qty", "Unit", "Rate (₹)", "Amount (₹)"]
    def row(it):
        return [
            p(it.get("sno",""),         "tbl_c"),
            p(it.get("description",""), "tbl_l"),
            p(it.get("hsn_sac",""),     "tbl_c"),
            p(fmt(it.get("qty",0)),     "tbl_r"),
            p(it.get("unit","Nos"),     "tbl_c"),
            p(fmt(it.get("rate",0)),    "tbl_r"),
            p(fmt(it.get("amount",0)),  "tbl_r"),
        ]
    el.append(items_table(d.get("items",[]), cw, hdrs, row))
    el.append(sp(2))

    # ── Tax Summary ───────────────────────────────────────────────────────────
    cgst_r = d.get("cgst_rate",0);  cgst_a = fmt(d.get("cgst_amount",0))
    sgst_r = d.get("sgst_rate",0);  sgst_a = fmt(d.get("sgst_amount",0))
    igst_r = d.get("igst_rate",0);  igst_a = fmt(d.get("igst_amount",0))

    tax_rows = [
        [p("Taxable Value", "body"),      p(f"₹ {fmt(d.get('taxable_value',0))}", "body_r")],
    ]
    if float(str(d.get("cgst_amount",0)).replace(",","")) > 0:
        tax_rows.append([p(f"CGST @ {cgst_r}%","body"), p(f"₹ {cgst_a}","body_r")])
    if float(str(d.get("sgst_amount",0)).replace(",","")) > 0:
        tax_rows.append([p(f"SGST @ {sgst_r}%","body"), p(f"₹ {sgst_a}","body_r")])
    if float(str(d.get("igst_amount",0)).replace(",","")) > 0:
        tax_rows.append([p(f"IGST @ {igst_r}%","body"), p(f"₹ {igst_a}","body_r")])
    tax_rows.append([p("GRAND TOTAL","grand_l"), p(f"₹ {fmt(d.get('total_amount',0))}","grand_r")])

    el.append(totals_table(tax_rows))
    el.append(sp(2))
    el.append(p(f"<b>Amount in Words:</b> {num_words(d.get('total_amount',0))}", "body"))
    el.append(sp(3))

    # ── Declaration | Payment Terms ───────────────────────────────────────────
    el.append(decl_box(
        d.get("declaration",""),
        d.get("payment_terms","Pay within 15 days"),
        show_split=True
    ))
    el.append(sp(3))

    # ── Authorised Signatory ──────────────────────────────────────────────────
    el.append(signatory_box(d.get("seller_name","")))

    # ── Footer ────────────────────────────────────────────────────────────────
    el.extend(footer_block())

    doc.build(el)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════════════════
# BUILD BILL OF SUPPLY
# ═══════════════════════════════════════════════════════════════════════════════
def build_bill_of_supply(d: dict) -> bytes:
    """
    Template:
      Header: GutInvoice | BILL OF SUPPLY
      Seller: Business Name, Address, GSTIN, Reverse Charge | Invoice No, Date, Place of Supply
      Bill To: Name, Address  (NO GSTIN field)
      Items: # | Description | HSN/SAC | Qty | Unit | Rate | Amount  (NO TAX COLUMNS)
      Totals: Sub Total | GRAND TOTAL
      Declaration: MANDATORY FOR COMPOSITION DEALERS + Payment Terms
      Authorised Signatory
      Footer
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=M, rightMargin=M,
                            topMargin=M, bottomMargin=M)
    el = []

    el.append(doc_header("BILL OF SUPPLY"))
    el.append(sp(3))

    # ── Seller Details | Invoice Details ─────────────────────────────────────
    el.append(two_box(
        left_rows=[
            p("SELLER DETAILS", "lbl"),
            p(f"<b>Business Name:</b> {d.get('seller_name','')}", "body"),
            p(f"<b>Address:</b> {d.get('seller_address','')}", "body"),
            p(f"<b>GSTIN:</b> {d.get('seller_gstin','N/A')}", "body"),
        ],
        right_rows=[
            p("INVOICE DETAILS", "lbl"),
            p(f"<b>Invoice No:</b> {d.get('invoice_number','')}", "body"),
            p(f"<b>Invoice Date:</b> {d.get('invoice_date','')}", "body"),
            p(f"<b>Place of Supply:</b> {d.get('place_of_supply','')}", "body"),
            p(f"<b>Reverse Charge:</b> {d.get('reverse_charge','No')}", "body"),
        ]
    ))
    el.append(sp(2))

    # ── Bill To (NO GSTIN) ────────────────────────────────────────────────────
    el.append(full_box([
        p("BILL TO (CUSTOMER DETAILS)", "lbl"),
        p(f"<b>Name:</b> {d.get('customer_name','')}", "body"),
        p(f"<b>Address:</b> {d.get('customer_address','')}", "body"),
    ]))
    el.append(sp(2))

    # ── Line Items (NO tax columns) ───────────────────────────────────────────
    cw = [W*0.05, W*0.33, W*0.11, W*0.08, W*0.09, W*0.17, W*0.17]
    hdrs = ["#", "Description", "HSN/SAC", "Qty", "Unit", "Rate (₹)", "Amount (₹)"]
    def row(it):
        return [
            p(it.get("sno",""),         "tbl_c"),
            p(it.get("description",""), "tbl_l"),
            p(it.get("hsn_sac",""),     "tbl_c"),
            p(fmt(it.get("qty",0)),     "tbl_r"),
            p(it.get("unit","Nos"),     "tbl_c"),
            p(fmt(it.get("rate",0)),    "tbl_r"),
            p(fmt(it.get("amount",0)),  "tbl_r"),
        ]
    el.append(items_table(d.get("items",[]), cw, hdrs, row))
    el.append(sp(2))

    # ── Totals (NO tax rows) ──────────────────────────────────────────────────
    tot_rows = [
        [p("Sub Total","body"),    p(f"₹ {fmt(d.get('taxable_value',0))}","body_r")],
        [p("GRAND TOTAL","grand_l"), p(f"₹ {fmt(d.get('total_amount',0))}","grand_r")],
    ]
    el.append(totals_table(tot_rows))
    el.append(sp(2))
    el.append(p(f"<b>Amount in Words:</b> {num_words(d.get('total_amount',0))}", "body"))
    el.append(sp(3))

    # ── Declaration (MANDATORY FOR COMPOSITION DEALERS) ───────────────────────
    el.append(decl_box(
        d.get("declaration","Composition taxable person, not eligible to collect tax on supplies"),
        d.get("payment_terms","Pay within 15 days"),
        show_split=False
    ))
    el.append(sp(3))

    el.append(signatory_box(d.get("seller_name","")))
    el.extend(footer_block())

    doc.build(el)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════════════════
# BUILD NON-GST INVOICE
# ═══════════════════════════════════════════════════════════════════════════════
def build_nongst_invoice(d: dict) -> bytes:
    """
    Template:
      Header: GutInvoice | INVOICE
      Seller: Business Name, Address  (NO GSTIN field)
      Invoice Details: Invoice No, Date, Place of Supply
      Bill To: Name, Address  (NO GSTIN)
      Items: # | Description | HSN/SAC | Qty | Unit | Rate | Amount
      Totals: Sub Total | TOTAL AMOUNT
      Declaration + Payment Terms
      Authorised Signatory
      Footer
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=M, rightMargin=M,
                            topMargin=M, bottomMargin=M)
    el = []

    el.append(doc_header("INVOICE"))
    el.append(sp(3))

    # ── Seller Details (NO GSTIN) | Invoice Details ───────────────────────────
    el.append(two_box(
        left_rows=[
            p("SELLER DETAILS", "lbl"),
            p(f"<b>Business Name:</b> {d.get('seller_name','')}", "body"),
            p(f"<b>Address:</b> {d.get('seller_address','')}", "body"),
        ],
        right_rows=[
            p("INVOICE DETAILS", "lbl"),
            p(f"<b>Invoice No:</b> {d.get('invoice_number','')}", "body"),
            p(f"<b>Invoice Date:</b> {d.get('invoice_date','')}", "body"),
            p(f"<b>Place of Supply:</b> {d.get('place_of_supply','')}", "body"),
        ]
    ))
    el.append(sp(2))

    # ── Bill To (NO GSTIN) ────────────────────────────────────────────────────
    el.append(full_box([
        p("BILL TO (CUSTOMER DETAILS)", "lbl"),
        p(f"<b>Name:</b> {d.get('customer_name','')}", "body"),
        p(f"<b>Address:</b> {d.get('customer_address','')}", "body"),
    ]))
    el.append(sp(2))

    # ── Line Items (has HSN/SAC per template, no tax) ─────────────────────────
    cw = [W*0.05, W*0.33, W*0.11, W*0.08, W*0.09, W*0.17, W*0.17]
    hdrs = ["#", "Description", "HSN/SAC", "Qty", "Unit", "Rate (₹)", "Amount (₹)"]
    def row(it):
        return [
            p(it.get("sno",""),         "tbl_c"),
            p(it.get("description",""), "tbl_l"),
            p(it.get("hsn_sac",""),     "tbl_c"),
            p(fmt(it.get("qty",0)),     "tbl_r"),
            p(it.get("unit","Nos"),     "tbl_c"),
            p(fmt(it.get("rate",0)),    "tbl_r"),
            p(fmt(it.get("amount",0)),  "tbl_r"),
        ]
    el.append(items_table(d.get("items",[]), cw, hdrs, row))
    el.append(sp(2))

    # ── Totals ────────────────────────────────────────────────────────────────
    tot_rows = [
        [p("Sub Total","body"),      p(f"₹ {fmt(d.get('taxable_value',0))}","body_r")],
        [p("TOTAL AMOUNT","grand_l"),p(f"₹ {fmt(d.get('total_amount',0))}","grand_r")],
    ]
    el.append(totals_table(tot_rows))
    el.append(sp(2))
    el.append(p(f"<b>Amount in Words:</b> {num_words(d.get('total_amount',0))}", "body"))
    el.append(sp(3))

    # ── Declaration ───────────────────────────────────────────────────────────
    decl_data = [[p(
        f"<b>DECLARATION</b><br/>"
        f"{d.get('declaration','Seller not registered under GST. GST not applicable.')}<br/><br/>"
        f"<b>Payment Terms:</b> {d.get('payment_terms','Pay within 15 days')}",
        "body"
    )]]
    decl_t = Table(decl_data, colWidths=[W])
    decl_t.setStyle(TableStyle([
        ("BOX",           (0,0),(-1,-1), 0.8, TEAL_MID),
        ("TOPPADDING",    (0,0),(-1,-1), 6),
        ("BOTTOMPADDING", (0,0),(-1,-1), 6),
        ("LEFTPADDING",   (0,0),(-1,-1), 8),
    ]))
    el.append(decl_t)
    el.append(sp(3))

    el.append(signatory_box(d.get("seller_name","")))
    el.extend(footer_block())

    doc.build(el)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════════════════
# BUILD MONTHLY REPORT
# ═══════════════════════════════════════════════════════════════════════════════
def _section_hdr(text, bg=None):
    bg = bg or TEAL
    data = [[p(text, "sec_hdr")]]
    t = Table(data, colWidths=[W])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), bg),
        ("TOPPADDING",    (0,0),(-1,-1), 5),
        ("BOTTOMPADDING", (0,0),(-1,-1), 5),
        ("LEFTPADDING",   (0,0),(-1,-1), 8),
    ]))
    return t


def _invoice_section(el, title, rows, totals, bg, show_gst=True):
    el.append(_section_hdr(title, bg))

    if not rows:
        el.append(Paragraph("No invoices in this category.", STYLES["small"]))
        el.append(sp(2))
        return

    if show_gst:
        cw   = [W*0.14, W*0.09, W*0.15, W*0.17, W*0.13, W*0.11, W*0.11, W*0.10]
        hdrs = ["Invoice No","Date","Customer","Description","Taxable ₹","CGST ₹","SGST ₹","IGST ₹"]
        def build_row(r):
            return [
                p(r.get("invoice_number",""), "small"),
                p(r.get("invoice_date",""),   "small"),
                p(r.get("customer_name",""),  "small"),
                p(r.get("description",""),    "small"),
                p(r.get("taxable_value","0.00"), "small_r"),
                p(r.get("cgst_amount","0.00"),   "small_r"),
                p(r.get("sgst_amount","0.00"),   "small_r"),
                p(r.get("igst_amount","0.00"),   "small_r"),
            ]
        tot_row = [
            p(f"TOTAL  ({totals.get('count',0)} invoices)", "bold"),
            p("","bold"), p("","bold"), p("","bold"),
            p(totals.get("taxable_value","0.00"),"bold_r"),
            p(totals.get("cgst","0.00"),         "bold_r"),
            p(totals.get("sgst","0.00"),         "bold_r"),
            p(totals.get("igst","0.00"),         "bold_r"),
        ]
    else:
        cw   = [W*0.18, W*0.10, W*0.20, W*0.27, W*0.25]
        hdrs = ["Invoice No","Date","Customer","Description","Amount ₹"]
        def build_row(r):
            return [
                p(r.get("invoice_number",""), "small"),
                p(r.get("invoice_date",""),   "small"),
                p(r.get("customer_name",""),  "small"),
                p(r.get("description",""),    "small"),
                p(r.get("taxable_value","0.00"), "small_r"),
            ]
        tot_row = [
            p(f"TOTAL  ({totals.get('count',0)} invoices)", "bold"),
            p("","bold"), p("","bold"), p("","bold"),
            p(totals.get("taxable_value","0.00"), "bold_r"),
        ]

    data = [[p(h,"tbl_hdr") for h in hdrs]]
    for r in rows:
        data.append(build_row(r))
    data.append(tot_row)

    n = len(data)
    t = Table(data, colWidths=cw, repeatRows=1)
    t.setStyle(TableStyle([
        ("BOX",           (0,0),(-1,-1), 0.8, TEAL_MID),
        ("INNERGRID",     (0,0),(-1,-1), 0.3, LGREY),
        ("BACKGROUND",    (0,0),(-1,0),  bg),
        ("FONTNAME",      (0,0),(-1,0),  "Helvetica-Bold"),
        ("TEXTCOLOR",     (0,0),(-1,0),  WHITE),
        ("ROWBACKGROUNDS",(0,1),(-1,n-2),[WHITE, TEAL_LIGHT]),
        ("BACKGROUND",    (0,n-1),(-1,n-1), DARK),
        ("TEXTCOLOR",     (0,n-1),(-1,n-1), WHITE),
        ("FONTNAME",      (0,n-1),(-1,n-1),"Helvetica-Bold"),
        ("TOPPADDING",    (0,0),(-1,-1), 3),
        ("BOTTOMPADDING", (0,0),(-1,-1), 3),
        ("LEFTPADDING",   (0,0),(-1,-1), 4),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ("FONTSIZE",      (0,1),(-1,n-2), 7.5),
    ]))
    el.append(t)
    el.append(sp(3))


def build_monthly_report(rd: dict) -> bytes:
    """
    Template:
      Header: GutInvoice | Invoice & Tax Liability Report — Month Year
      Sub-header: seller name | GSTIN | Generated date
      Summary bar: Total Invoices | Total Taxable Value | Total GST Payable
      Section A: Tax Invoices (with CGST/SGST/IGST columns)
      Section B: Bill of Supply (amount only, no tax)
      Section C: Non-GST Invoices (amount only, no tax)
      Section D: HSN-wise Tax Summary
      Final Tax Liability Box: CGST | SGST | IGST | TOTAL GST PAYABLE TO GOVERNMENT
      Footer
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=M, rightMargin=M,
                            topMargin=M, bottomMargin=M)
    el = []

    # ── Report Header ─────────────────────────────────────────────────────────
    hdr_data = [[
        p(f"Invoice &amp; Tax Liability Report  —  {rd.get('report_month','')} {rd.get('report_year','')}", "hdr_type"),
    ]]
    hdr_t = Table(hdr_data, colWidths=[W])
    hdr_t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), TEAL),
        ("TOPPADDING",    (0,0),(-1,-1), 11),
        ("BOTTOMPADDING", (0,0),(-1,-1), 11),
        ("LEFTPADDING",   (0,0),(-1,-1), 10),
        ("RIGHTPADDING",  (0,0),(-1,-1), 10),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
    ]))
    el.append(hdr_t)

    # Seller sub-header
    sub_data = [[
        p(f"<b>{rd.get('seller_name','')}</b>  |  {rd.get('seller_address','')}", "body"),
        p(f"GSTIN: <b>{rd.get('seller_gstin','')}</b>  |  Generated: {rd.get('generated_date','')}", "body_r"),
    ]]
    sub_t = Table(sub_data, colWidths=[W*0.6, W*0.4])
    sub_t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), TEAL_LIGHT),
        ("BOX",           (0,0),(-1,-1), 0.8, TEAL_MID),
        ("TOPPADDING",    (0,0),(-1,-1), 5),
        ("BOTTOMPADDING", (0,0),(-1,-1), 5),
        ("LEFTPADDING",   (0,0),(-1,-1), 8),
    ]))
    el.append(sub_t)
    el.append(sp(3))

    # ── Summary Bar ───────────────────────────────────────────────────────────
    summary = rd.get("summary", {})
    smry_data = [[
        p(f"<b>Total Invoices</b><br/><font size='13'><b>{rd.get('total_count',0)}</b></font>", "sum_c"),
        p(f"<b>Total Taxable Value</b><br/><font size='13'><b>₹ {summary.get('total_taxable_value','0.00')}</b></font>", "sum_c"),
        p(f"<b>Total GST Payable</b><br/><font size='13'><b>₹ {summary.get('total_gst_payable','0.00')}</b></font>", "sum_c"),
    ]]
    smry_t = Table(smry_data, colWidths=[W/3, W/3, W/3])
    smry_t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), DARK),
        ("INNERGRID",     (0,0),(-1,-1), 0.5, colors.HexColor("#334E68")),
        ("BOX",           (0,0),(-1,-1), 0.8, TEAL_MID),
        ("TOPPADDING",    (0,0),(-1,-1), 10),
        ("BOTTOMPADDING", (0,0),(-1,-1), 10),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
    ]))
    el.append(smry_t)
    el.append(sp(4))

    # ── Section A — Tax Invoices ──────────────────────────────────────────────
    _invoice_section(
        el, "SECTION A — TAX INVOICES (GST Registered)",
        rd.get("tax_invoices",[]), rd.get("tax_invoices_total",{}),
        TEAL, show_gst=True
    )

    # ── Section B — Bill of Supply ────────────────────────────────────────────
    _invoice_section(
        el, "SECTION B — BILL OF SUPPLY (Composition / Exempt)",
        rd.get("bos_invoices",[]), rd.get("bos_total",{}),
        colors.HexColor("#1B5E3B"), show_gst=False
    )

    # ── Section C — Non-GST Invoices ──────────────────────────────────────────
    _invoice_section(
        el, "SECTION C — NON-GST INVOICES (Unregistered)",
        rd.get("nongst_invoices",[]), rd.get("nongst_total",{}),
        colors.HexColor("#7B3F00"), show_gst=False
    )

    # ── Section D — HSN-wise Tax Summary ─────────────────────────────────────
    el.append(_section_hdr("SECTION D — HSN-WISE TAX SUMMARY", colors.HexColor("#4A235A")))
    hsn_rows = rd.get("hsn_summary",[])
    hgt      = rd.get("hsn_grand_total",{})
    if hsn_rows:
        cw_h = [W*0.12, W*0.24, W*0.16, W*0.12, W*0.12, W*0.12, W*0.12]
        hdrs = ["HSN Code","Description","Taxable ₹","CGST ₹","SGST ₹","IGST ₹","Total Tax ₹"]
        hsn_data = [[p(h,"tbl_hdr") for h in hdrs]]
        for hr in hsn_rows:
            hsn_data.append([
                p(hr.get("hsn_code",""),    "small"),
                p(hr.get("description",""), "small"),
                p(hr.get("taxable_value","0.00"), "small_r"),
                p(hr.get("cgst","0.00"),         "small_r"),
                p(hr.get("sgst","0.00"),         "small_r"),
                p(hr.get("igst","0.00"),         "small_r"),
                p(hr.get("total_tax","0.00"),    "small_r"),
            ])
        hsn_data.append([
            p("GRAND TOTAL","bold"), p("","bold"),
            p(hgt.get("taxable_value","0.00"),"bold_r"),
            p(hgt.get("cgst","0.00"),         "bold_r"),
            p(hgt.get("sgst","0.00"),         "bold_r"),
            p(hgt.get("igst","0.00"),         "bold_r"),
            p(hgt.get("total_tax","0.00"),    "bold_r"),
        ])
        n = len(hsn_data)
        hsn_t = Table(hsn_data, colWidths=cw_h, repeatRows=1)
        hsn_t.setStyle(TableStyle([
            ("BOX",           (0,0),(-1,-1), 0.8, TEAL_MID),
            ("INNERGRID",     (0,0),(-1,-1), 0.3, LGREY),
            ("BACKGROUND",    (0,0),(-1,0),  colors.HexColor("#4A235A")),
            ("TEXTCOLOR",     (0,0),(-1,0),  WHITE),
            ("FONTNAME",      (0,0),(-1,0),  "Helvetica-Bold"),
            ("ROWBACKGROUNDS",(0,1),(-1,n-2),[WHITE, colors.HexColor("#F5F0FF")]),
            ("BACKGROUND",    (0,n-1),(-1,n-1), DARK),
            ("TEXTCOLOR",     (0,n-1),(-1,n-1), WHITE),
            ("FONTNAME",      (0,n-1),(-1,n-1), "Helvetica-Bold"),
            ("TOPPADDING",    (0,0),(-1,-1), 3),
            ("BOTTOMPADDING", (0,0),(-1,-1), 3),
            ("LEFTPADDING",   (0,0),(-1,-1), 4),
            ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
            ("FONTSIZE",      (0,1),(-1,n-2), 7.5),
        ]))
        el.append(hsn_t)
    else:
        el.append(p("No HSN data available.", "small"))
    el.append(sp(4))

    # ── Final Tax Liability Box ───────────────────────────────────────────────
    el.append(_section_hdr("FINAL TAX LIABILITY SUMMARY", colors.HexColor("#880000")))
    fin_rows = [
        [p("Total Taxable Value (all invoices)","body"),
         p(f"₹ {summary.get('total_taxable_value','0.00')}","body_r")],
        [p("Total CGST Collected","body"),
         p(f"₹ {summary.get('total_cgst','0.00')}","body_r")],
        [p("Total SGST Collected","body"),
         p(f"₹ {summary.get('total_sgst','0.00')}","body_r")],
        [p("Total IGST Collected","body"),
         p(f"₹ {summary.get('total_igst','0.00')}","body_r")],
        [p("TOTAL GST PAYABLE TO GOVERNMENT ★","grand_l"),
         p(f"₹ {summary.get('total_gst_payable','0.00')}","grand_r")],
    ]
    fin_t = Table(fin_rows, colWidths=[W*0.7, W*0.3])
    n = len(fin_rows)
    fin_t.setStyle(TableStyle([
        ("BOX",           (0,0),(-1,-1), 0.8, TEAL_MID),
        ("INNERGRID",     (0,0),(-1,-1), 0.4, LGREY),
        ("ROWBACKGROUNDS",(0,0),(-1,n-2), [colors.HexColor("#FFF5F5"), WHITE]),
        ("BACKGROUND",    (0,n-1),(-1,n-1), colors.HexColor("#880000")),
        ("TOPPADDING",    (0,0),(-1,-1), 5),
        ("BOTTOMPADDING", (0,0),(-1,-1), 5),
        ("LEFTPADDING",   (0,0),(-1,-1), 8),
    ]))
    el.append(fin_t)
    el.append(sp(2))
    el.append(p(
        "Use this report to prepare your GSTR-1 filing. "
        "Verify all amounts with your Chartered Accountant before submission.",
        "small"
    ))

    el.extend(footer_block())

    doc.build(el)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINTS — called from main.py
# ═══════════════════════════════════════════════════════════════════════════════
def select_and_generate_pdf(invoice_data: dict, seller_phone: str) -> str:
    """Generate correct PDF type → upload to Supabase → return public URL."""
    inv_type = (invoice_data.get("invoice_type") or "").upper()
    inv_no   = invoice_data.get("invoice_number") or f"GUT-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    if "BILL" in inv_type:
        pdf_bytes = build_bill_of_supply(invoice_data)
    elif "TAX" in inv_type:
        pdf_bytes = build_tax_invoice(invoice_data)
    else:
        pdf_bytes = build_nongst_invoice(invoice_data)

    phone_clean = seller_phone.replace("whatsapp:+","").replace("+","").replace(" ","")
    return upload_pdf_to_supabase(pdf_bytes, f"{phone_clean}/{inv_no}.pdf")


def generate_report_pdf_local(report_data: dict, seller_phone: str) -> str:
    """Generate monthly report PDF → upload to Supabase → return public URL."""
    month = report_data.get("report_month", "Report")
    year  = report_data.get("report_year", datetime.now().year)
    pdf_bytes = build_monthly_report(report_data)

    phone_clean = seller_phone.replace("whatsapp:+","").replace("+","").replace(" ","")
    return upload_pdf_to_supabase(pdf_bytes, f"{phone_clean}/reports/{month}_{year}.pdf")
