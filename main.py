"""
╔═══════════════════════════════════════════════════════════╗
║           GutInvoice — Every Invoice has a Voice          ║
║     India's First Voice-First GST Invoice in Telugu       ║
║                                                           ║
║  Voice Note → Sarvam AI → Claude AI → Carbone PDF        ║
║              Delivered via WhatsApp in 30 seconds         ║
╚═══════════════════════════════════════════════════════════╝
"""

import os
import json
import requests
import anthropic
from flask import Flask, request, Response, render_template_string
from twilio.rest import Client as TwilioClient
from twilio.request_validator import RequestValidator
from datetime import datetime
import logging

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)

# ─── Environment Variables (set in Railway Variables tab) ─────────────────────
TWILIO_ACCOUNT_SID   = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN    = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER   = os.environ.get("TWILIO_FROM_NUMBER", "whatsapp:+14155238886")
SARVAM_API_KEY       = os.environ.get("SARVAM_API_KEY")
CLAUDE_API_KEY       = os.environ.get("CLAUDE_API_KEY")
CARBONE_API_KEY      = os.environ.get("CARBONE_API_KEY")
CARBONE_TAX_ID       = os.environ.get("CARBONE_TAX_ID")
CARBONE_BOS_ID       = os.environ.get("CARBONE_BOS_ID")
CARBONE_NONGST_ID    = os.environ.get("CARBONE_NONGST_ID")

# ─── Clients ─────────────────────────────────────────────────────────────────
twilio_client   = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
claude_client   = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

# ─── Homepage ─────────────────────────────────────────────────────────────────
HOME_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>GutInvoice — Every Invoice has a Voice</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    
    body {
      font-family: 'Segoe UI', Arial, sans-serif;
      background: #0A0F1E;
      color: #fff;
      min-height: 100vh;
    }

    /* ── NAV ── */
    nav {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 20px 60px;
      border-bottom: 1px solid rgba(255,107,53,0.2);
      background: rgba(10,15,30,0.95);
      position: sticky;
      top: 0;
      z-index: 100;
    }
    .logo {
      font-size: 26px;
      font-weight: 800;
      color: #FF6B35;
      letter-spacing: -0.5px;
    }
    .logo span { color: #fff; }
    .nav-tag {
      font-size: 12px;
      color: #aaa;
      font-style: italic;
      margin-top: 2px;
    }
    .status-badge {
      background: rgba(16,185,129,0.15);
      border: 1px solid #10B981;
      color: #10B981;
      padding: 6px 16px;
      border-radius: 20px;
      font-size: 13px;
      font-weight: 600;
    }
    .status-dot {
      display: inline-block;
      width: 8px; height: 8px;
      background: #10B981;
      border-radius: 50%;
      margin-right: 6px;
      animation: pulse 2s infinite;
    }
    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.4; }
    }

    /* ── HERO ── */
    .hero {
      text-align: center;
      padding: 100px 40px 60px;
      background: radial-gradient(ellipse at top, rgba(255,107,53,0.12) 0%, transparent 65%);
    }
    .hero-badge {
      display: inline-block;
      background: rgba(255,107,53,0.1);
      border: 1px solid rgba(255,107,53,0.4);
      color: #FF6B35;
      padding: 6px 18px;
      border-radius: 20px;
      font-size: 13px;
      font-weight: 600;
      margin-bottom: 28px;
      letter-spacing: 0.5px;
    }
    .hero h1 {
      font-size: clamp(36px, 6vw, 72px);
      font-weight: 900;
      line-height: 1.1;
      margin-bottom: 16px;
      letter-spacing: -1px;
    }
    .hero h1 .accent { color: #FF6B35; }
    .tagline {
      font-size: clamp(18px, 3vw, 26px);
      color: #94A3B8;
      font-style: italic;
      margin-bottom: 20px;
      font-weight: 300;
    }
    .tagline strong { color: #FF6B35; font-style: normal; }
    .hero-sub {
      font-size: 16px;
      color: #64748B;
      max-width: 600px;
      margin: 0 auto 50px;
      line-height: 1.7;
    }

    /* ── FLOW ── */
    .flow {
      display: flex;
      justify-content: center;
      align-items: center;
      gap: 0;
      flex-wrap: wrap;
      margin: 0 auto 80px;
      max-width: 900px;
      padding: 0 20px;
    }
    .flow-step {
      text-align: center;
      padding: 20px 16px;
      min-width: 120px;
    }
    .flow-icon {
      width: 56px; height: 56px;
      border-radius: 16px;
      display: flex;
      align-items: center;
      justify-content: center;
      margin: 0 auto 10px;
      font-size: 24px;
    }
    .flow-step p {
      font-size: 12px;
      color: #94A3B8;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .flow-arrow {
      font-size: 22px;
      color: #FF6B35;
      opacity: 0.6;
      padding: 0 4px;
    }
    .fi-1 { background: rgba(255,107,53,0.15); }
    .fi-2 { background: rgba(99,102,241,0.15); }
    .fi-3 { background: rgba(16,185,129,0.15); }
    .fi-4 { background: rgba(245,158,11,0.15); }
    .fi-5 { background: rgba(236,72,153,0.15); }

    /* ── WHAT WE'RE BUILDING ── */
    .building {
      background: rgba(255,255,255,0.02);
      border-top: 1px solid rgba(255,255,255,0.06);
      border-bottom: 1px solid rgba(255,255,255,0.06);
      padding: 80px 40px;
    }
    .section-title {
      text-align: center;
      font-size: 36px;
      font-weight: 800;
      margin-bottom: 12px;
    }
    .section-sub {
      text-align: center;
      color: #64748B;
      font-size: 16px;
      margin-bottom: 60px;
    }
    .build-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 24px;
      max-width: 1100px;
      margin: 0 auto;
    }
    .build-card {
      background: rgba(255,255,255,0.03);
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 16px;
      padding: 28px;
      transition: border-color 0.2s, transform 0.2s;
    }
    .build-card:hover {
      border-color: rgba(255,107,53,0.4);
      transform: translateY(-2px);
    }
    .build-card-icon {
      font-size: 32px;
      margin-bottom: 16px;
    }
    .build-card h3 {
      font-size: 18px;
      font-weight: 700;
      margin-bottom: 10px;
      color: #fff;
    }
    .build-card p {
      font-size: 14px;
      color: #64748B;
      line-height: 1.7;
    }
    .build-card .highlight {
      color: #FF6B35;
      font-weight: 600;
    }

    /* ── VOICE FEATURE ── */
    .voice-section {
      padding: 80px 40px;
      text-align: center;
    }
    .voice-box {
      background: linear-gradient(135deg, rgba(255,107,53,0.08), rgba(30,58,95,0.3));
      border: 1px solid rgba(255,107,53,0.25);
      border-radius: 24px;
      padding: 50px 40px;
      max-width: 750px;
      margin: 0 auto;
    }
    .voice-example {
      background: rgba(0,0,0,0.3);
      border-radius: 12px;
      padding: 20px 28px;
      margin: 24px 0;
      text-align: left;
      border-left: 3px solid #FF6B35;
    }
    .voice-example .label {
      font-size: 11px;
      color: #FF6B35;
      text-transform: uppercase;
      letter-spacing: 1px;
      margin-bottom: 8px;
      font-weight: 700;
    }
    .voice-example .text {
      font-size: 16px;
      color: #E2E8F0;
      line-height: 1.6;
    }
    .voice-example .text .telugu { color: #FBBF24; }
    .voice-example .text .english { color: #34D399; }
    .arrow-down {
      font-size: 28px;
      color: #FF6B35;
      margin: 8px 0;
    }

    /* ── INVOICE TYPES ── */
    .types-section {
      padding: 80px 40px;
      background: rgba(255,255,255,0.01);
    }
    .types-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 24px;
      max-width: 1000px;
      margin: 0 auto;
    }
    .type-card {
      border-radius: 16px;
      padding: 32px;
      position: relative;
      overflow: hidden;
    }
    .type-card::before {
      content: '';
      position: absolute;
      top: 0; left: 0;
      right: 0; height: 3px;
    }
    .tc-1 { background: rgba(255,107,53,0.08); border: 1px solid rgba(255,107,53,0.2); }
    .tc-1::before { background: #FF6B35; }
    .tc-2 { background: rgba(99,102,241,0.08); border: 1px solid rgba(99,102,241,0.2); }
    .tc-2::before { background: #6366F1; }
    .tc-3 { background: rgba(16,185,129,0.08); border: 1px solid rgba(16,185,129,0.2); }
    .tc-3::before { background: #10B981; }
    .type-card h3 { font-size: 20px; font-weight: 800; margin-bottom: 8px; }
    .type-card .who { font-size: 13px; color: #94A3B8; margin-bottom: 16px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
    .type-card ul { list-style: none; }
    .type-card ul li { font-size: 14px; color: #94A3B8; padding: 5px 0; padding-left: 20px; position: relative; }
    .type-card ul li::before { content: "✓"; position: absolute; left: 0; color: #FF6B35; font-weight: 700; }

    /* ── TECH STACK ── */
    .tech-section {
      padding: 80px 40px;
      text-align: center;
    }
    .tech-grid {
      display: flex;
      justify-content: center;
      flex-wrap: wrap;
      gap: 16px;
      max-width: 800px;
      margin: 0 auto;
    }
    .tech-pill {
      background: rgba(255,255,255,0.05);
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: 50px;
      padding: 10px 22px;
      font-size: 14px;
      font-weight: 600;
      color: #94A3B8;
    }
    .tech-pill span { color: #FF6B35; }

    /* ── FOOTER ── */
    footer {
      border-top: 1px solid rgba(255,255,255,0.06);
      padding: 40px;
      text-align: center;
      color: #374151;
      font-size: 14px;
    }
    footer strong { color: #FF6B35; }
  </style>
</head>
<body>

<!-- NAV -->
<nav>
  <div>
    <div class="logo">Gut<span>Invoice</span></div>
    <div class="nav-tag">Every Invoice has a Voice</div>
  </div>
  <div class="status-badge">
    <span class="status-dot"></span> Webhook Active
  </div>
</nav>

<!-- HERO -->
<section class="hero">
  <div class="hero-badge">🇮🇳 Built for Telugu-speaking MSMEs</div>
  <h1>Every Invoice<br/>has a <span class="accent">Voice.</span></h1>
  <p class="tagline">మీ గొంతే మీ Invoice — <strong>Speak. Get Invoice. Done.</strong></p>
  <p class="hero-sub">
    India's first voice-first GST invoice generator for Telugu-speaking small businesses.
    Just send a WhatsApp voice note — get a professional GST invoice PDF in 30 seconds.
    No app. No typing. No English required.
  </p>

  <!-- FLOW -->
  <div class="flow">
    <div class="flow-step">
      <div class="flow-icon fi-1">🎙️</div>
      <p>Voice Note</p>
    </div>
    <div class="flow-arrow">→</div>
    <div class="flow-step">
      <div class="flow-icon fi-2">🧠</div>
      <p>Sarvam AI</p>
    </div>
    <div class="flow-arrow">→</div>
    <div class="flow-step">
      <div class="flow-icon fi-3">⚡</div>
      <p>Claude AI</p>
    </div>
    <div class="flow-arrow">→</div>
    <div class="flow-step">
      <div class="flow-icon fi-4">📄</div>
      <p>GST PDF</p>
    </div>
    <div class="flow-arrow">→</div>
    <div class="flow-step">
      <div class="flow-icon fi-5">💬</div>
      <p>WhatsApp</p>
    </div>
  </div>
</section>

<!-- WHAT WE'RE BUILDING -->
<section class="building">
  <h2 class="section-title">What We're Building</h2>
  <p class="section-sub">A complete voice-to-invoice automation stack for India's 5.7 crore MSMEs</p>
  <div class="build-grid">
    <div class="build-card">
      <div class="build-card-icon">🎙️</div>
      <h3>Telugu + English Voice Input</h3>
      <p>Sellers can speak in <span class="highlight">pure Telugu, pure English, or a natural mix</span> of both. Sarvam AI handles Hinglish-style Telugu perfectly — exactly how traders speak.</p>
    </div>
    <div class="build-card">
      <div class="build-card-icon">🤖</div>
      <h3>Claude AI Invoice Brain</h3>
      <p>Claude extracts customer name, items, quantities, rates, and GST details from the transcript. <span class="highlight">Even partial information</span> gets intelligently interpreted.</p>
    </div>
    <div class="build-card">
      <div class="build-card-icon">📋</div>
      <h3>3 GST Invoice Types</h3>
      <p>Auto-detects and generates <span class="highlight">Tax Invoice, Bill of Supply, or plain Invoice</span> based on seller's GST registration status. Fully GST compliant.</p>
    </div>
    <div class="build-card">
      <div class="build-card-icon">📲</div>
      <h3>WhatsApp PDF Delivery</h3>
      <p>Professional PDF invoice delivered back to the seller on WhatsApp in <span class="highlight">under 30 seconds</span>. No app download. No login. Just WhatsApp.</p>
    </div>
    <div class="build-card">
      <div class="build-card-icon">🏪</div>
      <h3>Seller Profile Memory</h3>
      <p>Seller's business name, GSTIN, and address are <span class="highlight">remembered automatically</span> after first setup. Never repeat your details again.</p>
    </div>
    <div class="build-card">
      <div class="build-card-icon">💰</div>
      <h3>₹199/month — No Hidden Fees</h3>
      <p>Simple flat pricing. <span class="highlight">3 free invoices</span> to try. Unlimited after that. No per-invoice charges. No setup fees. Cancel anytime.</p>
    </div>
  </div>
</section>

<!-- VOICE EXAMPLE -->
<section class="voice-section">
  <h2 class="section-title">Hear How It Works</h2>
  <p class="section-sub">Sellers speak naturally — Telugu, English, or both mixed together</p>
  <div class="voice-box">
    <div class="voice-example">
      <div class="label">🎙️ Seller speaks (Telugu + English mix)</div>
      <div class="text">
        "<span class="telugu">Customer Suresh</span>, 
        <span class="telugu">Dilsukhnagar</span>, 
        <span class="english">50 iron rods</span>, 
        <span class="telugu">ఒక్కొక్కటి 800 rupees</span>, 
        <span class="english">18% GST</span>, 
        <span class="telugu">15 రోజుల్లో pay చేయాలి</span>"
      </div>
    </div>
    <div class="arrow-down">↓</div>
    <div class="voice-example">
      <div class="label">🤖 Claude AI extracts</div>
      <div class="text">
        Customer: Suresh, Dilsukhnagar &nbsp;|&nbsp; 
        50 × Iron Rods @ ₹800 &nbsp;|&nbsp; 
        CGST 9% + SGST 9% &nbsp;|&nbsp; 
        Total: ₹47,200
      </div>
    </div>
    <div class="arrow-down">↓</div>
    <div class="voice-example">
      <div class="label">📄 PDF delivered on WhatsApp in 30 seconds</div>
      <div class="text">
        Professional TAX INVOICE with GSTIN, HSN codes, 
        tax breakup, and authorised signatory — 
        ready to share with customer.
      </div>
    </div>
  </div>
</section>

<!-- INVOICE TYPES -->
<section class="types-section">
  <h2 class="section-title" style="text-align:center">3 Invoice Types, Auto-Detected</h2>
  <p class="section-sub">GutInvoice knows which invoice to generate based on what the seller says</p>
  <div class="types-grid">
    <div class="type-card tc-1">
      <h3>🧾 Tax Invoice</h3>
      <div class="who">For GST Registered Sellers</div>
      <ul>
        <li>Seller's GSTIN shown</li>
        <li>CGST + SGST or IGST rows</li>
        <li>Buyer can claim Input Tax Credit</li>
        <li>Mandatory for B2B transactions</li>
      </ul>
    </div>
    <div class="type-card tc-2">
      <h3>📝 Bill of Supply</h3>
      <div class="who">For Composition Scheme Dealers</div>
      <ul>
        <li>No tax rows shown</li>
        <li>Mandatory declaration included</li>
        <li>Composition taxable person</li>
        <li>Auto-detected from voice</li>
      </ul>
    </div>
    <div class="type-card tc-3">
      <h3>📃 Invoice</h3>
      <div class="who">For Unregistered Sellers</div>
      <ul>
        <li>No GSTIN required</li>
        <li>No tax calculations</li>
        <li>Simple clean invoice</li>
        <li>Perfect for small traders</li>
      </ul>
    </div>
  </div>
</section>

<!-- TECH STACK -->
<section class="tech-section">
  <h2 class="section-title">Powered By</h2>
  <p class="section-sub" style="margin-bottom:40px">Best-in-class AI stack for Indian language processing</p>
  <div class="tech-grid">
    <div class="tech-pill">🎙️ <span>Sarvam AI</span> — Telugu STT</div>
    <div class="tech-pill">⚡ <span>Claude AI</span> — Invoice Brain</div>
    <div class="tech-pill">📄 <span>Carbone.io</span> — PDF Generation</div>
    <div class="tech-pill">💬 <span>Twilio</span> — WhatsApp API</div>
    <div class="tech-pill">🚀 <span>Railway</span> — Cloud Hosting</div>
    <div class="tech-pill">🐍 <span>Python Flask</span> — Webhook Server</div>
  </div>
</section>

<!-- FOOTER -->
<footer>
  <strong>GutInvoice</strong> — Every Invoice has a Voice &nbsp;|&nbsp;
  Built for Telugu MSMEs &nbsp;|&nbsp;
  Hyderabad, India &nbsp;|&nbsp;
  © 2026
</footer>

</body>
</html>
"""

# ─── Step 1: Download audio from Twilio ───────────────────────────────────────
def download_audio(media_url: str) -> bytes:
    log.info(f"Downloading audio from: {media_url}")
    # Construct full URL if relative
    if media_url.startswith("/"):
        media_url = f"https://api.twilio.com{media_url}"
    response = requests.get(
        media_url,
        auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
        timeout=30
    )
    response.raise_for_status()
    log.info(f"Audio downloaded: {len(response.content)} bytes, type: {response.headers.get('content-type')}")
    return response.content

# ─── Step 2: Transcribe with Sarvam AI ────────────────────────────────────────
def transcribe_audio(audio_bytes: bytes) -> str:
    log.info("Transcribing audio with Sarvam AI...")
    response = requests.post(
        "https://api.sarvam.ai/speech-to-text-translate",
        headers={"API-Subscription-Key": SARVAM_API_KEY},
        files={"file": ("audio.ogg", audio_bytes, "audio/ogg")},
        data={
            "model": "saarika:v2.5",
            "source_language_code": "te-IN",
            "target_language_code": "en-IN"
        },
        timeout=60
    )
    if response.status_code != 200:
        log.error(f"Sarvam error: {response.status_code} - {response.text}")
        raise Exception(f"Sarvam transcription failed: {response.text}")
    
    result = response.json()
    transcript = result.get("transcript", "") or result.get("translated_text", "")
    log.info(f"Transcript: {transcript}")
    return transcript

# ─── Step 3: Extract invoice data with Claude ─────────────────────────────────
def extract_invoice_data(transcript: str, seller_info: dict) -> dict:
    log.info("Extracting invoice data with Claude AI...")
    
    today = datetime.now().strftime("%d/%m/%Y")
    invoice_number = f"GUT-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    prompt = f"""You are a GST invoice assistant for Indian small businesses.

Extract invoice details from this voice transcript and return ONLY a valid JSON object.
The seller may speak in Telugu, English, or a mix of both.

Transcript: {transcript}

Seller Information (pre-saved):
- Seller Name: {seller_info.get('seller_name', 'Unknown Seller')}
- Seller Address: {seller_info.get('seller_address', '')}
- Seller GSTIN: {seller_info.get('seller_gstin', '')}
- Invoice Type Preference: {seller_info.get('invoice_type', 'TAX INVOICE')}

Today's Date: {today}
Invoice Number: {invoice_number}

Rules:
1. invoice_type must be exactly: "TAX INVOICE" or "BILL OF SUPPLY" or "INVOICE"
2. Use "TAX INVOICE" if seller has GSTIN and no special mention
3. Use "BILL OF SUPPLY" if seller mentions composition scheme
4. Use "INVOICE" if seller has no GSTIN
5. Calculate all tax amounts correctly
6. For intra-state (same state): use CGST + SGST (split GST rate equally)
7. For inter-state: use IGST only
8. If GST rate not mentioned, assume 18% for goods
9. amount = qty × rate (before tax)
10. total_amount = taxable_value + all tax amounts
11. declaration for BILL OF SUPPLY: "Composition taxable person, not eligible to collect tax on supplies"
12. declaration for INVOICE: "Seller not registered under GST. GST not applicable on this invoice."

Return ONLY this JSON, no other text:
{{
  "invoice_type": "TAX INVOICE",
  "seller_name": "{seller_info.get('seller_name', '')}",
  "seller_address": "{seller_info.get('seller_address', '')}",
  "seller_gstin": "{seller_info.get('seller_gstin', '')}",
  "invoice_number": "{invoice_number}",
  "invoice_date": "{today}",
  "customer_name": "",
  "customer_address": "",
  "customer_gstin": "",
  "place_of_supply": "Telangana",
  "reverse_charge": "No",
  "items": [
    {{
      "sno": 1,
      "description": "",
      "hsn_sac": "",
      "qty": 0,
      "unit": "Nos",
      "rate": 0,
      "amount": 0
    }}
  ],
  "taxable_value": 0,
  "cgst_rate": 9,
  "cgst_amount": 0,
  "sgst_rate": 9,
  "sgst_amount": 0,
  "igst_rate": 0,
  "igst_amount": 0,
  "total_amount": 0,
  "declaration": "",
  "payment_terms": "Pay within 15 days"
}}"""

    message = claude_client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )
    
    response_text = message.content[0].text.strip()
    log.info(f"Claude response: {response_text[:200]}...")
    
    # Clean JSON if wrapped in backticks
    if "```json" in response_text:
        response_text = response_text.split("```json")[1].split("```")[0].strip()
    elif "```" in response_text:
        response_text = response_text.split("```")[1].split("```")[0].strip()
    
    invoice_data = json.loads(response_text)
    log.info(f"Invoice data extracted: {invoice_data.get('invoice_type')} for {invoice_data.get('customer_name')}")
    return invoice_data

# ─── Step 4: Generate PDF with Carbone ────────────────────────────────────────
def generate_pdf(invoice_data: dict) -> str:
    log.info(f"Generating PDF with Carbone for: {invoice_data.get('invoice_type')}")
    
    # Select correct template based on invoice type
    invoice_type = invoice_data.get("invoice_type", "TAX INVOICE")
    if "BILL" in invoice_type:
        template_id = CARBONE_BOS_ID
    elif "TAX" in invoice_type:
        template_id = CARBONE_TAX_ID
    else:
        template_id = CARBONE_NONGST_ID
    
    log.info(f"Using template ID: {template_id}")
    
    response = requests.post(
        f"https://api.carbone.io/render/{template_id}",
        headers={
            "Authorization": f"Bearer {CARBONE_API_KEY}",
            "Content-Type": "application/json"
        },
        json={"data": invoice_data, "convertTo": "pdf"},
        timeout=60
    )
    
    if response.status_code != 200:
        log.error(f"Carbone error: {response.status_code} - {response.text}")
        raise Exception(f"Carbone PDF generation failed: {response.text}")
    
    result = response.json()
    render_id = result.get("data", {}).get("renderId")
    
    if not render_id:
        raise Exception(f"No renderId in Carbone response: {result}")
    
    pdf_url = f"https://api.carbone.io/render/{render_id}"
    log.info(f"PDF generated: {pdf_url}")
    return pdf_url

# ─── Step 5: Send PDF via Twilio WhatsApp ─────────────────────────────────────
def send_whatsapp_pdf(to_number: str, pdf_url: str, invoice_data: dict):
    log.info(f"Sending PDF to: {to_number}")
    
    customer = invoice_data.get("customer_name", "Customer")
    total = invoice_data.get("total_amount", 0)
    invoice_type = invoice_data.get("invoice_type", "Invoice")
    invoice_no = invoice_data.get("invoice_number", "")
    
    message_body = (
        f"✅ *Your {invoice_type} is Ready!*\n\n"
        f"📋 Invoice No: {invoice_no}\n"
        f"👤 Customer: {customer}\n"
        f"💰 Total: ₹{total:,.0f}\n\n"
        f"Powered by *GutInvoice* 🎙️\n"
        f"_Every Invoice has a Voice_"
    )
    
    message = twilio_client.messages.create(
        from_=TWILIO_FROM_NUMBER,
        to=to_number,
        body=message_body,
        media_url=[pdf_url]
    )
    
    log.info(f"WhatsApp message sent: {message.sid}")
    return message.sid

# ─── Default seller info (update per seller in production) ────────────────────
def get_seller_info(from_number: str) -> dict:
    """
    In production this will look up seller profile from Airtable/database.
    For now returns default info — seller sets this up during onboarding.
    """
    return {
        "seller_name": "My Business",
        "seller_address": "Hyderabad, Telangana",
        "seller_gstin": "",
        "invoice_type": "TAX INVOICE"
    }

# ─── Main Webhook ─────────────────────────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        from_number = request.form.get("From", "")
        num_media   = int(request.form.get("NumMedia", 0))
        body        = request.form.get("Body", "")
        
        log.info(f"Incoming message from {from_number} | Media: {num_media} | Body: {body}")
        
        # ── No voice note ──
        if num_media == 0:
            twilio_client.messages.create(
                from_=TWILIO_FROM_NUMBER,
                to=from_number,
                body=(
                    "🎙️ *GutInvoice — Every Invoice has a Voice*\n\n"
                    "Please send a *voice note* with your invoice details.\n\n"
                    "Example:\n"
                    "_\"Customer Suresh, 50 iron rods, 800 rupees each, 18% GST\"\n\n"
                    "Telugu లో కూడా చెప్పవచ్చు! 🙏_"
                )
            )
            return Response("OK", status=200)
        
        # ── Get media URL ──
        media_url       = request.form.get("MediaUrl0", "")
        media_type      = request.form.get("MediaContentType0", "")
        
        log.info(f"Media URL: {media_url} | Type: {media_type}")
        
        # ── Only process audio ──
        if "audio" not in media_type and "ogg" not in media_type:
            twilio_client.messages.create(
                from_=TWILIO_FROM_NUMBER,
                to=from_number,
                body="Please send a *voice note* 🎙️, not an image or document."
            )
            return Response("OK", status=200)
        
        # ── Send acknowledgement immediately ──
        twilio_client.messages.create(
            from_=TWILIO_FROM_NUMBER,
            to=from_number,
            body="🎙️ Voice note received! Generating your invoice... ⏳\n_(Ready in ~30 seconds)_"
        )
        
        # ── Process the invoice ──
        seller_info = get_seller_info(from_number)
        
        # Step 1: Download audio
        audio_bytes = download_audio(media_url)
        
        # Step 2: Transcribe
        transcript = transcribe_audio(audio_bytes)
        
        if not transcript:
            raise Exception("Empty transcript from Sarvam")
        
        # Step 3: Extract invoice data
        invoice_data = extract_invoice_data(transcript, seller_info)
        
        # Step 4: Generate PDF
        pdf_url = generate_pdf(invoice_data)
        
        # Step 5: Send PDF
        send_whatsapp_pdf(from_number, pdf_url, invoice_data)
        
        log.info("✅ Invoice generated and sent successfully!")
        return Response("OK", status=200)

    except Exception as e:
        log.error(f"❌ Error processing invoice: {str(e)}", exc_info=True)
        try:
            twilio_client.messages.create(
                from_=TWILIO_FROM_NUMBER,
                to=request.form.get("From", ""),
                body=(
                    "❌ Sorry, something went wrong generating your invoice.\n"
                    "Please try again or contact support.\n\n"
                    f"Error: {str(e)[:100]}"
                )
            )
        except Exception as send_err:
            log.error(f"Failed to send error message: {send_err}")
        return Response("Error", status=500)

# ─── Health check ─────────────────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    checks = {
        "twilio":  bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN),
        "sarvam":  bool(SARVAM_API_KEY),
        "claude":  bool(CLAUDE_API_KEY),
        "carbone": bool(CARBONE_API_KEY),
        "templates": {
            "tax_invoice":    bool(CARBONE_TAX_ID),
            "bill_of_supply": bool(CARBONE_BOS_ID),
            "non_gst":        bool(CARBONE_NONGST_ID),
        }
    }
    all_ok = all([checks["twilio"], checks["sarvam"], checks["claude"], checks["carbone"]])
    return {
        "status": "healthy" if all_ok else "missing_config",
        "service": "GutInvoice Webhook",
        "tagline": "Every Invoice has a Voice",
        "checks": checks,
        "timestamp": datetime.now().isoformat()
    }, 200 if all_ok else 500

# ─── Homepage ─────────────────────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def home():
    return render_template_string(HOME_HTML)

# ─── Run ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    log.info(f"🚀 GutInvoice webhook starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
