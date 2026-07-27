"""
Betelgeuse TI Comment Moderator + Sentiment Analysis + n8n Integration
Flask app with Meta App Review compliance + real-time sentiment KPIs
English UI version (App Review screencast requirement)
"""

import os
import re
import json
import requests
import hashlib
import hmac
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, redirect, request, session, render_template_string, url_for, jsonify

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-key-change-in-prod")

# =============================================================================
# CONFIG
# =============================================================================
FB_APP_ID = os.environ.get("FB_APP_ID", "YOUR_APP_ID")
FB_APP_SECRET = os.environ.get("FB_APP_SECRET", "YOUR_APP_SECRET")
FB_API_VERSION = "v25.0"
FB_BASE_URL = f"https://graph.facebook.com/{FB_API_VERSION}"
REDIRECT_URI = os.environ.get("REDIRECT_URI", "https://betelgeuse-ti.vercel.app/callback")

REQUIRED_SCOPES = [
    "pages_show_list",
    "pages_read_engagement",
    "pages_read_user_content",
    "pages_manage_metadata"  # page webhooks (App Review; admin grants before approval)
]

# Human-readable descriptions for each requested permission (landing + dashboard)
PERMISSION_INFO = {
    "pages_show_list": {
        "desc": "Display the list of Facebook Pages you manage",
        "badge": "green"
    },
    "pages_read_engagement": {
        "desc": "Read posts and metrics to select which post to moderate",
        "badge": "orange"
    },
    "pages_read_user_content": {
        "desc": "Read comments with author name, message and date for moderation",
        "badge": "red"
    },
    "pages_manage_metadata": {
        "desc": "Subscribe the Page to real-time webhooks for instant comment notifications",
        "badge": "purple"
    }
}

# Gemini Config
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
# Cost-optimized model: 3.1-flash-lite is the budget tier of the current generation
# (~6x cheaper than 3.5-flash). 2.5-flash-lite was retired by Google for new users
# (404 error confirmed on 2026-07-23).
# To switch models without a deploy: set GEMINI_MODEL in Vercel env vars
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# n8n Config
N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "")

# Key for local n8n to call /poll_comments without login (set in Vercel)
POLL_API_KEY = os.environ.get("POLL_API_KEY", "")

# Webhook Config
WEBHOOK_VERIFY_TOKEN = os.environ.get("WEBHOOK_VERIFY_TOKEN", "betelgeuse_webhook_2026")
WEBHOOK_APP_SECRET = os.environ.get("FB_APP_SECRET", "")
WEBHOOK_LOG_FILE = "webhook_comments.json"

# In-memory webhook event store (Vercel filesystem is read-only)
_WEBHOOK_EVENTS = []

# Fixed Page Access Token via Vercel environment variable (Graph API)
# Accepts both spellings for safety; falls back to /me/accounts flow if absent
PAGE_ACCESS_TOKEN_ENV = os.environ.get("PAGE_ACCESS_TOKEN") or os.environ.get("PAGE_ACESS_TOKEN") or ""

def get_session_page_token(page_id):
    """Fetches the Page Token for the page via /me/accounts using the session token."""
    if "access_token" not in session:
        return None
    try:
        resp = requests.get(
            f"{FB_BASE_URL}/me/accounts",
            params={"access_token": session["access_token"]},
            timeout=30
        )
        for acc in resp.json().get("data", []):
            if acc.get("id") == page_id:
                return acc.get("access_token")
    except Exception as e:
        print(f"Error fetching session page token: {e}")
    return None

def _fb_tokens(page_id=None):
    """Builds the token list in priority order:
    1) PAGE_ACCESS_TOKEN from Vercel env;
    2) Page Token via /me/accounts (session);
    3) Session User Token."""
    tokens = []
    if PAGE_ACCESS_TOKEN_ENV:
        tokens.append(PAGE_ACCESS_TOKEN_ENV)
    if page_id:
        session_page_token = get_session_page_token(page_id)
        if session_page_token and session_page_token not in tokens:
            tokens.append(session_page_token)
    if "access_token" in session and session["access_token"] not in tokens:
        tokens.append(session["access_token"])
    return tokens

def fb_get(url_path, params, page_id=None):
    """Graph API GET with automatic token fallback.
    Returns the first JSON without 'error'; if all fail, returns the last error."""
    last_data = {}
    for token in _fb_tokens(page_id):
        try:
            resp = requests.get(
                f"{FB_BASE_URL}/{url_path}",
                params={**params, "access_token": token},
                timeout=30
            )
            data = resp.json()
            if "error" not in data:
                return data
            print(f"Graph API rejected token (...{token[-6:]}): {data['error']}")
            last_data = data
        except Exception as e:
            print(f"Graph API call error: {e}")
    return last_data

def fb_get_paginated(url_path, params, page_id=None, max_items=200):
    """Paginated GET: follows paging.next until max_items.
    Uses the first working token (same order as fb_get).
    Returns (items, error) — error is None on success."""
    last_err = None
    for token in _fb_tokens(page_id):
        items = []
        url = f"{FB_BASE_URL}/{url_path}"
        next_params = {**params, "access_token": token}
        try:
            while len(items) < max_items:
                resp = requests.get(url, params=next_params, timeout=30)
                data = resp.json()
                if "error" in data:
                    last_err = data["error"].get("message", str(data["error"]))
                    print(f"Pagination rejected (...{token[-6:]}): {data['error']}")
                    break
                batch = data.get("data", [])
                if not batch:
                    return items, None
                items.extend(batch)
                next_url = data.get("paging", {}).get("next")
                if not next_url:
                    return items, None
                url = next_url
                next_params = {}  # paging.next already carries token and cursors
            return items[:max_items], None
        except Exception as e:
            last_err = str(e)
            print(f"Pagination error: {e}")
    return [], last_err

def fb_post(url_path, params, page_id=None):
    """Graph API POST with token fallback (e.g. subscribing page to webhooks).
    Returns (True, None) on success or (False, error_message)."""
    last_err = "No token available"
    for token in _fb_tokens(page_id):
        try:
            resp = requests.post(
                f"{FB_BASE_URL}/{url_path}",
                params={**params, "access_token": token},
                timeout=30
            )
            data = resp.json()
            if "error" not in data:
                return True, None
            print(f"POST rejected (...{token[-6:]}): {data['error']}")
            last_err = data["error"].get("message", str(data["error"]))
        except Exception as e:
            last_err = str(e)
    return False, last_err

def get_granted_permissions():
    """Queries /me/permissions with the session user token and returns
    the set of permissions with status 'granted'."""
    granted = set()
    if "access_token" not in session:
        return granted
    try:
        resp = requests.get(
            f"{FB_BASE_URL}/me/permissions",
            params={"access_token": session["access_token"]},
            timeout=30
        )
        for item in resp.json().get("data", []):
            if item.get("status") == "granted":
                granted.add(item.get("permission"))
    except Exception as e:
        print(f"Error fetching permissions: {e}")
    return granted

def is_page_subscribed(page_id):
    """Checks whether the app is already subscribed to this Page's webhooks."""
    try:
        status = fb_get(f"{page_id}/subscribed_apps", {}, page_id=page_id)
        for app_entry in status.get("data", []):
            if str(app_entry.get("id")) == str(FB_APP_ID):
                return True
    except Exception as e:
        print(f"Error checking subscription: {e}")
    return False

# =============================================================================
# SENTIMENT ANALYSIS (Gemini) - NO CACHE (Vercel read-only filesystem)
# =============================================================================

def analyze_sentiment(text):
    """Analyze sentiment using Gemini API - no cache, direct call"""
    if not GOOGLE_API_KEY or not text:
        return "NEUTRO"

    try:
        url = f"{GEMINI_URL}?key={GOOGLE_API_KEY}"
        payload = {
            "contents": [{
                "role": "user",
                "parts": [{"text": f"Classifique o sentimento deste comentario em UMA palavra apenas: POSITIVO, NEUTRO ou NEGATIVO. Comentario: {text}"}]
            }],
            "generationConfig": {"temperature": 0}
        }

        resp = requests.post(url, json=payload, timeout=30)
        data = resp.json()

        if "candidates" in data and data["candidates"]:
            result_text = data["candidates"][0]["content"]["parts"][0]["text"].upper().strip()

            # Extract sentiment from response
            if "POSITIVO" in result_text:
                return "POSITIVO"
            elif "NEGATIVO" in result_text:
                return "NEGATIVO"
            else:
                return "NEUTRO"

        # No candidates = API refused the call; log the real reason
        print(f"Gemini API ERROR (single): {json.dumps(data)[:400]}")
        return "NEUTRO"

    except Exception as e:
        print(f"Gemini error: {e}")
        return "NEUTRO"

def get_sentiment(text, comment_id):
    """Get sentiment - no cache, direct analysis every time"""
    return analyze_sentiment(text)

# =============================================================================
# BATCH ANALYSIS (cost control): 20 comments per Gemini call
# Before: 1 call per comment (500 comments = 500 calls)
# Now: 500 comments = 25 calls -> ~95% fewer requests and tokens
# =============================================================================
BATCH_SIZE = 20

def analyze_sentiments_batch(texts):
    """Analyzes up to BATCH_SIZE texts in ONE Gemini call.
    Returns a list of sentiments in the SAME ORDER as the texts."""
    if not texts:
        return []
    if not GOOGLE_API_KEY:
        return ["NEUTRO"] * len(texts)
    try:
        numbered = "\n".join(
            f"{i+1}. {t[:280].replace(chr(10), ' ')}" for i, t in enumerate(texts)
        )
        prompt = (
            "Classifique o sentimento de cada comentário em UMA palavra: POSITIVO, NEUTRO ou NEGATIVO.\n"
            "Responda APENAS um JSON array de strings, na MESMA ORDEM dos comentários, sem explicações.\n"
            'Exemplo de resposta: ["POSITIVO","NEUTRO","NEGATIVO"]\n\n'
            f"Comentários:\n{numbered}"
        )
        url = f"{GEMINI_URL}?key={GOOGLE_API_KEY}"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0}
        }
        resp = requests.post(url, json=payload, timeout=60)
        data = resp.json()
        if "candidates" not in data:
            # Shows the REAL API error in logs instead of silent fallback
            print(f"Gemini API ERROR (batch): {json.dumps(data)[:400]}")
            return ["NEUTRO"] * len(texts)
        result_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()

        # Extracts the JSON array even if the model wraps it in ```json
        match = re.search(r"\[.*\]", result_text, re.DOTALL)
        if match:
            arr = json.loads(match.group(0))
            sentiments = []
            for item in arr[:len(texts)]:
                s = str(item).upper().strip()
                if "POSITIVO" in s:
                    sentiments.append("POSITIVO")
                elif "NEGATIVO" in s:
                    sentiments.append("NEGATIVO")
                else:
                    sentiments.append("NEUTRO")
            # If the model returned fewer items, pad with NEUTRO
            while len(sentiments) < len(texts):
                sentiments.append("NEUTRO")
            return sentiments

        print(f"Gemini batch: response without JSON array: {result_text[:120]}")
        return ["NEUTRO"] * len(texts)

    except Exception as e:
        print(f"Gemini batch error: {e}")
        return ["NEUTRO"] * len(texts)

def analyze_many(texts):
    """Splits the list into BATCH_SIZE chunks and processes batches in parallel."""
    if not texts:
        return []
    batches = [texts[i:i + BATCH_SIZE] for i in range(0, len(texts), BATCH_SIZE)]
    results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        for batch_result in executor.map(analyze_sentiments_batch, batches):
            results.extend(batch_result)
    return results

# PT -> EN map: Gemini answers in Portuguese (POSITIVO/NEUTRO/NEGATIVO);
# CSS classes and display badges use English
SENTIMENT_EN = {"POSITIVO": "positive", "NEUTRO": "neutral", "NEGATIVO": "negative"}
SENTIMENT_DISPLAY = {"POSITIVO": "POSITIVE", "NEUTRO": "NEUTRAL", "NEGATIVO": "NEGATIVE"}

# In-memory cache (Vercel filesystem is read-only)
_SENTIMENT_CACHE = {}

def load_sentiment_cache():
    return _SENTIMENT_CACHE

def save_sentiment_cache(cache):
    pass  # no disk persistence on Vercel

# =============================================================================
# n8n WEBHOOK
# =============================================================================

def send_to_n8n(summary_data):
    """Send summary to n8n webhook"""
    if not N8N_WEBHOOK_URL:
        print("N8N_WEBHOOK_URL not configured")
        return False

    try:
        resp = requests.post(N8N_WEBHOOK_URL, json=summary_data, timeout=30)
        return resp.status_code == 200
    except Exception as e:
        print(f"n8n error: {e}")
        return False

# =============================================================================
# WEBHOOK SECURITY HELPERS (these were missing — POST /webhook would crash)
# =============================================================================

def verify_signature(payload_body, signature_header):
    """Validates the X-Hub-Signature-256 header sent by Meta.
    Signature = HMAC-SHA256(payload, APP_SECRET), hex-encoded, prefixed 'sha256='.
    If APP_SECRET is not configured, accept (dev mode) but log a warning."""
    if not WEBHOOK_APP_SECRET:
        print("WARNING: FB_APP_SECRET empty — skipping webhook signature validation")
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(
        WEBHOOK_APP_SECRET.encode("utf-8"),
        payload_body,
        hashlib.sha256
    ).hexdigest()
    received = signature_header.split("sha256=", 1)[1]
    return hmac.compare_digest(expected, received)

def save_webhook_payload(payload):
    """Stores the webhook payload in memory (Vercel filesystem is read-only).
    Also attempts a best-effort file write for local runs."""
    try:
        _WEBHOOK_EVENTS.append({
            "received_at": datetime.now().isoformat(),
            "payload": payload
        })
        # Keep only the last 100 events in memory
        if len(_WEBHOOK_EVENTS) > 100:
            del _WEBHOOK_EVENTS[:-100]
    except Exception as e:
        print(f"Error storing webhook payload (memory): {e}")
    # Best effort: local dev only (fails silently on Vercel read-only FS)
    try:
        data = []
        if os.path.exists(WEBHOOK_LOG_FILE):
            with open(WEBHOOK_LOG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        data.append({"received_at": datetime.now().isoformat(), "payload": payload})
        with open(WEBHOOK_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(data[-100:], f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# =============================================================================
# HTML TEMPLATES
# =============================================================================

BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Betelgeuse TI - Comment Moderator</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f0f2f5; 
            color: #1c1e21; 
            line-height: 1.5;
        }
        .header { 
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: white; 
            padding: 20px; 
            text-align: center;
            border-bottom: 3px solid #1877f2;
        }
        .header h1 { font-size: 24px; margin-bottom: 4px; }
        .header p { color: #b0b3b8; font-size: 14px; }

        .container { max-width: 900px; margin: 0 auto; padding: 20px; }

        .permission-badge {
            display: inline-block;
            background: #e3f2fd;
            color: #1565c0;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border: 1px solid #bbdefb;
            margin-bottom: 12px;
        }
        .permission-badge.red { background: #ffebee; color: #c62828; border-color: #ef9a9a; }
        .permission-badge.green { background: #e8f5e9; color: #2e7d32; border-color: #a5d6a7; }
        .permission-badge.orange { background: #fff3e0; color: #ef6c00; border-color: #ffcc80; }
        .permission-badge.purple { background: #f3e5f5; color: #7b1fa2; border-color: #ce93d8; }

        .review-tag {
            display: inline-block;
            background: #fff8e1;
            color: #f57f17;
            padding: 2px 10px;
            border-radius: 10px;
            font-size: 11px;
            font-weight: 700;
            border: 1px solid #ffe082;
            margin-left: 8px;
            vertical-align: middle;
        }

        .granted-check {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            color: #2e7d32;
            font-size: 12px;
            font-weight: 700;
            margin-left: 8px;
        }
        .not-granted {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            color: #c62828;
            font-size: 12px;
            font-weight: 700;
            margin-left: 8px;
        }

        .authorized-seal {
            display: flex;
            align-items: center;
            gap: 12px;
            background: #e8f5e9;
            border: 2px solid #2e7d32;
            border-radius: 12px;
            padding: 16px 20px;
        }
        .authorized-seal .seal-icon {
            width: 44px; height: 44px;
            border-radius: 50%;
            background: #2e7d32;
            color: white;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 22px;
            font-weight: 700;
            flex-shrink: 0;
        }
        .authorized-seal .seal-title { color: #2e7d32; font-weight: 700; font-size: 16px; }
        .authorized-seal .seal-desc { color: #4a4a4a; font-size: 13px; }

        .card {
            background: white;
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }
        .card-title {
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .card-desc { color: #65676b; font-size: 14px; margin-bottom: 16px; }

        .btn {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 12px 24px;
            border-radius: 8px;
            border: none;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
            transition: all 0.2s;
        }
        .btn-primary {
            background: #1877f2;
            color: white;
        }
        .btn-primary:hover { background: #166fe5; }
        .btn-danger {
            background: #ef4444;
            color: white;
            font-size: 13px;
            padding: 6px 14px;
        }
        .btn-danger:hover { background: #dc2626; }
        .btn-outline {
            background: white;
            color: #1877f2;
            border: 1px solid #1877f2;
            font-size: 13px;
            padding: 6px 14px;
        }
        .btn-outline:hover { background: #f0f7ff; }

        .alert {
            padding: 16px;
            border-radius: 8px;
            margin-bottom: 20px;
            font-size: 14px;
        }
        .alert-success { background: #e8f5e9; color: #2e7d32; border: 1px solid #a5d6a7; }
        .alert-info { background: #e3f2fd; color: #1565c0; border: 1px solid #bbdefb; }

        .step-indicator {
            display: flex;
            gap: 8px;
            margin-bottom: 24px;
            justify-content: center;
        }
        .step {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
            color: #65676b;
        }
        .step.active { color: #1877f2; font-weight: 600; }
        .step-number {
            width: 28px; height: 28px;
            border-radius: 50%;
            background: #e4e6eb;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
            font-weight: 700;
        }
        .step.active .step-number { background: #1877f2; color: white; }

        .post-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
            gap: 16px;
            margin-top: 16px;
        }
        .post-card {
            background: white;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            cursor: pointer;
            transition: transform 0.2s;
            border: 2px solid transparent;
        }
        .post-card:hover { transform: translateY(-2px); border-color: #1877f2; }
        .post-card img { width: 100%; height: 160px; object-fit: cover; }
        .post-card-body { padding: 12px; }
        .post-card-title { font-size: 14px; font-weight: 600; margin-bottom: 4px; }
        .post-card-meta { font-size: 12px; color: #65676b; }

        .comment-card {
            background: #f8f9fa;
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 12px;
            border-left: 4px solid #1877f2;
        }
        .comment-card.positive { border-left-color: #2e7d32; background: #e8f5e9; }
        .comment-card.neutral { border-left-color: #f9a825; background: #fff8e1; }
        .comment-card.negative { border-left-color: #c62828; background: #ffebee; }

        .comment-header {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 8px;
        }
        .comment-avatar {
            width: 36px; height: 36px;
            border-radius: 50%;
            background: #1877f2;
            color: white;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 14px;
        }
        .comment-author { font-weight: 600; font-size: 14px; }
        .comment-id { font-size: 11px; color: #65676b; }
        .comment-text { font-size: 14px; color: #1c1e21; margin-bottom: 8px; }
        .comment-meta {
            display: flex;
            gap: 16px;
            font-size: 12px;
            color: #65676b;
            align-items: center;
        }
        .comment-actions {
            display: flex;
            gap: 8px;
            margin-top: 10px;
        }
        .hidden-comment { opacity: 0.55; filter: grayscale(0.6); }
        .hidden-label { font-size: 12px; color: #c62828; font-weight: 700; }

        .sentiment-badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
        }
        .sentiment-positive { background: #2e7d32; color: white; }
        .sentiment-neutral { background: #f9a825; color: white; }
        .sentiment-negative { background: #c62828; color: white; }

        .stats-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
            margin-bottom: 20px;
        }
        .stat-box {
            background: white;
            border-radius: 12px;
            padding: 16px;
            text-align: center;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            border-top: 3px solid #1877f2;
        }
        .stat-box.positive { border-top-color: #2e7d32; }
        .stat-box.neutral { border-top-color: #f9a825; }
        .stat-box.negative { border-top-color: #c62828; }
        .stat-value { font-size: 28px; font-weight: 700; color: #1877f2; }
        .stat-value.positive { color: #2e7d32; }
        .stat-value.neutral { color: #f9a825; }
        .stat-value.negative { color: #c62828; }
        .stat-label { font-size: 12px; color: #65676b; text-transform: uppercase; }

        .footer {
            text-align: center;
            padding: 40px 20px;
            color: #65676b;
            font-size: 13px;
        }
        .footer a { color: #1877f2; text-decoration: none; margin: 0 8px; }

        .privacy-card {
            background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 16px;
        }
        .privacy-card h3 { font-size: 16px; margin-bottom: 8px; }
        .privacy-card ul { list-style: none; padding: 0; }
        .privacy-card li {
            padding: 6px 0;
            font-size: 14px;
            color: #4a4a4a;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .privacy-card li::before {
            content: "✓";
            color: #2e7d32;
            font-weight: bold;
        }

        select {
            width: 100%;
            padding: 12px;
            border-radius: 8px;
            border: 1px solid #ddd;
            font-size: 15px;
            background: white;
        }

        .back-btn {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            color: #1877f2;
            text-decoration: none;
            font-size: 14px;
            font-weight: 600;
            margin-bottom: 16px;
        }

        .filter-buttons {
            display: flex;
            gap: 8px;
            margin-bottom: 16px;
            flex-wrap: wrap;
        }
        .filter-btn {
            padding: 8px 16px;
            border-radius: 20px;
            border: 1px solid #ddd;
            background: white;
            cursor: pointer;
            font-size: 13px;
            font-weight: 600;
        }
        .filter-btn.active {
            background: #1877f2;
            color: white;
            border-color: #1877f2;
        }
        .filter-btn.positive.active { background: #2e7d32; border-color: #2e7d32; }
        .filter-btn.neutral.active { background: #f9a825; border-color: #f9a825; }
        .filter-btn.negative.active { background: #c62828; border-color: #c62828; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🌟 Betelgeuse TI</h1>
        <p>COMMENT MODERATION WITH SENTIMENT ANALYSIS</p>
    </div>
    <div class="container">
        {{ content | safe }}
    </div>
    <div class="footer">
        <p>© 2026 Betelgeuse IT Services - CNPJ 51.770.524/0001-87</p>
        <p style="margin-top: 8px;">
            <a href="/privacy">🔒 Privacy Policy</a>
            <a href="/terms">📋 Terms of Use</a>
            <a href="/delete">🗑️ Data Deletion</a>
            <a href="/data-use">📊 Data Use</a>
        </p>
    </div>
    <script>
        function hideComment(commentId) {
            const card = document.getElementById('comment-' + commentId);
            if (card) {
                card.classList.add('hidden-comment');
                const actions = card.querySelector('.comment-actions');
                if (actions) {
                    actions.innerHTML = '<span class="hidden-label">🚫 Hidden by moderator</span>';
                }
            }
        }
        function filterComments(sentiment) {
            const cards = document.querySelectorAll('.comment-card');
            cards.forEach(card => {
                if (sentiment === 'all' || card.dataset.sentiment === sentiment) {
                    card.style.display = 'block';
                } else {
                    card.style.display = 'none';
                }
            });
            document.querySelectorAll('.filter-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelector('.filter-btn[data-filter="' + sentiment + '"').classList.add('active');
        }
    </script>
</body>
</html>
"""

HOME_TEMPLATE = """
<div class="card" style="text-align: center; max-width: 600px; margin: 40px auto;">
    <div class="permission-badge">App Review Screencast</div>
    <h2 style="font-size: 22px; margin-bottom: 12px;">AI-Powered Comment Moderation</h2>
    <p style="color: #65676b; margin-bottom: 24px;">
        Monitor and analyze comments in real time with sentiment classification (Positive, Neutral, Negative).
        Real-time processing. No data storage.
    </p>

    <div style="text-align: left; margin-bottom: 24px;">
        <div class="privacy-card">
            <h3>🔐 Requested Permissions</h3>
            <div style="margin-top: 12px;">
                <div style="background: white; padding: 12px; border-radius: 8px; margin-bottom: 8px;">
                    <strong style="color: #1877f2;">pages_show_list</strong>
                    <p style="font-size: 13px; color: #65676b; margin-top: 4px;">Display the list of Facebook Pages you manage</p>
                </div>
                <div style="background: white; padding: 12px; border-radius: 8px; margin-bottom: 8px;">
                    <strong style="color: #1877f2;">pages_read_engagement</strong>
                    <p style="font-size: 13px; color: #65676b; margin-top: 4px;">Read posts and metrics to select which post to moderate</p>
                </div>
                <div style="background: white; padding: 12px; border-radius: 8px; margin-bottom: 8px;">
                    <strong style="color: #1877f2;">pages_read_user_content</strong>
                    <p style="font-size: 13px; color: #65676b; margin-top: 4px;">Read comments with author name, message and date for moderation</p>
                </div>
                <div style="background: white; padding: 12px; border-radius: 8px;">
                    <strong style="color: #1877f2;">pages_manage_metadata</strong><span class="review-tag">Under App Review</span>
                    <p style="font-size: 13px; color: #65676b; margin-top: 4px;">Subscribe the Page to real-time webhooks for instant comment notifications</p>
                </div>
            </div>
        </div>
    </div>

    <a href="/login" class="btn btn-primary" style="font-size: 16px;">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="white"><path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"/></svg>
        Log in with Facebook
    </a>

    <div class="privacy-card" style="margin-top: 24px; text-align: left;">
        <h3>🔒 Privacy Commitment</h3>
        <ul>
            <li>No data storage — real-time processing only</li>
            <li>Session cleared on logout</li>
            <li>Revoke access anytime in Facebook Settings</li>
            <li>Verified company — CNPJ 51.770.524/0001-87</li>
        </ul>
    </div>
</div>
"""

DASHBOARD_TEMPLATE = """
<div class="step-indicator">
    <div class="step active">
        <div class="step-number">1</div>
        <span>Choose Page</span>
    </div>
    <div class="step">
        <div class="step-number">2</div>
        <span>Choose Post</span>
    </div>
    <div class="step">
        <div class="step-number">3</div>
        <span>Moderate Comments</span>
    </div>
</div>

<div class="alert alert-success">
    ✅ <strong>Successfully authenticated.</strong> Select a Page to start moderating.
</div>

<div class="card">
    <div class="card-title">🔐 Permission Status</div>
    <p class="card-desc">Live status of each permission granted to this app (read from your Facebook account via <code>/me/permissions</code>).</p>
    {% for scope in required_scopes %}
    <div style="background: #f8f9fa; padding: 12px; border-radius: 8px; margin-bottom: 8px; display: flex; align-items: center; justify-content: space-between;">
        <div>
            <strong style="color: #1877f2;">{{ scope }}</strong>{% if scope == 'pages_manage_metadata' %}<span class="review-tag">Under App Review</span>{% endif %}
            <p style="font-size: 13px; color: #65676b; margin-top: 2px;">{{ permission_info[scope].desc }}</p>
        </div>
        {% if scope in granted_permissions %}
        <span class="granted-check">✓ Granted</span>
        {% else %}
        <span class="not-granted">⚠ Not granted</span>
        {% endif %}
    </div>
    {% endfor %}
</div>

<div class="card">
    <span class="permission-badge green">pages_show_list</span>
    <div class="card-title">📋 Choose your Page</div>
    <p class="card-desc">Select a Facebook Page to load posts for moderation.</p>

    <form action="/posts" method="get">
        <select name="page_id" required onchange="this.form.submit()">
            <option value="">-- Select a Page --</option>
            {% for page in pages %}
            <option value="{{ page.id }}">{{ page.name }}</option>
            {% endfor %}
        </select>
    </form>

    <p style="margin-top: 12px; font-size: 13px; color: #65676b;">
        {{ pages|length }} Page(s) found
    </p>
</div>

<div style="text-align: center;">
    <a href="/logout" class="btn btn-outline">↩️ Log out</a>
</div>
"""

POSTS_TEMPLATE = """
<a href="/" class="back-btn">← Back to Pages</a>

<div class="step-indicator">
    <div class="step">
        <div class="step-number">1</div>
        <span>Choose Page</span>
    </div>
    <div class="step active">
        <div class="step-number">2</div>
        <span>Choose Post</span>
    </div>
    <div class="step">
        <div class="step-number">3</div>
        <span>Moderate Comments</span>
    </div>
</div>

{% if webhook_status %}
<div class="alert {{ 'alert-success' if webhook_status == 'ativo' else 'alert-info' }}">
    {% if webhook_status == 'ativo' %}
    ✅ <strong>Webhooks active on this Page!</strong> New comments will arrive in real time.
    {% else %}
    ⚠️ <strong>Failed to enable webhooks:</strong> {{ webhook_status }}
    {% endif %}
</div>
{% endif %}

<div class="card">
    <span class="permission-badge purple">pages_manage_metadata</span><span class="review-tag">Under App Review</span>
    <div class="card-title">🔔 Real-Time Notifications (Webhooks)</div>
    {% if webhook_subscribed %}
    <div class="authorized-seal">
        <div class="seal-icon">✓</div>
        <div>
            <div class="seal-title">Authorized</div>
            <div class="seal-desc">
                This Page is subscribed to real-time comment notifications
                (<code>pages_manage_metadata</code> granted — subscribed to the <code>feed</code> field).
            </div>
        </div>
    </div>
    {% else %}
    <p class="card-desc">Subscribe to this Page's events to receive new comments in real time, without polling.</p>
    <a href="/subscribe_webhook?page_id={{ page_id }}" class="btn btn-primary">🔔 Enable Webhooks on this Page</a>
    {% endif %}
</div>

<div class="card">
    <span class="permission-badge orange">pages_read_engagement</span>
    <div class="card-title">📝 Choose a Post</div>
    <p class="card-desc">Select a post to view and moderate its comments with sentiment analysis.</p>

    <div class="post-grid">
        {% for post in posts %}
        <div class="post-card" onclick="window.location.href='/comments?post_id={{ post.id }}&page_id={{ page_id }}'">
            {% if post.picture %}
            <img src="{{ post.picture }}" alt="Post image">
            {% else %}
            <div style="height: 160px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); display: flex; align-items: center; justify-content: center; color: white; font-size: 14px;">📄 Text Post</div>
            {% endif %}
            <div class="post-card-body">
                <div class="post-card-title">{{ post.message[:60] }}{% if post.message|length > 60 %}...{% endif %}</div>
                <div class="post-card-meta">
                    📅 {{ post.created_time[:10] }} 
                    💬 {{ post.comments_count }} comments
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
</div>
"""

COMMENTS_TEMPLATE = """
<a href="/posts?page_id={{ page_id }}" class="back-btn">← Back to Posts</a>

<div class="step-indicator">
    <div class="step">
        <div class="step-number">1</div>
        <span>Choose Page</span>
    </div>
    <div class="step">
        <div class="step-number">2</div>
        <span>Choose Post</span>
    </div>
    <div class="step active">
        <div class="step-number">3</div>
        <span>Moderate Comments</span>
    </div>
</div>

<div class="card">
    <span class="permission-badge red">pages_read_user_content</span>
    <div class="card-title">💬 Moderate Comments with Sentiment Analysis</div>
    <p class="card-desc">Review comments in real time. Automatic classification: Positive, Neutral, Negative.</p>

    <p style="font-size: 13px; color: #65676b; margin-bottom: 16px;">
        💬 Showing the <strong>{{ comments|length }}</strong> most recent comments
        {% if truncated %}— this post has more; adjust the limit:{% else %}— adjust limit:{% endif %}
        <a href="/comments?post_id={{ post_id }}&page_id={{ page_id }}&max=100" style="color:#1877f2;">100</a> ·
        <a href="/comments?post_id={{ post_id }}&page_id={{ page_id }}&max=200" style="color:#1877f2;">200</a> ·
        <a href="/comments?post_id={{ post_id }}&page_id={{ page_id }}&max=500" style="color:#1877f2;">500</a>
    </p>

    {% if fb_error and comments|length == 0 %}
    <div class="alert" style="background: #ffebee; color: #c62828; border: 1px solid #ef9a9a;">
        ⚠️ <strong>The Graph API returned no comments.</strong> Technical detail: {{ fb_error }}
    </div>
    {% endif %}

    <div class="stats-grid">
        <div class="stat-box positive">
            <div class="stat-value positive">{{ sentiment_counts.positive|default(0) }}</div>
            <div class="stat-label">😊 Positive</div>
            <div style="font-size: 11px; color: #2e7d32;">{{ sentiment_pct.positive|default(0) }}%</div>
        </div>
        <div class="stat-box neutral">
            <div class="stat-value neutral">{{ sentiment_counts.neutral|default(0) }}</div>
            <div class="stat-label">😐 Neutral</div>
            <div style="font-size: 11px; color: #f9a825;">{{ sentiment_pct.neutral|default(0) }}%</div>
        </div>
        <div class="stat-box negative">
            <div class="stat-value negative">{{ sentiment_counts.negative|default(0) }}</div>
            <div class="stat-label">😠 Negative</div>
            <div style="font-size: 11px; color: #c62828;">{{ sentiment_pct.negative|default(0) }}%</div>
        </div>
        <div class="stat-box">
            <div class="stat-value">{{ comments|length }}</div>
            <div class="stat-label">💬 Total</div>
            <div style="font-size: 11px; color: #1877f2;">100%</div>
        </div>
    </div>

    <div class="filter-buttons">
        <button class="filter-btn active" data-filter="all" onclick="filterComments('all')">All ({{ comments|length }})</button>
        <button class="filter-btn positive" data-filter="positive" onclick="filterComments('positive')">😊 Positive ({{ sentiment_counts.positive|default(0) }})</button>
        <button class="filter-btn neutral" data-filter="neutral" onclick="filterComments('neutral')">😐 Neutral ({{ sentiment_counts.neutral|default(0) }})</button>
        <button class="filter-btn negative" data-filter="negative" onclick="filterComments('negative')">😠 Negative ({{ sentiment_counts.negative|default(0) }})</button>
    </div>

    {% for comment in comments %}
    {% set sentiment = comment.sentiment_en|default('neutral') %}
    <div class="comment-card {{ sentiment }}" id="comment-{{ comment.id }}" data-sentiment="{{ sentiment }}">
        <div class="comment-header">
            <div class="comment-avatar">{{ comment.from_name[0] if comment.from_name else '?' }}</div>
            <div>
                <div class="comment-author">{{ comment.from_name or 'Facebook User' }}</div>
                <div class="comment-id">ID: {{ comment.id }}</div>
            </div>
            <span class="sentiment-badge sentiment-{{ sentiment }}">{{ comment.sentiment_display|default('NEUTRAL') }}</span>
        </div>
        <div class="comment-text">{{ comment.message }}</div>
        <div class="comment-meta">
            <span>📅 {{ comment.created_time[:10] }}</span>
            <span>❤️ {{ comment.like_count }} likes</span>
            <span>⏰ {{ comment.created_time }}</span>
        </div>
        <div class="comment-actions">
            <button class="btn btn-danger" onclick="hideComment('{{ comment.id }}')">
                🚫 Hide Comment
            </button>
            <a href="{{ comment.fb_url }}" 
               target="_blank" 
               class="btn btn-outline">
                🔗 View on Facebook
            </a>
        </div>
    </div>
    {% endfor %}
</div>
"""

PRIVACY_TEMPLATE = """
<div class="card">
    <h1 style="color: #1877f2; margin-bottom: 8px;">Privacy Policy</h1>
    <p style="color: #65676b; font-size: 13px; margin-bottom: 24px;">Updated: July 27, 2026</p>

    <p style="margin-bottom: 16px;"><strong>Betelgeuse IT Services</strong> — CNPJ 51.770.524/0001-87</p>

    <h3 style="margin: 20px 0 8px;">1. Information We Process</h3>
    <p style="margin-bottom: 12px;">Our application processes the following data <strong>only in real time</strong>:</p>
    <ul style="margin-left: 20px; line-height: 2;">
        <li>Names and IDs of Facebook Pages you administer (via <code>pages_show_list</code>)</li>
        <li>Post content, IDs, and creation dates (via <code>pages_read_engagement</code>)</li>
        <li>Author names, author IDs, comment text, creation dates, and like counts (via <code>pages_read_user_content</code>)</li>
        <li>Page webhook subscription status (via <code>pages_manage_metadata</code>)</li>
    </ul>

    <h3 style="margin: 20px 0 8px;">2. No Data Storage</h3>
    <p><strong>We do not store, persist, or retain any user data on our servers.</strong> All data is obtained directly from the Facebook Graph API and displayed in your browser session.</p>

    <h3 style="margin: 20px 0 8px;">3. Data Retention</h3>
    <p>Data is retained only for the duration of your active session (typically less than 30 minutes).</p>

    <h3 style="margin: 20px 0 8px;">4. Data Sharing</h3>
    <p>We do not share, sell, rent, or transfer user data to third parties. We do not use comment data to train AI models.</p>

    <h3 style="margin: 20px 0 8px;">5. Your Rights</h3>
    <ul style="margin-left: 20px; line-height: 2;">
        <li>Revoke app permissions anytime via <a href="https://www.facebook.com/settings?tab=applications" target="_blank">Facebook Settings → Apps</a></li>
        <li>Request deletion of any cached session data via our <a href="/delete">Data Deletion</a> page</li>
        <li>Contact us at <a href="mailto:falecom@mariomello.com.br">falecom@mariomello.com.br</a></li>
    </ul>

    <h3 style="margin: 20px 0 8px;">6. Contact</h3>
    <p>Betelgeuse IT Services<br>CNPJ: 51.770.524/0001-87<br>Email: <a href="mailto:falecom@mariomello.com.br">falecom@mariomello.com.br</a><br>Address: Navegantes, SC, Brazil</p>
</div>
"""

TERMS_TEMPLATE = """
<div class="card">
    <h1 style="color: #1877f2; margin-bottom: 8px;">Terms of Use</h1>
    <p style="color: #65676b; font-size: 13px; margin-bottom: 24px;">Effective: May 30, 2026</p>

    <p style="margin-bottom: 16px;"><strong>Betelgeuse IT Services</strong> — CNPJ 51.770.524/0001-87</p>

    <h3 style="margin: 20px 0 8px;">1. Service Description</h3>
    <p>The Betelgeuse TI Comment Moderator is a real-time tool that allows Facebook Page administrators to view and monitor public comments on posts they manage.</p>

    <h3 style="margin: 20px 0 8px;">2. Eligibility</h3>
    <p>You must be at least 18 years old and an administrator of the Facebook Page you wish to monitor.</p>

    <h3 style="margin: 20px 0 8px;">3. Permitted Use</h3>
    <p>You agree to use this service exclusively for:</p>
    <ul style="margin-left: 20px; line-height: 2;">
        <li>Monitoring and moderating comments on Facebook Pages you administer</li>
        <li>Improving customer service response times</li>
    </ul>
    <p style="margin-top: 12px;">You may <strong>NOT</strong> use this service for:</p>
    <ul style="margin-left: 20px; line-height: 2;">
        <li>Accessing Pages you do not administer</li>
        <li>Scraping or bulk downloading user data</li>
        <li>Using comment data to train AI/ML models</li>
        <li>Sharing user content with unauthorized third parties</li>
    </ul>

    <h3 style="margin: 20px 0 8px;">4. Data Processing</h3>
    <p>All data processing occurs <strong>in real time</strong>. We do not store Facebook user data on our servers.</p>

    <h3 style="margin: 20px 0 8px;">5. Termination</h3>
    <p>We may suspend access for violations of these terms or Facebook Platform Policies. You may terminate use anytime by disconnecting the app in Facebook Settings.</p>

    <h3 style="margin: 20px 0 8px;">6. Applicable Law</h3>
    <p>These terms are governed by the laws of Brazil. Disputes will be resolved in the courts of Navegantes, SC.</p>

    <h3 style="margin: 20px 0 8px;">7. Contact</h3>
    <p>Email: <a href="mailto:falecom@mariomello.com.br">falecom@mariomello.com.br</a></p>
</div>
"""

DELETE_TEMPLATE = """
<div class="card">
    <h1 style="color: #1877f2; margin-bottom: 8px;">Data Deletion Request</h1>
    <span style="display: inline-block; background: #ffebee; color: #c62828; padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: 600; margin-bottom: 16px;">LGPD / GDPR Compliant</span>

    <p style="margin-bottom: 16px;"><strong>Betelgeuse IT Services</strong> — CNPJ 51.770.524/0001-87</p>

    <div class="alert alert-success" style="margin-bottom: 20px;">
        <strong>Good news:</strong> Our application does not store any personal data on our servers. All Facebook data is processed in real time and exists only during your active browser session.
    </div>

    <h3 style="margin: 20px 0 8px;">Immediate Steps (Instant)</h3>
    <ol style="margin-left: 20px; line-height: 2;">
        <li><strong>Revoke App Access:</strong> Go to <a href="https://www.facebook.com/settings?tab=applications" target="_blank">Facebook Settings → Apps and Websites</a>, find "Betelgeuse TI Comment Moderator" and click "Remove".</li>
        <li><strong>Clear Session:</strong> Click <a href="/logout" class="btn btn-primary" style="font-size: 12px; padding: 4px 12px;">Log Out</a> to clear your current session.</li>
    </ol>

    <h3 style="margin: 20px 0 8px;">Contact for Confirmation</h3>
    <p>If you would like written confirmation that no data is retained, please contact us:</p>
    <ul style="margin-left: 20px; line-height: 2;">
        <li>Email: <a href="mailto:falecom@mariomello.com.br">falecom@mariomello.com.br</a></li>
        <li>Subject: Data Deletion Request - [Your Facebook ID or Email]</li>
        <li>Response time: Up to 48 hours (business days)</li>
    </ul>

    <h3 style="margin: 20px 0 8px;">Legal Rights</h3>
    <p>Under Brazilian LGPD and European GDPR, you have the right to be forgotten. As we do not store personal data, compliance is immediate upon app removal.</p>
</div>
"""

DATA_USE_TEMPLATE = """
<div class="card">
    <h1 style="color: #1877f2; margin-bottom: 8px;">Data Use Agreement</h1>
    <span style="display: inline-block; background: #e8f5e9; color: #2e7d32; padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: 600; margin-bottom: 16px;">Meta Platform Supplemental Terms</span>

    <p style="margin-bottom: 16px;"><strong>Betelgeuse IT Services</strong> — CNPJ 51.770.524/0001-87</p>

    <h3 style="margin: 20px 0 8px;">1. Purpose of Data Use</h3>
    <p>We use Facebook Platform data exclusively for <strong>real-time comment moderation on Facebook Pages administered by the authenticated user</strong>.</p>

    <h3 style="margin: 20px 0 8px;">2. Data We Access</h3>
    <table style="width: 100%; border-collapse: collapse; margin: 16px 0;">
        <thead>
            <tr style="background: #f0f2f5;">
                <th style="padding: 12px; text-align: left; border: 1px solid #ddd; font-size: 13px;">Permission</th>
                <th style="padding: 12px; text-align: left; border: 1px solid #ddd; font-size: 13px;">Data Accessed</th>
                <th style="padding: 12px; text-align: left; border: 1px solid #ddd; font-size: 13px;">Use</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td style="padding: 12px; border: 1px solid #ddd; font-size: 13px;"><code>pages_show_list</code></td>
                <td style="padding: 12px; border: 1px solid #ddd; font-size: 13px;">Page name, ID, and category</td>
                <td style="padding: 12px; border: 1px solid #ddd; font-size: 13px;">Display list of Pages the user manages</td>
            </tr>
            <tr style="background: #f8f9fa;">
                <td style="padding: 12px; border: 1px solid #ddd; font-size: 13px;"><code>pages_read_engagement</code></td>
                <td style="padding: 12px; border: 1px solid #ddd; font-size: 13px;">Post ID, message, created_time, permalink</td>
                <td style="padding: 12px; border: 1px solid #ddd; font-size: 13px;">List posts for the user to select</td>
            </tr>
            <tr>
                <td style="padding: 12px; border: 1px solid #ddd; font-size: 13px;"><code>pages_read_user_content</code></td>
                <td style="padding: 12px; border: 1px solid #ddd; font-size: 13px;">Author name, author ID, message, created_time, like_count</td>
                <td style="padding: 12px; border: 1px solid #ddd; font-size: 13px;">Display comments for moderation</td>
            </tr>
            <tr style="background: #f8f9fa;">
                <td style="padding: 12px; border: 1px solid #ddd; font-size: 13px;"><code>pages_manage_metadata</code></td>
                <td style="padding: 12px; border: 1px solid #ddd; font-size: 13px;">Webhook subscription status (subscribed_apps edge)</td>
                <td style="padding: 12px; border: 1px solid #ddd; font-size: 13px;">Subscribe the Page to real-time comment notifications</td>
            </tr>
        </tbody>
    </table>

    <h3 style="margin: 20px 0 8px;">3. Prohibited Uses</h3>
    <p>We expressly commit to <strong>NOT</strong>:</p>
    <ul style="margin-left: 20px; line-height: 2;">
        <li>Store Facebook user data beyond the active session</li>
        <li>Use data for advertising or marketing purposes</li>
        <li>Sell, rent, or transfer data to third parties</li>
        <li>Use comment content to train AI or ML models</li>
        <li>Access Pages not administered by the authenticated user</li>
    </ul>

    <h3 style="margin: 20px 0 8px;">4. Compliance</h3>
    <p>We comply with Meta Platform Terms, Meta Data Processing Terms, Brazilian LGPD, and European GDPR.</p>

    <h3 style="margin: 20px 0 8px;">5. Contact</h3>
    <p>Email: <a href="mailto:falecom@mariomello.com.br">falecom@mariomello.com.br</a></p>
</div>
"""

# =============================================================================
# FLASK ROUTES
# =============================================================================

@app.route("/")
def home():
    if "access_token" in session:
        return redirect("/dashboard")
    return render_template_string(BASE_TEMPLATE, content=HOME_TEMPLATE)

@app.route("/login")
def login():
    scopes = ",".join(REQUIRED_SCOPES)
    auth_url = (
        f"https://www.facebook.com/{FB_API_VERSION}/dialog/oauth"
        f"?client_id={FB_APP_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope={scopes}"
        f"&response_type=code"
    )
    return redirect(auth_url)

@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "Error: No code provided", 400

    token_url = f"{FB_BASE_URL}/oauth/access_token"
    params = {
        "client_id": FB_APP_ID,
        "client_secret": FB_APP_SECRET,
        "redirect_uri": REDIRECT_URI,
        "code": code
    }

    try:
        resp = requests.get(token_url, params=params, timeout=30)
        data = resp.json()

        if "access_token" not in data:
            return f"Error: {data}", 400

        session["access_token"] = data["access_token"]
        return redirect("/dashboard")

    except Exception as e:
        return f"Error during authentication: {str(e)}", 500

@app.route("/dashboard")
def dashboard():
    if "access_token" not in session:
        return redirect("/")

    try:
        resp = requests.get(
            f"{FB_BASE_URL}/me/accounts",
            params={"access_token": session["access_token"]},
            timeout=30
        )
        data = resp.json()
        pages = data.get("data", [])

        # Live permission status for the dashboard checklist
        granted = get_granted_permissions()

        return render_template_string(
            BASE_TEMPLATE,
            content=render_template_string(
                DASHBOARD_TEMPLATE,
                pages=pages,
                required_scopes=REQUIRED_SCOPES,
                permission_info=PERMISSION_INFO,
                granted_permissions=granted
            )
        )
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route("/posts")
def posts():
    if "access_token" not in session:
        return redirect("/")

    page_id = request.args.get("page_id")
    if not page_id:
        return redirect("/dashboard")

    session["current_page_id"] = page_id

    try:
        data = fb_get(
            f"{page_id}/posts",
            {"fields": "id,message,created_time,full_picture,comments.summary(true)", "limit": 25},
            page_id=page_id
        )

        if "error" in data:
            return f"Error from Facebook: {data['error']}", 400

        posts_data = data.get("data", [])

        posts = []
        for post in posts_data:
            posts.append({
                "id": post["id"],
                "message": post.get("message", "(Media Post)"),
                "created_time": post.get("created_time", ""),
                "picture": post.get("full_picture") or post.get("picture", ""),
                "comments_count": post.get("comments", {}).get("summary", {}).get("total_count", 0)
            })

        # Check whether this Page is already subscribed to webhooks (Authorized seal)
        webhook_subscribed = is_page_subscribed(page_id)

        return render_template_string(
            BASE_TEMPLATE,
            content=render_template_string(
                POSTS_TEMPLATE,
                posts=posts,
                page_id=page_id,
                webhook_status=request.args.get("webhook", ""),
                webhook_subscribed=webhook_subscribed
            )
        )

    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route("/comments")
def comments():
    if "access_token" not in session:
        return redirect("/")

    post_id = request.args.get("post_id")
    page_id = request.args.get("page_id") or session.get("current_page_id")

    if not post_id:
        return redirect("/dashboard")

    try:
        try:
            max_items = int(request.args.get("max", 200))
            max_items = max(25, min(max_items, 500))
        except ValueError:
            max_items = 200

        # Real pagination: fetch up to max_items comments
        # (filter=stream = proven combination in production with the page token)
        comments_data, fb_error = fb_get_paginated(
            f"{post_id}/comments",
            {"fields": "id,from,message,created_time,like_count,permalink_url",
             "filter": "stream", "limit": 100},
            page_id=page_id,
            max_items=max_items
        )
        truncated = len(comments_data) >= max_items

        # Sentiment in a parallel PRE-PASS (5 threads) with in-memory cache
        cache = load_sentiment_cache()
        sentiments = {}
        pending = []
        for c in comments_data:
            cached = cache.get(c["id"])
            if cached:
                sentiments[c["id"]] = cached["sentiment"]
            else:
                pending.append(c)
        if pending:
            results = analyze_many([c.get("message", "") for c in pending])
            for c, s in zip(pending, results):
                sentiments[c["id"]] = s
                cache[c["id"]] = {"sentiment": s, "text": c.get("message", "")[:100],
                                  "analyzed_at": datetime.now().isoformat()}

        comments = []
        total_likes = 0
        sentiment_counts = {"positive": 0, "neutral": 0, "negative": 0}

        for c in comments_data:
            from_data = c.get("from", {})
            fb_url = c.get("permalink_url")

            if not fb_url:
                comment_full_id = c["id"]
                parts = comment_full_id.split("_")
                if len(parts) >= 2:
                    fb_url = f"https://www.facebook.com/{parts[0]}?comment_id={parts[1]}"
                else:
                    fb_url = f"https://www.facebook.com/{comment_full_id}"

            if isinstance(fb_url, str):
                fb_url = fb_url.replace("https://www.facebook.com/https://www.facebook.com/", "https://www.facebook.com/")

            # Sentiment already computed in the parallel pre-pass
            sentiment = sentiments.get(c["id"], "NEUTRO")
            sentiment_en = SENTIMENT_EN.get(sentiment, "neutral")
            sentiment_counts[sentiment_en] += 1

            comments.append({
                "id": c["id"],
                "from_name": from_data.get("name", "Facebook User"),
                "message": c.get("message", ""),
                "created_time": c.get("created_time", ""),
                "like_count": c.get("like_count", 0),
                "fb_url": fb_url,
                "sentiment": sentiment,
                "sentiment_en": sentiment_en,
                "sentiment_display": SENTIMENT_DISPLAY.get(sentiment, "NEUTRAL")
            })
            total_likes += c.get("like_count", 0)

        # Calculate percentages
        total = len(comments)
        sentiment_pct = {
            "positive": round((sentiment_counts["positive"] / total * 100), 1) if total > 0 else 0,
            "neutral": round((sentiment_counts["neutral"] / total * 100), 1) if total > 0 else 0,
            "negative": round((sentiment_counts["negative"] / total * 100), 1) if total > 0 else 0
        }

        return render_template_string(
            BASE_TEMPLATE,
            content=render_template_string(
                COMMENTS_TEMPLATE,
                comments=comments,
                page_id=page_id,
                post_id=post_id,
                truncated=truncated,
                max_items=max_items,
                fb_error=fb_error,
                total_likes=total_likes,
                sentiment_counts=sentiment_counts,
                sentiment_pct=sentiment_pct
            )
        )

    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/test_gemini")
def test_gemini():
    """Temporary diagnostic: makes 1 Gemini call and shows the RAW response.
    Usage: /test_gemini?key=YOUR_POLL_API_KEY"""
    if request.args.get("key") != POLL_API_KEY:
        return jsonify({"error": "Not authorized"}), 401
    if not GOOGLE_API_KEY:
        return jsonify({"ok": False, "error": "GOOGLE_API_KEY is EMPTY in Vercel env vars"})
    try:
        url = f"{GEMINI_URL}?key={GOOGLE_API_KEY}"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": "Responda uma palavra: POSITIVO, NEUTRO ou NEGATIVO. Comentario: Muito top"}]}],
            "generationConfig": {"temperature": 0}
        }
        resp = requests.post(url, json=payload, timeout=30)
        return jsonify({
            "model_used": GEMINI_MODEL,
            "http_status": resp.status_code,
            "raw_response": resp.json()
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

# =============================================================================
# LEGAL PAGES
# =============================================================================

@app.route("/privacy")
def privacy():
    return render_template_string(BASE_TEMPLATE, content=PRIVACY_TEMPLATE)

@app.route("/terms")
def terms():
    return render_template_string(BASE_TEMPLATE, content=TERMS_TEMPLATE)

@app.route("/delete")
def delete():
    return render_template_string(BASE_TEMPLATE, content=DELETE_TEMPLATE)

@app.route("/data-use")
def data_use():
    return render_template_string(BASE_TEMPLATE, content=DATA_USE_TEMPLATE)

# =============================================================================
# WEBHOOK ROUTES
# =============================================================================

@app.route("/subscribe_webhook")
def subscribe_webhook():
    """Subscribes the selected page to the app's webhooks ('feed' field).
    Uses pages_manage_metadata — this is the action demonstrated in the App Review screencast."""
    if "access_token" not in session and not PAGE_ACCESS_TOKEN_ENV:
        return redirect("/")

    page_id = request.args.get("page_id") or session.get("current_page_id")
    if not page_id:
        return redirect("/dashboard")

    # 1) Already subscribed?
    status = fb_get(f"{page_id}/subscribed_apps", {}, page_id=page_id)
    for app_entry in status.get("data", []):
        if str(app_entry.get("id")) == str(FB_APP_ID):
            print(f"Page {page_id} was already subscribed to webhooks.")
            return redirect(f"/posts?page_id={page_id}&webhook=ativo")

    # 2) Subscribe to the 'feed' field (posts, comments, reactions)
    ok, err = fb_post(f"{page_id}/subscribed_apps", {"subscribed_fields": "feed"}, page_id=page_id)
    if ok:
        print(f"Page {page_id} subscribed to webhooks (feed) successfully!")
        return redirect(f"/posts?page_id={page_id}&webhook=ativo")
    return redirect(f"/posts?page_id={page_id}&webhook=erro:{err}")

@app.route("/webhook", methods=["GET"])
def webhook_verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == WEBHOOK_VERIFY_TOKEN:
        print(f"Webhook verified successfully. Challenge: {challenge}")
        return challenge, 200
    else:
        print(f"Verification failed. mode={mode}, token={token}")
        return "Verification failed", 403

@app.route("/webhook", methods=["POST"])
def webhook_receive():
    signature = request.headers.get("X-Hub-Signature-256", "")
    payload_body = request.get_data()

    if not verify_signature(payload_body, signature):
        print("Invalid signature!")
        return "Invalid signature", 403

    try:
        payload = request.get_json()
        print(f"Webhook received: {json.dumps(payload, indent=2)}")

        save_webhook_payload(payload)

        return "OK", 200

    except Exception as e:
        print(f"Error processing webhook: {e}")
        return "Error", 500

@app.route("/webhook/logs")
def webhook_logs():
    # In-memory events first (works on Vercel), then file fallback (local dev)
    if _WEBHOOK_EVENTS:
        return jsonify(_WEBHOOK_EVENTS)
    try:
        if os.path.exists(WEBHOOK_LOG_FILE):
            with open(WEBHOOK_LOG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return jsonify(data)
        return jsonify([])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# =============================================================================
# POLLING + SENTIMENT + n8n ROUTE
# =============================================================================

@app.route("/poll_comments")
def poll_comments():
    """
    Polling endpoint for local n8n to query Vercel.
    Auth: ?key=POLL_API_KEY  or  logged-in browser session.
    Returns: all posts in the period + comments + sentiments (detailed per post).
    """
    key = request.args.get("key", "")
    if POLL_API_KEY and key == POLL_API_KEY:
        pass  # authorized access via n8n
    elif "access_token" not in session:
        return jsonify({"error": "Not authenticated. Use ?key=POLL_API_KEY or log in."}), 401

    page_id = request.args.get("page_id") or session.get("current_page_id")
    if not page_id:
        return jsonify({"error": "No page selected"}), 400

    try:
        limit = int(request.args.get("limit", 10))
        limit = max(1, min(limit, 25))  # between 1 and 25 posts
    except ValueError:
        limit = 10

    # --- Load control (avoids Vercel timeout) ---
    # comments_limit = comments per post (default 100; use 25 for fast calls)
    try:
        comments_limit = int(request.args.get("comments_limit", 100))
        comments_limit = max(1, min(comments_limit, 100))
    except ValueError:
        comments_limit = 100
    # analyze=0 -> skips Gemini entirely (response in seconds; sentiment comes as None)
    analyze = request.args.get("analyze", "1") != "0"
    # max_analyze = cap on new analyses per call (the rest waits for the next one)
    try:
        max_analyze = int(request.args.get("max_analyze", 120))
        max_analyze = max(0, min(max_analyze, 300))
    except ValueError:
        max_analyze = 120

    try:
        # Fetch the latest N posts from the page (regardless of creation date)
        data = fb_get(
            f"{page_id}/posts",
            {"fields": "id,message,created_time", "limit": limit},
            page_id=page_id
        )

        if "error" in data:
            return jsonify({"error": data["error"]}), 400

        posts = data.get("data", [])

        all_comments = []
        posts_detail = []
        cache = load_sentiment_cache()
        pending = []

        # 1) Collect all comments from all posts
        for post in posts:
            post_id = post["id"]
            post_title = (post.get("message") or "(Media Post)")[:80]
            post_comments = []

            # Get comments (per-post limit via parameter)
            data = fb_get(
                f"{post_id}/comments",
                {"fields": "id,from,message,created_time,like_count", "limit": comments_limit, "order": "reverse_chronological"},
                page_id=page_id
            )
            comments = data.get("data", [])

            for c in comments:
                comment_id = c["id"]
                cached = cache.get(comment_id)

                comment_data = {
                    "id": comment_id,
                    "post_id": post_id,
                    "post_titulo": post_title,
                    "author": c.get("from", {}).get("name", "Facebook User"),
                    "message": c.get("message", ""),
                    "sentiment": cached["sentiment"] if cached else None,
                    "likes": c.get("like_count", 0),
                    "created_time": c.get("created_time", "")
                }

                if not cached:
                    pending.append(comment_data)

                all_comments.append(comment_data)
                post_comments.append(comment_data)

            posts_detail.append({
                "post_id": post_id,
                "titulo": post_title,
                "created_time": post.get("created_time", ""),
                "comentarios": post_comments
            })

        # 2) Analyze new comments in PARALLEL (up to 5 simultaneous Gemini calls)
        #    Respecting analyze=0 (fast mode) and the max_analyze cap (anti-timeout)
        total_new = 0
        if pending and analyze:
            to_analyze = pending[:max_analyze]
            for c in pending[max_analyze:]:
                c["sentiment"] = None  # left for the next call
            new_sentiments = analyze_many([c["message"] for c in to_analyze])
            for comment_data, sentiment in zip(to_analyze, new_sentiments):
                comment_data["sentiment"] = sentiment
                cache[comment_data["id"]] = {
                    "sentiment": sentiment,
                    "text": comment_data["message"][:100],
                    "analyzed_at": datetime.now().isoformat()
                }
            save_sentiment_cache(cache)
            total_new = len(to_analyze)

        # 3) Per-post counters
        for p in posts_detail:
            counts = {"POSITIVO": 0, "NEUTRO": 0, "NEGATIVO": 0}
            for c in p["comentarios"]:
                if c["sentiment"] in counts:
                    counts[c["sentiment"]] += 1
            p["sentimentos"] = counts
            p["total_comentarios"] = len(p["comentarios"])

        # Calculate summary
        sentiment_counts = {"POSITIVO": 0, "NEUTRO": 0, "NEGATIVO": 0}
        for c in all_comments:
            if c["sentiment"] in sentiment_counts:
                sentiment_counts[c["sentiment"]] += 1

        total = len(all_comments)
        total_analisados = sum(sentiment_counts.values())
        summary = {
            "tipo": "resumo_comentarios",
            "pagina": page_id,
            "gerado_em": datetime.now().isoformat(),
            "limite_posts": limit,
            "total_posts": len(posts),
            "total_comentarios": total,
            "total_analisados": total_analisados,
            "novos_analisados": total_new,
            "sentimentos": sentiment_counts,
            "percentuais": {
                "positivo": round(sentiment_counts["POSITIVO"] / total_analisados * 100, 1) if total_analisados > 0 else 0,
                "neutro": round(sentiment_counts["NEUTRO"] / total_analisados * 100, 1) if total_analisados > 0 else 0,
                "negativo": round(sentiment_counts["NEGATIVO"] / total_analisados * 100, 1) if total_analisados > 0 else 0
            },
            "posts": posts_detail,
            "comentarios": all_comments,
            "alertas": [c for c in all_comments if c["sentiment"] == "NEGATIVO"][:5],
            "resumo_executivo": f"{total} comentários em {len(posts)} posts ({total_analisados} analisados). {sentiment_counts['POSITIVO']} positivos, {sentiment_counts['NEUTRO']} neutros, {sentiment_counts['NEGATIVO']} negativos."
        }

        # Optional: push directly to n8n (only works if n8n is publicly reachable)
        if total_new > 0 and N8N_WEBHOOK_URL:
            send_to_n8n(summary)

        return jsonify(summary)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
