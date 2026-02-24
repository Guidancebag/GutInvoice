"""
GutInvoice — Every Invoice has a Voice
v12 — Pure Python PDF Generation (ReportLab replaces Carbone.io)
  ✅ All v11 features intact (onboarding, Supabase, invoice + report pipeline)
  ✅ NEW: pdf_generators.py handles all PDF building locally via ReportLab
  ✅ NEW: PDFs uploaded directly to Supabase Storage bucket "invoices"
  ✅ REMOVED: All Carbone.io API calls (generate_pdf, generate_report_pdf)
  ✅ Zero new env vars — uses existing SUPABASE_URL + SUPABASE_KEY
  ✅ Templates: TAX INVOICE, BILL OF SUPPLY, INVOICE (Non-GST), MONTHLY REPORT
  ✅ All templates have branded footer: Powered by GutInvoice / Developed by Tejesh

After testing, delete from Railway:
    CARBONE_API_KEY
    CARBONE_TAX_VERSION_ID
    CARBONE_BOS_VERSION_ID
    CARBONE_NONGST_VERSION_ID
    CARBONE_REPORT_VERSION_ID

Trigger phrases (text or voice) — unchanged from v11:
    "Send January 2026 summary"
    "January report"
    "జనవరి 2026 invoices summary"
    "Last month summary"
    "February invoices"
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
from pdf_generators import select_and_generate_pdf, generate_report_pdf_local

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
        "status":           "generated"
    }
    r = requests.post(sb_url("invoices"), headers=sb_headers(), json=row, timeout=10)
    rows = safe_json(r, "SB-SaveInvoice")
    log.info(f"Invoice saved: {invoice_data.get('invoice_number')} for {seller_phone}")
    return rows[0] if rows else {}


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
    Fetch all invoices for a seller in a given month/year from Supabase.
    Returns list of invoice dicts.
    """
    # Date range for the month
    from calendar import monthrange
    last_day = monthrange(year, month_num)[1]
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
    invoices = safe_json(r, "SB-FetchMonthly")
    log.info(f"Fetched {len(invoices)} invoices for {seller_phone} in {month_num}/{year}")
    return invoices


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

def aggregate_report_data(invoices, seller, month_num, year):
    """
    Aggregate invoice list into Carbone-ready data dict.
    Splits into TAX / BOS / NONGST sections + HSN summary.
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
        raw = inv.get("invoice_data") or {}
        inv_type = (inv.get("invoice_type") or "").upper()

        row = {
            "invoice_number": inv.get("invoice_number", ""),
            "invoice_date":   (inv.get("created_at") or "")[:10],
            "customer_name":  inv.get("customer_name") or "—",
            "description":    get_items_desc(raw),
            "taxable_value":  fmt(inv.get("taxable_value", 0)),
            "cgst_amount":    fmt(inv.get("cgst_amount", 0)),
            "sgst_amount":    fmt(inv.get("sgst_amount", 0)),
            "igst_amount":    fmt(inv.get("igst_amount", 0)),
            "hsn":            get_hsn(raw),
        }

        # HSN accumulation
        hsn_key = get_hsn(raw) or "MISC"
        hsn_acc[hsn_key]["description"] = get_items_desc(raw)
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

    # Grand totals
    all_taxable = sum(float(inv.get("taxable_value",0)) for inv in invoices)
    all_cgst    = sum(float(inv.get("cgst_amount",0)) for inv in invoices)
    all_sgst    = sum(float(inv.get("sgst_amount",0)) for inv in invoices)
    all_igst    = sum(float(inv.get("igst_amount",0)) for inv in invoices)
    all_gst     = all_cgst + all_sgst + all_igst

    return {
        # Header
        "seller_name":    seller.get("seller_name") or "My Business",
        "seller_address": seller.get("seller_address") or "Hyderabad, Telangana",
        "seller_gstin":   seller.get("seller_gstin") or "Not Registered",
        "report_month":   MONTH_NAMES[month_num],
        "report_year":    str(year),
        "generated_date": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "total_count":    len(invoices),

        # Section 1 — Tax Invoices
        "tax_invoices":       tax_rows if tax_rows else [{"invoice_number":"No tax invoices","invoice_date":"","customer_name":"","description":"","taxable_value":"0.00","cgst_amount":"0.00","sgst_amount":"0.00","igst_amount":"0.00","hsn":""}],
        "tax_invoices_total": make_total(tax_rows),

        # Section 2 — Bill of Supply
        "bos_invoices": bos_rows if bos_rows else [{"invoice_number":"No bill of supply","invoice_date":"","customer_name":"","description":"","taxable_value":"0.00","cgst_amount":"0.00","sgst_amount":"0.00","igst_amount":"0.00","hsn":""}],
        "bos_total":    make_total(bos_rows),

        # Section 3 — Non-GST
        "nongst_invoices": nongst_rows if nongst_rows else [{"invoice_number":"No non-GST invoices","invoice_date":"","customer_name":"","description":"","taxable_value":"0.00","cgst_amount":"0.00","sgst_amount":"0.00","igst_amount":"0.00","hsn":""}],
        "nongst_total":    make_total(nongst_rows),

        # Section 4 — HSN Summary
        "hsn_summary": hsn_rows if hsn_rows else [{"hsn_code":"—","description":"No data","taxable_value":"0.00","cgst":"0.00","sgst":"0.00","igst":"0.00","total_tax":"0.00"}],
        "hsn_grand_total": {
            "taxable_value": fmt(sum(float(str(r["taxable_value"]).replace(",","")) for r in hsn_rows)),
            "cgst":  fmt(sum(float(str(r["cgst"]).replace(",","")) for r in hsn_rows)),
            "sgst":  fmt(sum(float(str(r["sgst"]).replace(",","")) for r in hsn_rows)),
            "igst":  fmt(sum(float(str(r["igst"]).replace(",","")) for r in hsn_rows)),
            "total_tax": fmt(sum(float(str(r["total_tax"]).replace(",","")) for r in hsn_rows)),
        },

        # Section 5 — Summary
        "summary": {
            "total_taxable_value": fmt(all_taxable),
            "total_cgst":          fmt(all_cgst),
            "total_sgst":          fmt(all_sgst),
            "total_igst":          fmt(all_igst),
            "total_gst_payable":   fmt(all_gst),
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# MONTHLY REPORT — STEP 4: RENDER PDF VIA CARBONE
# ═══════════════════════════════════════════════════════════════════════════════

# generate_report_pdf() removed in v12 — replaced by generate_report_pdf_local() from pdf_generators.py


# ═══════════════════════════════════════════════════════════════════════════════
# MONTHLY REPORT — STEP 5: SEND REPORT VIA WHATSAPP
# ═══════════════════════════════════════════════════════════════════════════════

def send_report_whatsapp(twilio, to, pdf_url, report_data, lang="english"):
    month = report_data.get("report_month","")
    year  = report_data.get("report_year","")
    count = report_data.get("total_count", 0)
    tv    = report_data.get("summary",{}).get("total_taxable_value","0.00")
    gst   = report_data.get("summary",{}).get("total_gst_payable","0.00")

    if lang == "telugu":
        body = (
            f"📊 *{month} {year} Invoice Report Ready!*\n\n"
            f"📄 Total Invoices: {count}\n"
            f"💰 Total Taxable Value: ₹{tv}\n"
            f"🏛️ GST Payable: ₹{gst}\n\n"
            f"_GutInvoice 🎙️ — మీ గొంతే మీ Invoice_"
        )
    else:
        body = (
            f"📊 *{month} {year} Invoice & Tax Report*\n\n"
            f"📄 Total Invoices: {count}\n"
            f"💰 Total Taxable Value: ₹{tv}\n"
            f"🏛️ GST Payable to Govt: ₹{gst}\n\n"
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

    invoices = fetch_monthly_invoices(from_num, month_num, year)

    if not invoices:
        send_msg(twilio, from_num,
            f"ℹ️ No invoices found for *{month_name} {year}*.\n"
            f"Send a voice note to create invoices first!"
            if lang != "telugu" else
            f"ℹ️ *{month_name} {year}* లో invoices కనుగొనబడలేదు.\n"
            f"Invoice create చేయడానికి voice note పంపండి!"
        )
        return

    report_data = aggregate_report_data(invoices, seller, month_num, year)
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


def extract_invoice_data(transcript, seller):
    today  = datetime.now().strftime("%d/%m/%Y")
    inv_no = f"GUT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
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

            # ── Check if voice is asking for a REPORT ───────────────────────
            is_report, month_num, year = detect_report_from_voice(transcript)
            if is_report:
                handle_report_request(twilio, from_num, seller, month_num, year, lang)
                return Response("OK", status=200)

            # ── Regular invoice pipeline ─────────────────────────────────────
            send_msg(twilio, from_num,
                "Generating your invoice... _(Ready in ~30 seconds)_"
                if lang != "telugu" else
                "Invoice generate అవుతోంది... _(30 seconds లో ready)_"
            )
            invoice = extract_invoice_data(transcript, seller)
            pdf_url = select_and_generate_pdf(invoice, from_num)
            save_invoice(from_num, invoice, pdf_url, transcript)
            send_invoice_whatsapp(twilio, from_num, pdf_url, invoice, lang)
            log.info(f"✅ Invoice delivered + saved for {from_num}")
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
            # Check if text is a report request BEFORE onboarding handler
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
        "version":   "v12",
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
