"""
GutInvoice — Every Invoice has a Voice
v13 — Sequential Invoice Numbers + Credit Note System
  ✅ All v12 features intact (ReportLab PDFs, Supabase storage)
  ✅ NEW: Sequential invoice numbering — TEJ001-022026 format (per seller per month)
  ✅ NEW: Cancel invoice via voice/text → Credit Note auto-generated + sent on WhatsApp
  ✅ NEW: Monthly report includes Section E (Credit Notes) + Net GST Payable
  ✅ Rs. symbol used throughout (no box rendering issues)
  ✅ Invoice numbers never reused — cancelled invoices retired permanently

Invoice number format: {3-letter prefix}{3-digit seq}-{MMYYYY}
  Example: Tejesh Enterprises, Feb 2026, 1st invoice → TEJ001-022026
  Next:    TEJ002-022026  |  March:  TEJ001-032026

Cancel trigger examples (text or voice):
  "cancel TEJ001-022026"
  "cancel invoice TEJ002-022026"
  "TEJ001-022026 cancel cheyyi"  (Telugu)
  "001-022026 invoice cancel"
"""

import os
import re
import json
import requests
import anthropic
from flask import Flask, request, Response, render_template_string
from twilio.rest import Client as TwilioClient
from datetime import datetime
from collections import defaultdict
import logging
from pdf_generators import select_and_generate_pdf, generate_report_pdf_local, generate_credit_note_pdf

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)
app = Flask(__name__)


# ─── Helpers ──────────────────────────────────────────────────────────────────
def get_twilio():
    return TwilioClient(os.environ.get("TWILIO_ACCOUNT_SID"), os.environ.get("TWILIO_AUTH_TOKEN"))

def get_claude():
    return anthropic.Anthropic(api_key=os.environ.get("CLAUDE_API_KEY"))

def env(key):
    return os.environ.get(key, "")


# ─── Safe JSON — identical to v9/v10 ─────────────────────────────────────────
def safe_json(response, label):
    raw = response.text.strip()
    log.info(f"[{label}] HTTP {response.status_code} | raw: {raw[:300]}")
    if not raw:
        raise Exception(f"{label} returned empty response body (HTTP {response.status_code})")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise Exception(f"{label} returned non-JSON (HTTP {response.status_code}): {raw[:200]} | {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# SUPABASE HELPERS — identical to v10
# ═══════════════════════════════════════════════════════════════════════════════

def sb_headers():
    return {
        "apikey": env("SUPABASE_KEY"),
        "Authorization": f"Bearer {env('SUPABASE_KEY')}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

def sb_url(table, query=""):
    return f"{env('SUPABASE_URL')}/rest/v1/{table}{query}"


def get_seller(phone):
    r = requests.get(
        sb_url("sellers", f"?phone_number=eq.{requests.utils.quote(phone)}&limit=1"),
        headers=sb_headers(), timeout=10
    )
    rows = safe_json(r, "SB-GetSeller")
    return rows[0] if rows else None


def create_seller(phone):
    r = requests.post(
        sb_url("sellers"),
        headers=sb_headers(),
        json={"phone_number": phone, "onboarding_step": "new"},
        timeout=10
    )
    rows = safe_json(r, "SB-CreateSeller")
    log.info(f"New seller created: {phone}")
    return rows[0] if rows else {}


def update_seller(phone, fields: dict):
    r = requests.patch(
        sb_url("sellers", f"?phone_number=eq.{requests.utils.quote(phone)}"),
        headers=sb_headers(),
        json=fields,
        timeout=10
    )
    rows = safe_json(r, "SB-UpdateSeller")
    return rows[0] if rows else {}


def get_or_create_seller(phone):
    seller = get_seller(phone)
    if not seller:
        seller = create_seller(phone)
    return seller


def save_invoice(seller_phone, invoice_data, pdf_url, transcript):
    row = {
        "seller_phone":     seller_phone,
        "invoice_number":   invoice_data.get("invoice_number", ""),
        "invoice_type":     invoice_data.get("invoice_type", ""),
        "customer_name":    invoice_data.get("customer_name", ""),
        "customer_address": invoice_data.get("customer_address", ""),
        "customer_gstin":   invoice_data.get("customer_gstin", ""),
        "taxable_value":    float(invoice_data.get("taxable_value", 0)),
        "cgst_amount":      float(invoice_data.get("cgst_amount", 0)),
        "sgst_amount":      float(invoice_data.get("sgst_amount", 0)),
        "igst_amount":      float(invoice_data.get("igst_amount", 0)),
        "total_amount":     float(invoice_data.get("total_amount", 0)),
        "invoice_data":     invoice_data,
        "pdf_url":          pdf_url,
        "transcript":       transcript,
        "status":           "active"          # v13: active | cancelled
    }
    r = requests.post(sb_url("invoices"), headers=sb_headers(), json=row, timeout=10)
    rows = safe_json(r, "SB-SaveInvoice")
    log.info(f"Invoice saved: {invoice_data.get('invoice_number')} for {seller_phone}")
    return rows[0] if rows else {}


# ═══════════════════════════════════════════════════════════════════════════════
# v13 — SEQUENTIAL INVOICE NUMBERING
# ═══════════════════════════════════════════════════════════════════════════════

def get_next_invoice_number(seller_phone: str, seller_name: str, month: int, year: int) -> str:
    """
    Generate next sequential invoice number for this seller in this month/year.
    Format: TEJ001-022026
    """
    seller_name = seller_name or "GUT"          # ← guard: never None
    prefix = re.sub(r'[^A-Za-z]', '', seller_name)[:3].upper() or "GUT"
    suffix = f"{month:02d}{year}"

    # Count ALL invoice records for this seller in this month/year
    # (includes active + cancelled — ensures sequence never reuses a number)
    from calendar import monthrange
    last_day  = monthrange(year, month)[1]
    date_from = f"{year}-{month:02d}-01T00:00:00"
    date_to   = f"{year}-{month:02d}-{last_day:02d}T23:59:59"

    r = requests.get(
        sb_url("invoices",
               f"?seller_phone=eq.{requests.utils.quote(seller_phone)}"
               f"&created_at=gte.{date_from}"
               f"&created_at=lte.{date_to}"
               f"&invoice_type=neq.CREDIT NOTE"   # don't count credit notes
               f"&select=invoice_number&limit=500"),
        headers=sb_headers(), timeout=10
    )
    existing = []
    try:
        existing = safe_json(r, "SB-GetSeq")
    except Exception as e:
        log.warning(f"Could not fetch invoice sequence: {e}")

    seq = len(existing) + 1
    inv_no = f"{prefix}{seq:03d}-{suffix}"
    log.info(f"Generated invoice number: {inv_no}")
    return inv_no


# ═══════════════════════════════════════════════════════════════════════════════
# v13 — CANCEL & CREDIT NOTE SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════

# Cancel detection patterns — kept STRICT to avoid false positives on normal voice notes.
# Only match proper invoice number format: PREFIX + 3digits + dash + 6digits (MMYYYY)
# e.g. GUT006-022026 or TEJ001-022026
# Loose digit-only patterns (\d{9}) were removed — they matched phone numbers in voice notes.
CANCEL_PATTERNS = [
    # Full format: cancel GUT006-022026  /  cancel invoice GUT006-022026
    r'\bcancel\b\s+(?:invoice\s+)?([A-Z]{2,5}\d{3}-\d{6})',
    # Full format after: GUT006-022026 cancel  /  GUT006-022026 cancel cheyyi
    r'([A-Z]{2,5}\d{3}-\d{6})\s+\bcancel\b',
    # Partial (no prefix): cancel 006-022026
    r'\bcancel\b\s+(?:invoice\s+)?(\d{3}-\d{6})',
    # Partial after: 006-022026 cancel
    r'(\d{3}-\d{6})\s+\bcancel\b',
]


def detect_cancel_request(text: str):
    """
    Returns (True, invoice_number_fragment) or (False, None).
    STRICT matching — requires invoice number format to avoid false positives.
    """
    for t in [text, text.strip()]:
        for pat in CANCEL_PATTERNS:
            m = re.search(pat, t, re.IGNORECASE)
            if m:
                fragment = m.group(1).upper()
                log.info(f"Cancel detected — fragment: {fragment}")
                return True, fragment
    return False, None


def fetch_invoice_by_number(invoice_number_fragment: str, seller_phone: str) -> dict | None:
    """
    Look up an active invoice by full or partial invoice number for this seller.
    Tries: exact match → ends-with match → contains match.
    """
    fragment = invoice_number_fragment.upper().strip()

    # 1. Exact match (e.g. GUT006-022026)
    r = requests.get(
        sb_url("invoices",
               f"?seller_phone=eq.{requests.utils.quote(seller_phone)}"
               f"&invoice_number=eq.{requests.utils.quote(fragment)}"
               f"&status=eq.active&limit=1"),
        headers=sb_headers(), timeout=10
    )
    try:
        rows = safe_json(r, "SB-FetchInvExact")
        if rows: return rows[0]
    except: pass

    # 2. Ends-with match (e.g. user says 006-022026, actual is GUT006-022026)
    r2 = requests.get(
        sb_url("invoices",
               f"?seller_phone=eq.{requests.utils.quote(seller_phone)}"
               f"&invoice_number=ilike.*{requests.utils.quote(fragment)}"
               f"&status=eq.active&limit=1"),
        headers=sb_headers(), timeout=10
    )
    try:
        rows2 = safe_json(r2, "SB-FetchInvPartial")
        if rows2: return rows2[0]
    except: pass

    # 3. Contains match (fallback)
    r3 = requests.get(
        sb_url("invoices",
               f"?seller_phone=eq.{requests.utils.quote(seller_phone)}"
               f"&invoice_number=ilike.*{requests.utils.quote(fragment)}*"
               f"&status=eq.active&limit=1"),
        headers=sb_headers(), timeout=10
    )
    try:
        rows3 = safe_json(r3, "SB-FetchInvContains")
        if rows3: return rows3[0]
    except: pass

    return None


def cancel_invoice_in_db(invoice_number: str, seller_phone: str) -> bool:
    """Mark invoice as cancelled in Supabase. Returns True on success."""
    r = requests.patch(
        sb_url("invoices",
               f"?seller_phone=eq.{requests.utils.quote(seller_phone)}"
               f"&invoice_number=eq.{requests.utils.quote(invoice_number)}"),
        headers=sb_headers(),
        json={"status": "cancelled"},
        timeout=10
    )
    log.info(f"Cancel invoice {invoice_number}: HTTP {r.status_code}")
    return r.status_code in (200, 204)


def build_credit_note_data(original_invoice: dict, seller: dict) -> dict:
    """
    Build credit note data dict from original invoice DB row.
    Credit note number = CN- + original invoice number.
    """
    inv_data = original_invoice.get("invoice_data") or {}
    orig_no  = original_invoice.get("invoice_number", "")
    cn_no    = f"CN-{orig_no}"
    today    = datetime.now().strftime("%d/%m/%Y")

    return {
        "credit_note_number":    cn_no,
        "credit_note_date":      today,
        "original_invoice_number": orig_no,
        "original_invoice_date": inv_data.get("invoice_date", ""),
        "reason":                "Cancellation of invoice as requested by seller",
        # Seller
        "seller_name":    inv_data.get("seller_name") or seller.get("seller_name",""),
        "seller_address": inv_data.get("seller_address") or seller.get("seller_address",""),
        "seller_gstin":   inv_data.get("seller_gstin") or seller.get("seller_gstin",""),
        "place_of_supply":inv_data.get("place_of_supply","Telangana"),
        # Customer
        "customer_name":    inv_data.get("customer_name",""),
        "customer_address": inv_data.get("customer_address",""),
        "customer_gstin":   inv_data.get("customer_gstin",""),
        # Items (same as original, for reference)
        "items":            inv_data.get("items",[]),
        # Financials (reversed)
        "taxable_value": inv_data.get("taxable_value", original_invoice.get("taxable_value",0)),
        "cgst_rate":     inv_data.get("cgst_rate",0),
        "cgst_amount":   inv_data.get("cgst_amount", original_invoice.get("cgst_amount",0)),
        "sgst_rate":     inv_data.get("sgst_rate",0),
        "sgst_amount":   inv_data.get("sgst_amount", original_invoice.get("sgst_amount",0)),
        "igst_rate":     inv_data.get("igst_rate",0),
        "igst_amount":   inv_data.get("igst_amount", original_invoice.get("igst_amount",0)),
        "total_amount":  inv_data.get("total_amount", original_invoice.get("total_amount",0)),
        "invoice_type":  "CREDIT NOTE",
    }


def save_credit_note(seller_phone: str, cn_data: dict, pdf_url: str):
    """Save credit note to invoices table with invoice_type=CREDIT NOTE."""
    row = {
        "seller_phone":   seller_phone,
        "invoice_number": cn_data.get("credit_note_number",""),
        "invoice_type":   "CREDIT NOTE",
        "customer_name":  cn_data.get("customer_name",""),
        "customer_address":cn_data.get("customer_address",""),
        "customer_gstin": cn_data.get("customer_gstin",""),
        "taxable_value":  float(cn_data.get("taxable_value",0)),
        "cgst_amount":    float(cn_data.get("cgst_amount",0)),
        "sgst_amount":    float(cn_data.get("sgst_amount",0)),
        "igst_amount":    float(cn_data.get("igst_amount",0)),
        "total_amount":   float(cn_data.get("total_amount",0)),
        "invoice_data":   cn_data,
        "pdf_url":        pdf_url,
        "transcript":     f"Credit note for {cn_data.get('original_invoice_number','')}",
        "status":         "active",
    }
    r = requests.post(sb_url("invoices"), headers=sb_headers(), json=row, timeout=10)
    log.info(f"Credit note saved: {cn_data.get('credit_note_number')} HTTP {r.status_code}")


def handle_cancel_request(twilio, from_num, seller, invoice_fragment, lang):
    """
    Full cancel pipeline:
      1. Look up original invoice
      2. Mark it cancelled in DB
      3. Build credit note data
      4. Generate credit note PDF
      5. Save credit note to DB
      6. Send credit note to WhatsApp
    """
    # Acknowledge
    send_msg(twilio, from_num,
        f"🔍 Looking up invoice *{invoice_fragment}*... ⏳"
        if lang != "telugu" else
        f"🔍 Invoice *{invoice_fragment}* వెతుకుతున్నాం... ⏳"
    )

    original = fetch_invoice_by_number(invoice_fragment, from_num)

    if not original:
        send_msg(twilio, from_num,
            f"❌ Invoice *{invoice_fragment}* not found or already cancelled.\n"
            f"Please check the invoice number and try again."
            if lang != "telugu" else
            f"❌ Invoice *{invoice_fragment}* కనుగొనబడలేదు లేదా ఇప్పటికే cancel అయింది.\n"
            f"Invoice number తనిఖీ చేసి మళ్ళీ try చేయండి."
        )
        return

    full_inv_no = original.get("invoice_number","")

    # Cancel in DB
    cancel_invoice_in_db(full_inv_no, from_num)

    # Build + generate credit note
    cn_data  = build_credit_note_data(original, seller)
    cn_pdf   = generate_credit_note_pdf(cn_data, from_num)
    save_credit_note(from_num, cn_data, cn_pdf)

    # Send to WhatsApp
    cn_no = cn_data.get("credit_note_number","")
    total = cn_data.get("total_amount",0)

    if lang == "telugu":
        body = (
            f"✅ *Invoice Cancel అయింది!*\n\n"
            f"❌ Cancelled: *{full_inv_no}*\n"
            f"📋 Credit Note: *{cn_no}*\n"
            f"💰 Amount Reversed: Rs.{float(total):,.0f}\n\n"
            f"ఈ credit note మీ GST records లో invoice ని reverse చేస్తుంది.\n"
            f"_GutInvoice 🎙️ — మీ గొంతే మీ Invoice_"
        )
    else:
        body = (
            f"✅ *Invoice Cancelled Successfully!*\n\n"
            f"❌ Cancelled: *{full_inv_no}*\n"
            f"📋 Credit Note: *{cn_no}*\n"
            f"💰 Amount Reversed: Rs.{float(total):,.0f}\n\n"
            f"This credit note reverses the invoice in your GST records.\n"
            f"_Powered by GutInvoice 🎙️ — Every Invoice has a Voice_"
        )

    msg = twilio.messages.create(
        from_=env("TWILIO_FROM_NUMBER"), to=from_num,
        body=body, media_url=[cn_pdf]
    )
    log.info(f"✅ Credit note {cn_no} sent for cancelled invoice {full_inv_no} | msg {msg.sid}")


# ═══════════════════════════════════════════════════════════════════════════════
# MONTHLY REPORT — STEP 1: DETECT REPORT REQUEST
# ═══════════════════════════════════════════════════════════════════════════════

MONTH_MAP = {
    # English
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
    # Telugu transliterated
    "januvari":1,"phivruvari":2,"march":3,"epril":4,"me":5,"jun":6,
    "juli":7,"agastu":8,"september":9,"aktobar":10,"november":11,"disambar":12,
    # Short
    "jan":1,"feb":2,"mar":3,"apr":4,"jun":6,"jul":7,
    "aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
}

REPORT_KEYWORDS = [
    "summary", "report", "statement", "invoices summary",
    "tax report", "monthly report", "month report",
    "all invoices", "invoice list", "month summary",
    # Telugu
    "summary పంపు", "report పంపు", "నెల report", "నెల summary",
    "invoices పంపు", "అన్ని invoices",
]

def is_report_request(text):
    """
    Returns (True, month_num, year) if text is a report request.
    Returns (False, None, None) otherwise.
    """
    t = text.lower().strip()

    # Must contain at least one report keyword
    has_keyword = any(kw in t for kw in REPORT_KEYWORDS)

    # Try to find month
    month_num = None
    for m_name, m_num in MONTH_MAP.items():
        if m_name in t:
            month_num = m_num
            break

    # Try to find year (4-digit or 2-digit)
    year_match = re.search(r"\b(20\d{2})\b", t)
    year = int(year_match.group(1)) if year_match else datetime.now().year

    # "last month" handling
    if "last month" in t or "previous month" in t or "గత నెల" in t:
        now = datetime.now()
        month_num = now.month - 1 if now.month > 1 else 12
        year      = now.year if now.month > 1 else now.year - 1
        has_keyword = True

    # "this month" handling
    if "this month" in t or "ఈ నెల" in t:
        month_num = datetime.now().month
        year      = datetime.now().year
        has_keyword = True

    if has_keyword and month_num:
        return True, month_num, year

    return False, None, None


def detect_report_from_voice(transcript):
    """
    Use Claude to detect if a voice transcript is asking for a monthly report.
    Returns (is_report, month_num, year) or (False, None, None).
    """
    prompt = f"""Analyze this transcript from an Indian business owner using WhatsApp.
Are they asking for a monthly invoice summary/report?

Transcript: "{transcript}"

If YES, extract the month number (1-12) and year they want.
Return ONLY valid JSON:
{{"is_report": true, "month": 1, "year": 2026}}
or
{{"is_report": false, "month": null, "year": null}}

Note: They may speak in Telugu, English, or mixed. 
"January report", "January 2026 invoices", "జనవరి summary పంపు" etc. all count as YES."""

    try:
        claude = get_claude()
        msg = claude.messages.create(
            model="claude-opus-4-6",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}]
        )
        text = msg.content[0].text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        start = text.find("{")
        end   = text.rfind("}") + 1
        data  = json.loads(text[start:end])
        if data.get("is_report") and data.get("month"):
            return True, int(data["month"]), int(data.get("year", datetime.now().year))
    except Exception as e:
        log.warning(f"Report detection from voice failed: {e}")

    return False, None, None


# ═══════════════════════════════════════════════════════════════════════════════
# MONTHLY REPORT — STEP 2: FETCH FROM SUPABASE
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_monthly_invoices(seller_phone, month_num, year):
    """
    Fetch all records for a seller in a given month/year from Supabase.
    Returns (all_original_invoices, credit_notes).

    IMPORTANT for GST accounting:
    - all_original_invoices includes BOTH active AND cancelled invoices.
      Cancelled ones still raised a GST liability when issued — the credit note
      reverses it. Both must appear in the gross totals for GSTR-1.
    - credit_notes are separated so Section E and net GST deduction works correctly.
    - Net GST = gross GST (all originals) - credit note reversals = correct payable.
    """
    from calendar import monthrange
    last_day  = monthrange(year, month_num)[1]
    date_from = f"{year}-{month_num:02d}-01T00:00:00"
    date_to   = f"{year}-{month_num:02d}-{last_day:02d}T23:59:59"

    query = (
        f"?seller_phone=eq.{requests.utils.quote(seller_phone)}"
        f"&created_at=gte.{date_from}"
        f"&created_at=lte.{date_to}"
        f"&order=created_at.asc"
        f"&limit=500"
    )
    r = requests.get(sb_url("invoices", query), headers=sb_headers(), timeout=15)
    all_rows = safe_json(r, "SB-FetchMonthly")

    # ALL original invoices (active + cancelled) — needed for correct gross GST total
    all_invoices = [row for row in all_rows
                    if row.get("invoice_type","").upper() != "CREDIT NOTE"]

    # Credit notes only
    credit_notes = [row for row in all_rows
                    if row.get("invoice_type","").upper() == "CREDIT NOTE"]

    log.info(f"Fetched {len(all_invoices)} invoices "
             f"({sum(1 for r in all_invoices if r.get('status')=='cancelled')} cancelled) "
             f"+ {len(credit_notes)} credit notes for {seller_phone} in {month_num}/{year}")
    return all_invoices, credit_notes


# ═══════════════════════════════════════════════════════════════════════════════
# MONTHLY REPORT — STEP 3: AGGREGATE DATA
# ═══════════════════════════════════════════════════════════════════════════════

MONTH_NAMES = ["","January","February","March","April","May","June",
               "July","August","September","October","November","December"]

def fmt(val):
    """Format number as Indian currency string."""
    try:
        return f"{float(val):,.2f}"
    except:
        return "0.00"

def aggregate_report_data(invoices, credit_notes, seller, month_num, year):
    """
    Aggregate invoice list into report data dict.
    Splits into TAX / BOS / NONGST / CREDIT NOTES + HSN summary.
    Net GST = Gross GST - GST reversed by credit notes.
    """
    tax_rows   = []
    bos_rows   = []
    nongst_rows = []

    # HSN accumulator: {hsn_code: {desc, taxable, cgst, sgst, igst}}
    hsn_acc = defaultdict(lambda: {
        "description": "", "taxable_value": 0.0,
        "cgst": 0.0, "sgst": 0.0, "igst": 0.0
    })

    def get_items_desc(inv_data):
        """Extract first item description from invoice_data JSON."""
        items = inv_data.get("items", [])
        if items:
            descs = [it.get("description","") for it in items if it.get("description")]
            return ", ".join(descs[:2]) or "—"
        return "—"

    def get_hsn(inv_data):
        items = inv_data.get("items", [])
        if items:
            hsns = [str(it.get("hsn_sac","")) for it in items if it.get("hsn_sac")]
            return ", ".join(hsns[:2]) or "—"
        return "—"

    for inv in invoices:
        raw      = inv.get("invoice_data") or {}
        inv_type = (inv.get("invoice_type") or "").upper()
        is_cancelled = inv.get("status") == "cancelled"

        # Mark cancelled invoices clearly in the description
        inv_no   = inv.get("invoice_number", "")
        if is_cancelled:
            inv_no = f"{inv_no} (CANCELLED)"

        row = {
            "invoice_number": inv_no,
            "invoice_date":   (inv.get("created_at") or "")[:10],
            "customer_name":  inv.get("customer_name") or "—",
            "description":    get_items_desc(raw),
            "taxable_value":  fmt(inv.get("taxable_value", 0)),
            "cgst_amount":    fmt(inv.get("cgst_amount", 0)),
            "sgst_amount":    fmt(inv.get("sgst_amount", 0)),
            "igst_amount":    fmt(inv.get("igst_amount", 0)),
            "hsn":            get_hsn(raw),
        }

        # HSN accumulation — include ALL invoices (active + cancelled)
        # because gross GST must include cancelled invoice amounts
        hsn_key = get_hsn(raw) or "MISC"
        hsn_acc[hsn_key]["description"]   = get_items_desc(raw)
        hsn_acc[hsn_key]["taxable_value"] += float(inv.get("taxable_value", 0))
        hsn_acc[hsn_key]["cgst"]          += float(inv.get("cgst_amount", 0))
        hsn_acc[hsn_key]["sgst"]          += float(inv.get("sgst_amount", 0))
        hsn_acc[hsn_key]["igst"]          += float(inv.get("igst_amount", 0))

        if "BILL" in inv_type or "SUPPLY" in inv_type:
            bos_rows.append(row)
        elif "TAX" in inv_type:
            tax_rows.append(row)
        else:
            nongst_rows.append(row)

    def section_total(rows, key):
        return sum(
            float(str(r.get(key,"0")).replace(",","")) for r in rows
        )

    def make_total(rows):
        return {
            "count":         len(rows),
            "taxable_value": fmt(section_total(rows, "taxable_value")),
            "cgst":          fmt(section_total(rows, "cgst_amount")),
            "sgst":          fmt(section_total(rows, "sgst_amount")),
            "igst":          fmt(section_total(rows, "igst_amount")),
        }

    # HSN summary rows
    hsn_rows = []
    for code, acc in hsn_acc.items():
        total_tax = acc["cgst"] + acc["sgst"] + acc["igst"]
        hsn_rows.append({
            "hsn_code":     code,
            "description":  acc["description"],
            "taxable_value":fmt(acc["taxable_value"]),
            "cgst":         fmt(acc["cgst"]),
            "sgst":         fmt(acc["sgst"]),
            "igst":         fmt(acc["igst"]),
            "total_tax":    fmt(total_tax),
        })

    # ── Credit notes section ──────────────────────────────────────────────────
    def make_cn_row(cn):
        cn_data = cn.get("invoice_data") or {}
        return {
            "invoice_number":  cn.get("invoice_number",""),
            "invoice_date":    (cn.get("created_at",""))[:10],
            "customer_name":   cn.get("customer_name","—"),
            "description":     f"Reversal of {cn_data.get('original_invoice_number','')}",
            "taxable_value":   fmt(cn.get("taxable_value",0)),
            "cgst_amount":     fmt(cn.get("cgst_amount",0)),
            "sgst_amount":     fmt(cn.get("sgst_amount",0)),
            "igst_amount":     fmt(cn.get("igst_amount",0)),
        }

    cn_rows = [make_cn_row(cn) for cn in credit_notes]

    def make_cn_total(rows):
        return {
            "count": len(rows),
            "taxable_value": fmt(section_total(rows,"taxable_value")),
            "cgst":          fmt(section_total(rows,"cgst_amount")),
            "sgst":          fmt(section_total(rows,"sgst_amount")),
            "igst":          fmt(section_total(rows,"igst_amount")),
        }

    # Grand totals — ALL original invoices (active + cancelled) for correct gross GST
    # Cancelled invoices created a liability when raised; credit notes reverse them.
    # Both must appear in GSTR-1. Net = gross - reversals.
    all_taxable   = sum(float(inv.get("taxable_value",0)) for inv in invoices)
    all_cgst      = sum(float(inv.get("cgst_amount",0))   for inv in invoices)
    all_sgst      = sum(float(inv.get("sgst_amount",0))   for inv in invoices)
    all_igst      = sum(float(inv.get("igst_amount",0))   for inv in invoices)
    all_gst       = all_cgst + all_sgst + all_igst

    # Credit note reversals
    cn_cgst = sum(float(cn.get("cgst_amount",0)) for cn in credit_notes)
    cn_sgst = sum(float(cn.get("sgst_amount",0)) for cn in credit_notes)
    cn_igst = sum(float(cn.get("igst_amount",0)) for cn in credit_notes)
    cn_gst  = cn_cgst + cn_sgst + cn_igst

    net_gst = all_gst - cn_gst  # Net GST payable after credit note reversals

    return {
        # Header
        "seller_name":    seller.get("seller_name") or "My Business",
        "seller_address": seller.get("seller_address") or "Hyderabad, Telangana",
        "seller_gstin":   seller.get("seller_gstin") or "Not Registered",
        "report_month":   MONTH_NAMES[month_num],
        "report_year":    str(year),
        "generated_date": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "total_count":    sum(1 for inv in invoices if inv.get("status") != "cancelled"),

        # Section A — Tax Invoices
        "tax_invoices":       tax_rows,
        "tax_invoices_total": make_total(tax_rows),

        # Section B — Bill of Supply
        "bos_invoices": bos_rows,
        "bos_total":    make_total(bos_rows),

        # Section C — Non-GST
        "nongst_invoices": nongst_rows,
        "nongst_total":    make_total(nongst_rows),

        # Section D — HSN Summary
        "hsn_summary": hsn_rows,
        "hsn_grand_total": {
            "taxable_value": fmt(sum(float(str(r["taxable_value"]).replace(",","")) for r in hsn_rows)),
            "cgst":  fmt(sum(float(str(r["cgst"]).replace(",","")) for r in hsn_rows)),
            "sgst":  fmt(sum(float(str(r["sgst"]).replace(",","")) for r in hsn_rows)),
            "igst":  fmt(sum(float(str(r["igst"]).replace(",","")) for r in hsn_rows)),
            "total_tax": fmt(sum(float(str(r["total_tax"]).replace(",","")) for r in hsn_rows)),
        },

        # Section E — Credit Notes
        "credit_notes":       cn_rows,
        "credit_notes_total": make_cn_total(cn_rows),

        # Final Summary (with credit note adjustment)
        "summary": {
            "total_taxable_value": fmt(all_taxable),
            "total_cgst":          fmt(all_cgst),
            "total_sgst":          fmt(all_sgst),
            "total_igst":          fmt(all_igst),
            "total_gst_payable":   fmt(all_gst),     # Gross
            "cn_cgst":             fmt(cn_cgst),
            "cn_sgst":             fmt(cn_sgst),
            "cn_igst":             fmt(cn_igst),
            "net_gst_payable":     fmt(net_gst),     # After credit note reversals ← key field
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# MONTHLY REPORT — STEP 4: PDF + SEND
# ═══════════════════════════════════════════════════════════════════════════════

# generate_report_pdf() removed in v12 — replaced by generate_report_pdf_local() from pdf_generators.py


# ═══════════════════════════════════════════════════════════════════════════════
# MONTHLY REPORT — STEP 5: SEND REPORT VIA WHATSAPP
# ═══════════════════════════════════════════════════════════════════════════════

def send_report_whatsapp(twilio, to, pdf_url, report_data, lang="english"):
    month  = report_data.get("report_month","")
    year   = report_data.get("report_year","")
    count  = report_data.get("total_count", 0)
    tv     = report_data.get("summary",{}).get("total_taxable_value","0.00")
    gst    = report_data.get("summary",{}).get("total_gst_payable","0.00")
    net    = report_data.get("summary",{}).get("net_gst_payable","0.00")
    cn_cnt = len(report_data.get("credit_notes",[]))

    if lang == "telugu":
        cn_line = f"❌ Credit Notes: {cn_cnt}\n" if cn_cnt else ""
        body = (
            f"📊 *{month} {year} Invoice Report Ready!*\n\n"
            f"📄 Total Invoices: {count}\n"
            f"{cn_line}"
            f"💰 Total Taxable Value: Rs.{tv}\n"
            f"🏛️ Gross GST: Rs.{gst}\n"
            f"✅ Net GST Payable: Rs.{net}\n\n"
            f"_GutInvoice 🎙️ — మీ గొంతే మీ Invoice_"
        )
    else:
        cn_line = f"❌ Credit Notes: {cn_cnt}\n" if cn_cnt else ""
        body = (
            f"📊 *{month} {year} Invoice & Tax Report*\n\n"
            f"📄 Total Invoices: {count}\n"
            f"{cn_line}"
            f"💰 Total Taxable Value: Rs.{tv}\n"
            f"🏛️ Gross GST: Rs.{gst}\n"
            f"✅ Net GST Payable to Govt: Rs.{net}\n\n"
            f"_Powered by GutInvoice 🎙️ — Every Invoice has a Voice_"
        )

    msg = twilio.messages.create(
        from_=env("TWILIO_FROM_NUMBER"),
        to=to,
        body=body,
        media_url=[pdf_url]
    )
    log.info(f"Report sent: {msg.sid}")


# ═══════════════════════════════════════════════════════════════════════════════
# FULL REPORT PIPELINE — called from webhook
# ═══════════════════════════════════════════════════════════════════════════════

def handle_report_request(twilio, from_num, seller, month_num, year, lang):
    """End-to-end: fetch → aggregate → PDF → send."""
    month_name = MONTH_NAMES[month_num]

    # Acknowledge immediately
    send_msg(twilio, from_num,
        f"📊 Generating your *{month_name} {year} report*... ⏳\n_(This may take 30–60 seconds)_"
        if lang != "telugu" else
        f"📊 మీ *{month_name} {year} report* generate అవుతోంది... ⏳\n_(30–60 seconds పట్టవచ్చు)_"
    )

    invoices, credit_notes = fetch_monthly_invoices(from_num, month_num, year)

    if not invoices and not credit_notes:
        send_msg(twilio, from_num,
            f"ℹ️ No invoices found for *{month_name} {year}*.\n"
            f"Send a voice note to create invoices first!"
            if lang != "telugu" else
            f"ℹ️ *{month_name} {year}* లో invoices కనుగొనబడలేదు.\n"
            f"Invoice create చేయడానికి voice note పంపండి!"
        )
        return

    report_data = aggregate_report_data(invoices, credit_notes, seller, month_num, year)
    pdf_url     = generate_report_pdf_local(report_data, from_num)
    send_report_whatsapp(twilio, from_num, pdf_url, report_data, lang)
    log.info(f"✅ Report delivered for {from_num} — {month_name} {year}")


# ═══════════════════════════════════════════════════════════════════════════════
# ONBOARDING MESSAGES — identical to v10
# ═══════════════════════════════════════════════════════════════════════════════

def msg_welcome():
    return (
        "🎙️ *Welcome to GutInvoice!*\n"
        "_Every Invoice has a Voice_\n\n"
        "Please choose your preferred language:\n\n"
        "1️⃣  *English*\n"
        "2️⃣  *Telugu* (తెలుగు)\n"
        "3️⃣  *Both* (English + Telugu)\n\n"
        "Reply with *1*, *2*, or *3*"
    )

def msg_lang_confirmed(lang):
    return {"english":"✅ Language set to *English*.",
            "telugu": "✅ భాష *Telugu* గా సెట్ చేయబడింది.",
            "both":   "✅ Language set to *English + Telugu*."}.get(lang,"✅ Done.")

def msg_ask_register(lang):
    if lang == "telugu":
        return ("\n\n📝 మీ వ్యాపార వివరాలు నమోదు చేయాలా?\n"
                "_(ఒక్కసారి నమోదు చేస్తే — ప్రతి invoice లో auto-fill అవుతాయి!)_\n\n"
                "✅ *YES* — నమోదు చేయండి\n⏭️ *NO* — Skip & start")
    return ("\n\n📝 Would you like to register your *business details*?\n"
            "_(Set once — auto-filled on every invoice forever!)_\n\n"
            "✅ Reply *YES* to register\n⏭️ Reply *NO* to skip and start")

def msg_ask_name(lang):
    if lang == "telugu":
        return "🏪 మీ *వ్యాపార పేరు* చెప్పండి:\n_(skip చేయాలంటే *SKIP* అని పంపండి)_"
    return "🏪 Enter your *Business Name*:\n_(Type *SKIP* to leave blank)_"

def msg_ask_address(lang):
    if lang == "telugu":
        return "📍 మీ *వ్యాపార చిరునామా* చెప్పండి:\n_(skip చేయాలంటే *SKIP* అని పంపండి)_"
    return "📍 Enter your *Business Address*:\n_(Type *SKIP* to leave blank)_"

def msg_ask_gstin(lang):
    if lang == "telugu":
        return "🔢 మీ *GSTIN నంబర్* చెప్పండి:\n_(లేకపోతే *SKIP* అని పంపండి)_"
    return "🔢 Enter your *GSTIN Number*:\n_(Type *SKIP* if not applicable)_"

def msg_reg_complete(lang, seller):
    name = seller.get("seller_name") or "Not set"
    addr = seller.get("seller_address") or "Not set"
    gstin= seller.get("seller_gstin") or "Not set"
    if lang == "telugu":
        return (f"✅ *నమోదు పూర్తయింది!*\n\n🏪 పేరు: {name}\n📍 చిరునామా: {addr}\n"
                f"🔢 GSTIN: {gstin}\n\n🎙️ Voice note పంపండి — 30 seconds లో PDF వస్తుంది!\n"
                f"_ఉదాహరణ: \"Customer Suresh, 50 iron rods, 800 rupees, 18% GST\"_")
    return (f"✅ *Registration Complete!*\n\n🏪 Name: {name}\n📍 Address: {addr}\n"
            f"🔢 GSTIN: {gstin}\n\n🎙️ Send a *voice note* with invoice details.\n"
            f"_Example: \"Customer Suresh, 50 iron rods, 800 each, 18% GST\"_")

def msg_ready(lang):
    if lang == "telugu":
        return ("✅ *GutInvoice Ready!*\n\n🎙️ Voice note పంపండి — 30 seconds లో PDF వస్తుంది!\n"
                "_ఉదాహరణ: \"Customer Suresh, 50 rods, 800 rupees each, 18% GST\"_")
    return ("✅ *GutInvoice Ready!*\n\n🎙️ Send a *voice note* with invoice details.\n"
            "_Example: \"Customer Suresh, 50 rods, 800 each, 18% GST\"_")

def msg_voice_reminder(lang):
    if lang == "telugu":
        return ("🎙️ Invoice కోసం *voice note* పంపండి!\n"
                "📊 Monthly report కోసం: *'January 2026 summary'* అని పంపండి\n"
                "_సహాయానికి *HELP* type చేయండి._")
    return ("🎙️ Send a *voice note* to generate an invoice!\n"
            "📊 For monthly report: type *'January 2026 summary'*\n"
            "_Type *HELP* for all commands._")

def msg_help(lang):
    if lang == "telugu":
        return ("📖 *GutInvoice Help*\n\n"
                "🎙️ *Voice note* — invoice generate చేయండి\n"
                "📊 *'January 2026 summary'* — monthly report పంపండి\n"
                "📝 *UPDATE* — profile update చేయండి\n"
                "📈 *STATUS* — invoice count చూడండి\n\n"
                "_ఉదాహరణ: \"Customer Suresh, 50 rods, 800 each, 18% GST\"_")
    return ("📖 *GutInvoice Help*\n\n"
            "🎙️ *Voice note* — generate an invoice\n"
            "📊 *'January 2026 summary'* — get monthly PDF report\n"
            "📝 *UPDATE* — change your business profile\n"
            "📈 *STATUS* — see your invoice count\n\n"
            "_Example: \"Customer Suresh, 50 rods, 800 each, 18% GST\"_")

def msg_status(lang, seller):
    name  = seller.get("seller_name") or "Not set"
    gstin = seller.get("seller_gstin") or "Not set"
    count = seller.get("total_invoices", 0)
    if lang == "telugu":
        return f"📊 *మీ GutInvoice Status*\n\n🏪 {name}\n🔢 GSTIN: {gstin}\n📄 Total Invoices: {count}"
    return f"📊 *Your GutInvoice Status*\n\n🏪 {name}\n🔢 GSTIN: {gstin}\n📄 Total Invoices: {count}"

def send_msg(twilio, to, body):
    twilio.messages.create(from_=env("TWILIO_FROM_NUMBER"), to=to, body=body)


# ═══════════════════════════════════════════════════════════════════════════════
# ONBOARDING STATE MACHINE — identical to v10
# ═══════════════════════════════════════════════════════════════════════════════

def handle_onboarding(twilio, from_num, seller, body_text):
    step = seller.get("onboarding_step","new")
    lang = seller.get("language","english")
    txt  = (body_text or "").strip()

    if step == "new":
        update_seller(from_num, {"onboarding_step":"language_asked"})
        send_msg(twilio, from_num, msg_welcome())
        return True

    if step == "language_asked":
        chosen = {"1":"english","2":"telugu","3":"both"}.get(txt.strip())
        if not chosen:
            send_msg(twilio, from_num, "Please reply with *1* (English), *2* (Telugu), or *3* (Both).")
            return True
        update_seller(from_num, {"language":chosen,"onboarding_step":"registration_asked"})
        send_msg(twilio, from_num, msg_lang_confirmed(chosen) + msg_ask_register(chosen))
        return True

    if step == "registration_asked":
        if txt.upper() in ("YES","Y","అవును","HA"):
            update_seller(from_num, {"onboarding_step":"reg_name"})
            send_msg(twilio, from_num, msg_ask_name(lang))
        else:
            update_seller(from_num, {"onboarding_step":"complete","is_profile_complete":False})
            send_msg(twilio, from_num, msg_ready(lang))
        return True

    if step == "reg_name":
        update_seller(from_num, {
            "seller_name": None if txt.upper()=="SKIP" else txt,
            "onboarding_step":"reg_address"
        })
        send_msg(twilio, from_num, msg_ask_address(lang))
        return True

    if step == "reg_address":
        update_seller(from_num, {
            "seller_address": None if txt.upper()=="SKIP" else txt,
            "onboarding_step":"reg_gstin"
        })
        send_msg(twilio, from_num, msg_ask_gstin(lang))
        return True

    if step == "reg_gstin":
        gstin_val = None if txt.upper()=="SKIP" else txt.upper().strip()
        update_seller(from_num, {
            "seller_gstin":gstin_val,
            "onboarding_step":"complete",
            "is_profile_complete":True
        })
        updated = get_seller(from_num) or {}
        send_msg(twilio, from_num, msg_reg_complete(lang, updated))
        return True

    if step == "complete":
        cmd = txt.upper()
        if cmd in ("UPDATE","CHANGE","EDIT","PROFILE"):
            update_seller(from_num, {"onboarding_step":"reg_name"})
            send_msg(twilio, from_num, f"📝 Let's update your profile!\n\n{msg_ask_name(lang)}")
        elif cmd in ("HELP","సహాయం"):
            send_msg(twilio, from_num, msg_help(lang))
        elif cmd in ("STATUS","STATS"):
            fresh = get_seller(from_num) or seller
            send_msg(twilio, from_num, msg_status(lang, fresh))
        else:
            send_msg(twilio, from_num, msg_voice_reminder(lang))
        return True

    return True


# ═══════════════════════════════════════════════════════════════════════════════
# INVOICE PIPELINE — identical to v9/v10
# ═══════════════════════════════════════════════════════════════════════════════

def download_audio(media_url):
    if media_url.startswith("/"):
        media_url = f"https://api.twilio.com{media_url}"
    r = requests.get(
        media_url,
        auth=(env("TWILIO_ACCOUNT_SID"), env("TWILIO_AUTH_TOKEN")),
        timeout=30
    )
    r.raise_for_status()
    log.info(f"Audio: {len(r.content)} bytes | {r.headers.get('content-type')}")
    return r.content


def transcribe_audio(audio_bytes, language="english"):
    src_lang = "te-IN" if language in ("telugu","both") else "en-IN"
    r = requests.post(
        "https://api.sarvam.ai/speech-to-text-translate",
        headers={"API-Subscription-Key": env("SARVAM_API_KEY")},
        files={"file": ("audio.ogg", audio_bytes, "audio/ogg")},
        data={
            "model":"saaras:v2.5",
            "source_language_code": src_lang,
            "target_language_code":"en-IN"
        },
        timeout=60
    )
    if r.status_code != 200:
        raise Exception(f"Sarvam error {r.status_code}: {r.text[:300]}")
    result = safe_json(r, "Sarvam")
    transcript = (result.get("transcript","") or result.get("translated_text","")
                  or result.get("text","") or "").strip()
    if not transcript:
        raise Exception("Sarvam returned empty transcript. Please speak clearly and try again.")
    log.info(f"Transcript: {transcript}")
    return transcript


def extract_invoice_data(transcript, seller, inv_no: str):
    """Extract invoice JSON from transcript via Claude. inv_no is pre-generated sequentially."""
    today  = datetime.now().strftime("%d/%m/%Y")
    seller_name    = seller.get("seller_name") or "My Business"
    seller_address = seller.get("seller_address") or "Hyderabad, Telangana"
    seller_gstin   = seller.get("seller_gstin") or ""

    prompt = f"""You are a GST invoice assistant for Indian small businesses.
Extract invoice details from this transcript and return ONLY valid JSON.
Seller may speak Telugu, English, or a mix of both.

Transcript: {transcript}

Seller: {seller_name}, {seller_address}, GSTIN: {seller_gstin}
Date: {today}, Invoice No: {inv_no}

Rules:
- invoice_type: "TAX INVOICE" (has GSTIN) | "BILL OF SUPPLY" (composition) | "INVOICE" (unregistered)
- If seller has no GSTIN, use "INVOICE"
- Intra-state (Telangana): CGST+SGST split equally. Inter-state: IGST only.
- amount = qty x rate. total_amount = taxable_value + all taxes.
- Default GST 18% if not mentioned.
- BILL OF SUPPLY declaration: "Composition taxable person, not eligible to collect tax on supplies"
- INVOICE declaration: "Seller not registered under GST. GST not applicable."

Return ONLY this JSON, no extra text:
{{"invoice_type":"TAX INVOICE","seller_name":"{seller_name}","seller_address":"{seller_address}","seller_gstin":"{seller_gstin}","invoice_number":"{inv_no}","invoice_date":"{today}","customer_name":"","customer_address":"","customer_gstin":"","place_of_supply":"Telangana","reverse_charge":"No","items":[{{"sno":1,"description":"","hsn_sac":"","qty":0,"unit":"Nos","rate":0,"amount":0}}],"taxable_value":0,"cgst_rate":9,"cgst_amount":0,"sgst_rate":9,"sgst_amount":0,"igst_rate":0,"igst_amount":0,"total_amount":0,"declaration":"","payment_terms":"Pay within 15 days"}}"""

    claude = get_claude()
    msg = claude.messages.create(
        model="claude-opus-4-6", max_tokens=1500,
        messages=[{"role":"user","content":prompt}]
    )
    if not msg.content or not msg.content[0].text:
        raise Exception("Claude returned empty response.")
    text = msg.content[0].text.strip()
    log.info(f"Claude raw: {text[:300]}")
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    start = text.find("{"); end = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise Exception(f"No JSON in Claude response: {text[:200]}")
    data = json.loads(text[start:end])
    log.info(f"Invoice: {data.get('invoice_type')} for {data.get('customer_name')}")
    return data


# generate_pdf() removed in v12 — replaced by select_and_generate_pdf() from pdf_generators.py


def send_invoice_whatsapp(twilio, to, pdf_url, invoice_data, lang="english"):
    if lang == "telugu":
        body = (f"✅ *మీ {invoice_data.get('invoice_type','Invoice')} Ready!*\n\n"
                f"📋 {invoice_data.get('invoice_number','')}\n"
                f"👤 {invoice_data.get('customer_name','Customer')}\n"
                f"💰 ₹{invoice_data.get('total_amount',0):,.0f}\n\n"
                f"Powered by *GutInvoice* 🎙️\n_మీ గొంతే మీ Invoice_")
    else:
        body = (f"✅ *Your {invoice_data.get('invoice_type','Invoice')} is Ready!*\n\n"
                f"📋 {invoice_data.get('invoice_number','')}\n"
                f"👤 {invoice_data.get('customer_name','Customer')}\n"
                f"💰 ₹{invoice_data.get('total_amount',0):,.0f}\n\n"
                f"Powered by *GutInvoice* 🎙️\n_Every Invoice has a Voice_")
    msg = twilio.messages.create(
        from_=env("TWILIO_FROM_NUMBER"), to=to, body=body, media_url=[pdf_url]
    )
    log.info(f"Invoice sent: {msg.sid}")


# ═══════════════════════════════════════════════════════════════════════════════
# WEBHOOK — v11 adds report detection before everything else
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/webhook", methods=["POST"])
def webhook():
    twilio     = get_twilio()
    from_num   = request.form.get("From","")
    body_text  = request.form.get("Body","").strip()
    num_media  = int(request.form.get("NumMedia",0))
    media_type = request.form.get("MediaContentType0","")
    media_url  = request.form.get("MediaUrl0","")

    log.info(f"Webhook — From: {from_num} | Media: {num_media} | Body: '{body_text[:60]}'")

    try:
        seller = get_or_create_seller(from_num)
        step   = seller.get("onboarding_step","new")
        lang   = seller.get("language","english")

        # ── AUDIO (voice note) ───────────────────────────────────────────────
        if num_media > 0 and ("audio" in media_type or "ogg" in media_type):

            if step != "complete":
                if step == "new":
                    handle_onboarding(twilio, from_num, seller, "")
                else:
                    send_msg(twilio, from_num,
                        "Please finish the quick setup first! Reply to the question above. 🙏")
                return Response("OK", status=200)

            # Transcribe first to check if it's a report request
            send_msg(twilio, from_num,
                "🎙️ Voice note received! Processing... ⏳"
                if lang != "telugu" else
                "🎙️ Voice note అందింది! Process అవుతోంది... ⏳"
            )

            audio      = download_audio(media_url)
            transcript = transcribe_audio(audio, lang)

            # ── 1. Check if voice is asking to CANCEL an invoice ────────────
            is_cancel, inv_fragment = detect_cancel_request(transcript)
            if is_cancel:
                handle_cancel_request(twilio, from_num, seller, inv_fragment, lang)
                return Response("OK", status=200)

            # ── 2. Check if voice is asking for a REPORT ────────────────────
            is_report, month_num, year = detect_report_from_voice(transcript)
            if is_report:
                handle_report_request(twilio, from_num, seller, month_num, year, lang)
                return Response("OK", status=200)

            # ── 3. Regular invoice pipeline ──────────────────────────────────
            send_msg(twilio, from_num,
                "Generating your invoice... _(Ready in ~30 seconds)_"
                if lang != "telugu" else
                "Invoice generate అవుతోంది... _(30 seconds లో ready)_"
            )
            now      = datetime.now()
            inv_no   = get_next_invoice_number(from_num, seller.get("seller_name") or "GUT", now.month, now.year)
            invoice  = extract_invoice_data(transcript, seller, inv_no)
            pdf_url  = select_and_generate_pdf(invoice, from_num)
            save_invoice(from_num, invoice, pdf_url, transcript)
            send_invoice_whatsapp(twilio, from_num, pdf_url, invoice, lang)
            log.info(f"✅ Invoice {inv_no} delivered + saved for {from_num}")
            return Response("OK", status=200)

        # ── NON-AUDIO MEDIA ──────────────────────────────────────────────────
        if num_media > 0 and "audio" not in media_type:
            send_msg(twilio, from_num,
                "Please send a *voice note* 🎙️, not an image or document."
                if lang != "telugu" else
                "*Voice note* పంపండి 🎙️ — image లేదా document కాదు."
            )
            return Response("OK", status=200)

        # ── TEXT MESSAGE ─────────────────────────────────────────────────────
        if step == "complete" and body_text:
            # 1. Check for cancel request
            is_cancel, inv_fragment = detect_cancel_request(body_text)
            if is_cancel:
                handle_cancel_request(twilio, from_num, seller, inv_fragment, lang)
                return Response("OK", status=200)

            # 2. Check if text is a report request
            is_report, month_num, year = is_report_request(body_text)
            if is_report:
                handle_report_request(twilio, from_num, seller, month_num, year, lang)
                return Response("OK", status=200)

        # Route through onboarding handler
        handle_onboarding(twilio, from_num, seller, body_text)
        return Response("OK", status=200)

    except Exception as e:
        log.error(f"❌ Error: {e}", exc_info=True)
        try:
            send_msg(twilio, from_num, f"❌ Error: {str(e)[:180]}\n\nPlease try again.")
        except:
            pass
        return Response("Error", status=500)


# ═══════════════════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/health")
def health():
    keys = [
        "TWILIO_ACCOUNT_SID","TWILIO_AUTH_TOKEN","TWILIO_FROM_NUMBER",
        "SARVAM_API_KEY","CLAUDE_API_KEY",
        "SUPABASE_URL","SUPABASE_KEY"
        # v12: CARBONE_* keys no longer needed — PDF generation is local (ReportLab)
    ]
    checks = {k: bool(env(k)) for k in keys}
    try:
        r = requests.get(sb_url("sellers","?limit=1"), headers=sb_headers(), timeout=5)
        checks["supabase_connection"] = (r.status_code == 200)
    except:
        checks["supabase_connection"] = False

    all_ok = all(checks.values())
    return {
        "status":    "healthy" if all_ok else "missing_config",
        "version":   "v13",
        "checks":    checks,
        "timestamp": datetime.now().isoformat()
    }, 200 if all_ok else 500


# ═══════════════════════════════════════════════════════════════════════════════
# HOME
# ═══════════════════════════════════════════════════════════════════════════════

HOME_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>GutInvoice — Every Invoice has a Voice</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0A0F1E;color:#fff;min-height:100vh}
nav{display:flex;justify-content:space-between;align-items:center;padding:18px 60px;border-bottom:1px solid rgba(255,107,53,0.12);background:rgba(10,15,30,0.98)}
.logo{font-size:24px;font-weight:900;color:#FF6B35}.logo span{color:#fff}
.logo-sub{font-size:11px;color:#475569;margin-top:3px;letter-spacing:1px;text-transform:uppercase}
.live-pill{display:flex;align-items:center;gap:8px;background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.25);padding:8px 18px;border-radius:50px;font-size:12px;color:#10B981;font-weight:700}
.live-dot{width:7px;height:7px;background:#10B981;border-radius:50%;animation:blink 2s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0.4}}
.hero{min-height:90vh;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;padding:80px 40px}
.hero h1{font-size:clamp(42px,7vw,82px);font-weight:900;line-height:1.05;letter-spacing:-2.5px;margin-bottom:24px}
.hero h1 em{color:#FF6B35;font-style:normal}
.hero-desc{font-size:20px;color:#64748B;max-width:580px;line-height:1.7}
.btn{background:#FF6B35;color:#fff;padding:15px 36px;border-radius:50px;font-size:15px;font-weight:800;text-decoration:none;margin-top:36px;display:inline-block}
footer{border-top:1px solid rgba(255,255,255,0.05);padding:40px;text-align:center;color:#374151;font-size:12px}
</style>
</head>
<body>
<nav>
  <div><div class="logo">Gut<span>Invoice</span></div><div class="logo-sub">Every Invoice has a Voice</div></div>
  <div class="live-pill"><span class="live-dot"></span>LIVE v11</div>
</nav>
<section class="hero">
  <h1>Your Voice.<br/>Your <em>Invoice.</em></h1>
  <p class="hero-desc">Voice note → GST invoice PDF in 30 seconds.<br/>Type "January 2026 summary" → full monthly tax report.</p>
  <p style="color:#FBBF24;font-size:16px;margin-top:16px;font-style:italic">మాట్లాడండి — Invoice వస్తుంది. అంతే.</p>
  <a href="#" class="btn">Start Free — 3 Invoices</a>
</section>
<footer>Built for Telugu-speaking MSMEs · Hyderabad, India · © 2026 GutInvoice</footer>
</body></html>"""

@app.route("/")
def home():
    return render_template_string(HOME_HTML)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    log.info(f"🚀 GutInvoice v11 starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
