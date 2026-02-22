"""
GutInvoice — Every Invoice has a Voice
v10 — Supabase Backend + Onboarding Flow
  ✅ Built on top of working v9 (all pipeline functions identical)
  ✅ Supabase: sellers table (profile + onboarding state + language)
  ✅ Supabase: invoices table (every invoice stored with full JSON + PDF URL)
  ✅ Onboarding: new → language choice → optional registration → complete
  ✅ Language: English | Telugu | Both
  ✅ Seller profile: name, address, GSTIN — all optional, stored in DB
  ✅ Auto-fill seller details on every invoice from saved profile
  ✅ Commands: STATUS, UPDATE, HELP
  ✅ All v9 fixes preserved (no ?download=true, safe_json, saaras:v2.5, versioning=true)

New ENV vars needed in Railway:
    SUPABASE_URL   = https://xxxx.supabase.co
    SUPABASE_KEY   = eyJhbGci...  (service_role key — NOT anon key)
"""

import os
import json
import requests
import anthropic
from flask import Flask, request, Response, render_template_string
from twilio.rest import Client as TwilioClient
from datetime import datetime
import logging

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


# ─── Safe JSON — identical to v9 ─────────────────────────────────────────────
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
# SUPABASE HELPERS
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
    """Fetch seller by phone. Returns dict or None."""
    r = requests.get(
        sb_url("sellers", f"?phone_number=eq.{requests.utils.quote(phone)}&limit=1"),
        headers=sb_headers(), timeout=10
    )
    rows = safe_json(r, "SB-GetSeller")
    return rows[0] if rows else None


def create_seller(phone):
    """Create new seller with default state 'new'."""
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
    """Update seller fields by phone number."""
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
    """Save every generated invoice to Supabase invoices table."""
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
    r = requests.post(
        sb_url("invoices"),
        headers=sb_headers(),
        json=row,
        timeout=10
    )
    rows = safe_json(r, "SB-SaveInvoice")
    log.info(f"Invoice saved: {invoice_data.get('invoice_number')} for {seller_phone}")
    return rows[0] if rows else {}


# ═══════════════════════════════════════════════════════════════════════════════
# ONBOARDING MESSAGES
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
    return {
        "english": "✅ Language set to *English*.",
        "telugu":  "✅ భాష *Telugu* గా సెట్ చేయబడింది.",
        "both":    "✅ Language set to *English + Telugu*."
    }.get(lang, "✅ Done.")

def msg_ask_register(lang):
    if lang == "telugu":
        return (
            "\n\n📝 మీ వ్యాపార వివరాలు నమోదు చేయాలా?\n"
            "_(ఒక్కసారి నమోదు చేస్తే — ప్రతి invoice లో auto-fill అవుతాయి!)_\n\n"
            "✅ *YES* — నమోదు చేయండి\n"
            "⏭️ *NO* — Skip & వెంటనే start చేయండి"
        )
    return (
        "\n\n📝 Would you like to register your *business details*?\n"
        "_(Set once — auto-filled on every invoice forever!)_\n\n"
        "✅ Reply *YES* to register\n"
        "⏭️ Reply *NO* to skip and start invoicing right away"
    )

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
    name    = seller.get("seller_name") or "Not set"
    address = seller.get("seller_address") or "Not set"
    gstin   = seller.get("seller_gstin") or "Not set"
    if lang == "telugu":
        return (
            f"✅ *నమోదు పూర్తయింది!*\n\n"
            f"🏪 పేరు: {name}\n"
            f"📍 చిరునామా: {address}\n"
            f"🔢 GSTIN: {gstin}\n\n"
            f"🎙️ Voice note పంపండి — 30 seconds లో PDF వస్తుంది!\n\n"
            f"_ఉదాహరణ: \"Customer Suresh, 50 iron rods, 800 rupees, 18% GST\"_"
        )
    return (
        f"✅ *Registration Complete!*\n\n"
        f"🏪 Name: {name}\n"
        f"📍 Address: {address}\n"
        f"🔢 GSTIN: {gstin}\n\n"
        f"🎙️ Send a *voice note* with invoice details.\n"
        f"PDF ready in 30 seconds!\n\n"
        f"_Example: \"Customer Suresh, 50 iron rods, 800 each, 18% GST\"_"
    )

def msg_ready(lang):
    if lang == "telugu":
        return (
            "✅ *GutInvoice Ready!*\n\n"
            "🎙️ Voice note పంపండి — 30 seconds లో PDF వస్తుంది!\n\n"
            "_ఉదాహరణ: \"Customer Suresh, 50 rods, 800 rupees each, 18% GST\"_"
        )
    return (
        "✅ *GutInvoice Ready!*\n\n"
        "🎙️ Send a *voice note* with invoice details.\n"
        "PDF delivered in 30 seconds!\n\n"
        "_Example: \"Customer Suresh, 50 rods, 800 each, 18% GST\"_"
    )

def msg_voice_reminder(lang):
    if lang == "telugu":
        return "🎙️ Invoice కోసం *voice note* పంపండి!\n_సహాయానికి *HELP* type చేయండి._"
    return "🎙️ Please send a *voice note* to generate an invoice!\n_Type *HELP* for commands._"

def msg_help(lang):
    if lang == "telugu":
        return (
            "📖 *GutInvoice Help*\n\n"
            "🎙️ *Voice note* — invoice generate చేయండి\n"
            "📝 *UPDATE* — profile update చేయండి\n"
            "📊 *STATUS* — invoice count చూడండి\n\n"
            "_ఉదాహరణ: \"Customer Suresh, 50 rods, 800 each, 18% GST\"_"
        )
    return (
        "📖 *GutInvoice Help*\n\n"
        "🎙️ *Voice note* — generate an invoice\n"
        "📝 *UPDATE* — change your business profile\n"
        "📊 *STATUS* — see your invoice count\n\n"
        "_Example: \"Customer Suresh, 50 rods, 800 each, 18% GST\"_"
    )

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
# ONBOARDING STATE MACHINE
# States: new → language_asked → registration_asked
#         → reg_name → reg_address → reg_gstin → complete
# ═══════════════════════════════════════════════════════════════════════════════

def handle_onboarding(twilio, from_num, seller, body_text):
    """
    Route text messages through onboarding states.
    Always returns True (onboarding handled the message).
    """
    step = seller.get("onboarding_step", "new")
    lang = seller.get("language", "english")
    txt  = (body_text or "").strip()

    # new → send welcome, ask language
    if step == "new":
        update_seller(from_num, {"onboarding_step": "language_asked"})
        send_msg(twilio, from_num, msg_welcome())
        return True

    # language_asked → process 1/2/3
    if step == "language_asked":
        chosen = {"1": "english", "2": "telugu", "3": "both"}.get(txt.strip())
        if not chosen:
            send_msg(twilio, from_num,
                "Please reply with *1* (English), *2* (Telugu), or *3* (Both).")
            return True
        update_seller(from_num, {"language": chosen, "onboarding_step": "registration_asked"})
        send_msg(twilio, from_num, msg_lang_confirmed(chosen) + msg_ask_register(chosen))
        return True

    # registration_asked → YES or NO
    if step == "registration_asked":
        if txt.upper() in ("YES", "Y", "అవును", "HA"):
            update_seller(from_num, {"onboarding_step": "reg_name"})
            send_msg(twilio, from_num, msg_ask_name(lang))
        else:
            update_seller(from_num, {"onboarding_step": "complete", "is_profile_complete": False})
            send_msg(twilio, from_num, msg_ready(lang))
        return True

    # reg_name → save name, ask address
    if step == "reg_name":
        update_seller(from_num, {
            "seller_name": None if txt.upper() == "SKIP" else txt,
            "onboarding_step": "reg_address"
        })
        send_msg(twilio, from_num, msg_ask_address(lang))
        return True

    # reg_address → save address, ask GSTIN
    if step == "reg_address":
        update_seller(from_num, {
            "seller_address": None if txt.upper() == "SKIP" else txt,
            "onboarding_step": "reg_gstin"
        })
        send_msg(twilio, from_num, msg_ask_gstin(lang))
        return True

    # reg_gstin → save GSTIN, mark complete
    if step == "reg_gstin":
        gstin_val = None if txt.upper() == "SKIP" else txt.upper().strip()
        update_seller(from_num, {
            "seller_gstin": gstin_val,
            "onboarding_step": "complete",
            "is_profile_complete": True
        })
        updated = get_seller(from_num) or {}
        send_msg(twilio, from_num, msg_reg_complete(lang, updated))
        return True

    # complete → handle commands
    if step == "complete":
        cmd = txt.upper()
        if cmd in ("UPDATE", "CHANGE", "EDIT", "PROFILE"):
            update_seller(from_num, {"onboarding_step": "reg_name"})
            send_msg(twilio, from_num, f"📝 Let's update your profile!\n\n{msg_ask_name(lang)}")
        elif cmd in ("HELP", "సహాయం"):
            send_msg(twilio, from_num, msg_help(lang))
        elif cmd in ("STATUS", "STATS"):
            fresh = get_seller(from_num) or seller
            send_msg(twilio, from_num, msg_status(lang, fresh))
        else:
            send_msg(twilio, from_num, msg_voice_reminder(lang))
        return True

    return True


# ═══════════════════════════════════════════════════════════════════════════════
# INVOICE PIPELINE — identical to v9
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
    log.info(f"Audio downloaded: {len(r.content)} bytes | type: {r.headers.get('content-type')}")
    return r.content


def transcribe_audio(audio_bytes, language="english"):
    """
    Sarvam AI transcription — identical to v9.
    saaras:v2.5 handles Telugu, English, and mixed speech.
    te-IN source for Telugu/Both. en-IN for English only.
    """
    src_lang = "te-IN" if language in ("telugu", "both") else "en-IN"
    r = requests.post(
        "https://api.sarvam.ai/speech-to-text-translate",
        headers={"API-Subscription-Key": env("SARVAM_API_KEY")},
        files={"file": ("audio.ogg", audio_bytes, "audio/ogg")},
        data={
            "model": "saaras:v2.5",
            "source_language_code": src_lang,
            "target_language_code": "en-IN"
        },
        timeout=60
    )
    if r.status_code != 200:
        raise Exception(f"Sarvam error {r.status_code}: {r.text[:300]}")

    result = safe_json(r, "Sarvam")
    transcript = (
        result.get("transcript", "")
        or result.get("translated_text", "")
        or result.get("text", "")
        or ""
    ).strip()

    if not transcript:
        log.warning(f"Sarvam empty transcript. Keys: {list(result.keys())}")
        raise Exception("Sarvam returned empty transcript. Please speak clearly and try again.")

    log.info(f"Transcript: {transcript}")
    return transcript


def extract_invoice_data(transcript, seller):
    """
    Claude AI extraction — identical to v9.
    seller dict now comes from Supabase (auto-filled from profile).
    """
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
        model="claude-opus-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )

    if not msg.content or not msg.content[0].text:
        raise Exception("Claude returned empty response.")

    text = msg.content[0].text.strip()
    log.info(f"Claude raw: {text[:300]}")

    if not text:
        raise Exception("Claude returned blank text response.")

    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    start = text.find("{")
    end   = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise Exception(f"No JSON in Claude response: {text[:200]}")
    text = text[start:end]

    if not text.strip():
        raise Exception("Extracted JSON string is empty.")

    data = json.loads(text)
    log.info(f"Invoice parsed: {data.get('invoice_type')} for {data.get('customer_name')}")
    return data


def generate_pdf(invoice_data):
    """
    Carbone PDF generation — identical to v9.
    No ?download=true. Returns renderId JSON, builds URL from it.
    """
    t = invoice_data.get("invoice_type", "TAX INVOICE")

    if "BILL" in t:
        version_id = env("CARBONE_BOS_VERSION_ID")
    elif "TAX" in t:
        version_id = env("CARBONE_TAX_VERSION_ID")
    else:
        version_id = env("CARBONE_NONGST_VERSION_ID")

    if not version_id:
        raise Exception(f"Missing Carbone versionId for: {t}. Check Railway env vars.")

    log.info(f"Carbone versionId: {version_id[:16]}... for {t}")

    r = requests.post(
        f"https://api.carbone.io/render/{version_id}?versioning=true",
        headers={
            "Authorization": f"Bearer {env('CARBONE_API_KEY')}",
            "Content-Type": "application/json",
            "carbone-version": "5"
        },
        json={"data": invoice_data, "convertTo": "pdf"},
        timeout=60
    )

    if r.status_code != 200:
        raise Exception(f"Carbone error {r.status_code}: {r.text[:300]}")

    result = safe_json(r, "Carbone-Render")
    rid = result.get("data", {}).get("renderId")
    if not rid:
        raise Exception(f"Carbone returned no renderId. Response: {result}")

    pdf_url = f"https://api.carbone.io/render/{rid}"
    log.info(f"PDF ready: {pdf_url}")
    return pdf_url


def send_invoice_whatsapp(twilio, to, pdf_url, invoice_data, lang="english"):
    if lang == "telugu":
        body = (
            f"✅ *మీ {invoice_data.get('invoice_type','Invoice')} Ready!*\n\n"
            f"📋 {invoice_data.get('invoice_number','')}\n"
            f"👤 {invoice_data.get('customer_name','Customer')}\n"
            f"💰 ₹{invoice_data.get('total_amount',0):,.0f}\n\n"
            f"Powered by *GutInvoice* 🎙️\n_మీ గొంతే మీ Invoice_"
        )
    else:
        body = (
            f"✅ *Your {invoice_data.get('invoice_type','Invoice')} is Ready!*\n\n"
            f"📋 {invoice_data.get('invoice_number','')}\n"
            f"👤 {invoice_data.get('customer_name','Customer')}\n"
            f"💰 ₹{invoice_data.get('total_amount',0):,.0f}\n\n"
            f"Powered by *GutInvoice* 🎙️\n_Every Invoice has a Voice_"
        )
    msg = twilio.messages.create(
        from_=env("TWILIO_FROM_NUMBER"),
        to=to,
        body=body,
        media_url=[pdf_url]
    )
    log.info(f"Invoice sent: {msg.sid}")


# ═══════════════════════════════════════════════════════════════════════════════
# WEBHOOK
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/webhook", methods=["POST"])
def webhook():
    twilio     = get_twilio()
    from_num   = request.form.get("From", "")
    body_text  = request.form.get("Body", "").strip()
    num_media  = int(request.form.get("NumMedia", 0))
    media_type = request.form.get("MediaContentType0", "")
    media_url  = request.form.get("MediaUrl0", "")

    log.info(f"Webhook — From: {from_num} | Media: {num_media} | Type: {media_type} | Body: '{body_text[:50]}'")

    try:
        seller = get_or_create_seller(from_num)
        step   = seller.get("onboarding_step", "new")
        lang   = seller.get("language", "english")

        # ── Voice note received ──────────────────────────────────────────────
        if num_media > 0 and ("audio" in media_type or "ogg" in media_type):

            # Block audio until onboarding is complete
            if step != "complete":
                if step == "new":
                    # Trigger welcome flow
                    handle_onboarding(twilio, from_num, seller, "")
                else:
                    send_msg(twilio, from_num,
                        "Please finish the quick setup first! Reply to the question above. 🙏")
                return Response("OK", status=200)

            # ── Invoice pipeline (identical to v9) ───────────────────────────
            send_msg(twilio, from_num,
                "🎙️ Voice note received! Generating your invoice... ⏳\n_(Ready in ~30 seconds)_"
                if lang != "telugu" else
                "🎙️ Voice note అందింది! Invoice generate అవుతోంది... ⏳\n_(30 seconds లో ready)_"
            )

            audio      = download_audio(media_url)
            transcript = transcribe_audio(audio, lang)
            invoice    = extract_invoice_data(transcript, seller)
            pdf_url    = generate_pdf(invoice)

            # ✅ NEW in v10: save to Supabase
            save_invoice(from_num, invoice, pdf_url, transcript)

            # Send PDF to WhatsApp
            send_invoice_whatsapp(twilio, from_num, pdf_url, invoice, lang)
            log.info(f"✅ Invoice delivered + saved to Supabase for {from_num}")
            return Response("OK", status=200)

        # ── Non-audio media (image / doc) ────────────────────────────────────
        if num_media > 0 and "audio" not in media_type:
            send_msg(twilio, from_num,
                "Please send a *voice note* 🎙️, not an image or document."
                if lang != "telugu" else
                "*Voice note* పంపండి 🎙️ — image లేదా document కాదు."
            )
            return Response("OK", status=200)

        # ── Text message → onboarding handler ───────────────────────────────
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
        "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER",
        "SARVAM_API_KEY", "CLAUDE_API_KEY", "CARBONE_API_KEY",
        "CARBONE_TAX_VERSION_ID", "CARBONE_BOS_VERSION_ID", "CARBONE_NONGST_VERSION_ID",
        "SUPABASE_URL", "SUPABASE_KEY"
    ]
    checks = {k: bool(env(k)) for k in keys}

    # Live Supabase connection test
    try:
        r = requests.get(sb_url("sellers", "?limit=1"), headers=sb_headers(), timeout=5)
        checks["supabase_connection"] = (r.status_code == 200)
    except Exception as e:
        checks["supabase_connection"] = False
        log.warning(f"Supabase health check failed: {e}")

    all_ok = all(checks.values())
    return {
        "status":    "healthy" if all_ok else "missing_config",
        "version":   "v10",
        "checks":    checks,
        "timestamp": datetime.now().isoformat()
    }, 200 if all_ok else 500


# ═══════════════════════════════════════════════════════════════════════════════
# HOME PAGE
# ═══════════════════════════════════════════════════════════════════════════════

HOME_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>GutInvoice — Every Invoice has a Voice</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--orange:#FF6B35;--navy:#0A0F1E;--green:#10B981;--card:#111827}
body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--navy);color:#fff;min-height:100vh;overflow-x:hidden}
nav{display:flex;justify-content:space-between;align-items:center;padding:18px 60px;border-bottom:1px solid rgba(255,107,53,0.12);background:rgba(10,15,30,0.98);position:sticky;top:0;z-index:100}
.logo{font-size:24px;font-weight:900;color:var(--orange)}.logo span{color:#fff}
.logo-sub{font-size:11px;color:#475569;margin-top:3px;letter-spacing:1px;text-transform:uppercase}
.live-pill{display:flex;align-items:center;gap:8px;background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.25);padding:8px 18px;border-radius:50px;font-size:12px;color:var(--green);font-weight:700}
.live-dot{width:7px;height:7px;background:var(--green);border-radius:50%;animation:blink 2s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0.4}}
.hero{min-height:90vh;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;padding:80px 40px}
.hero h1{font-size:clamp(42px,7vw,82px);font-weight:900;line-height:1.05;letter-spacing:-2.5px;margin-bottom:24px}
.hero h1 em{color:var(--orange);font-style:normal}
.hero-desc{font-size:20px;color:#64748B;max-width:580px;line-height:1.7;margin-bottom:16px}
.btn-primary{background:var(--orange);color:#fff;padding:15px 36px;border-radius:50px;font-size:15px;font-weight:800;text-decoration:none;margin-top:36px;display:inline-block}
footer{border-top:1px solid rgba(255,255,255,0.05);padding:40px;text-align:center;color:#374151;font-size:12px}
</style>
</head>
<body>
<nav>
  <div><div class="logo">Gut<span>Invoice</span></div><div class="logo-sub">Every Invoice has a Voice</div></div>
  <div class="live-pill"><span class="live-dot"></span>LIVE v10</div>
</nav>
<section class="hero">
  <h1>Your Voice.<br/>Your <em>Invoice.</em></h1>
  <p class="hero-desc">Send a WhatsApp voice note in Telugu or English — get a professional GST invoice PDF in 30 seconds.</p>
  <p style="color:#FBBF24;font-size:16px;margin-top:16px;font-style:italic">మాట్లాడండి — Invoice వస్తుంది. అంతే.</p>
  <a href="#" class="btn-primary">Start Free — 3 Invoices</a>
</section>
<footer>Built for Telugu-speaking MSMEs · Hyderabad, India · © 2026 GutInvoice</footer>
</body></html>"""

@app.route("/")
def home():
    return render_template_string(HOME_HTML)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    log.info(f"🚀 GutInvoice v10 starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
