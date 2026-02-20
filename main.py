"""
╔═══════════════════════════════════════════════════════════╗
║        GutInvoice — Every Invoice has a Voice [v2]        ║
║     India's First Voice-First GST Invoice in Telugu       ║
║                                                           ║
║  Voice Note → Sarvam AI → Claude AI → Carbone PDF        ║
║              Delivered via WhatsApp in 30 seconds         ║
╚═══════════════════════════════════════════════════════════╝

FIX v2: Lazy client initialization — clients created per request
        so missing env vars at startup no longer crash the server.
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

# ─── Lazy helpers — read env vars at request time, not at startup ─────────────
def get_twilio():
    return TwilioClient(
        os.environ.get("TWILIO_ACCOUNT_SID"),
        os.environ.get("TWILIO_AUTH_TOKEN")
    )

def get_claude():
    return anthropic.Anthropic(api_key=os.environ.get("CLAUDE_API_KEY"))

def env(key):
    return os.environ.get(key, "")

# ─── Homepage HTML ─────────────────────────────────────────────────────────────
HOME_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>GutInvoice — Every Invoice has a Voice</title>
  <style>
    *{margin:0;padding:0;box-sizing:border-box}
    body{font-family:'Segoe UI',Arial,sans-serif;background:#0A0F1E;color:#fff;min-height:100vh}
    nav{display:flex;justify-content:space-between;align-items:center;padding:20px 60px;border-bottom:1px solid rgba(255,107,53,0.2);background:rgba(10,15,30,0.95);position:sticky;top:0;z-index:100}
    .logo{font-size:26px;font-weight:800;color:#FF6B35}.logo span{color:#fff}
    .nav-tag{font-size:12px;color:#aaa;font-style:italic;margin-top:2px}
    .badge{background:rgba(16,185,129,0.15);border:1px solid #10B981;color:#10B981;padding:6px 16px;border-radius:20px;font-size:13px;font-weight:600}
    .dot{display:inline-block;width:8px;height:8px;background:#10B981;border-radius:50%;margin-right:6px;animation:pulse 2s infinite}
    @keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}
    .hero{text-align:center;padding:100px 40px 60px;background:radial-gradient(ellipse at top,rgba(255,107,53,0.12) 0%,transparent 65%)}
    .hbadge{display:inline-block;background:rgba(255,107,53,0.1);border:1px solid rgba(255,107,53,0.4);color:#FF6B35;padding:6px 18px;border-radius:20px;font-size:13px;font-weight:600;margin-bottom:28px}
    h1{font-size:clamp(36px,6vw,72px);font-weight:900;line-height:1.1;margin-bottom:16px}
    .accent{color:#FF6B35}
    .tagline{font-size:clamp(18px,3vw,26px);color:#94A3B8;font-style:italic;margin-bottom:20px}
    .tagline strong{color:#FF6B35;font-style:normal}
    .sub{font-size:16px;color:#64748B;max-width:600px;margin:0 auto 50px;line-height:1.7}
    .flow{display:flex;justify-content:center;align-items:center;flex-wrap:wrap;margin:0 auto 80px;max-width:900px;padding:0 20px}
    .fs{text-align:center;padding:20px 16px;min-width:120px}
    .fi{width:56px;height:56px;border-radius:16px;display:flex;align-items:center;justify-content:center;margin:0 auto 10px;font-size:24px}
    .fs p{font-size:12px;color:#94A3B8;font-weight:600;text-transform:uppercase;letter-spacing:0.5px}
    .fa{font-size:22px;color:#FF6B35;opacity:0.6;padding:0 4px}
    .fi1{background:rgba(255,107,53,0.15)}.fi2{background:rgba(99,102,241,0.15)}.fi3{background:rgba(16,185,129,0.15)}.fi4{background:rgba(245,158,11,0.15)}.fi5{background:rgba(236,72,153,0.15)}
    .sec{padding:80px 40px}
    .sec-alt{background:rgba(255,255,255,0.02);border-top:1px solid rgba(255,255,255,0.06);border-bottom:1px solid rgba(255,255,255,0.06)}
    .sec-title{text-align:center;font-size:36px;font-weight:800;margin-bottom:12px}
    .sec-sub{text-align:center;color:#64748B;font-size:16px;margin-bottom:60px}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px;max-width:1100px;margin:0 auto}
    .card{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:28px;transition:border-color 0.2s,transform 0.2s}
    .card:hover{border-color:rgba(255,107,53,0.4);transform:translateY(-2px)}
    .card-icon{font-size:32px;margin-bottom:16px}
    .card h3{font-size:18px;font-weight:700;margin-bottom:10px}
    .card p{font-size:14px;color:#64748B;line-height:1.7}
    .hl{color:#FF6B35;font-weight:600}
    .voice-box{background:linear-gradient(135deg,rgba(255,107,53,0.08),rgba(30,58,95,0.3));border:1px solid rgba(255,107,53,0.25);border-radius:24px;padding:50px 40px;max-width:750px;margin:0 auto;text-align:left}
    .vex{background:rgba(0,0,0,0.3);border-radius:12px;padding:20px 28px;margin:24px 0;border-left:3px solid #FF6B35}
    .vlabel{font-size:11px;color:#FF6B35;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;font-weight:700}
    .vtext{font-size:16px;color:#E2E8F0;line-height:1.6}
    .tel{color:#FBBF24}.eng{color:#34D399}
    .arr{font-size:28px;color:#FF6B35;margin:8px 0;text-align:center}
    .tgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:24px;max-width:1000px;margin:0 auto}
    .tc{border-radius:16px;padding:32px;position:relative;overflow:hidden}
    .tc::before{content:'';position:absolute;top:0;left:0;right:0;height:3px}
    .tc1{background:rgba(255,107,53,0.08);border:1px solid rgba(255,107,53,0.2)}.tc1::before{background:#FF6B35}
    .tc2{background:rgba(99,102,241,0.08);border:1px solid rgba(99,102,241,0.2)}.tc2::before{background:#6366F1}
    .tc3{background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.2)}.tc3::before{background:#10B981}
    .tc h3{font-size:20px;font-weight:800;margin-bottom:8px}
    .who{font-size:13px;color:#94A3B8;margin-bottom:16px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px}
    .tc ul{list-style:none}.tc ul li{font-size:14px;color:#94A3B8;padding:5px 0;padding-left:20px;position:relative}
    .tc ul li::before{content:"✓";position:absolute;left:0;color:#FF6B35;font-weight:700}
    .pills{display:flex;justify-content:center;flex-wrap:wrap;gap:16px;max-width:800px;margin:0 auto}
    .pill{background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:50px;padding:10px 22px;font-size:14px;font-weight:600;color:#94A3B8}
    .pill span{color:#FF6B35}
    footer{border-top:1px solid rgba(255,255,255,0.06);padding:40px;text-align:center;color:#374151;font-size:14px}
    footer strong{color:#FF6B35}
  </style>
</head>
<body>
<nav>
  <div><div class="logo">Gut<span>Invoice</span></div><div class="nav-tag">Every Invoice has a Voice</div></div>
  <div class="badge"><span class="dot"></span>Webhook Active</div>
</nav>
<section class="hero">
  <div class="hbadge">🇮🇳 Built for Telugu-speaking MSMEs</div>
  <h1>Every Invoice<br/>has a <span class="accent">Voice.</span></h1>
  <p class="tagline">మీ గొంతే మీ Invoice — <strong>Speak. Get Invoice. Done.</strong></p>
  <p class="sub">India's first voice-first GST invoice generator for Telugu-speaking small businesses. Just send a WhatsApp voice note — get a professional GST invoice PDF in 30 seconds. No app. No typing. No English required.</p>
  <div class="flow">
    <div class="fs"><div class="fi fi1">🎙️</div><p>Voice Note</p></div><div class="fa">→</div>
    <div class="fs"><div class="fi fi2">🧠</div><p>Sarvam AI</p></div><div class="fa">→</div>
    <div class="fs"><div class="fi fi3">⚡</div><p>Claude AI</p></div><div class="fa">→</div>
    <div class="fs"><div class="fi fi4">📄</div><p>GST PDF</p></div><div class="fa">→</div>
    <div class="fs"><div class="fi fi5">💬</div><p>WhatsApp</p></div>
  </div>
</section>
<section class="sec sec-alt">
  <h2 class="sec-title">What We're Building</h2>
  <p class="sec-sub">A complete voice-to-invoice automation stack for India's 5.7 crore MSMEs</p>
  <div class="grid">
    <div class="card"><div class="card-icon">🎙️</div><h3>Telugu + English Voice Input</h3><p>Sellers speak in <span class="hl">pure Telugu, pure English, or a natural mix</span>. Sarvam AI handles code-switched Telugu perfectly — exactly how traders speak.</p></div>
    <div class="card"><div class="card-icon">🤖</div><h3>Claude AI Invoice Brain</h3><p>Extracts customer name, items, quantities, rates, and GST details. <span class="hl">Even partial information</span> gets intelligently interpreted.</p></div>
    <div class="card"><div class="card-icon">📋</div><h3>3 GST Invoice Types</h3><p>Auto-detects and generates <span class="hl">Tax Invoice, Bill of Supply, or plain Invoice</span> based on seller's registration. Fully GST compliant.</p></div>
    <div class="card"><div class="card-icon">📲</div><h3>WhatsApp PDF Delivery</h3><p>Professional PDF delivered on WhatsApp in <span class="hl">under 30 seconds</span>. No app download. No login. Just WhatsApp.</p></div>
    <div class="card"><div class="card-icon">🏪</div><h3>Seller Profile Memory</h3><p>Business name, GSTIN, and address <span class="hl">remembered automatically</span> after first setup. Never repeat details again.</p></div>
    <div class="card"><div class="card-icon">💰</div><h3>₹199/month — No Hidden Fees</h3><p>Flat pricing. <span class="hl">3 free invoices</span> to try. Unlimited after that. No per-invoice charges.</p></div>
  </div>
</section>
<section class="sec" style="text-align:center">
  <h2 class="sec-title">Hear How It Works</h2>
  <p class="sec-sub">Sellers speak naturally — Telugu, English, or both mixed together</p>
  <div class="voice-box">
    <div class="vex"><div class="vlabel">🎙️ Seller speaks (Telugu + English mix)</div><div class="vtext">"<span class="tel">Customer Suresh</span>, <span class="tel">Dilsukhnagar</span>, <span class="eng">50 iron rods</span>, <span class="tel">ఒక్కొక్కటి 800 rupees</span>, <span class="eng">18% GST</span>, <span class="tel">15 రోజుల్లో pay చేయాలి</span>"</div></div>
    <div class="arr">↓</div>
    <div class="vex"><div class="vlabel">🤖 Claude AI extracts</div><div class="vtext">Customer: Suresh, Dilsukhnagar &nbsp;|&nbsp; 50 × Iron Rods @ ₹800 &nbsp;|&nbsp; CGST 9% + SGST 9% &nbsp;|&nbsp; Total: ₹47,200</div></div>
    <div class="arr">↓</div>
    <div class="vex"><div class="vlabel">📄 PDF on WhatsApp in 30 seconds</div><div class="vtext">Professional TAX INVOICE with GSTIN, HSN codes, tax breakup — ready to share with customer.</div></div>
  </div>
</section>
<section class="sec sec-alt">
  <h2 class="sec-title">3 Invoice Types, Auto-Detected</h2>
  <p class="sec-sub">GutInvoice knows which invoice to generate based on what the seller says</p>
  <div class="tgrid">
    <div class="tc tc1"><h3>🧾 Tax Invoice</h3><div class="who">For GST Registered Sellers</div><ul><li>Seller GSTIN shown</li><li>CGST + SGST or IGST rows</li><li>Buyer can claim ITC</li><li>Mandatory for B2B</li></ul></div>
    <div class="tc tc2"><h3>📝 Bill of Supply</h3><div class="who">For Composition Dealers</div><ul><li>No tax rows shown</li><li>Mandatory declaration</li><li>Composition taxable person</li><li>Auto-detected from voice</li></ul></div>
    <div class="tc tc3"><h3>📃 Invoice</h3><div class="who">For Unregistered Sellers</div><ul><li>No GSTIN required</li><li>No tax calculations</li><li>Simple clean invoice</li><li>Perfect for small traders</li></ul></div>
  </div>
</section>
<section class="sec" style="text-align:center">
  <h2 class="sec-title">Powered By</h2>
  <p class="sec-sub" style="margin-bottom:40px">Best-in-class AI stack for Indian language processing</p>
  <div class="pills">
    <div class="pill">🎙️ <span>Sarvam AI</span> — Telugu STT</div>
    <div class="pill">⚡ <span>Claude Opus</span> — Invoice Brain</div>
    <div class="pill">📄 <span>Carbone.io</span> — PDF Generation</div>
    <div class="pill">💬 <span>Twilio</span> — WhatsApp API</div>
    <div class="pill">🚀 <span>Railway</span> — Cloud Hosting</div>
    <div class="pill">🐍 <span>Python Flask</span> — Webhook</div>
  </div>
</section>
<footer><strong>GutInvoice</strong> — Every Invoice has a Voice &nbsp;|&nbsp; Built for Telugu MSMEs &nbsp;|&nbsp; Hyderabad, India &nbsp;|&nbsp; © 2026</footer>
</body></html>"""

# ─── Step 1: Download audio ───────────────────────────────────────────────────
def download_audio(media_url):
    if media_url.startswith("/"):
        media_url = f"https://api.twilio.com{media_url}"
    r = requests.get(media_url, auth=(env("TWILIO_ACCOUNT_SID"), env("TWILIO_AUTH_TOKEN")), timeout=30)
    r.raise_for_status()
    log.info(f"Audio: {len(r.content)} bytes, type: {r.headers.get('content-type')}")
    return r.content

# ─── Step 2: Transcribe ───────────────────────────────────────────────────────
def transcribe_audio(audio_bytes):
    r = requests.post(
        "https://api.sarvam.ai/speech-to-text-translate",
        headers={"API-Subscription-Key": env("SARVAM_API_KEY")},
        files={"file": ("audio.ogg", audio_bytes, "audio/ogg")},
        data={"model": "saarika:v2.5", "source_language_code": "te-IN", "target_language_code": "en-IN"},
        timeout=60
    )
    if r.status_code != 200:
        raise Exception(f"Sarvam error {r.status_code}: {r.text}")
    result = r.json()
    transcript = result.get("transcript", "") or result.get("translated_text", "")
    log.info(f"Transcript: {transcript}")
    return transcript

# ─── Step 3: Extract invoice with Claude ─────────────────────────────────────
def extract_invoice_data(transcript, seller_info):
    today = datetime.now().strftime("%d/%m/%Y")
    inv_no = f"GUT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    prompt = f"""You are a GST invoice assistant for Indian small businesses.
Extract invoice details from this transcript and return ONLY valid JSON.
Seller may speak Telugu, English, or a mix of both.

Transcript: {transcript}

Seller: {seller_info.get('seller_name','My Business')}, {seller_info.get('seller_address','Hyderabad')}, GSTIN: {seller_info.get('seller_gstin','')}
Date: {today}, Invoice No: {inv_no}

Rules:
- invoice_type: "TAX INVOICE" (has GSTIN) | "BILL OF SUPPLY" (composition) | "INVOICE" (unregistered)
- Intra-state: CGST+SGST. Inter-state: IGST only.
- amount = qty x rate. total = taxable_value + taxes.
- Default GST 18% if not mentioned.

Return ONLY this JSON:
{{"invoice_type":"TAX INVOICE","seller_name":"{seller_info.get('seller_name','')}","seller_address":"{seller_info.get('seller_address','')}","seller_gstin":"{seller_info.get('seller_gstin','')}","invoice_number":"{inv_no}","invoice_date":"{today}","customer_name":"","customer_address":"","customer_gstin":"","place_of_supply":"Telangana","reverse_charge":"No","items":[{{"sno":1,"description":"","hsn_sac":"","qty":0,"unit":"Nos","rate":0,"amount":0}}],"taxable_value":0,"cgst_rate":9,"cgst_amount":0,"sgst_rate":9,"sgst_amount":0,"igst_rate":0,"igst_amount":0,"total_amount":0,"declaration":"","payment_terms":"Pay within 15 days"}}"""

    claude = get_claude()
    msg = claude.messages.create(model="claude-opus-4-6", max_tokens=1500, messages=[{"role":"user","content":prompt}])
    text = msg.content[0].text.strip()
    if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text: text = text.split("```")[1].split("```")[0].strip()
    data = json.loads(text)
    log.info(f"Invoice: {data.get('invoice_type')} for {data.get('customer_name')}")
    return data

# ─── Step 4: Generate PDF ─────────────────────────────────────────────────────
def generate_pdf(invoice_data):
    t = invoice_data.get("invoice_type","TAX INVOICE")
    tid = env("CARBONE_BOS_ID") if "BILL" in t else (env("CARBONE_TAX_ID") if "TAX" in t else env("CARBONE_NONGST_ID"))
    r = requests.post(
        f"https://api.carbone.io/render/{tid}",
        headers={"Authorization": f"Bearer {env('CARBONE_API_KEY')}", "Content-Type":"application/json"},
        json={"data": invoice_data, "convertTo": "pdf"},
        timeout=60
    )
    if r.status_code != 200:
        raise Exception(f"Carbone error {r.status_code}: {r.text}")
    rid = r.json().get("data",{}).get("renderId")
    if not rid: raise Exception(f"No renderId: {r.json()}")
    url = f"https://api.carbone.io/render/{rid}"
    log.info(f"PDF: {url}")
    return url

# ─── Step 5: Send WhatsApp ────────────────────────────────────────────────────
def send_whatsapp(to, pdf_url, invoice_data):
    twilio = get_twilio()
    body = (
        f"✅ *Your {invoice_data.get('invoice_type','Invoice')} is Ready!*\n\n"
        f"📋 {invoice_data.get('invoice_number','')}\n"
        f"👤 {invoice_data.get('customer_name','Customer')}\n"
        f"💰 ₹{invoice_data.get('total_amount',0):,.0f}\n\n"
        f"Powered by *GutInvoice* 🎙️\n_Every Invoice has a Voice_"
    )
    msg = twilio.messages.create(from_=env("TWILIO_FROM_NUMBER"), to=to, body=body, media_url=[pdf_url])
    log.info(f"Sent: {msg.sid}")

# ─── Seller lookup ────────────────────────────────────────────────────────────
def get_seller_info(from_number):
    return {"seller_name":"My Business","seller_address":"Hyderabad, Telangana","seller_gstin":"","invoice_type":"TAX INVOICE"}

# ─── Webhook ──────────────────────────────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    twilio = get_twilio()
    from_num   = request.form.get("From","")
    num_media  = int(request.form.get("NumMedia",0))
    media_type = request.form.get("MediaContentType0","")
    media_url  = request.form.get("MediaUrl0","")

    log.info(f"From: {from_num} | Media: {num_media} | Type: {media_type}")

    try:
        if num_media == 0:
            twilio.messages.create(from_=env("TWILIO_FROM_NUMBER"), to=from_num,
                body="🎙️ *GutInvoice — Every Invoice has a Voice*\n\nPlease send a *voice note* with your invoice details.\n\nExample:\n_\"Customer Suresh, 50 iron rods, 800 rupees each, 18% GST\"\n\nTelugu లో కూడా చెప్పవచ్చు! 🙏_")
            return Response("OK", status=200)

        if "audio" not in media_type and "ogg" not in media_type:
            twilio.messages.create(from_=env("TWILIO_FROM_NUMBER"), to=from_num, body="Please send a *voice note* 🎙️")
            return Response("OK", status=200)

        twilio.messages.create(from_=env("TWILIO_FROM_NUMBER"), to=from_num,
            body="🎙️ Voice note received! Generating your invoice... ⏳\n_(Ready in ~30 seconds)_")

        seller      = get_seller_info(from_num)
        audio       = download_audio(media_url)
        transcript  = transcribe_audio(audio)
        if not transcript: raise Exception("Empty transcript")
        invoice     = extract_invoice_data(transcript, seller)
        pdf_url     = generate_pdf(invoice)
        send_whatsapp(from_num, pdf_url, invoice)
        log.info("✅ Done!")
        return Response("OK", status=200)

    except Exception as e:
        log.error(f"❌ {e}", exc_info=True)
        try:
            twilio.messages.create(from_=env("TWILIO_FROM_NUMBER"), to=from_num,
                body=f"❌ Error generating invoice. Please try again.\n\n{str(e)[:100]}")
        except: pass
        return Response("Error", status=500)

# ─── Health ───────────────────────────────────────────────────────────────────
@app.route("/health")
def health():
    c = {k: bool(env(k)) for k in ["TWILIO_ACCOUNT_SID","SARVAM_API_KEY","CLAUDE_API_KEY","CARBONE_API_KEY","CARBONE_TAX_ID","CARBONE_BOS_ID","CARBONE_NONGST_ID"]}
    ok = all(c.values())
    return {"status":"healthy" if ok else "missing_config","checks":c,"timestamp":datetime.now().isoformat()}, 200 if ok else 500

# ─── Home ─────────────────────────────────────────────────────────────────────
@app.route("/")
def home():
    return render_template_string(HOME_HTML)

# ─── Run ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    log.info(f"🚀 GutInvoice v2 starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
