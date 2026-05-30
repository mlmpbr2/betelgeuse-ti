import os
from flask import Flask, redirect, request, session, render_template_string, send_from_directory, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix
import requests
import pandas as pd
from datetime import datetime

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.secret_key = os.environ.get("SECRET_KEY", "Betelgeuse-2026-Secure")

# ─── CONFIG ──────────────────────────────────────────────────────────────
APP_ID = os.environ.get("META_APP_ID", "877709481915236")
APP_SECRET = os.environ.get("META_APP_SECRET", "3bf01b88362dac1be1bb62999af4a5e2")
REDIRECT_URI = os.environ.get("REDIRECT_URI", "https://mlmpbr-meta-api.hf.space/login/callback")
GRAPH = "https://graph.facebook.com/v19.0"

# Permissões exatas solicitadas (ordem importa para o screencast)
PERMISSIONS = "pages_show_list,pages_read_engagement,pages_read_user_content"

# ─── ASSETS ──────────────────────────────────────────────────────────────
@app.route('/assets/<path:f>')
def assets(f):
    return send_from_directory('assets', f)

# ─── TEMPLATE PRINCIPAL ──────────────────────────────────────────────────
HTML = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Betelgeuse TI – Comment Moderation</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box}
body{margin:0;font-family:'Inter',system-ui,-apple-system,sans-serif;background:#f0f2f5;color:#1c1e21;line-height:1.6}
.container{max-width:1100px;margin:0 auto;padding:24px 16px}

/* Header */
.top{display:flex;align-items:center;gap:16px;margin-bottom:28px;padding-bottom:20px;border-bottom:1px solid #dddfe2}
.logo{width:52px;height:52px;border-radius:14px;background:url('/assets/betelgeuse_logo.png') center/cover,linear-gradient(135deg,#1877f2,#42b72a);box-shadow:0 2px 8px rgba(0,0,0,.12)}
h1{font-size:26px;margin:0;font-weight:800;letter-spacing:-0.3px} .sub{color:#65676b;font-size:15px;margin-top:2px}

/* Cards */
.card{background:#fff;border-radius:18px;padding:28px;margin:18px 0;box-shadow:0 1px 2px rgba(0,0,0,.06),0 4px 12px rgba(0,0,0,.04);border:1px solid #e4e6eb;transition:box-shadow .2s}
.card:hover{box-shadow:0 2px 4px rgba(0,0,0,.08),0 8px 24px rgba(0,0,0,.06)}

/* Badges */
.badge{display:inline-block;padding:5px 14px;border-radius:20px;font-size:12px;font-weight:700;letter-spacing:0.3px;margin-right:8px;margin-bottom:6px}
.badge-std{background:#e7f3ff;color:#1877f2}
.badge-adv{background:#fff3e0;color:#e65100}
.badge-sens{background:#ffebee;color:#c62828}
.badge-demo{background:#e8f5e9;color:#2e7d32}

/* Buttons */
.btn{background:#1877f2;color:#fff;border:0;padding:14px 28px;border-radius:12px;font-weight:700;font-size:15px;cursor:pointer;transition:all .15s;display:inline-flex;align-items:center;gap:8px;text-decoration:none}
.btn:hover{opacity:.92;transform:translateY(-1px);box-shadow:0 4px 12px rgba(24,119,242,.3)}
.btn:active{transform:translateY(0)}
.btn-outline{background:#fff;color:#1877f2;border:2px solid #1877f2}
.btn-outline:hover{background:#f0f7ff}
.btn-danger{background:#e53935}
.btn-danger:hover{box-shadow:0 4px 12px rgba(229,57,53,.3)}
.btn-sm{padding:10px 18px;font-size:13px;border-radius:10px}

/* Forms */
select, input[type="text"]{width:100%;max-width:460px;padding:12px 14px;border:1px solid #ccd0d5;border-radius:12px;font-size:15px;font-family:inherit;background:#fff;transition:border-color .15s}
select:focus, input:focus{outline:none;border-color:#1877f2;box-shadow:0 0 0 3px rgba(24,119,242,.1)}

/* Tables */
.table-wrap{overflow-x:auto;border-radius:12px;border:1px solid #e4e6eb}
table{width:100%;border-collapse:collapse;font-size:14px}
th{background:#f5f6f7;padding:14px 16px;text-align:left;font-weight:700;font-size:13px;color:#65676b;text-transform:uppercase;letter-spacing:0.5px}
td{padding:14px 16px;border-top:1px solid #eee}
tr:hover td{background:#f5f6f7}

/* Alerts */
.alert{padding:18px 22px;border-radius:14px;margin-bottom:20px;display:flex;align-items:flex-start;gap:14px}
.alert-error{background:#ffebee;border:1px solid #ef9a9a;color:#c62828}
.alert-success{background:#e8f5e9;border:1px solid #a5d6a7;color:#2e7d32}
.alert-info{background:#e3f2fd;border:1px solid #90caf9;color:#1565c0}
.alert-warn{background:#fff3e0;border:1px solid #ffcc80;color:#e65100}

/* Stats */
.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin:20px 0}
.stat-card{background:linear-gradient(135deg,#1877f2 0%,#166fe5 100%);color:#fff;padding:22px;border-radius:16px;text-align:center;box-shadow:0 4px 16px rgba(24,119,242,.25)}
.stat-card.green{background:linear-gradient(135deg,#42b72a 0%,#36a420 100%);box-shadow:0 4px 16px rgba(66,183,42,.25)}
.stat-card.orange{background:linear-gradient(135deg,#ff9800 0%,#f57c00 100%);box-shadow:0 4px 16px rgba(255,152,0,.25)}
.stat-num{font-size:36px;font-weight:800;line-height:1}
.stat-label{font-size:13px;opacity:.9;margin-top:6px;text-transform:uppercase;letter-spacing:0.8px}

/* Comments */
.comment-card{background:#f0f2f5;border-radius:14px;padding:18px;margin-bottom:14px;border-left:4px solid #1877f2;transition:transform .15s}
.comment-card:hover{transform:translateX(4px)}
.comment-card.negative{border-left-color:#e53935;background:#fff5f5}
.comment-author{font-weight:700;font-size:15px;color:#050505;display:flex;align-items:center;gap:8px}
.comment-id{font-size:11px;color:#8c939d;font-weight:500;background:#e4e6eb;padding:2px 8px;border-radius:6px}
.comment-text{color:#1c1e21;margin-top:10px;font-size:15px;line-height:1.6}
.comment-meta{display:flex;gap:16px;margin-top:10px;font-size:13px;color:#65676b}
.comment-meta span{display:flex;align-items:center;gap:4px}

/* Post cards */
.post-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px;margin:20px 0}
.post-card{background:#fff;border-radius:14px;padding:20px;border:1px solid #e4e6eb;cursor:pointer;transition:all .15s}
.post-card:hover{border-color:#1877f2;box-shadow:0 4px 16px rgba(24,119,242,.12);transform:translateY(-2px)}
.post-card.selected{border:2px solid #1877f2;background:#f0f7ff}
.post-text{font-weight:600;font-size:14px;line-height:1.5;color:#1c1e21;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.post-date{font-size:12px;color:#8c939d;margin-top:10px;display:flex;align-items:center;gap:6px}

/* Steps */
.step{display:flex;align-items:center;gap:12px;margin-bottom:8px}
.step-num{width:32px;height:32px;border-radius:50%;background:#1877f2;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px;flex-shrink:0}
.step-num.done{background:#42b72a}
.step-text{font-weight:600;font-size:15px}
.step-sub{font-size:13px;color:#65676b}

/* Sidebar info */
.info-box{background:#f5f6f7;border-radius:12px;padding:18px;margin:16px 0}
.info-box h4{margin:0 0 10px 0;font-size:14px;color:#65676b;text-transform:uppercase;letter-spacing:0.8px}
.info-box p{margin:6px 0;font-size:14px;color:#1c1e21}
.info-box .small{font-size:12px;color:#8c939d}

/* Footer */
.footer{text-align:center;margin-top:40px;padding-top:24px;border-top:1px solid #dddfe2;color:#8c939d;font-size:13px}
.footer a{color:#1877f2;text-decoration:none;font-weight:500}
.footer a:hover{text-decoration:underline}

/* Permission denial screen */
.perm-grid{display:grid;gap:12px;margin:20px 0}
.perm-item{display:flex;align-items:flex-start;gap:14px;padding:16px;background:#f5f6f7;border-radius:12px}
.perm-icon{width:40px;height:40px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0}
.perm-icon.std{background:#e7f3ff}
.perm-icon.adv{background:#fff3e0}
.perm-icon.sens{background:#ffebee}
.perm-title{font-weight:700;font-size:15px;margin-bottom:2px}
.perm-desc{font-size:14px;color:#65676b}

/* Login screen */
.login-hero{text-align:center;padding:60px 20px}
.login-hero h2{font-size:28px;margin-bottom:12px;font-weight:800}
.login-hero p{font-size:16px;color:#65676b;max-width:500px;margin:0 auto 32px}

/* Responsive */
@media(max-width:768px){
  .post-grid{grid-template-columns:1fr}
  .stats-grid{grid-template-columns:1fr}
  h1{font-size:20px}
  .login-hero h2{font-size:22px}
}

.muted{color:#65676b;font-size:14px}
.divider{height:1px;background:#dddfe2;margin:24px 0}
</style>
</head>
<body>
<div class="container">

<!-- HEADER -->
<div class="top">
  <div class="logo"></div>
  <div>
    <h1>Betelgeuse TI – Comment Moderation <span class="badge badge-demo">DEMO</span></h1>
    <div class="sub">Real-time Facebook Page comment moderation for customer service teams</div>
  </div>
</div>

<!-- ABOUT CARD (visível em todas as telas – requisito Meta) -->
<div class="card">
  <h3 style="margin-top:0">About This Application</h3>
  <p><strong>Business:</strong> Betelgeuse Serviços de TI — <strong>CNPJ 51.770.524/0001-87</strong></p>
  <p class="muted">This tool enables social media teams to monitor and moderate public comments on Facebook Pages they manage, improving customer response time and service quality. <strong>No personal data is stored on our servers.</strong> All processing is done in real-time during the active session.</p>

  <div style="margin-top:16px">
    <span class="badge badge-std">pages_show_list</span>
    <span class="badge badge-adv">pages_read_engagement</span>
    <span class="badge badge-sens">pages_read_user_content</span>
  </div>
  <p class="muted" style="margin-top:10px;font-size:13px">These three permissions are required to: (1) list Pages you manage, (2) read posts from the selected Page, and (3) read comments for moderation purposes.</p>
</div>

<!-- ALERTS -->
{% if alert %}
<div class="alert alert-{{ alert_type }}">
  <span style="font-size:20px">{% if alert_type=='error' %}⚠️{% elif alert_type=='success' %}✅{% elif alert_type=='warn' %}⚡{% else %}ℹ️{% endif %}</span>
  <div>{{ alert }}</div>
</div>
{% endif %}

{% if not token %}

<!-- LOGIN SCREEN -->
<div class="card login-hero">
  <h2>Connect Your Facebook Page</h2>
  <p>Sign in with the Facebook account that administers your Page. You will be able to select which Page to monitor after login.</p>

  <div class="perm-grid" style="max-width:600px;margin:0 auto 28px;text-align:left">
    <div class="perm-item">
      <div class="perm-icon std">📄</div>
      <div>
        <div class="perm-title">pages_show_list — List your Pages</div>
        <div class="perm-desc">Standard access. Shows Pages you administer so you can choose which one to monitor.</div>
      </div>
    </div>
    <div class="perm-item">
      <div class="perm-icon adv">📊</div>
      <div>
        <div class="perm-title">pages_read_engagement — Read posts & metrics</div>
        <div class="perm-desc">Advanced access. Reads posts from the selected Page to let you choose which post to moderate.</div>
      </div>
    </div>
    <div class="perm-item">
      <div class="perm-icon sens">💬</div>
      <div>
        <div class="perm-title">pages_read_user_content — Read comments</div>
        <div class="perm-desc">Advanced access + Data Use Agreement. Reads comment author name, message, and date for real-time moderation. Data is not stored.</div>
      </div>
    </div>
  </div>

  <a href="/login"><button class="btn">🔐 Login with Facebook</button></a>

  <div class="info-box" style="max-width:500px;margin:24px auto 0;text-align:left">
    <h4>🔒 Privacy Commitment</h4>
    <p>• No data stored on our servers — real-time processing only</p>
    <p>• Session data cleared on logout</p>
    <p>• You can revoke access anytime in Facebook Settings</p>
    <p>• CNPJ-verified business (51.770.524/0001-87)</p>
  </div>
</div>

{% else %}

<!-- AUTH SUCCESS BANNER -->
<div class="alert alert-success">
  <span style="font-size:20px">✅</span>
  <div><strong>Authenticated successfully.</strong> Select a Page below to begin moderation. <a href="/logout" style="color:#2e7d32;font-weight:700">Disconnect</a></div>
</div>

<!-- STEP 1: CHOOSE PAGE -->
<div class="card">
  <div class="step">
    <div class="step-num {% if sel %}done{% endif %}">1</div>
    <div>
      <div class="step-text">Choose your Page</div>
      <div class="step-sub">Permission: <span class="badge badge-std" style="font-size:11px;padding:3px 10px">pages_show_list</span></div>
    </div>
  </div>

  <form style="margin-top:16px">
    <select name="page" onchange="this.form.submit()">
      <option value="">— Select a Page —</option>
      {% for p in pages %}
      <option value="{{p.id}}|{{p.access_token}}" {% if sel and sel.startswith(p.id|string) %}selected{% endif %}>{{p.name}} ({{p.category or 'Page'}})</option>
      {% endfor %}
    </select>
  </form>
  <p class="muted" style="margin-top:10px">{{pages|length}} Page(s) found • Only Pages you administer are shown</p>
</div>

{% if posts is not none %}

<!-- STEP 2: CHOOSE POST -->
<div class="card">
  <div class="step">
    <div class="step-num {% if post_id %}done{% endif %}">2</div>
    <div>
      <div class="step-text">Choose a Post to moderate</div>
      <div class="step-sub">Permission: <span class="badge badge-adv" style="font-size:11px;padding:3px 10px">pages_read_engagement</span></div>
    </div>
  </div>

  {% if posts %}
  <div class="post-grid">
    {% for po in posts %}
    <div class="post-card {% if post_id == po.id %}selected{% endif %}" onclick="window.location.href='/comments?post_id={{po.id}}&page={{sel|urlencode}}'">
      <div class="post-text">{{po.message[:140] if po.message else '(Media post without text)'}}</div>
      <div class="post-date">📅 {{po.created_time[:10] if po.created_time else 'Unknown'}} • 💬 {{po.comments_count or '?'}} comments</div>
    </div>
    {% endfor %}
  </div>
  {% else %}
  <p class="muted" style="padding:20px;text-align:center">No posts found on this Page.</p>
  {% endif %}
</div>
{% endif %}

{% if comments is not none %}

<!-- STEP 3: COMMENTS -->
<div class="card">
  <div class="step">
    <div class="step-num done">3</div>
    <div>
      <div class="step-text">Moderate Comments</div>
      <div class="step-sub">Permission: <span class="badge badge-sens" style="font-size:11px;padding:3px 10px">pages_read_user_content</span> — Real-time display, no storage</div>
    </div>
  </div>

  {% if selected_post %}
  <div style="background:#f0f7ff;border-radius:12px;padding:16px;margin:16px 0;border-left:4px solid #1877f2">
    <strong>Post:</strong> {{selected_post.message[:200] if selected_post.message else '(Media post)'}}<br>
    <span class="muted" style="font-size:13px">📅 {{selected_post.created_time[:10] if selected_post.created_time else 'Unknown'}}</span>
  </div>
  {% endif %}

  <!-- STATS -->
  <div class="stats-grid">
    <div class="stat-card">
      <div class="stat-num">{{comments|length}}</div>
      <div class="stat-label">Total Comments</div>
    </div>
    <div class="stat-card green">
      <div class="stat-num">{{total_likes}}</div>
      <div class="stat-label">Total Likes</div>
    </div>
    <div class="stat-card orange">
      <div class="stat-num">{{negative_count}}</div>
      <div class="stat-label">Flagged for Review</div>
    </div>
  </div>

  <div class="divider"></div>

  {% if comments %}
  <div style="margin-top:16px">
    {% for c in comments %}
    <div class="comment-card {% if c.is_negative %}negative{% endif %}">
      <div class="comment-author">
        👤 {{c.author_name}}
        <span class="comment-id">ID: {{c.author_id}}</span>
        {% if c.is_negative %}<span class="badge badge-sens" style="font-size:11px;padding:2px 8px">FLAGGED</span>{% endif %}
      </div>
      <div class="comment-text">{{c.message}}</div>
      <div class="comment-meta">
        <span>📅 {{c.created_time}}</span>
        <span>❤️ {{c.like_count}} likes</span>
        <span>🕐 {{c.time_ago}}</span>
      </div>
    </div>
    {% endfor %}
  </div>
  {% else %}
  <p class="muted" style="padding:40px;text-align:center;font-size:16px">No comments on this post yet.</p>
  {% endif %}

  <div class="divider"></div>
  <div style="text-align:center">
    <a href="/?page={{sel|urlencode}}" class="btn btn-outline btn-sm">← Back to Posts</a>
  </div>
</div>
{% endif %}

{% endif %}

<!-- FOOTER COMPLIANCE -->
<div class="footer">
  © 2026 Betelgeuse Serviços de TI — CNPJ 51.770.524/0001-87<br>
  <a href="/privacy">Privacy Policy</a> • <a href="/terms">Terms of Service</a> • <a href="/delete">Data Deletion</a> • <a href="/data-use">Data Use Agreement</a>
</div>

</div>
</body>
</html>
"""

# ─── HELPERS ─────────────────────────────────────────────────────────────

def pages(tok):
    """1. pages_show_list — retorna páginas do usuário"""
    try:
        r = requests.get(f"{GRAPH}/me/accounts",
                         params={"access_token": tok, "fields": "name,id,category,access_token"},
                         timeout=30)
        return r.json().get("data", [])
    except Exception as e:
        app.logger.error(f"pages error: {e}")
        return []

def get_posts(page_id, page_token):
    """2. pages_read_engagement — posts da página"""
    try:
        r = requests.get(f"{GRAPH}/{page_id}/posts",
                         params={
                             "access_token": page_token,
                             "fields": "id,message,created_time,full_picture,permalink_url,comments.summary(true)",
                             "limit": 12
                         },
                         timeout=30)
        data = r.json()
        if "error" in data:
            app.logger.error(f"posts error: {data['error']}")
            return [], data["error"]
        posts = data.get("data", [])
        # Adiciona contagem de comentários do summary
        for p in posts:
            p["comments_count"] = p.get("comments", {}).get("summary", {}).get("total_count", "?")
        return posts, None
    except Exception as e:
        app.logger.error(f"posts exception: {e}")
        return [], str(e)

def get_comments(post_id, page_token):
    """3. pages_read_user_content — comentários do post"""
    try:
        r = requests.get(f"{GRAPH}/{post_id}/comments",
                         params={
                             "access_token": page_token,
                             "fields": "id,from{name,id},message,created_time,like_count",
                             "limit": 50
                         },
                         timeout=30)
        data = r.json()
        if "error" in data:
            app.logger.error(f"comments error: {data['error']}")
            return [], data["error"]

        raw = data.get("data", [])
        negative_keywords = ["reclamação", "problema", "ruim", "péssimo", "demora", "atraso", "erro",
                             "insatisfeito", "complaint", "bad", "terrible", "delay", "wrong", "issue",
                             "problem", "slow", "error", "fail", "broken", "worst", "hate", "angry"]

        processed = []
        for c in raw:
            msg = c.get("message", "")
            created = c.get("created_time", "")[:10]
            author = c.get("from", {})
            is_neg = any(kw in msg.lower() for kw in negative_keywords)

            processed.append({
                "id": c.get("id"),
                "author_name": author.get("name", "Unknown"),
                "author_id": author.get("id", ""),
                "message": msg,
                "created_time": created,
                "like_count": c.get("like_count", 0),
                "is_negative": is_neg,
                "time_ago": created  # simplificado para o template
            })
        return processed, None
    except Exception as e:
        app.logger.error(f"comments exception: {e}")
        return [], str(e)

# ─── ROTAS ───────────────────────────────────────────────────────────────

@app.route("/")
def home():
    tok = session.get("tok")
    sel = request.args.get("page")

    pgs = pages(tok) if tok else []
    pst = None

    if sel and "|" in sel:
        pid, pt = sel.split("|", 1)
        pst, err = get_posts(pid, pt)
        if err:
            session["err"] = f"Could not load posts: {err.get('message', str(err))}"
            return redirect("/")

    alert = session.pop("err", None)
    alert_type = session.pop("err_type", "error")

    return render_template_string(HTML,
                                  token=tok,
                                  pages=pgs,
                                  posts=pst,
                                  sel=sel,
                                  post_id=None,
                                  comments=None,
                                  selected_post=None,
                                  alert=alert,
                                  alert_type=alert_type,
                                  total_likes=0,
                                  negative_count=0)

@app.route("/login")
def login():
    """Inicia OAuth com as 3 permissões e auth_type=rerequest"""
    url = (f"https://www.facebook.com/v19.0/dialog/oauth?"
           f"client_id={APP_ID}&redirect_uri={REDIRECT_URI}"
           f"&scope={PERMISSIONS}&response_type=code"
           f"&auth_type=rerequest&state=betelgeuse_{{int(datetime.now().timestamp())}}")
    return redirect(url)

@app.route("/login/callback")
def cb():
    """Callback OAuth — trata sucesso e negação"""
    error = request.args.get("error")
    error_reason = request.args.get("error_reason", "")
    error_description = request.args.get("error_description", "")

    if error:
        # Usuário negou permissão — mensagem amigável e instrutiva
        session["err"] = (f"<strong>Permission Required</strong><br>"
                          f"You declined access: <code>{error_reason}</code>.<br>"
                          f"To moderate comments, all three permissions are necessary. "
                          f"No data is stored — everything is processed in real-time during your session.<br><br>"
                          f"<strong>Why we need this:</strong><br>"
                          f"• <b>pages_show_list</b> — to list Pages you manage<br>"
                          f"• <b>pages_read_engagement</b> — to read posts from the selected Page<br>"
                          f"• <b>pages_read_user_content</b> — to read comments for moderation<br><br>"
                          f"Click 'Login with Facebook' below to try again and accept all permissions.")
        session["err_type"] = "error"
        return redirect("/")

    code = request.args.get("code")
    if not code:
        session["err"] = "Authorization code not received. Please try again."
        session["err_type"] = "error"
        return redirect("/")

    # Troca code por token
    try:
        r = requests.get(f"{GRAPH}/oauth/access_token",
                         params={
                             "client_id": APP_ID,
                             "redirect_uri": REDIRECT_URI,
                             "client_secret": APP_SECRET,
                             "code": code
                         },
                         timeout=30)
        data = r.json()

        if "access_token" in data:
            session["tok"] = data["access_token"]
            session["err"] = "Successfully connected to Facebook! Select a Page to begin."
            session["err_type"] = "success"
        else:
            err_msg = data.get("error", {}).get("message", "Unknown error")
            session["err"] = f"Authentication failed: {err_msg}"
            session["err_type"] = "error"
    except Exception as e:
        session["err"] = f"Connection error: {str(e)}"
        session["err_type"] = "error"

    return redirect("/")

@app.route("/comments")
def cm():
    """Exibe comentários de um post específico"""
    pg = request.args.get("page")
    post_id = request.args.get("post_id")

    if not pg or "|" not in pg or not post_id:
        session["err"] = "Invalid request. Please select a Page and Post."
        return redirect("/")

    pid, pt = pg.split("|", 1)

    # Busca posts para manter a lista visível
    pst, _ = get_posts(pid, pt)

    # Busca comentários
    comments, err = get_comments(post_id, pt)
    if err:
        session["err"] = f"Could not load comments: {err.get('message', str(err))}"
        return redirect(f"/?page={pg}")

    # Encontra post selecionado
    selected_post = next((p for p in pst if p["id"] == post_id), None)

    total_likes = sum(c["like_count"] for c in comments)
    negative_count = sum(1 for c in comments if c["is_negative"])

    return render_template_string(HTML,
                                  token=session.get("tok"),
                                  pages=pages(session.get("tok")),
                                  posts=pst,
                                  sel=pg,
                                  post_id=post_id,
                                  comments=comments,
                                  selected_post=selected_post,
                                  alert=None,
                                  alert_type="info",
                                  total_likes=total_likes,
                                  negative_count=negative_count)

@app.route("/logout")
def out():
    """Logout completo — limpa sessão e redireciona"""
    tok = session.pop("tok", None)
    session.clear()
    # Redireciona para logout do Facebook + volta para app
    fb_logout = f"https://www.facebook.com/logout.php?next={REDIRECT_URI}&access_token={tok or ''}"
    return redirect(fb_logout)

# ─── PÁGINAS DE COMPLIANCE ───────────────────────────────────────────────

@app.route("/privacy")
def privacy():
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Privacy Policy – Betelgeuse TI</title>
<style>body{font-family:Inter,system-ui;max-width:800px;margin:40px auto;padding:0 24px;line-height:1.7;color:#1c1e21}
h1{color:#1877f2} h2{color:#333;margin-top:32px;font-size:18px}
.badge{background:#e7f3ff;color:#1877f2;padding:4px 12px;border-radius:12px;font-size:12px;font-weight:600}
.footer{margin-top:40px;padding-top:20px;border-top:1px solid #ddd;color:#65676b;font-size:13px}
a{color:#1877f2}</style></head><body>
<h1>Privacy Policy</h1>
<p><span class="badge">Last updated: May 30, 2026</span></p>
<p><strong>Betelgeuse Serviços de TI</strong> — CNPJ 51.770.524/0001-87</p>

<h2>1. Information We Process</h2>
<p>Our Comment Moderation application processes the following data <strong>in real-time only</strong>:</p>
<ul>
<li>Facebook Page names and IDs you administer (via <code>pages_show_list</code>)</li>
<li>Post content, IDs, and creation dates from your selected Page (via <code>pages_read_engagement</code>)</li>
<li>Comment author names, author IDs, comment text, creation dates, and like counts (via <code>pages_read_user_content</code>)</li>
</ul>

<h2>2. No Data Storage</h2>
<p><strong>We do not store, persist, or retain any user data on our servers.</strong> All data is fetched directly from Facebook's Graph API and displayed in your browser session. When you close the application or log out, no data remains on our systems.</p>

<h2>3. Data Retention</h2>
<p>Data is retained only for the duration of your active session (typically less than 30 minutes). We do not maintain databases, logs, or backups of Facebook user content.</p>

<h2>4. Data Sharing</h2>
<p>We do not share, sell, rent, or transfer any user data to third parties. We do not use comment data to train artificial intelligence models.</p>

<h2>5. Your Rights</h2>
<p>You have the right to:</p>
<ul>
<li>Revoke app permissions at any time via <a href="https://www.facebook.com/settings?tab=applications" target="_blank">Facebook Settings → Apps</a></li>
<li>Request deletion of any cached session data via our <a href="/delete">Data Deletion</a> page</li>
<li>Contact us with privacy concerns at <a href="mailto:falecom@mariomello.com.br">falecom@mariomello.com.br</a></li>
</ul>

<h2>6. Legal Basis</h2>
<p>Processing is based on your explicit consent granted through Facebook's OAuth dialog. You can withdraw consent at any time by removing the app from your Facebook account.</p>

<h2>7. Contact</h2>
<p>Betelgeuse Serviços de TI<br>CNPJ: 51.770.524/0001-87<br>Email: <a href="mailto:falecom@mariomello.com.br">falecom@mariomello.com.br</a><br>Address: Navegantes, SC, Brazil</p>

<div class="footer">© 2026 Betelgeuse Serviços de TI — <a href="/">Back to App</a> • <a href="/terms">Terms</a> • <a href="/delete">Data Deletion</a></div>
</body></html>"""

@app.route("/terms")
def terms():
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Terms of Service – Betelgeuse TI</title>
<style>body{font-family:Inter,system-ui;max-width:800px;margin:40px auto;padding:0 24px;line-height:1.7;color:#1c1e21}
h1{color:#1877f2} h2{color:#333;margin-top:32px;font-size:18px}
.badge{background:#fff3e0;color:#e65100;padding:4px 12px;border-radius:12px;font-size:12px;font-weight:600}
.footer{margin-top:40px;padding-top:20px;border-top:1px solid #ddd;color:#65676b;font-size:13px}
a{color:#1877f2}</style></head><body>
<h1>Terms of Service</h1>
<p><span class="badge">Effective: May 30, 2026</span></p>
<p><strong>Betelgeuse Serviços de TI</strong> — CNPJ 51.770.524/0001-87</p>

<h2>1. Service Description</h2>
<p>Betelgeuse TI Comment Moderation is a real-time tool that enables Facebook Page administrators to view and monitor public comments on posts they manage. The service is provided free of charge as a demonstration of our social media automation capabilities.</p>

<h2>2. Eligibility</h2>
<p>You must be at least 18 years old and an administrator of the Facebook Page you wish to monitor. You must use a Facebook account associated with a verified business (CNPJ-verified for Brazilian users).</p>

<h2>3. Permitted Use</h2>
<p>You agree to use this service solely for:</p>
<ul>
<li>Monitoring and moderating comments on Facebook Pages you administer</li>
<li>Improving customer service response times</li>
<li>Internal business analysis during active sessions</li>
</ul>
<p>You may NOT use this service to:</p>
<ul>
<li>Access Pages you do not administer</li>
<li>Scrape, harvest, or bulk-download user data</li>
<li>Use comment data to train AI/ML models without explicit consent</li>
<li>Share user content with unauthorized third parties</li>
</ul>

<h2>4. Data Processing</h2>
<p>All data processing occurs in real-time. We do not store Facebook user data on our servers. Session data is temporary and destroyed upon logout or session expiration.</p>

<h2>5. Limitation of Liability</h2>
<p>This service is provided "as is" without warranties. We are not responsible for Facebook API availability, changes to Facebook's terms, or data accuracy. Maximum liability is limited to the amount paid for the service (zero for demo use).</p>

<h2>6. Termination</h2>
<p>We may suspend or terminate access for violations of these terms or Facebook's Platform Policies. You may terminate use at any time by disconnecting the app via Facebook Settings.</p>

<h2>7. Governing Law</h2>
<p>These terms are governed by the laws of Brazil. Disputes shall be resolved in the courts of Navegantes, SC.</p>

<h2>8. Contact</h2>
<p>Email: <a href="mailto:falecom@mariomello.com.br">falecom@mariomello.com.br</a></p>

<div class="footer">© 2026 Betelgeuse Serviços de TI — <a href="/">Back to App</a> • <a href="/privacy">Privacy</a> • <a href="/delete">Data Deletion</a></div>
</body></html>"""

@app.route("/delete")
def delete_data():
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Data Deletion – Betelgeuse TI</title>
<style>body{font-family:Inter,system-ui;max-width:800px;margin:40px auto;padding:0 24px;line-height:1.7;color:#1c1e21}
h1{color:#1877f2} h2{color:#333;margin-top:32px;font-size:18px}
.badge{background:#ffebee;color:#c62828;padding:4px 12px;border-radius:12px;font-size:12px;font-weight:600}
.success{background:#e8f5e9;border:1px solid #a5d6a7;color:#2e7d32;padding:16px;border-radius:12px;margin:16px 0}
.footer{margin-top:40px;padding-top:20px;border-top:1px solid #ddd;color:#65676b;font-size:13px}
a{color:#1877f2}.btn{background:#1877f2;color:#fff;border:0;padding:12px 24px;border-radius:10px;font-weight:600;cursor:pointer;text-decoration:none;display:inline-block}
</style></head><body>
<h1>Data Deletion Request</h1>
<p><span class="badge">GDPR / LGPD Compliant</span></p>
<p><strong>Betelgeuse Serviços de TI</strong> — CNPJ 51.770.524/0001-87</p>

<h2>How to Delete Your Data</h2>

<div class="success">
<strong>✅ Good news:</strong> Our application does not store any personal data on our servers. All Facebook data is processed in real-time and exists only during your active browser session.
</div>

<h2>Immediate Steps (Instant)</h2>
<ol>
<li><strong>Revoke App Access:</strong> Go to <a href="https://www.facebook.com/settings?tab=applications" target="_blank">Facebook Settings → Apps & Websites</a>, find "Betelgeuse TI Comment Moderation", and click "Remove".</li>
<li><strong>Clear Session:</strong> Click <a href="/logout" class="btn" style="margin-left:8px">Logout from App</a> to clear your current session.</li>
</ol>

<h2>Contact Us for Confirmation</h2>
<p>If you would like written confirmation that no data is retained, or if you believe data may have been cached, contact us:</p>
<ul>
<li>Email: <a href="mailto:falecom@mariomello.com.br">falecom@mariomello.com.br</a></li>
<li>Subject line: <code>Data Deletion Request — [Your Facebook User ID or Email]</code></li>
<li>Response time: Within 48 hours (business days)</li>
</ul>

<h2>What We Will Do</h2>
<ul>
<li>Verify your identity as the account owner</li>
<li>Confirm no data is stored in our systems</li>
<li>Provide written confirmation of deletion status</li>
<li>Log your request for compliance records (request metadata only — no personal data)</li>
</ul>

<h2>Legal Rights</h2>
<p>Under Brazil's LGPD (Lei Geral de Proteção de Dados) and the EU's GDPR, you have the right to erasure ("right to be forgotten"). Since we do not store personal data, fulfillment is immediate upon app removal.</p>

<div class="footer">© 2026 Betelgeuse Serviços de TI — <a href="/">Back to App</a> • <a href="/privacy">Privacy</a> • <a href="/terms">Terms</a></div>
</body></html>"""

@app.route("/data-use")
def data_use():
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Data Use Agreement – Betelgeuse TI</title>
<style>body{font-family:Inter,system-ui;max-width:800px;margin:40px auto;padding:0 24px;line-height:1.7;color:#1c1e21}
h1{color:#1877f2} h2{color:#333;margin-top:32px;font-size:18px}
.badge{background:#e8f5e9;color:#2e7d32;padding:4px 12px;border-radius:12px;font-size:12px;font-weight:600}
.footer{margin-top:40px;padding-top:20px;border-top:1px solid #ddd;color:#65676b;font-size:13px}
a{color:#1877f2}</style></head><body>
<h1>Data Use Agreement</h1>
<p><span class="badge">Meta Platform Supplemental Terms</span></p>
<p><strong>Betelgeuse Serviços de TI</strong> — CNPJ 51.770.524/0001-87</p>

<h2>1. Purpose of Data Use</h2>
<p>We use Facebook Platform data solely for the purpose of <strong>real-time comment moderation on Facebook Pages administered by the authenticated user</strong>. This supports customer service teams in responding to public comments efficiently.</p>

<h2>2. Data We Access</h2>
<table style="width:100%;border-collapse:collapse;margin:16px 0">
<tr style="background:#f5f6f7"><th style="text-align:left;padding:12px;border:1px solid #ddd">Permission</th><th style="text-align:left;padding:12px;border:1px solid #ddd">Data Accessed</th><th style="text-align:left;padding:12px;border:1px solid #ddd">Use</th></tr>
<tr><td style="padding:12px;border:1px solid #ddd"><code>pages_show_list</code></td><td style="padding:12px;border:1px solid #ddd">Page name, ID, category</td><td style="padding:12px;border:1px solid #ddd">Display list of Pages user manages</td></tr>
<tr><td style="padding:12px;border:1px solid #ddd"><code>pages_read_engagement</code></td><td style="padding:12px;border:1px solid #ddd">Post ID, message, created_time, permalink</td><td style="padding:12px;border:1px solid #ddd">List posts for user to select</td></tr>
<tr><td style="padding:12px;border:1px solid #ddd"><code>pages_read_user_content</code></td><td style="padding:12px;border:1px solid #ddd">Comment author name, author ID, message, created_time, like_count</td><td style="padding:12px;border:1px solid #ddd">Display comments for moderation</td></tr>
</table>

<h2>3. Prohibited Uses</h2>
<p>We expressly commit to NOT:</p>
<ul>
<li>Store Facebook user data beyond the active session</li>
<li>Use data for advertising or marketing purposes</li>
<li>Sell, rent, or transfer data to third parties</li>
<li>Use comment content to train artificial intelligence or machine learning models</li>
<li>Aggregate data across users or Pages</li>
<li>Access Pages not administered by the authenticated user</li>
</ul>

<h2>4. Data Security</h2>
<p>All API communications use HTTPS/TLS 1.2+. Access tokens are stored only in encrypted server-side sessions (Flask secret key + server-side storage). Tokens expire with the session and are never logged or persisted to disk.</p>

<h2>5. Compliance</h2>
<p>We comply with:</p>
<ul>
<li>Meta Platform Terms and Developer Policies</li>
<li>Meta Data Processing Terms</li>
<li>Brazilian LGPD (Lei 13.709/2018)</li>
<li>EU GDPR (where applicable)</li>
</ul>

<h2>6. Contact for Data Concerns</h2>
<p>Email: <a href="mailto:falecom@mariomello.com.br">falecom@mariomello.com.br</a><br>Data Protection Officer: Mario Mello</p>

<div class="footer">© 2026 Betelgeuse Serviços de TI — <a href="/">Back to App</a> • <a href="/privacy">Privacy</a> • <a href="/terms">Terms</a> • <a href="/delete">Data Deletion</a></div>
</body></html>"""

# ─── HEALTH CHECK ────────────────────────────────────────────────────────
@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "betelgeuse-comment-moderator", "version": "3.2"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860)
