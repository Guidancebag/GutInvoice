"""
GutInvoice — Every Invoice has a Voice
India's First Voice-First GST Invoice Generator for Telugu MSMEs
v3 — Fixed saaras model name + redesigned website
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

def get_twilio():
    return TwilioClient(os.environ.get("TWILIO_ACCOUNT_SID"), os.environ.get("TWILIO_AUTH_TOKEN"))

def get_claude():
    return anthropic.Anthropic(api_key=os.environ.get("CLAUDE_API_KEY"))

def env(key):
    return os.environ.get(key, "")

HOME_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>GutInvoice — Every Invoice has a Voice</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--orange:#FF6B35;--navy:#0A0F1E;--green:#10B981}
body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--navy);color:#fff;min-height:100vh;overflow-x:hidden}

/* NAV */
nav{display:flex;justify-content:space-between;align-items:center;padding:18px 60px;border-bottom:1px solid rgba(255,107,53,0.15);background:rgba(10,15,30,0.97);position:sticky;top:0;z-index:100;backdrop-filter:blur(10px)}
.logo{font-size:24px;font-weight:900;color:var(--orange);letter-spacing:-0.5px}
.logo span{color:#fff}
.logo-sub{font-size:11px;color:#64748B;margin-top:2px;letter-spacing:0.5px;text-transform:uppercase}
.live{display:flex;align-items:center;gap:8px;background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.3);padding:7px 16px;border-radius:50px;font-size:12px;color:var(--green);font-weight:700;letter-spacing:0.5px}
.live-dot{width:7px;height:7px;background:var(--green);border-radius:50%;animation:blink 2s infinite}
@keyframes blink{0%,100%{opacity:1;box-shadow:0 0 0 0 rgba(16,185,129,0.4)}50%{opacity:0.5;box-shadow:0 0 0 4px rgba(16,185,129,0)}}

/* HERO */
.hero{min-height:92vh;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;padding:80px 40px;position:relative;overflow:hidden}
.hero::before{content:'';position:absolute;width:800px;height:800px;background:radial-gradient(circle,rgba(255,107,53,0.08) 0%,transparent 70%);top:-200px;left:50%;transform:translateX(-50%);pointer-events:none}
.hero::after{content:'';position:absolute;width:600px;height:600px;background:radial-gradient(circle,rgba(30,58,95,0.3) 0%,transparent 70%);bottom:-200px;right:-100px;pointer-events:none}
.chip{display:inline-flex;align-items:center;gap:8px;background:rgba(255,107,53,0.08);border:1px solid rgba(255,107,53,0.3);color:var(--orange);padding:8px 20px;border-radius:50px;font-size:13px;font-weight:700;margin-bottom:32px;letter-spacing:0.3px;position:relative;z-index:1}
.hero h1{font-size:clamp(40px,7vw,80px);font-weight:900;line-height:1.05;letter-spacing:-2px;margin-bottom:20px;position:relative;z-index:1}
.hero h1 em{color:var(--orange);font-style:normal;position:relative}
.hero h1 em::after{content:'';position:absolute;bottom:-4px;left:0;right:0;height:3px;background:var(--orange);border-radius:2px;opacity:0.5}
.tagline{font-size:clamp(16px,2.5vw,22px);color:#64748B;margin-bottom:12px;position:relative;z-index:1}
.tagline-te{font-size:clamp(14px,2vw,18px);color:#475569;font-style:italic;margin-bottom:48px;position:relative;z-index:1}
.tagline-te span{color:#FBBF24}

/* FLOW BAR */
.flow-bar{display:flex;align-items:center;justify-content:center;gap:0;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:20px;padding:24px 40px;margin-bottom:60px;flex-wrap:wrap;position:relative;z-index:1;max-width:900px}
.fstep{display:flex;flex-direction:column;align-items:center;gap:10px;padding:0 20px}
.ficon{width:52px;height:52px;border-radius:14px;display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0}
.fi1{background:rgba(255,107,53,0.12);border:1px solid rgba(255,107,53,0.2)}
.fi2{background:rgba(139,92,246,0.12);border:1px solid rgba(139,92,246,0.2)}
.fi3{background:rgba(16,185,129,0.12);border:1px solid rgba(16,185,129,0.2)}
.fi4{background:rgba(245,158,11,0.12);border:1px solid rgba(245,158,11,0.2)}
.fi5{background:rgba(236,72,153,0.12);border:1px solid rgba(236,72,153,0.2)}
.flabel{font-size:11px;color:#64748B;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;white-space:nowrap}
.farrow{font-size:18px;color:rgba(255,107,53,0.4);padding:0 8px;margin-top:-20px}

/* CTA */
.cta-group{display:flex;gap:16px;flex-wrap:wrap;justify-content:center;position:relative;z-index:1}
.cta-primary{background:var(--orange);color:#fff;padding:16px 36px;border-radius:50px;font-size:15px;font-weight:800;text-decoration:none;letter-spacing:0.3px;transition:all 0.2s;box-shadow:0 0 30px rgba(255,107,53,0.3)}
.cta-primary:hover{background:#e85d25;transform:translateY(-2px);box-shadow:0 0 40px rgba(255,107,53,0.5)}
.cta-secondary{background:transparent;color:#94A3B8;padding:16px 36px;border-radius:50px;font-size:15px;font-weight:600;text-decoration:none;border:1px solid rgba(255,255,255,0.1);transition:all 0.2s}
.cta-secondary:hover{border-color:rgba(255,107,53,0.4);color:var(--orange)}

/* STATS */
.stats{display:flex;justify-content:center;gap:60px;padding:60px 40px;border-top:1px solid rgba(255,255,255,0.05);border-bottom:1px solid rgba(255,255,255,0.05);flex-wrap:wrap}
.stat{text-align:center}
.stat-num{font-size:42px;font-weight:900;color:var(--orange);letter-spacing:-1px;line-height:1}
.stat-label{font-size:13px;color:#64748B;margin-top:6px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px}

/* HOW IT WORKS */
.section{padding:100px 40px}
.section-alt{background:rgba(255,255,255,0.015)}
.section-label{display:inline-block;background:rgba(255,107,53,0.08);border:1px solid rgba(255,107,53,0.2);color:var(--orange);padding:5px 14px;border-radius:50px;font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:1px;margin-bottom:20px}
.section-title{font-size:clamp(28px,4vw,48px);font-weight:900;letter-spacing:-1px;margin-bottom:16px}
.section-sub{color:#64748B;font-size:17px;line-height:1.7;max-width:600px}
.center{text-align:center;display:flex;flex-direction:column;align-items:center}

/* STEPS */
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:2px;max-width:1200px;margin:60px auto 0;background:rgba(255,255,255,0.04);border-radius:24px;overflow:hidden;border:1px solid rgba(255,255,255,0.06)}
.step{padding:40px;background:var(--navy);position:relative;transition:background 0.2s}
.step:hover{background:rgba(255,107,53,0.03)}
.step-num{font-size:11px;font-weight:800;color:var(--orange);text-transform:uppercase;letter-spacing:1px;margin-bottom:20px;opacity:0.7}
.step-icon{font-size:36px;margin-bottom:16px}
.step h3{font-size:18px;font-weight:800;margin-bottom:10px}
.step p{font-size:14px;color:#64748B;line-height:1.7}
.step-accent{color:var(--orange);font-weight:600}

/* VOICE DEMO */
.demo-container{max-width:800px;margin:60px auto 0}
.demo-card{background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:20px;overflow:hidden}
.demo-header{background:rgba(255,107,53,0.06);border-bottom:1px solid rgba(255,107,53,0.1);padding:16px 24px;display:flex;align-items:center;gap:12px}
.demo-dot{width:10px;height:10px;border-radius:50%}
.demo-dot-1{background:#FF5F57}
.demo-dot-2{background:#FEBC2E}
.demo-dot-3{background:#28C840}
.demo-title{font-size:13px;color:#64748B;margin-left:8px;font-weight:600}
.demo-body{padding:32px}
.demo-row{display:flex;gap:16px;margin-bottom:20px;align-items:flex-start}
.demo-row:last-child{margin-bottom:0}
.demo-tag{flex-shrink:0;font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:0.8px;padding:4px 10px;border-radius:6px;margin-top:2px}
.tag-voice{background:rgba(255,107,53,0.15);color:var(--orange);border:1px solid rgba(255,107,53,0.3)}
.tag-ai{background:rgba(16,185,129,0.15);color:var(--green);border:1px solid rgba(16,185,129,0.3)}
.tag-pdf{background:rgba(99,102,241,0.15);color:#818CF8;border:1px solid rgba(99,102,241,0.3)}
.demo-text{font-size:15px;line-height:1.7;color:#CBD5E1}
.demo-text .te{color:#FBBF24;font-weight:500}
.demo-text .en{color:#34D399;font-weight:500}
.demo-arrow{text-align:center;color:rgba(255,107,53,0.4);font-size:20px;margin:4px 0}

/* INVOICE TYPES */
.types-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px;max-width:1000px;margin:60px auto 0}
.type-card{border-radius:20px;padding:36px;border:1px solid;position:relative;overflow:hidden;transition:transform 0.2s}
.type-card:hover{transform:translateY(-4px)}
.type-card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px}
.tc1{background:rgba(255,107,53,0.04);border-color:rgba(255,107,53,0.15)}.tc1::before{background:linear-gradient(90deg,var(--orange),#FF8C61)}
.tc2{background:rgba(99,102,241,0.04);border-color:rgba(99,102,241,0.15)}.tc2::before{background:linear-gradient(90deg,#6366F1,#818CF8)}
.tc3{background:rgba(16,185,129,0.04);border-color:rgba(16,185,129,0.15)}.tc3::before{background:linear-gradient(90deg,var(--green),#34D399)}
.type-badge{display:inline-block;font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:1px;padding:4px 12px;border-radius:50px;margin-bottom:16px}
.tb1{background:rgba(255,107,53,0.12);color:var(--orange)}.tb2{background:rgba(99,102,241,0.12);color:#818CF8}.tb3{background:rgba(16,185,129,0.12);color:var(--green)}
.type-card h3{font-size:22px;font-weight:900;margin-bottom:6px}
.type-card .who{font-size:13px;color:#64748B;margin-bottom:20px}
.type-card ul{list-style:none}
.type-card li{font-size:14px;color:#94A3B8;padding:6px 0;padding-left:18px;position:relative;border-bottom:1px solid rgba(255,255,255,0.04)}
.type-card li:last-child{border-bottom:none}
.type-card li::before{content:'✓';position:absolute;left:0;font-weight:900;font-size:12px}
.tc1 li::before{color:var(--orange)}.tc2 li::before{color:#818CF8}.tc3 li::before{color:var(--green)}

/* PRICING */
.price-card{max-width:480px;margin:60px auto 0;background:rgba(255,255,255,0.02);border:1px solid rgba(255,107,53,0.2);border-radius:24px;padding:48px;text-align:center;position:relative;overflow:hidden}
.price-card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,var(--orange),#FF8C61)}
.price-num{font-size:72px;font-weight:900;color:var(--orange);letter-spacing:-3px;line-height:1}
.price-period{font-size:18px;color:#64748B;font-weight:600}
.price-desc{color:#64748B;margin:16px 0 32px;font-size:15px;line-height:1.6}
.price-features{list-style:none;text-align:left;margin-bottom:36px}
.price-features li{padding:10px 0;font-size:15px;color:#94A3B8;border-bottom:1px solid rgba(255,255,255,0.05);display:flex;align-items:center;gap:10px}
.price-features li:last-child{border-bottom:none}
.check{color:var(--green);font-weight:900}

/* TECH */
.tech-pills{display:flex;justify-content:center;flex-wrap:wrap;gap:12px;max-width:800px;margin:40px auto 0}
.tech-pill{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:50px;padding:10px 24px;font-size:14px;font-weight:600;color:#94A3B8;transition:all 0.2s}
.tech-pill:hover{border-color:rgba(255,107,53,0.3);color:#fff}
.tech-pill span{color:var(--orange)}

/* FOOTER */
footer{border-top:1px solid rgba(255,255,255,0.05);padding:48px 40px;display:flex;justify-content:space-between;align-items:center;flex-wrap:gap;gap:20px}
.footer-logo{font-size:20px;font-weight:900;color:var(--orange)}
.footer-logo span{color:#fff}
.footer-tagline{font-size:13px;color:#374151;margin-top:4px}
.footer-right{font-size:13px;color:#374151;text-align:right}

@media(max-width:768px){
  nav{padding:16px 24px}
  .hero{padding:60px 24px}
  .flow-bar{padding:20px;gap:4px}
  .fstep{padding:0 8px}
  .farrow{display:none}
  .stats{gap:30px}
  footer{flex-direction:column;text-align:center}
  .footer-right{text-align:center}
}
</style>
</head>
<body>

<!-- NAV -->
<nav>
  <div>
    <div class="logo">Gut<span>Invoice</span></div>
    <div class="logo-sub">Every Invoice has a Voice</div>
  </div>
  <div class="live"><span class="live-dot"></span>LIVE</div>
</nav>

<!-- HERO -->
<section class="hero">
  <div class="chip">🇮🇳 Built for Telugu-speaking MSMEs</div>
  <h1>Every Invoice<br/>has a <em>Voice.</em></h1>
  <p class="tagline">India's first voice-first GST invoice generator</p>
  <p class="tagline-te">మీ గొంతే మీ Invoice — <span>మాట్లాడండి. Invoice పొందండి.</span></p>

  <div class="flow-bar">
    <div class="fstep"><div class="ficon fi1">🎙️</div><div class="flabel">Voice Note</div></div>
    <div class="farrow">→</div>
    <div class="fstep"><div class="ficon fi2">🧠</div><div class="flabel">Sarvam AI</div></div>
    <div class="farrow">→</div>
    <div class="fstep"><div class="ficon fi3">⚡</div><div class="flabel">Claude AI</div></div>
    <div class="farrow">→</div>
    <div class="fstep"><div class="ficon fi4">📄</div><div class="flabel">GST PDF</div></div>
    <div class="farrow">→</div>
    <div class="fstep"><div class="ficon fi5">💬</div><div class="flabel">WhatsApp</div></div>
  </div>

  <div class="cta-group">
    <a href="#how" class="cta-primary">See How It Works</a>
    <a href="#types" class="cta-secondary">Invoice Types →</a>
  </div>
</section>

<!-- STATS -->
<div class="stats">
  <div class="stat"><div class="stat-num">30s</div><div class="stat-label">Invoice Delivery</div></div>
  <div class="stat"><div class="stat-num">3</div><div class="stat-label">GST Invoice Types</div></div>
  <div class="stat"><div class="stat-num">5.7Cr</div><div class="stat-label">Target MSMEs</div></div>
  <div class="stat"><div class="stat-num">₹199</div><div class="stat-label">Per Month</div></div>
</div>

<!-- HOW IT WORKS -->
<section class="section" id="how">
  <div class="center">
    <div class="section-label">How It Works</div>
    <h2 class="section-title">Voice Note to GST Invoice<br/>in 4 Simple Steps</h2>
    <p class="section-sub">No app. No typing. No English required. Just speak on WhatsApp and get your professional invoice.</p>
  </div>

  <div class="steps">
    <div class="step">
      <div class="step-num">Step 01</div>
      <div class="step-icon">🎙️</div>
      <h3>Send a Voice Note</h3>
      <p>Open WhatsApp and send a voice note to your GutInvoice number. Speak in <span class="step-accent">Telugu, English, or any mix</span> — exactly how you normally talk.</p>
    </div>
    <div class="step">
      <div class="step-num">Step 02</div>
      <div class="step-icon">🧠</div>
      <h3>Sarvam AI Transcribes</h3>
      <p>Sarvam's Telugu-native AI converts your voice to text. It handles <span class="step-accent">code-switching between Telugu and English</span> perfectly — just like how traders actually speak.</p>
    </div>
    <div class="step">
      <div class="step-num">Step 03</div>
      <div class="step-icon">⚡</div>
      <h3>Claude AI Extracts Invoice</h3>
      <p>Claude Opus intelligently extracts customer name, items, quantities, rates, and GST details. <span class="step-accent">Even partial or casual speech</span> is understood correctly.</p>
    </div>
    <div class="step">
      <div class="step-num">Step 04</div>
      <div class="step-icon">📲</div>
      <h3>PDF on WhatsApp</h3>
      <p>A professional GST-compliant PDF invoice arrives on your WhatsApp in <span class="step-accent">under 30 seconds</span>. Share it directly with your customer.</p>
    </div>
  </div>
</section>

<!-- VOICE DEMO -->
<section class="section section-alt" id="demo">
  <div class="center">
    <div class="section-label">Live Example</div>
    <h2 class="section-title">Hear It in Action</h2>
    <p class="section-sub">A seller speaks in mixed Telugu-English — exactly how real traders communicate.</p>
  </div>

  <div class="demo-container">
    <div class="demo-card">
      <div class="demo-header">
        <div class="demo-dot demo-dot-1"></div>
        <div class="demo-dot demo-dot-2"></div>
        <div class="demo-dot demo-dot-3"></div>
        <div class="demo-title">GutInvoice Live Processing</div>
      </div>
      <div class="demo-body">
        <div class="demo-row">
          <div class="demo-tag tag-voice">🎙️ Voice</div>
          <div class="demo-text">"<span class="te">Customer Suresh</span>, <span class="te">Dilsukhnagar</span>, <span class="en">50 iron rods</span>, <span class="te">ఒక్కొక్కటి</span> <span class="en">800 rupees</span>, <span class="en">18% GST</span>, <span class="te">15 రోజుల్లో pay చేయాలి</span>"</div>
        </div>
        <div class="demo-arrow">↓</div>
        <div class="demo-row">
          <div class="demo-tag tag-ai">⚡ Claude</div>
          <div class="demo-text">Customer: <strong>Suresh, Dilsukhnagar</strong> &nbsp;·&nbsp; 50 × Iron Rods @ ₹800 &nbsp;·&nbsp; CGST 9% + SGST 9% &nbsp;·&nbsp; <strong>Total: ₹47,200</strong></div>
        </div>
        <div class="demo-arrow">↓</div>
        <div class="demo-row">
          <div class="demo-tag tag-pdf">📄 PDF</div>
          <div class="demo-text">Professional <strong>TAX INVOICE</strong> with GSTIN, HSN codes, full tax breakup — delivered to WhatsApp in <strong>28 seconds</strong> ✅</div>
        </div>
      </div>
    </div>
  </div>
</section>

<!-- INVOICE TYPES -->
<section class="section" id="types">
  <div class="center">
    <div class="section-label">Invoice Types</div>
    <h2 class="section-title">3 Invoice Types,<br/>Auto-Detected</h2>
    <p class="section-sub">GutInvoice automatically picks the right invoice type based on what you say — no manual selection needed.</p>
  </div>

  <div class="types-grid">
    <div class="type-card tc1">
      <div class="type-badge tb1">GST Registered</div>
      <h3>🧾 Tax Invoice</h3>
      <div class="who">For registered sellers with GSTIN</div>
      <ul>
        <li>Seller GSTIN displayed</li>
        <li>CGST + SGST (intra-state)</li>
        <li>IGST (inter-state)</li>
        <li>Buyer can claim Input Tax Credit</li>
        <li>Mandatory for B2B above ₹50,000</li>
      </ul>
    </div>
    <div class="type-card tc2">
      <div class="type-badge tb2">Composition Scheme</div>
      <h3>📝 Bill of Supply</h3>
      <div class="who">For composition scheme dealers</div>
      <ul>
        <li>No tax rows displayed</li>
        <li>Mandatory composition declaration</li>
        <li>Auto-detected from voice</li>
        <li>Compliant with GST rules</li>
        <li>Simple and clean format</li>
      </ul>
    </div>
    <div class="type-card tc3">
      <div class="type-badge tb3">Unregistered</div>
      <h3>📃 Invoice</h3>
      <div class="who">For sellers without GST registration</div>
      <ul>
        <li>No GSTIN required</li>
        <li>No tax calculations</li>
        <li>Clean professional format</li>
        <li>Unregistered declaration included</li>
        <li>Perfect for small traders</li>
      </ul>
    </div>
  </div>
</section>

<!-- PRICING -->
<section class="section section-alt" id="pricing">
  <div class="center">
    <div class="section-label">Pricing</div>
    <h2 class="section-title">Simple, Honest Pricing</h2>
    <p class="section-sub">No per-invoice fees. No hidden charges. Just one flat monthly price.</p>
  </div>

  <div class="price-card">
    <div class="price-num">₹199</div>
    <div class="price-period">/month</div>
    <p class="price-desc">Everything you need to run your invoicing on WhatsApp. Cancel anytime.</p>
    <ul class="price-features">
      <li><span class="check">✓</span> Unlimited GST invoices per month</li>
      <li><span class="check">✓</span> All 3 invoice types included</li>
      <li><span class="check">✓</span> Telugu + English voice input</li>
      <li><span class="check">✓</span> Professional PDF on WhatsApp</li>
      <li><span class="check">✓</span> Seller profile memory</li>
      <li><span class="check">✓</span> 3 free invoices to start</li>
    </ul>
    <a href="#" class="cta-primary" style="display:block;text-align:center;text-decoration:none">Start Free — 3 Invoices on Us</a>
  </div>
</section>

<!-- TECH STACK -->
<section class="section">
  <div class="center">
    <div class="section-label">Technology</div>
    <h2 class="section-title">Powered by Best-in-Class AI</h2>
    <p class="section-sub">Built with the most capable AI stack for Indian language processing and GST compliance.</p>
  </div>
  <div class="tech-pills">
    <div class="tech-pill">🎙️ <span>Sarvam AI</span> — Telugu Speech-to-Text</div>
    <div class="tech-pill">⚡ <span>Claude Opus</span> — Invoice Intelligence</div>
    <div class="tech-pill">📄 <span>Carbone.io</span> — PDF Generation</div>
    <div class="tech-pill">💬 <span>Twilio</span> — WhatsApp API</div>
    <div class="tech-pill">🚀 <span>Railway</span> — Cloud Infrastructure</div>
    <div class="tech-pill">🐍 <span>Python Flask</span> — Webhook Engine</div>
  </div>
</section>

<!-- FOOTER -->
<footer>
  <div>
    <div class="footer-logo">Gut<span>Invoice</span></div>
    <div class="footer-tagline">Every Invoice has a Voice — మీ గొంతే మీ Invoice</div>
  </div>
  <div class="footer-right">
    Built for Telugu MSMEs &nbsp;·&nbsp; Hyderabad, India<br/>
    © 2026 GutInvoice. All rights reserved.
  </div>
</footer>

</body>
</html>"""


# ─── Step 1: Download audio ───────────────────────────────────────────────────
def download_audio(media_url):
    if media_url.startswith("/"):
        media_url = f"https://api.twilio.com{media_url}"
    r = requests.get(media_url, auth=(env("TWILIO_ACCOUNT_SID"), env("TWILIO_AUTH_TOKEN")), timeout=30)
    r.raise_for_status()
    log.info(f"Audio: {len(r.content)} bytes, type: {r.headers.get('content-type')}")
    return r.content


# ─── Step 2: Transcribe ── FIXED: saaras not saarika ─────────────────────────
def transcribe_audio(audio_bytes):
    r = requests.post(
        "https://api.sarvam.ai/speech-to-text-translate",
        headers={"API-Subscription-Key": env("SARVAM_API_KEY")},
        files={"file": ("audio.ogg", audio_bytes, "audio/ogg")},
        data={
            "model": "saaras:v2.5",          # ✅ FIXED: was saarika:v2.5
            "source_language_code": "te-IN",
            "target_language_code": "en-IN"
        },
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
- Intra-state: use CGST+SGST. Inter-state: use IGST only.
- amount = qty x rate. total_amount = taxable_value + all taxes.
- Default GST 18% if not mentioned. Split equally for CGST/SGST.
- For BILL OF SUPPLY declaration: "Composition taxable person, not eligible to collect tax on supplies"
- For INVOICE declaration: "Seller not registered under GST"

Return ONLY this JSON, no other text:
{{"invoice_type":"TAX INVOICE","seller_name":"{seller_info.get('seller_name','')}","seller_address":"{seller_info.get('seller_address','')}","seller_gstin":"{seller_info.get('seller_gstin','')}","invoice_number":"{inv_no}","invoice_date":"{today}","customer_name":"","customer_address":"","customer_gstin":"","place_of_supply":"Telangana","reverse_charge":"No","items":[{{"sno":1,"description":"","hsn_sac":"","qty":0,"unit":"Nos","rate":0,"amount":0}}],"taxable_value":0,"cgst_rate":9,"cgst_amount":0,"sgst_rate":9,"sgst_amount":0,"igst_rate":0,"igst_amount":0,"total_amount":0,"declaration":"","payment_terms":"Pay within 15 days"}}"""

    claude = get_claude()
    msg = claude.messages.create(model="claude-opus-4-6", max_tokens=1500, messages=[{"role": "user", "content": prompt}])
    text = msg.content[0].text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    data = json.loads(text)
    log.info(f"Invoice: {data.get('invoice_type')} for {data.get('customer_name')}")
    return data


# ─── Step 4: Generate PDF ─────────────────────────────────────────────────────
def generate_pdf(invoice_data):
    t = invoice_data.get("invoice_type", "TAX INVOICE")
    tid = env("CARBONE_BOS_ID") if "BILL" in t else (env("CARBONE_TAX_ID") if "TAX" in t else env("CARBONE_NONGST_ID"))
    r = requests.post(
        f"https://api.carbone.io/render/{tid}?download=true",
        headers={
            "Authorization": f"Bearer {env('CARBONE_API_KEY')}",
            "Content-Type": "application/json",
            "carbone-version": "5"
        },
        json={"data": invoice_data, "convertTo": "pdf"},
        timeout=60
    )
```    )
    if r.status_code != 200:
        raise Exception(f"Carbone error {r.status_code}: {r.text}")
    rid = r.json().get("data", {}).get("renderId")
    if not rid:
        raise Exception(f"No renderId: {r.json()}")
    url = f"https://api.carbone.io/render/{rid}"
    log.info(f"PDF ready: {url}")
    return url


# ─── Step 5: Send WhatsApp ────────────────────────────────────────────────────
def send_whatsapp(to, pdf_url, invoice_data):
    twilio = get_twilio()
    body = (
        f"✅ *Your {invoice_data.get('invoice_type', 'Invoice')} is Ready!*\n\n"
        f"📋 {invoice_data.get('invoice_number', '')}\n"
        f"👤 {invoice_data.get('customer_name', 'Customer')}\n"
        f"💰 ₹{invoice_data.get('total_amount', 0):,.0f}\n\n"
        f"Powered by *GutInvoice* 🎙️\n"
        f"_Every Invoice has a Voice_"
    )
    msg = twilio.messages.create(from_=env("TWILIO_FROM_NUMBER"), to=to, body=body, media_url=[pdf_url])
    log.info(f"Sent: {msg.sid}")


def get_seller_info(from_number):
    return {"seller_name": "My Business", "seller_address": "Hyderabad, Telangana", "seller_gstin": "", "invoice_type": "TAX INVOICE"}


# ─── Webhook ──────────────────────────────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    twilio = get_twilio()
    from_num = request.form.get("From", "")
    num_media = int(request.form.get("NumMedia", 0))
    media_type = request.form.get("MediaContentType0", "")
    media_url = request.form.get("MediaUrl0", "")

    log.info(f"From: {from_num} | Media: {num_media} | Type: {media_type}")

    try:
        if num_media == 0:
            twilio.messages.create(
                from_=env("TWILIO_FROM_NUMBER"), to=from_num,
                body="🎙️ *GutInvoice — Every Invoice has a Voice*\n\nSend a *voice note* with your invoice details.\n\nExample:\n_\"Customer Suresh, 50 iron rods, 800 rupees each, 18% GST\"\n\nTelugu లో కూడా చెప్పవచ్చు! 🙏_"
            )
            return Response("OK", status=200)

        if "audio" not in media_type and "ogg" not in media_type:
            twilio.messages.create(from_=env("TWILIO_FROM_NUMBER"), to=from_num, body="Please send a *voice note* 🎙️")
            return Response("OK", status=200)

        twilio.messages.create(
            from_=env("TWILIO_FROM_NUMBER"), to=from_num,
            body="🎙️ Voice note received! Generating your invoice... ⏳\n_(Ready in ~30 seconds)_"
        )

        seller = get_seller_info(from_num)
        audio = download_audio(media_url)
        transcript = transcribe_audio(audio)
        if not transcript:
            raise Exception("Empty transcript from Sarvam")
        invoice = extract_invoice_data(transcript, seller)
        pdf_url = generate_pdf(invoice)
        send_whatsapp(from_num, pdf_url, invoice)
        log.info("✅ Invoice generated and sent!")
        return Response("OK", status=200)

    except Exception as e:
        log.error(f"❌ {e}", exc_info=True)
        try:
            twilio.messages.create(
                from_=env("TWILIO_FROM_NUMBER"), to=from_num,
                body=f"❌ Error generating invoice. Please try again.\n\n{str(e)[:100]}"
            )
        except:
            pass
        return Response("Error", status=500)


# ─── Health ───────────────────────────────────────────────────────────────────
@app.route("/health")
def health():
    keys = ["TWILIO_ACCOUNT_SID", "SARVAM_API_KEY", "CLAUDE_API_KEY", "CARBONE_API_KEY", "CARBONE_TAX_ID", "CARBONE_BOS_ID", "CARBONE_NONGST_ID"]
    c = {k: bool(env(k)) for k in keys}
    ok = all(c.values())
    return {"status": "healthy" if ok else "missing_config", "checks": c, "timestamp": datetime.now().isoformat()}, 200 if ok else 500


# ─── Home ─────────────────────────────────────────────────────────────────────
@app.route("/")
def home():
    return render_template_string(HOME_HTML)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    log.info(f"🚀 GutInvoice v3 starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
