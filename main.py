"""
GutInvoice — Every Invoice has a Voice
India's First Voice-First WhatsApp Invoice Generator for Telugu MSMEs
v4 — All fixes applied: saaras:v2.5, carbone-version:5, ?download=true
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
:root{--orange:#FF6B35;--navy:#0A0F1E;--green:#10B981;--card:#111827}
body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--navy);color:#fff;min-height:100vh;overflow-x:hidden}

nav{display:flex;justify-content:space-between;align-items:center;padding:18px 60px;border-bottom:1px solid rgba(255,107,53,0.12);background:rgba(10,15,30,0.98);position:sticky;top:0;z-index:100;backdrop-filter:blur(12px)}
.logo{font-size:24px;font-weight:900;color:var(--orange)}.logo span{color:#fff}
.logo-sub{font-size:11px;color:#475569;margin-top:3px;letter-spacing:1px;text-transform:uppercase}
.live-pill{display:flex;align-items:center;gap:8px;background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.25);padding:8px 18px;border-radius:50px;font-size:12px;color:var(--green);font-weight:700;letter-spacing:0.5px}
.live-dot{width:7px;height:7px;background:var(--green);border-radius:50%;animation:blink 2s infinite}
@keyframes blink{0%,100%{opacity:1;box-shadow:0 0 0 0 rgba(16,185,129,0.5)}50%{opacity:0.4;box-shadow:0 0 0 5px transparent}}

.hero{min-height:90vh;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;padding:80px 40px;position:relative}
.hero::before{content:'';position:absolute;width:900px;height:900px;background:radial-gradient(circle,rgba(255,107,53,0.07) 0%,transparent 65%);top:-300px;left:50%;transform:translateX(-50%);pointer-events:none}
.hero-chip{display:inline-flex;align-items:center;gap:8px;background:rgba(255,107,53,0.07);border:1px solid rgba(255,107,53,0.25);color:var(--orange);padding:8px 22px;border-radius:50px;font-size:13px;font-weight:700;margin-bottom:36px;letter-spacing:0.3px;position:relative;z-index:1}
.hero h1{font-size:clamp(42px,7vw,82px);font-weight:900;line-height:1.05;letter-spacing:-2.5px;margin-bottom:24px;position:relative;z-index:1}
.hero h1 em{color:var(--orange);font-style:normal}
.hero-desc{font-size:clamp(16px,2.2vw,20px);color:#64748B;max-width:580px;line-height:1.7;margin-bottom:16px;position:relative;z-index:1}
.hero-telugu{font-size:16px;color:#475569;font-style:italic;margin-bottom:52px;position:relative;z-index:1}
.hero-telugu span{color:#FBBF24}

.flow-visual{display:flex;align-items:center;justify-content:center;gap:0;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);border-radius:20px;padding:28px 40px;margin-bottom:52px;flex-wrap:wrap;position:relative;z-index:1;max-width:820px}
.fv-step{display:flex;flex-direction:column;align-items:center;gap:10px;padding:0 18px}
.fv-icon{width:54px;height:54px;border-radius:14px;display:flex;align-items:center;justify-content:center;font-size:24px}
.fv1{background:rgba(255,107,53,0.1);border:1px solid rgba(255,107,53,0.2)}
.fv2{background:rgba(139,92,246,0.1);border:1px solid rgba(139,92,246,0.2)}
.fv3{background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.2)}
.fv4{background:rgba(236,72,153,0.1);border:1px solid rgba(236,72,153,0.2)}
.fv-label{font-size:11px;color:#64748B;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;white-space:nowrap}
.fv-arrow{font-size:20px;color:rgba(255,107,53,0.3);padding:0 4px;margin-top:-20px}

.btn-group{display:flex;gap:14px;flex-wrap:wrap;justify-content:center;position:relative;z-index:1}
.btn-primary{background:var(--orange);color:#fff;padding:15px 36px;border-radius:50px;font-size:15px;font-weight:800;text-decoration:none;box-shadow:0 0 30px rgba(255,107,53,0.25);transition:all 0.2s}
.btn-primary:hover{background:#e85d25;transform:translateY(-2px);box-shadow:0 0 45px rgba(255,107,53,0.4)}
.btn-secondary{background:transparent;color:#64748B;padding:15px 36px;border-radius:50px;font-size:15px;font-weight:600;text-decoration:none;border:1px solid rgba(255,255,255,0.08);transition:all 0.2s}
.btn-secondary:hover{border-color:rgba(255,107,53,0.3);color:var(--orange)}

.stats-bar{display:flex;justify-content:center;gap:0;border-top:1px solid rgba(255,255,255,0.04);border-bottom:1px solid rgba(255,255,255,0.04);flex-wrap:wrap}
.stat-item{padding:44px 60px;text-align:center;border-right:1px solid rgba(255,255,255,0.04);flex:1;min-width:160px}
.stat-item:last-child{border-right:none}
.stat-n{font-size:44px;font-weight:900;color:var(--orange);letter-spacing:-2px;line-height:1}
.stat-l{font-size:12px;color:#475569;margin-top:8px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px}

.section{padding:96px 40px}
.section-alt{background:rgba(255,255,255,0.012)}
.s-label{display:inline-block;background:rgba(255,107,53,0.07);border:1px solid rgba(255,107,53,0.18);color:var(--orange);padding:5px 14px;border-radius:50px;font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:1px;margin-bottom:18px}
.s-title{font-size:clamp(28px,4vw,50px);font-weight:900;letter-spacing:-1.5px;margin-bottom:16px;line-height:1.1}
.s-sub{color:#64748B;font-size:17px;line-height:1.75;max-width:560px}
.center-col{display:flex;flex-direction:column;align-items:center;text-align:center}

.promise-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:1px;max-width:1200px;margin:64px auto 0;background:rgba(255,255,255,0.04);border-radius:24px;overflow:hidden;border:1px solid rgba(255,255,255,0.04)}
.promise-card{padding:44px;background:var(--navy);transition:background 0.2s;position:relative}
.promise-card:hover{background:rgba(255,107,53,0.025)}
.p-icon{font-size:40px;margin-bottom:20px}
.p-title{font-size:19px;font-weight:800;margin-bottom:10px;color:#F1F5F9}
.p-desc{font-size:14px;color:#64748B;line-height:1.75}
.p-hl{color:var(--orange);font-weight:700}

.how-steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:20px;max-width:1100px;margin:64px auto 0}
.how-card{background:var(--card);border:1px solid rgba(255,255,255,0.05);border-radius:20px;padding:36px;position:relative;overflow:hidden;transition:transform 0.2s,border-color 0.2s}
.how-card:hover{transform:translateY(-3px);border-color:rgba(255,107,53,0.2)}
.how-card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--orange);opacity:0}
.how-card:hover::before{opacity:1}
.how-num{font-size:11px;font-weight:900;color:var(--orange);text-transform:uppercase;letter-spacing:1.5px;margin-bottom:20px;opacity:0.8}
.how-icon{font-size:38px;margin-bottom:18px}
.how-title{font-size:17px;font-weight:800;margin-bottom:10px}
.how-desc{font-size:13px;color:#64748B;line-height:1.7}

.demo-wrap{max-width:720px;margin:64px auto 0}
.demo-box{background:var(--card);border:1px solid rgba(255,255,255,0.06);border-radius:20px;overflow:hidden}
.demo-bar{background:rgba(255,255,255,0.03);border-bottom:1px solid rgba(255,255,255,0.05);padding:14px 20px;display:flex;align-items:center;gap:8px}
.db{width:10px;height:10px;border-radius:50%}
.db1{background:#FF5F57}.db2{background:#FEBC2E}.db3{background:#28C840}
.demo-inner{padding:30px}
.demo-row{display:flex;gap:14px;margin-bottom:18px;align-items:flex-start}
.demo-row:last-child{margin-bottom:0}
.d-tag{flex-shrink:0;font-size:10px;font-weight:900;text-transform:uppercase;letter-spacing:0.8px;padding:4px 10px;border-radius:6px;margin-top:3px;white-space:nowrap}
.dt1{background:rgba(255,107,53,0.12);color:var(--orange);border:1px solid rgba(255,107,53,0.2)}
.dt2{background:rgba(16,185,129,0.12);color:var(--green);border:1px solid rgba(16,185,129,0.2)}
.dt3{background:rgba(99,102,241,0.12);color:#818CF8;border:1px solid rgba(99,102,241,0.2)}
.d-text{font-size:14px;color:#CBD5E1;line-height:1.7}
.d-text .te{color:#FBBF24;font-weight:600}
.d-text .en{color:#34D399;font-weight:600}
.d-arrow{text-align:center;color:rgba(255,107,53,0.3);font-size:18px;margin:4px 0}

.inv-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px;max-width:1000px;margin:64px auto 0}
.inv-card{border-radius:20px;padding:36px;border:1px solid;transition:transform 0.2s;position:relative;overflow:hidden}
.inv-card:hover{transform:translateY(-4px)}
.inv-card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px}
.ic1{background:rgba(255,107,53,0.04);border-color:rgba(255,107,53,0.15)}.ic1::before{background:var(--orange)}
.ic2{background:rgba(99,102,241,0.04);border-color:rgba(99,102,241,0.15)}.ic2::before{background:#6366F1}
.ic3{background:rgba(16,185,129,0.04);border-color:rgba(16,185,129,0.15)}.ic3::before{background:var(--green)}
.i-badge{display:inline-block;font-size:10px;font-weight:900;text-transform:uppercase;letter-spacing:1px;padding:4px 12px;border-radius:50px;margin-bottom:16px}
.ib1{background:rgba(255,107,53,0.1);color:var(--orange)}
.ib2{background:rgba(99,102,241,0.1);color:#818CF8}
.ib3{background:rgba(16,185,129,0.1);color:var(--green)}
.inv-card h3{font-size:21px;font-weight:900;margin-bottom:6px}
.inv-card .who{font-size:13px;color:#64748B;margin-bottom:20px}
.inv-card ul{list-style:none}
.inv-card li{font-size:13px;color:#94A3B8;padding:6px 0;padding-left:18px;position:relative;border-bottom:1px solid rgba(255,255,255,0.04)}
.inv-card li:last-child{border-bottom:none}
.inv-card li::before{content:'✓';position:absolute;left:0;font-weight:900;font-size:12px}
.ic1 li::before{color:var(--orange)}.ic2 li::before{color:#818CF8}.ic3 li::before{color:var(--green)}

.price-wrap{max-width:460px;margin:64px auto 0}
.price-box{background:var(--card);border:1px solid rgba(255,107,53,0.18);border-radius:24px;padding:50px;text-align:center;position:relative;overflow:hidden}
.price-box::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,var(--orange),#FF9A6C)}
.price-amt{font-size:76px;font-weight:900;color:var(--orange);letter-spacing:-3px;line-height:1}
.price-per{font-size:18px;color:#475569;font-weight:600}
.price-note{font-size:15px;color:#64748B;margin:16px 0 32px;line-height:1.6}
.price-list{list-style:none;text-align:left;margin-bottom:36px}
.price-list li{padding:11px 0;font-size:15px;color:#94A3B8;border-bottom:1px solid rgba(255,255,255,0.05);display:flex;align-items:center;gap:10px}
.price-list li:last-child{border-bottom:none}
.chk{color:var(--green);font-weight:900;font-size:16px}

footer{border-top:1px solid rgba(255,255,255,0.05);padding:48px 60px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:20px}
.f-logo{font-size:20px;font-weight:900;color:var(--orange)}.f-logo span{color:#fff}
.f-tag{font-size:12px;color:#374151;margin-top:4px}
.f-right{font-size:12px;color:#374151;text-align:right;line-height:1.8}

@media(max-width:768px){
  nav{padding:16px 20px}
  .hero{padding:60px 20px}
  .flow-visual{padding:20px 16px;gap:6px}
  .fv-arrow{display:none}
  .fv-step{padding:0 8px}
  .stats-bar{flex-direction:column}
  .stat-item{border-right:none;border-bottom:1px solid rgba(255,255,255,0.04);padding:28px 20px}
  .section{padding:64px 20px}
  footer{flex-direction:column;text-align:center;padding:40px 20px}
  .f-right{text-align:center}
}
</style>
</head>
<body>

<nav>
  <div>
    <div class="logo">Gut<span>Invoice</span></div>
    <div class="logo-sub">Every Invoice has a Voice</div>
  </div>
  <div class="live-pill"><span class="live-dot"></span>LIVE</div>
</nav>

<!-- HERO -->
<section class="hero">
  <div class="hero-chip">🇮🇳 Made for Telugu-speaking Business Owners</div>
  <h1>Your Voice.<br/>Your <em>Invoice.</em></h1>
  <p class="hero-desc">Send a WhatsApp voice note in Telugu or English — get a professional GST invoice PDF delivered back in under 30 seconds. No app. No typing. No hassle.</p>
  <p class="hero-telugu">మాట్లాడండి — <span>Invoice వస్తుంది.</span> అంతే.</p>

  <div class="flow-visual">
    <div class="fv-step"><div class="fv-icon fv1">🎙️</div><div class="fv-label">You Speak</div></div>
    <div class="fv-arrow">→</div>
    <div class="fv-step"><div class="fv-icon fv2">⚡</div><div class="fv-label">We Process</div></div>
    <div class="fv-arrow">→</div>
    <div class="fv-step"><div class="fv-icon fv3">📄</div><div class="fv-label">GST PDF Ready</div></div>
    <div class="fv-arrow">→</div>
    <div class="fv-step"><div class="fv-icon fv4">💬</div><div class="fv-label">WhatsApp Delivered</div></div>
  </div>

  <div class="btn-group">
    <a href="#how" class="btn-primary">How It Works</a>
    <a href="#pricing" class="btn-secondary">See Pricing →</a>
  </div>
</section>

<!-- STATS -->
<div class="stats-bar">
  <div class="stat-item"><div class="stat-n">30s</div><div class="stat-l">Invoice Delivery</div></div>
  <div class="stat-item"><div class="stat-n">3</div><div class="stat-l">Invoice Types</div></div>
  <div class="stat-item"><div class="stat-n">0</div><div class="stat-l">Apps to Download</div></div>
  <div class="stat-item"><div class="stat-n">₹199</div><div class="stat-l">Per Month</div></div>
</div>

<!-- WHAT WE DELIVER -->
<section class="section" id="promise">
  <div class="center-col">
    <div class="s-label">What You Get</div>
    <h2 class="s-title">Everything a Business Owner<br/>Actually Needs</h2>
    <p class="s-sub">No complicated software. No CA needed for every invoice. Just speak on WhatsApp and your invoice is ready.</p>
  </div>
  <div class="promise-grid">
    <div class="promise-card">
      <div class="p-icon">🎙️</div>
      <div class="p-title">Speak in Your Language</div>
      <p class="p-desc">Use <span class="p-hl">Telugu, English, or a mix</span> of both — exactly how you speak every day. No need to learn any new system or language.</p>
    </div>
    <div class="promise-card">
      <div class="p-icon">📲</div>
      <div class="p-title">Only WhatsApp Needed</div>
      <p class="p-desc">No app to download. No website to visit. No login. <span class="p-hl">Just the WhatsApp you already use</span> every day on your phone.</p>
    </div>
    <div class="promise-card">
      <div class="p-icon">📄</div>
      <div class="p-title">Professional GST Invoice PDF</div>
      <p class="p-desc">Get a <span class="p-hl">proper GST-compliant invoice PDF</span> with your business name, GSTIN, tax breakup, and all required fields — in 30 seconds.</p>
    </div>
    <div class="promise-card">
      <div class="p-icon">⚡</div>
      <div class="p-title">Ready in 30 Seconds</div>
      <p class="p-desc">From voice note to PDF on your phone in <span class="p-hl">under 30 seconds</span>. Send it directly to your customer without any delay.</p>
    </div>
    <div class="promise-card">
      <div class="p-icon">🏪</div>
      <div class="p-title">Remembers Your Business</div>
      <p class="p-desc">Set up your business name, address, and GSTIN once. <span class="p-hl">Every invoice after that is automatic</span> — no need to repeat details.</p>
    </div>
    <div class="promise-card">
      <div class="p-icon">✅</div>
      <div class="p-title">GST Compliant Always</div>
      <p class="p-desc">All 3 invoice formats supported — <span class="p-hl">Tax Invoice, Bill of Supply, and plain Invoice</span> — auto-selected based on your business type.</p>
    </div>
  </div>
</section>

<!-- HOW IT WORKS -->
<section class="section section-alt" id="how">
  <div class="center-col">
    <div class="s-label">How It Works</div>
    <h2 class="s-title">4 Steps.<br/>30 Seconds.</h2>
    <p class="s-sub">The simplest invoice process ever built for an Indian small business owner.</p>
  </div>
  <div class="how-steps">
    <div class="how-card">
      <div class="how-num">Step 01</div>
      <div class="how-icon">🎙️</div>
      <div class="how-title">Send a Voice Note</div>
      <p class="how-desc">Open WhatsApp. Send a voice note to your GutInvoice number. Say your customer name, items, quantity, price, and GST.</p>
    </div>
    <div class="how-card">
      <div class="how-num">Step 02</div>
      <div class="how-icon">🧏</div>
      <div class="how-title">We Listen & Understand</div>
      <p class="how-desc">GutInvoice understands your voice in Telugu, English, or any mix. Even casual speech is understood correctly.</p>
    </div>
    <div class="how-card">
      <div class="how-num">Step 03</div>
      <div class="how-icon">🔢</div>
      <div class="how-title">Invoice is Built</div>
      <p class="how-desc">Customer details, item names, quantities, rates, CGST, SGST, IGST — everything is calculated and filled automatically.</p>
    </div>
    <div class="how-card">
      <div class="how-num">Step 04</div>
      <div class="how-icon">💬</div>
      <div class="how-title">PDF on WhatsApp</div>
      <p class="how-desc">Your professional GST invoice PDF arrives on WhatsApp in under 30 seconds. Forward it directly to your customer.</p>
    </div>
  </div>
</section>

<!-- LIVE EXAMPLE -->
<section class="section" id="demo">
  <div class="center-col">
    <div class="s-label">Live Example</div>
    <h2 class="s-title">See It in Action</h2>
    <p class="s-sub">A real business owner speaks — the invoice arrives in seconds.</p>
  </div>
  <div class="demo-wrap">
    <div class="demo-box">
      <div class="demo-bar">
        <div class="db db1"></div><div class="db db2"></div><div class="db db3"></div>
        <span style="font-size:12px;color:#475569;margin-left:10px;font-weight:600">GutInvoice — Live</span>
      </div>
      <div class="demo-inner">
        <div class="demo-row">
          <div class="d-tag dt1">🎙️ You Say</div>
          <div class="d-text">"<span class="te">Customer Suresh</span>, <span class="te">Dilsukhnagar</span>, <span class="en">50 iron rods</span>, <span class="te">ఒక్కొక్కటి</span> <span class="en">800 rupees</span>, <span class="en">18% GST</span>, <span class="te">15 రోజుల్లో pay చేయాలి</span>"</div>
        </div>
        <div class="d-arrow">↓</div>
        <div class="demo-row">
          <div class="d-tag dt2">⚡ Extracted</div>
          <div class="d-text">Customer: <strong>Suresh, Dilsukhnagar</strong> · 50 × Iron Rods @ ₹800 · CGST 9% + SGST 9% · <strong>Total: ₹47,200</strong></div>
        </div>
        <div class="d-arrow">↓</div>
        <div class="demo-row">
          <div class="d-tag dt3">📄 Delivered</div>
          <div class="d-text">Professional <strong>GST Tax Invoice</strong> PDF with all fields, tax breakup, and business details — on WhatsApp in <strong>28 seconds ✅</strong></div>
        </div>
      </div>
    </div>
  </div>
</section>

<!-- INVOICE TYPES -->
<section class="section section-alt" id="types">
  <div class="center-col">
    <div class="s-label">Invoice Types</div>
    <h2 class="s-title">Right Invoice,<br/>Every Time</h2>
    <p class="s-sub">GutInvoice automatically picks the correct format based on your business — no manual selection needed.</p>
  </div>
  <div class="inv-grid">
    <div class="inv-card ic1">
      <div class="i-badge ib1">GST Registered</div>
      <h3>🧾 Tax Invoice</h3>
      <div class="who">For businesses registered under GST</div>
      <ul>
        <li>Your GSTIN on every invoice</li>
        <li>CGST + SGST breakdown</li>
        <li>Your customer claims tax credit</li>
        <li>Mandatory for B2B above ₹50,000</li>
        <li>Fully compliant format</li>
      </ul>
    </div>
    <div class="inv-card ic2">
      <div class="i-badge ib2">Composition Scheme</div>
      <h3>📝 Bill of Supply</h3>
      <div class="who">For composition scheme businesses</div>
      <ul>
        <li>No tax rows — clean format</li>
        <li>Required GST declaration included</li>
        <li>Automatically detected</li>
        <li>100% GST compliant</li>
        <li>Simple and professional</li>
      </ul>
    </div>
    <div class="inv-card ic3">
      <div class="i-badge ib3">Unregistered</div>
      <h3>📃 Invoice</h3>
      <div class="who">For small businesses without GST</div>
      <ul>
        <li>No GSTIN required</li>
        <li>No tax calculations needed</li>
        <li>Clean professional layout</li>
        <li>Correct declaration included</li>
        <li>Perfect for small traders</li>
      </ul>
    </div>
  </div>
</section>

<!-- PRICING -->
<section class="section" id="pricing">
  <div class="center-col">
    <div class="s-label">Pricing</div>
    <h2 class="s-title">One Simple Price.<br/>No Surprises.</h2>
    <p class="s-sub">No per-invoice fees. No hidden charges. Flat monthly price that saves you hours every week.</p>
  </div>
  <div class="price-wrap">
    <div class="price-box">
      <div class="price-amt">₹199</div>
      <div class="price-per">/month</div>
      <p class="price-note">Cancel anytime. No contracts. Start with 3 free invoices — no payment needed.</p>
      <ul class="price-list">
        <li><span class="chk">✓</span> Unlimited invoices every month</li>
        <li><span class="chk">✓</span> All 3 GST invoice types</li>
        <li><span class="chk">✓</span> Telugu + English voice input</li>
        <li><span class="chk">✓</span> PDF delivered on WhatsApp</li>
        <li><span class="chk">✓</span> Your business details saved</li>
        <li><span class="chk">✓</span> 3 free invoices to start</li>
      </ul>
      <a href="#" class="btn-primary" style="display:block;text-align:center;text-decoration:none;padding:16px">Start Free — Try 3 Invoices</a>
    </div>
  </div>
</section>

<footer>
  <div>
    <div class="f-logo">Gut<span>Invoice</span></div>
    <div class="f-tag">Every Invoice has a Voice — మీ గొంతే మీ Invoice</div>
  </div>
  <div class="f-right">
    Built for Telugu-speaking MSMEs · Hyderabad, India<br/>
    © 2026 GutInvoice. All rights reserved.
  </div>
</footer>

</body></html>"""


# ─── Step 1: Download audio ───────────────────────────────────────────────────
def download_audio(media_url):
    if media_url.startswith("/"):
        media_url = f"https://api.twilio.com{media_url}"
    r = requests.get(
        media_url,
        auth=(env("TWILIO_ACCOUNT_SID"), env("TWILIO_AUTH_TOKEN")),
        timeout=30
    )
    r.raise_for_status()
    log.info(f"Audio: {len(r.content)} bytes | type: {r.headers.get('content-type')}")
    return r.content


# ─── Step 2: Transcribe — FIXED: saaras:v2.5 ─────────────────────────────────
def transcribe_audio(audio_bytes):
    r = requests.post(
        "https://api.sarvam.ai/speech-to-text-translate",
        headers={"API-Subscription-Key": env("SARVAM_API_KEY")},
        files={"file": ("audio.ogg", audio_bytes, "audio/ogg")},
        data={
            "model": "saaras:v2.5",           # ✅ FIXED
            "source_language_code": "te-IN",
            "target_language_code": "en-IN"
        },
        timeout=60
    )
    if r.status_code != 200:
        raise Exception(f"Transcription error {r.status_code}: {r.text}")
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
- Intra-state: use CGST+SGST (split equally). Inter-state: use IGST only.
- amount = qty x rate. total_amount = taxable_value + all taxes.
- Default GST 18% if not mentioned.
- BILL OF SUPPLY declaration: "Composition taxable person, not eligible to collect tax on supplies"
- INVOICE declaration: "Seller not registered under GST. GST not applicable."

Return ONLY this JSON, no other text:
{{"invoice_type":"TAX INVOICE","seller_name":"{seller_info.get('seller_name','')}","seller_address":"{seller_info.get('seller_address','')}","seller_gstin":"{seller_info.get('seller_gstin','')}","invoice_number":"{inv_no}","invoice_date":"{today}","customer_name":"","customer_address":"","customer_gstin":"","place_of_supply":"Telangana","reverse_charge":"No","items":[{{"sno":1,"description":"","hsn_sac":"","qty":0,"unit":"Nos","rate":0,"amount":0}}],"taxable_value":0,"cgst_rate":9,"cgst_amount":0,"sgst_rate":9,"sgst_amount":0,"igst_rate":0,"igst_amount":0,"total_amount":0,"declaration":"","payment_terms":"Pay within 15 days"}}"""

    claude = get_claude()
    msg = claude.messages.create(
        model="claude-opus-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )
    text = msg.content[0].text.strip()
    log.info(f"Claude raw response: {text[:300]}")
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    # Find JSON object in response
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise Exception(f"No JSON found in Claude response: {text[:200]}")
    text = text[start:end]
    data = json.loads(text)  log.info(f"Invoice: {data.get('invoice_type')} for {data.get('customer_name')}")
    return data


# ─── Step 4: Generate PDF — FIXED: carbone-version:5 + ?download=true ─────────
def generate_pdf(invoice_data):
    t = invoice_data.get("invoice_type", "TAX INVOICE")
    if "BILL" in t:
        tid = env("CARBONE_BOS_ID")
    elif "TAX" in t:
        tid = env("CARBONE_TAX_ID")
    else:
        tid = env("CARBONE_NONGST_ID")

    r = requests.post(
        f"https://api.carbone.io/render/{tid}?download=true",   # ✅ FIXED
        headers={
            "Authorization": f"Bearer {env('CARBONE_API_KEY')}",
            "Content-Type": "application/json",
            "carbone-version": "5"                               # ✅ FIXED
        },
        json={"data": invoice_data, "convertTo": "pdf"},
        timeout=60
    )
    if r.status_code != 200:
        raise Exception(f"PDF generation error {r.status_code}: {r.text}")
    rid = r.json().get("data", {}).get("renderId")
    if not rid:
        raise Exception(f"No renderId returned: {r.json()}")
    url = f"https://api.carbone.io/render/{rid}"
    log.info(f"PDF ready: {url}")
    return url


# ─── Step 5: Send WhatsApp ────────────────────────────────────────────────────
def send_whatsapp(to, pdf_url, invoice_data):
    twilio = get_twilio()
    body = (
        f"✅ *Your {invoice_data.get('invoice_type','Invoice')} is Ready!*\n\n"
        f"📋 {invoice_data.get('invoice_number','')}\n"
        f"👤 {invoice_data.get('customer_name','Customer')}\n"
        f"💰 ₹{invoice_data.get('total_amount',0):,.0f}\n\n"
        f"Powered by *GutInvoice* 🎙️\n"
        f"_Every Invoice has a Voice_"
    )
    msg = twilio.messages.create(
        from_=env("TWILIO_FROM_NUMBER"),
        to=to,
        body=body,
        media_url=[pdf_url]
    )
    log.info(f"WhatsApp sent: {msg.sid}")


def get_seller_info(from_number):
    return {
        "seller_name": "My Business",
        "seller_address": "Hyderabad, Telangana",
        "seller_gstin": "",
        "invoice_type": "TAX INVOICE"
    }


# ─── Webhook ──────────────────────────────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    twilio = get_twilio()
    from_num   = request.form.get("From", "")
    num_media  = int(request.form.get("NumMedia", 0))
    media_type = request.form.get("MediaContentType0", "")
    media_url  = request.form.get("MediaUrl0", "")

    log.info(f"From: {from_num} | Media: {num_media} | Type: {media_type}")

    try:
        if num_media == 0:
            twilio.messages.create(
                from_=env("TWILIO_FROM_NUMBER"), to=from_num,
                body=(
                    "🎙️ *GutInvoice — Every Invoice has a Voice*\n\n"
                    "Please send a *voice note* with your invoice details.\n\n"
                    "Example:\n"
                    "_\"Customer Suresh, 50 iron rods, 800 rupees each, 18% GST\"\n\n"
                    "Telugu లో కూడా చెప్పవచ్చు! 🙏_"
                )
            )
            return Response("OK", status=200)

        if "audio" not in media_type and "ogg" not in media_type:
            twilio.messages.create(
                from_=env("TWILIO_FROM_NUMBER"), to=from_num,
                body="Please send a *voice note* 🎙️, not an image or document."
            )
            return Response("OK", status=200)

        twilio.messages.create(
            from_=env("TWILIO_FROM_NUMBER"), to=from_num,
            body="🎙️ Voice note received! Generating your invoice... ⏳\n_(Ready in ~30 seconds)_"
        )

        seller     = get_seller_info(from_num)
        audio      = download_audio(media_url)
        transcript = transcribe_audio(audio)
        if not transcript:
            raise Exception("Could not understand the voice note. Please try again.")
        invoice    = extract_invoice_data(transcript, seller)
        pdf_url    = generate_pdf(invoice)
        send_whatsapp(from_num, pdf_url, invoice)
        log.info("✅ Invoice generated and delivered!")
        return Response("OK", status=200)

    except Exception as e:
        log.error(f"❌ {e}", exc_info=True)
        try:
            twilio.messages.create(
                from_=env("TWILIO_FROM_NUMBER"), to=from_num,
                body=f"❌ Error generating invoice. Please try again.\n\n{str(e)[:120]}"
            )
        except:
            pass
        return Response("Error", status=500)


# ─── Health Check ─────────────────────────────────────────────────────────────
@app.route("/health")
def health():
    keys = ["TWILIO_ACCOUNT_SID","SARVAM_API_KEY","CLAUDE_API_KEY","CARBONE_API_KEY","CARBONE_TAX_ID","CARBONE_BOS_ID","CARBONE_NONGST_ID"]
    c = {k: bool(env(k)) for k in keys}
    ok = all(c.values())
    return {"status":"healthy" if ok else "missing_config","checks":c,"timestamp":datetime.now().isoformat()}, 200 if ok else 500


# ─── Homepage ─────────────────────────────────────────────────────────────────
@app.route("/")
def home():
    return render_template_string(HOME_HTML)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    log.info(f"🚀 GutInvoice v4 starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
