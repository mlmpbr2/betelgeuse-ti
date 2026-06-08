import os
import logging
from flask import Flask, redirect, request, session, render_template_string, send_from_directory, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix
import requests
from datetime import datetime, timedelta

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(message)s', handlers=[logging.StreamHandler()])
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.secret_key = os.environ.get("SECRET_KEY", "Betelgeuse-2026-Secure")

APP_ID = os.environ.get("META_APP_ID", "877709481915236")
APP_SECRET = os.environ.get("META_APP_SECRET", "3bf01b88362dac1be1bb62999af4a5e2")
GRAPH = "https://graph.facebook.com/v19.0"
PERMISSIONS = "pages_show_list,pages_read_engagement,pages_read_user_content"

BETELGEUSE_PAGE_ID = "1057812024092361"
# Page Access Token manual da Betelgeuse (fallback quando nao aparece em /me/accounts)
BETELGEUSE_PAGE_TOKEN = "EAAMeRanis2QBRjV7d7ttXGnnvUjZBDbOjvdvq6I9LSLyPt4qpyofcyX3nK0ychzgZBuG0ojsMK8iAp7oAAIH6QZBVAOzTkHN2lcmd4mX7fZBi7L33TVlN0efhCZCrZAe8fZBptlNMKhHKjTF6Cp8dHhkyZB2FkRZBirGtWP46rP2vqX6WuIeXJM0hNGVieJGRZBKgf9uRA2yW5EGODEgn9JOdCdHglHirFB4UXuF2Ury0ZBBbX6S4v72ZCZC2IDMZD"

# ═══════════════════════════════════════════════════════════════════════════
# CACHE EM MEMORIA - TOLERANCIA A FALHAS DO HF
# ═══════════════════════════════════════════════════════════════════════════
_cache = {
    "pages": None,           # Lista de paginas
    "pages_time": None,      # Timestamp do cache
    "posts": {},             # {page_id: [posts]}
    "posts_time": {},        # {page_id: timestamp}
    "comments": {},          # {post_id: [comments]}
    "comments_time": {},     # {post_id: timestamp}
}
CACHE_TTL = 300  # 5 minutos de validade do cache

def get_cache(key, subkey=None):
    """Retorna dados do cache se ainda forem validos"""
    now = datetime.utcnow()
    if subkey:
        data = _cache.get(key, {}).get(subkey)
        ts = _cache.get(f"{key}_time", {}).get(subkey)
        if data and ts and (now - ts).seconds < CACHE_TTL:
            logger.info(f"CACHE HIT: {key}/{subkey}")
            return data
    else:
        data = _cache.get(key)
        ts = _cache.get(f"{key}_time")
        if data and ts and (now - ts).seconds < CACHE_TTL:
            logger.info(f"CACHE HIT: {key}")
            return data
    return None

def set_cache(key, value, subkey=None):
    """Salva dados no cache"""
    now = datetime.utcnow()
    if subkey:
        if key not in _cache:
            _cache[key] = {}
            _cache[f"{key}_time"] = {}
        _cache[key][subkey] = value
        _cache[f"{key}_time"][subkey] = now
    else:
        _cache[key] = value
        _cache[f"{key}_time"] = now
    logger.info(f"CACHE SET: {key}{'/' + subkey if subkey else ''}")

def is_cache_fresh(key, subkey=None):
    """Verifica se o cache existe e eh valido"""
    return get_cache(key, subkey) is not None

# ═══════════════════════════════════════════════════════════════════════════

def get_redirect_uri():
    env_uri = os.environ.get("REDIRECT_URI")
    if env_uri:
        return env_uri
    host = request.headers.get('X-Forwarded-Host') or request.headers.get('Host', '')
    proto = request.headers.get('X-Forwarded-Proto', 'https')
    if host:
        return f"{proto}://{host}/login/callback"
    return "https://mlmpbr-betelgeuse-api.hf.space/login/callback"

logger.info(f"=== APP START === APP_ID: {APP_ID}")

@app.route('/assets/<path:f>')
def assets(f):
    return send_from_directory('assets', f)

HTML = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Betelgeuse TI - Moderador de Comentarios</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
:root{--primary:#1877f2;--primary-dark:#166fe5;--secondary:#42b72a;--danger:#e53935;--warning:#ff9800;--dark:#1c1e21;--gray-50:#f5f6f7;--gray-100:#f0f2f5;--gray-200:#e4e6eb;--gray-300:#dddfe2;--gray-400:#bec3c9;--gray-500:#8c939d;--gray-600:#65676b;--gray-700:#4b4f56;--radius-sm:10px;--radius:14px;--radius-lg:18px;--radius-xl:24px;--shadow-sm:0 1px 2px rgba(0,0,0,.06);--shadow:0 4px 12px rgba(0,0,0,.08);--shadow-lg:0 8px 32px rgba(0,0,0,.12);--shadow-primary:0 4px 16px rgba(24,119,242,.25)}
*{box-sizing:border-box;margin:0;padding:0}html{scroll-behavior:smooth}body{font-family:'Inter',system-ui,-apple-system,sans-serif;background:var(--gray-100);color:var(--dark);line-height:1.6;min-height:100vh}
.container{max-width:1200px;margin:0 auto;padding:24px 16px}
.header{background:linear-gradient(135deg,#1a1a2e,#16213e);color:#fff;padding:20px 0;position:sticky;top:0;z-index:100;box-shadow:var(--shadow-lg)}
.header-inner{max-width:1200px;margin:0 auto;padding:0 16px;display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}
.header-brand{display:flex;align-items:center;gap:14px}
.header-logo{width:48px;height:48px;border-radius:14px;background:linear-gradient(135deg,var(--primary),var(--secondary));display:flex;align-items:center;justify-content:center;font-weight:900;font-size:22px;color:#fff;box-shadow:0 2px 12px rgba(24,119,242,.4)}
.header-title h1{font-size:22px;font-weight:800;letter-spacing:-.3px}
.header-title span{display:block;font-size:12px;font-weight:500;color:#8b9dc3;margin-top:2px;letter-spacing:.5px;text-transform:uppercase}
.header-badge{background:rgba(255,255,255,.12);backdrop-filter:blur(10px);padding:6px 14px;border-radius:20px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.8px}
.header-user{display:flex;align-items:center;gap:10px;font-size:13px;color:#b0b8d1}
.header-user i{font-size:16px;color:var(--secondary)}
.card{background:#fff;border-radius:var(--radius-lg);padding:28px;margin:18px 0;box-shadow:var(--shadow-sm),var(--shadow);border:1px solid var(--gray-200);transition:transform .2s,box-shadow .2s}
.card:hover{transform:translateY(-2px);box-shadow:var(--shadow-lg)}
.card-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;flex-wrap:wrap;gap:12px}
.card-title{font-size:18px;font-weight:800;color:var(--dark);display:flex;align-items:center;gap:10px}
.card-title i{color:var(--primary);font-size:20px}
.card-subtitle{font-size:13px;color:var(--gray-600);margin-top:4px}
.badge{display:inline-flex;align-items:center;gap:6px;padding:5px 14px;border-radius:20px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px}
.badge-std{background:#e7f3ff;color:var(--primary)}.badge-std::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--primary)}
.badge-adv{background:#fff3e0;color:#e65100}.badge-adv::before{content:"";width:6px;height:6px;border-radius:50%;background:#e65100}
.badge-sens{background:#ffebee;color:var(--danger)}.badge-sens::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--danger)}
.badge-success{background:#e8f5e9;color:#2e7d32}.badge-success::before{content:"";width:6px;height:6px;border-radius:50%;background:#2e7d32}
.badge-demo{background:linear-gradient(135deg,var(--primary),var(--secondary));color:#fff}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;background:var(--primary);color:#fff;border:0;padding:13px 26px;border-radius:var(--radius);font-weight:700;font-size:14px;cursor:pointer;transition:all .2s;text-decoration:none;white-space:nowrap}
.btn:hover{opacity:.92;transform:translateY(-2px);box-shadow:var(--shadow-primary)}
.btn:active{transform:translateY(0)}
.btn-lg{padding:16px 32px;font-size:15px;border-radius:var(--radius-lg)}
.btn-outline{background:#fff;color:var(--primary);border:2px solid var(--primary)}
.btn-outline:hover{background:#f0f7ff}
.btn-danger{background:var(--danger)}.btn-danger:hover{box-shadow:0 4px 16px rgba(229,57,53,.3)}
.btn-secondary{background:var(--gray-600)}
.btn-ghost{background:transparent;color:var(--gray-600);border:1px solid var(--gray-300)}
.btn-ghost:hover{background:var(--gray-50);color:var(--dark)}
.alert{padding:18px 22px;border-radius:var(--radius);margin-bottom:20px;display:flex;align-items:flex-start;gap:14px;border:1px solid transparent}
.alert-error{background:#ffebee;border-color:#ef9a9a;color:#c62828}
.alert-success{background:#e8f5e9;border-color:#a5d6a7;color:#2e7d32}
.alert-info{background:#e3f2fd;border-color:#90caf9;color:#1565c0}
.alert-warning{background:#fff3e0;border-color:#ffcc80;color:#e65100}
.alert-icon{font-size:22px;flex-shrink:0}
.alert-content{flex:1}
.alert-content strong{display:block;margin-bottom:4px;font-weight:700}
.steps{display:flex;align-items:center;gap:8px;margin:24px 0;overflow-x:auto;padding-bottom:8px}
.step{display:flex;align-items:center;gap:10px;white-space:nowrap}
.step-num{width:32px;height:32px;border-radius:50%;background:var(--gray-200);color:var(--gray-500);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:13px;transition:all .3s}
.step-num.active{background:var(--primary);color:#fff;box-shadow:var(--shadow-primary)}
.step-num.done{background:var(--secondary);color:#fff}
.step-label{font-size:13px;font-weight:600;color:var(--gray-500)}
.step.active .step-label{color:var(--primary)}
.step.done .step-label{color:var(--secondary)}
.step-arrow{color:var(--gray-400);font-size:12px}
.form-group{margin-bottom:16px}
.form-label{display:block;font-size:13px;font-weight:600;color:var(--gray-700);margin-bottom:6px}
select,input[type="text"]{width:100%;max-width:480px;padding:12px 14px;border:2px solid var(--gray-200);border-radius:var(--radius);font-size:14px;font-family:inherit;background:#fff;transition:border-color .2s,box-shadow .2s}
select:focus,input:focus{outline:none;border-color:var(--primary);box-shadow:0 0 0 3px rgba(24,119,242,.1)}
.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin:20px 0}
.stat-card{background:#fff;border-radius:var(--radius);padding:22px;text-align:center;border:1px solid var(--gray-200);transition:transform .2s}
.stat-card:hover{transform:translateY(-4px);box-shadow:var(--shadow)}
.stat-card.primary{border-top:4px solid var(--primary)}
.stat-card.success{border-top:4px solid var(--secondary)}
.stat-card.warning{border-top:4px solid var(--warning)}
.stat-card.danger{border-top:4px solid var(--danger)}
.stat-num{font-size:36px;font-weight:800;line-height:1}
.stat-num.primary{color:var(--primary)}.stat-num.success{color:var(--secondary)}.stat-num.warning{color:var(--warning)}.stat-num.danger{color:var(--danger)}
.stat-label{font-size:11px;font-weight:700;color:var(--gray-500);margin-top:8px;text-transform:uppercase;letter-spacing:1px}
.post-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px;margin:20px 0}
.post-card{background:#fff;border-radius:var(--radius);padding:20px;border:2px solid var(--gray-200);cursor:pointer;transition:all .2s;position:relative;overflow:hidden}
.post-card::before{content:"";position:absolute;top:0;left:0;right:0;height:4px;background:linear-gradient(90deg,var(--primary),var(--secondary));transform:scaleX(0);transition:transform .3s}
.post-card:hover::before{transform:scaleX(1)}
.post-card:hover{border-color:var(--primary);box-shadow:var(--shadow-primary);transform:translateY(-3px)}
.post-card.selected{border-color:var(--primary);background:linear-gradient(135deg,#f0f7ff,#e8f5e9)}
.post-card.selected::before{transform:scaleX(1)}
.post-image{width:100%;height:160px;object-fit:cover;border-radius:var(--radius-sm);margin-bottom:14px;background:var(--gray-100)}
.post-text{font-weight:600;font-size:14px;line-height:1.6;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;color:var(--dark)}
.post-text.empty{color:var(--gray-500);font-style:italic}
.post-meta{display:flex;align-items:center;gap:16px;margin-top:14px;padding-top:14px;border-top:1px solid var(--gray-200);font-size:12px;color:var(--gray-500)}
.post-meta i{color:var(--primary);font-size:13px}
.post-badge{position:absolute;top:12px;right:12px;background:var(--primary);color:#fff;padding:4px 10px;border-radius:20px;font-size:10px;font-weight:700;text-transform:uppercase}
.comment-list{display:flex;flex-direction:column;gap:14px}
.comment-card{background:#fff;border-radius:var(--radius);padding:20px;border:1px solid var(--gray-200);transition:all .2s;position:relative}
.comment-card:hover{box-shadow:var(--shadow)}
.comment-card.negative{border-left:4px solid var(--danger);background:linear-gradient(90deg,#fff5f5,#fff)}
.comment-card.negative:hover{box-shadow:0 4px 16px rgba(229,57,53,.15)}
.comment-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;flex-wrap:wrap;gap:8px}
.comment-author{display:flex;align-items:center;gap:10px}
.comment-avatar{width:40px;height:40px;border-radius:50%;background:linear-gradient(135deg,var(--primary),#00c6ff);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:16px}
.comment-name{font-weight:700;font-size:15px;color:var(--dark)}
.comment-id{font-size:10px;color:var(--gray-500);background:var(--gray-100);padding:2px 8px;border-radius:6px;font-family:monospace}
.comment-text{font-size:15px;line-height:1.7;color:var(--gray-700);margin:12px 0;padding:12px;background:var(--gray-50);border-radius:var(--radius-sm)}
.comment-footer{display:flex;align-items:center;gap:20px;font-size:13px;color:var(--gray-500);flex-wrap:wrap}
.comment-footer i{margin-right:4px}
.comment-actions{display:flex;gap:8px;margin-top:12px}
.comment-actions .btn{padding:8px 16px;font-size:12px;border-radius:var(--radius-sm)}
.post-banner{background:linear-gradient(135deg,var(--primary),#00c6ff);color:#fff;padding:20px 24px;border-radius:var(--radius);margin:16px 0;display:flex;align-items:center;gap:16px}
.post-banner i{font-size:28px;opacity:.9}
.post-banner-content{flex:1}
.post-banner-title{font-weight:700;font-size:15px;line-height:1.5}
.post-banner-meta{font-size:12px;opacity:.85;margin-top:4px}
.login-hero{text-align:center;padding:60px 20px;max-width:600px;margin:0 auto}
.login-hero h2{font-size:32px;margin-bottom:16px;font-weight:800;background:linear-gradient(135deg,var(--primary),var(--secondary));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.login-hero p{font-size:16px;color:var(--gray-600);margin-bottom:40px;line-height:1.7}
.perm-grid{display:grid;gap:12px;margin:32px 0;text-align:left}
.perm-item{display:flex;align-items:flex-start;gap:14px;padding:18px;background:var(--gray-50);border-radius:var(--radius);border:1px solid var(--gray-200);transition:all .2s}
.perm-item:hover{border-color:var(--primary);background:#fff;transform:translateX(4px)}
.perm-icon{width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0}
.perm-icon.std{background:#e7f3ff;color:var(--primary)}.perm-icon.adv{background:#fff3e0;color:#e65100}.perm-icon.sens{background:#ffebee;color:var(--danger)}
.perm-title{font-weight:700;font-size:14px;margin-bottom:4px}
.perm-desc{font-size:13px;color:var(--gray-600);line-height:1.5}
.divider{height:1px;background:linear-gradient(90deg,transparent,var(--gray-300),transparent);margin:28px 0}
.muted{color:var(--gray-600);font-size:14px}
.empty-state{text-align:center;padding:60px 20px;color:var(--gray-500)}
.empty-state i{font-size:48px;margin-bottom:16px;color:var(--gray-300)}
.empty-state p{font-size:16px}
.debug-box{background:#0d1117;color:#7ee787;padding:18px;border-radius:var(--radius-sm);font-family:'SF Mono',monospace;font-size:12px;margin:16px 0;overflow-x:auto;border:1px solid #30363d}
.debug-box pre{margin:0;white-space:pre-wrap;word-break:break-all;color:#e6edf3}
.debug-box strong{color:#58a6ff}
.footer{text-align:center;margin-top:48px;padding:28px 0;border-top:2px solid var(--gray-200);color:var(--gray-500);font-size:13px}
.footer a{color:var(--primary);text-decoration:none;font-weight:600;margin:0 8px}
.footer a:hover{text-decoration:underline}
.cache-badge{display:inline-flex;align-items:center;gap:6px;padding:4px 12px;border-radius:20px;font-size:11px;font-weight:700;background:#fff3e0;color:#e65100;margin-left:10px}
@keyframes fadeIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
.fade-in{animation:fadeIn .4s ease-out}
@media(max-width:768px){
.header-inner{flex-direction:column;text-align:center}
.header-brand{flex-direction:column}
.post-grid{grid-template-columns:1fr}
.stats-grid{grid-template-columns:repeat(2,1fr)}
.steps{justify-content:flex-start}
.login-hero h2{font-size:24px}
}
</style>
</head>
<body>
<div class="header">
  <div class="header-inner">
    <div class="header-brand">
      <div class="header-logo">B</div>
      <div class="header-title">
        <h1>Betelgeuse TI</h1>
        <span>Moderador de Comentarios</span>
      </div>
    </div>
    <div style="display:flex;align-items:center;gap:16px">
      <span class="header-badge"><i class="fas fa-shield-alt" style="margin-right:6px"></i>CNPJ 51.770.524/0001-87</span>
      {% if token %}<div class="header-user"><i class="fas fa-user-circle"></i> Conectado</div>{% endif %}
    </div>
  </div>
</div>
<div class="container">
{% if debug_info %}<div class="debug-box fade-in"><strong>DEBUG INFO</strong><pre>{{debug_info}}</pre></div>{% endif %}
{% if alert %}
<div class="alert alert-{{alert_type}} fade-in">
  <span class="alert-icon">{% if alert_type=='error' %}<i class="fas fa-exclamation-triangle"></i>{% elif alert_type=='success' %}<i class="fas fa-check-circle"></i>{% elif alert_type=='warning' %}<i class="fas fa-info-circle"></i>{% else %}<i class="fas fa-info-circle"></i>{% endif %}</span>
  <div class="alert-content">{{alert|safe}}</div>
</div>
{% endif %}
{% if not token %}
<div class="card login-hero fade-in">
  <h2><i class="fab fa-facebook" style="margin-right:10px;color:var(--primary)"></i>Conecte sua Pagina do Facebook</h2>
  <p>Faca login com a conta do Facebook que administra a pagina <strong>Betelgeuse Servicos de TI</strong> para monitorar e moderar comentarios em tempo real.</p>
  <div class="perm-grid">
    <div class="perm-item"><div class="perm-icon std"><i class="fas fa-file-alt"></i></div><div><div class="perm-title">pages_show_list - Listar suas Paginas</div><div class="perm-desc">Exibe as Paginas que voce administra para que possa escolher qual monitorar.</div></div></div>
    <div class="perm-item"><div class="perm-icon adv"><i class="fas fa-chart-bar"></i></div><div><div class="perm-title">pages_read_engagement - Ler posts e metricas</div><div class="perm-desc">Le as publicacoes da Pagina selecionada para voce escolher qual moderar.</div></div></div>
    <div class="perm-item"><div class="perm-icon sens"><i class="fas fa-comments"></i></div><div><div class="perm-title">pages_read_user_content - Ler comentarios</div><div class="perm-desc">Le nome do autor, mensagem e data dos comentarios para moderacao em tempo real. Nenhum dado e armazenado.</div></div></div>
  </div>
  <a href="/login" class="btn btn-lg"><i class="fab fa-facebook-f"></i> Entrar com Facebook</a>
  <div class="card" style="max-width:520px;margin:32px auto 0;text-align:left;padding:20px">
    <h4 style="margin-bottom:12px;font-size:15px"><i class="fas fa-lock" style="margin-right:8px;color:var(--secondary)"></i>Compromisso de Privacidade</h4>
    <p class="muted" style="font-size:13px;line-height:1.8">
      <i class="fas fa-check" style="color:var(--secondary);margin-right:8px"></i>Nenhum dado armazenado - processamento apenas em tempo real<br>
      <i class="fas fa-check" style="color:var(--secondary);margin-right:8px"></i>Sessao limpa ao sair<br>
      <i class="fas fa-check" style="color:var(--secondary);margin-right:8px"></i>Revogue o acesso a qualquer momento nas Configuracoes do Facebook<br>
      <i class="fas fa-check" style="color:var(--secondary);margin-right:8px"></i>Empresa verificada por CNPJ (51.770.524/0001-87)
    </p>
  </div>
</div>
{% else %}
<div class="alert alert-success fade-in">
  <span class="alert-icon"><i class="fas fa-check-circle"></i></span>
  <div class="alert-content"><strong>Autenticado com sucesso.</strong> Selecione uma Pagina para comecar a moderar. <a href="/logout" style="color:#2e7d32;font-weight:700;margin-left:8px"><i class="fas fa-sign-out-alt"></i> Desconectar</a></div>
</div>
<div class="card fade-in">
  <div class="steps">
    <div class="step active"><div class="step-num active">1</div><span class="step-label">Escolher Pagina</span></div>
    <span class="step-arrow"><i class="fas fa-chevron-right"></i></span>
    <div class="step {% if post_id %}done{% endif %}"><div class="step-num {% if post_id %}done{% endif %}">2</div><span class="step-label">Escolher Post</span></div>
    <span class="step-arrow"><i class="fas fa-chevron-right"></i></span>
    <div class="step {% if comments is not none %}done{% endif %}"><div class="step-num {% if comments is not none %}done{% endif %}">3</div><span class="step-label">Moderar Comentarios</span></div>
  </div>
  <div class="card-header"><div><div class="card-title"><i class="fas fa-flag"></i> Escolha sua Pagina {% if from_cache_pages %}<span class="cache-badge"><i class="fas fa-history"></i> Cache</span>{% endif %}</div><div class="card-subtitle">Permissao: <span class="badge badge-std">pages_show_list</span></div></div></div>
  <form><div class="form-group"><label class="form-label"><i class="fas fa-list" style="margin-right:6px;color:var(--primary)"></i>Pagina do Facebook</label><select name="page" onchange="this.form.submit()"><option value="">- Selecione uma Pagina -</option>{% for p in pages %}<option value="{{p.id}}|{{p.access_token}}" {% if sel and sel.startswith(p.id|string) %}selected{% endif %}>{{p.name}} {% if p.category %}({{p.category}}){% endif %}</option>{% endfor %}</select></div></form>
  <p class="muted" style="margin-top:12px"><i class="fas fa-info-circle" style="margin-right:6px"></i>{{pages|length}} Pagina(s) encontrada(s)</p>
  {% if betelgeuse_missing %}
  <div class="alert alert-warning fade-in" style="margin-top:16px">
    <span class="alert-icon"><i class="fas fa-exclamation-circle"></i></span>
    <div class="alert-content"><strong>Pagina Betelgeuse nao encontrada</strong><br>A pagina <strong>Betelgeuse Servicos de TI</strong> (ID: {{betelgeuse_id}}) nao aparece na lista. Verifique se:<br>- Voce e administrador da pagina<br>- A pagina esta vinculada ao Business Manager<br>- O app tem permissao para acessar a pagina</div>
  </div>
  {% endif %}
</div>
{% if posts is not none %}
<div class="card fade-in">
  <div class="card-header"><div><div class="card-title"><i class="fas fa-newspaper"></i> Escolha uma Publicacao {% if from_cache_posts %}<span class="cache-badge"><i class="fas fa-history"></i> Cache</span>{% endif %}</div><div class="card-subtitle">Permissao: <span class="badge badge-adv">pages_read_engagement</span></div></div></div>
  {% if posts %}
  <div class="post-grid">
    {% for po in posts %}
    <div class="post-card {% if post_id == po.id %}selected{% endif %}" onclick="window.location.href='/comments?post_id={{po.id}}&page={{sel|urlencode}}'">
      {% if po.full_picture %}<img src="{{po.full_picture}}" class="post-image" alt="Post image" onerror="this.style.display='none'">{% endif %}
      <div class="post-text {% if not po.message %}empty{% endif %}">{{po.message[:160] if po.message else '(Publicacao com midia)'}}</div>
      <div class="post-meta"><span><i class="far fa-calendar-alt"></i> {{po.created_time[:10] if po.created_time else 'Data desconhecida'}}</span><span><i class="far fa-comment"></i> {{po.comments_count or '0'}} comentarios</span></div>
      {% if post_id == po.id %}<div class="post-badge"><i class="fas fa-check"></i> Selecionado</div>{% endif %}
    </div>
    {% endfor %}
  </div>
  {% else %}
  <div class="empty-state"><i class="far fa-folder-open"></i><p>Nenhuma publicacao encontrada nesta pagina.</p></div>
  {% endif %}
</div>
{% endif %}
{% if comments is not none %}
<div class="card fade-in">
  <div class="card-header"><div><div class="card-title"><i class="fas fa-comments"></i> Moderar Comentarios {% if from_cache_comments %}<span class="cache-badge"><i class="fas fa-history"></i> Cache</span>{% endif %}</div><div class="card-subtitle">Permissao: <span class="badge badge-sens">pages_read_user_content</span></div></div></div>
  {% if selected_post %}
  <div class="post-banner"><i class="fas fa-newspaper"></i><div class="post-banner-content"><div class="post-banner-title">{{selected_post.message[:200] if selected_post.message else '(Publicacao com midia)'}}</div><div class="post-banner-meta"><i class="far fa-calendar-alt" style="margin-right:6px"></i>{{selected_post.created_time[:10] if selected_post.created_time else 'Data desconhecida'}}</div></div></div>
  {% endif %}
  <div class="stats-grid">
    <div class="stat-card primary"><div class="stat-num primary">{{comments|length}}</div><div class="stat-label">Total de Comentarios</div></div>
    <div class="stat-card success"><div class="stat-num success">{{total_likes}}</div><div class="stat-label">Total de Curtidas</div></div>
    <div class="stat-card warning"><div class="stat-num warning">{{negative_count}}</div><div class="stat-label">Sinalizados</div></div>
    <div class="stat-card danger"><div class="stat-num danger">{{(negative_count / comments|length * 100)|round(1) if comments|length > 0 else 0}}%</div><div class="stat-label">Taxa Negativa</div></div>
  </div>
  <div class="divider"></div>
  {% if comments %}
  <div class="comment-list">
    {% for c in comments %}
    <div class="comment-card {% if c.is_negative %}negative{% endif %} fade-in">
      <div class="comment-header">
        <div class="comment-author"><div class="comment-avatar">{{c.author_name[0]|upper if c.author_name else '?'}}</div><div><div class="comment-name">{{c.author_name}}</div><span class="comment-id">ID: {{c.author_id}}</span></div></div>
        {% if c.is_negative %}<span class="badge badge-sens"><i class="fas fa-flag" style="margin-right:4px"></i>SINALIZADO</span>{% endif %}
      </div>
      <div class="comment-text">{{c.message}}</div>
      <div class="comment-footer"><span><i class="far fa-calendar-alt"></i> {{c.created_time}}</span><span><i class="far fa-heart"></i> {{c.like_count}} curtidas</span><span><i class="far fa-clock"></i> {{c.time_ago}}</span></div>
      <div class="comment-actions">
        <a href="https://facebook.com/{{c.id}}" target="_blank" class="btn btn-ghost"><i class="fas fa-external-link-alt"></i> Ver no Facebook</a>
        {% if c.is_negative %}<button class="btn btn-danger" onclick="alert('Funcionalidade de resposta em desenvolvimento')" style="font-size:12px"><i class="fas fa-reply"></i> Responder</button>{% endif %}
      </div>
    </div>
    {% endfor %}
  </div>
  {% else %}
  <div class="empty-state"><i class="far fa-comment-dots"></i><p>Nenhum comentario nesta publicacao ainda.</p></div>
  {% endif %}
  <div class="divider"></div><div style="text-align:center"><a href="/?page={{sel|urlencode}}" class="btn btn-outline" style="font-size:13px"><i class="fas fa-arrow-left"></i> Voltar para Publicacoes</a></div>
</div>
{% endif %}
{% endif %}
<div class="footer">
  <p>&copy; 2026 <strong>Betelgeuse Servicos de TI</strong> - CNPJ 51.770.524/0001-87</p>
  <p style="margin-top:8px"><a href="/privacy"><i class="fas fa-shield-alt" style="margin-right:4px"></i>Politica de Privacidade</a><a href="/terms"><i class="fas fa-file-contract" style="margin-right:4px"></i>Termos de Uso</a><a href="/delete"><i class="fas fa-trash-alt" style="margin-right:4px"></i>Exclusao de Dados</a><a href="/data-use"><i class="fas fa-handshake" style="margin-right:4px"></i>Uso de Dados</a></p>
</div>
</div>
</body>
</html>"""

def pages(tok):
    # Tenta cache primeiro
    cached = get_cache("pages")

    try:
        r = requests.get(f"{GRAPH}/me/accounts", params={"access_token": tok, "fields": "name,id,category,access_token,tasks"}, timeout=60)
        data = r.json()
        logger.info(f"Pages API response keys: {list(data.keys())}")
        page_list = data.get("data", [])
        for p in page_list:
            logger.info(f"  -> Page: {p.get('name')} | ID: {p.get('id')} | Category: {p.get('category')} | Has token: {bool(p.get('access_token'))}")

        # Salva no cache
        set_cache("pages", page_list)

        betelgeuse_found = any(p.get("id") == BETELGEUSE_PAGE_ID for p in page_list)
        if not betelgeuse_found:
            logger.warning(f"Betelgeuse page (ID: {BETELGEUSE_PAGE_ID}) NOT found in /me/accounts. Pages found: {len(page_list)}")
            # FALLBACK: usar Page Access Token manual
            logger.info("Using BETELGEUSE_PAGE_TOKEN as fallback")
            page_list.append({
                "id": BETELGEUSE_PAGE_ID,
                "name": "Betelgeuse Servicos de TI",
                "category": "Business",
                "access_token": BETELGEUSE_PAGE_TOKEN
            })
            set_cache("pages", page_list)
            logger.info("Added Betelgeuse page via fallback token")
        else:
            logger.info(f"Betelgeuse page found in account list")
        return page_list
    except Exception as e:
        logger.error(f"pages error: {e}")
        # RETORNA CACHE se existir
        if cached:
            logger.info("Returning cached pages due to error")
            return cached
        return []

def get_posts(page_id, page_token):
    cached = get_cache("posts", page_id)

    try:
        logger.info(f"Fetching posts for page {page_id} with token length {len(page_token) if page_token else 0}")
        r = requests.get(f"{GRAPH}/{page_id}/posts", params={"access_token": page_token, "fields": "id,message,created_time,full_picture,permalink_url,comments.summary(true)", "limit": 12}, timeout=60)
        data = r.json()
        if "error" in data:
            err = data["error"]
            logger.error(f"Posts API error: {err}")
            return [], err
        posts = data.get("data", [])
        logger.info(f"Found {len(posts)} posts")
        for p in posts:
            p["comments_count"] = p.get("comments", {}).get("summary", {}).get("total_count", "0")
        # Salva no cache
        set_cache("posts", posts, page_id)
        return posts, None
    except Exception as e:
        logger.error(f"posts error: {e}")
        # RETORNA CACHE se existir
        if cached:
            logger.info("Returning cached posts due to error")
            return cached, {"message": "O Hugging Face esta com instabilidade momentanea - Dados em cache podem estar desatualizados", "type": "network_error", "from_cache": True}
        return [], {"message": "O Hugging Face esta com instabilidade momentanea - Clique para tentar novamente", "type": "network_error"}

def get_comments(post_id, page_token):
    cached = get_cache("comments", post_id)

    try:
        logger.info(f"Fetching comments for post {post_id}")
        r = requests.get(f"{GRAPH}/{post_id}/comments", params={"access_token": page_token, "fields": "id,from{name,id},message,created_time,like_count,attachment", "limit": 50}, timeout=30)
        data = r.json()
        if "error" in data:
            err = data["error"]
            logger.error(f"Comments API error: {err}")
            return [], err
        raw = data.get("data", [])
        logger.info(f"Found {len(raw)} comments")
        neg_kw = ["reclamacao","problema","ruim","pessimo","demora","atraso","erro","insatisfeito","complaint","bad","terrible","delay","wrong","issue","problem","slow","error","fail","broken","worst","hate","angry","horrivel","decepcionado","frustrado","nao funciona","bug","crash","lento","caro","roubo","golpe","fraud"]
        processed = []
        for c in raw:
            msg = c.get("message", "")
            author = c.get("from", {})
            created = c.get("created_time", "")
            time_ago = ""
            if created:
                try:
                    dt = datetime.strptime(created[:19], "%Y-%m-%dT%H:%M:%S")
                    delta = datetime.utcnow() - dt
                    if delta.days > 0:
                        time_ago = f"{delta.days}d atras"
                    elif delta.seconds > 3600:
                        time_ago = f"{delta.seconds//3600}h atras"
                    else:
                        time_ago = f"{delta.seconds//60}min atras"
                except:
                    time_ago = created[:10]
            processed.append({"id": c.get("id"), "author_name": author.get("name", "Usuario do Facebook"), "author_id": author.get("id", ""), "message": msg or "(sem texto)", "created_time": created[:10] if created else "Data desconhecida", "like_count": c.get("like_count", 0), "is_negative": any(kw in msg.lower() for kw in neg_kw), "time_ago": time_ago})
        # Salva no cache
        set_cache("comments", processed, post_id)
        return processed, None
    except Exception as e:
        logger.error(f"comments error: {e}")
        # RETORNA CACHE se existir
        if cached:
            logger.info("Returning cached comments due to error")
            return cached, {"message": "O Hugging Face esta com instabilidade momentanea - Dados em cache podem estar desatualizados", "type": "network_error", "from_cache": True}
        return [], {"message": "O Hugging Face esta com instabilidade momentanea - Clique para tentar novamente", "type": "network_error"}

@app.route("/")
def home():
    tok = session.get("tok")
    sel = request.args.get("page")
    pgs = pages(tok) if tok else []
    betelgeuse_missing = tok and not any(p.get("id") == BETELGEUSE_PAGE_ID for p in pgs)

    from_cache_pages = is_cache_fresh("pages") and pgs == get_cache("pages")

    pst = None
    from_cache_posts = False
    if sel and "|" in sel:
        pid, pt = sel.split("|", 1)
        pst, err = get_posts(pid, pt)
        if err:
            err_msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            from_cache_posts = err.get("from_cache", False)
            if from_cache_posts:
                session["err"] = err_msg
                session["err_type"] = "warning"
            else:
                session["err"] = f"Nao foi possivel carregar as publicacoes: {err_msg}"
                session["err_type"] = "error"
                return redirect("/")

    alert = session.pop("err", None)
    alert_type = session.pop("err_type", "error")
    debug = f"Host: {request.headers.get('Host','N/A')}\nX-Forwarded-Host: {request.headers.get('X-Forwarded-Host','N/A')}\nX-Forwarded-Proto: {request.headers.get('X-Forwarded-Proto','N/A')}\nPages found: {len(pgs)}\nBetelgeuse missing: {betelgeuse_missing}"
    return render_template_string(HTML, token=tok, pages=pgs, posts=pst, sel=sel, post_id=None, comments=None, selected_post=None, alert=alert, alert_type=alert_type, total_likes=0, negative_count=0, debug_info=debug, betelgeuse_missing=betelgeuse_missing, betelgeuse_id=BETELGEUSE_PAGE_ID, from_cache_pages=from_cache_pages, from_cache_posts=from_cache_posts, from_cache_comments=False)

@app.route("/login")
def login():
    redirect_uri = get_redirect_uri()
    state_val = f"bg_{int(datetime.now().timestamp())}"
    session["oauth_state"] = state_val
    url = f"https://www.facebook.com/v19.0/dialog/oauth?client_id={APP_ID}&redirect_uri={redirect_uri}&scope={PERMISSIONS}&response_type=code&auth_type=rerequest&state={state_val}"
    logger.info(f"LOGIN: redirect_uri={redirect_uri}")
    logger.info(f"LOGIN: full_url={url[:180]}...")
    return redirect(url)

@app.route("/login/callback")
def cb():
    redirect_uri = get_redirect_uri()
    logger.info(f"=== CALLBACK ===")
    logger.info(f"redirect_uri used: {redirect_uri}")
    logger.info(f"Full URL: {request.url}")
    logger.info(f"Args: {dict(request.args)}")
    error = request.args.get("error")
    if error:
        session["err"] = "<strong>Permissao necessaria</strong><br>Voce recusou o acesso. As tres permissoes sao necessarias para moderacao de comentarios. Nenhum dado e armazenado."
        session["err_type"] = "error"
        return redirect("/")
    code = request.args.get("code")
    if not code:
        session["err"] = "Codigo de autorizacao nao recebido."
        session["err_type"] = "error"
        return redirect("/")
    try:
        r = requests.get(f"{GRAPH}/oauth/access_token", params={"client_id": APP_ID, "redirect_uri": redirect_uri, "client_secret": APP_SECRET, "code": code}, timeout=60)
        data = r.json()
        logger.info(f"Token response keys: {list(data.keys())}")
        if "access_token" in data:
            session["tok"] = data["access_token"]
            session["err"] = "Conectado com sucesso! Selecione a pagina Betelgeuse para comecar."
            session["err_type"] = "success"
        else:
            err_msg = data.get("error", {}).get("message", "Erro desconhecido")
            session["err"] = f"Falha na autenticacao: {err_msg}"
            session["err_type"] = "error"
            logger.error(f"Token FAILED: {err_msg}")
    except Exception as e:
        session["err"] = f"Erro: {str(e)}"
        session["err_type"] = "error"
        logger.error(f"Token EXCEPTION: {e}")
    return redirect("/")

@app.route("/comments")
def cm():
    pg = request.args.get("page")
    post_id = request.args.get("post_id")
    if not pg or "|" not in pg or not post_id:
        session["err"] = "Requisicao invalida."
        return redirect("/")
    pid, pt = pg.split("|", 1)
    pst, _ = get_posts(pid, pt)
    comments, err = get_comments(post_id, pt)

    from_cache_comments = False
    if err:
        err_msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        from_cache_comments = err.get("from_cache", False)
        if from_cache_comments:
            session["err"] = err_msg
            session["err_type"] = "warning"
        else:
            session["err"] = f"Nao foi possivel carregar os comentarios: {err_msg}"
            return redirect(f"/?page={pg}")

    selected_post = next((p for p in pst if p["id"] == post_id), None)
    total_likes = sum(c["like_count"] for c in comments)
    negative_count = sum(1 for c in comments if c["is_negative"])
    return render_template_string(HTML, token=session.get("tok"), pages=pages(session.get("tok")), posts=pst, sel=pg, post_id=post_id, comments=comments, selected_post=selected_post, alert=None, alert_type="info", total_likes=total_likes, negative_count=negative_count, debug_info=None, betelgeuse_missing=False, betelgeuse_id=BETELGEUSE_PAGE_ID, from_cache_pages=False, from_cache_posts=False, from_cache_comments=from_cache_comments)

@app.route("/logout")
def out():
    tok = session.pop("tok", None)
    session.clear()
    # Limpa cache ao fazer logout
    _cache["pages"] = None
    _cache["pages_time"] = None
    _cache["posts"] = {}
    _cache["posts_time"] = {}
    _cache["comments"] = {}
    _cache["comments_time"] = {}
    return redirect(f"https://www.facebook.com/logout.php?next=https://mlmpbr-betelgeuse-api.hf.space/&access_token={tok or ''}")

PRIVACY_HTML = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Politica de Privacidade - Betelgeuse TI</title><style>body{font-family:Inter,system-ui;max-width:800px;margin:40px auto;padding:0 24px;line-height:1.7;color:#1c1e21}h1{color:#1877f2}h2{color:#333;margin-top:32px;font-size:18px}.badge{background:#e7f3ff;color:#1877f2;padding:4px 12px;border-radius:12px;font-size:12px;font-weight:600}.footer{margin-top:40px;padding-top:20px;border-top:1px solid #ddd;color:#65676b;font-size:13px}a{color:#1877f2}</style></head><body><h1>Politica de Privacidade</h1><p><span class="badge">Atualizado: 30 de maio de 2026</span></p><p><strong>Betelgeuse Servicos de TI</strong> - CNPJ 51.770.524/0001-87</p><h2>1. Informacoes que Processamos</h2><p>Nosso aplicativo processa os seguintes dados <strong>apenas em tempo real</strong>:</p><ul><li>Nomes e IDs de Paginas do Facebook que voce administra (via <code>pages_show_list</code>)</li><li>Conteudo de publicacoes, IDs e datas de criacao (via <code>pages_read_engagement</code>)</li><li>Nomes de autores, IDs de autores, texto de comentarios, datas de criacao e contagem de curtidas (via <code>pages_read_user_content</code>)</li></ul><h2>2. Nenhum Armazenamento de Dados</h2><p><strong>Nao armazenamos, persistimos ou retemos nenhum dado do usuario em nossos servidores.</strong> Todos os dados sao obtidos diretamente da API Graph do Facebook e exibidos na sua sessao do navegador.</p><h2>3. Retencao de Dados</h2><p>Os dados sao retidos apenas durante a duracao da sua sessao ativa (tipicamente menos de 30 minutos).</p><h2>4. Compartilhamento de Dados</h2><p>Nao compartilhamos, vendemos, alugamos ou transferimos dados do usuario para terceiros. Nao usamos dados de comentarios para treinar modelos de IA.</p><h2>5. Seus Direitos</h2><p>Voce tem o direito de:</p><ul><li>Revogar permissoes do aplicativo a qualquer momento via <a href="https://www.facebook.com/settings?tab=applications" target="_blank">Configuracoes do Facebook -> Aplicativos</a></li><li>Solicitar exclusao de qualquer dado de sessao em cache via nossa pagina de <a href="/delete">Exclusao de Dados</a></li><li>Entrar em contato pelo e-mail <a href="mailto:falecom@mariomello.com.br">falecom@mariomello.com.br</a></li></ul><h2>6. Contato</h2><p>Betelgeuse Servicos de TI<br>CNPJ: 51.770.524/0001-87<br>E-mail: <a href="mailto:falecom@mariomello.com.br">falecom@mariomello.com.br</a><br>Endereco: Navegantes, SC, Brasil</p><div class="footer">&copy; 2026 Betelgeuse Servicos de TI - <a href="/">Voltar ao App</a> - <a href="/terms">Termos</a> - <a href="/delete">Exclusao de Dados</a></div></body></html>"""

TERMS_HTML = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Termos de Uso - Betelgeuse TI</title><style>body{font-family:Inter,system-ui;max-width:800px;margin:40px auto;padding:0 24px;line-height:1.7;color:#1c1e21}h1{color:#1877f2}h2{color:#333;margin-top:32px;font-size:18px}.badge{background:#fff3e0;color:#e65100;padding:4px 12px;border-radius:12px;font-size:12px;font-weight:600}.footer{margin-top:40px;padding-top:20px;border-top:1px solid #ddd;color:#65676b;font-size:13px}a{color:#1877f2}</style></head><body><h1>Termos de Uso</h1><p><span class="badge">Efetivo: 30 de maio de 2026</span></p><p><strong>Betelgeuse Servicos de TI</strong> - CNPJ 51.770.524/0001-87</p><h2>1. Descricao do Servico</h2><p>O Moderador de Comentarios Betelgeuse TI e uma ferramenta em tempo real que permite aos administradores de Paginas do Facebook visualizar e monitorar comentarios publicos em publicacoes que gerenciam.</p><h2>2. Elegibilidade</h2><p>Voce deve ter pelo menos 18 anos de idade e ser administrador da Pagina do Facebook que deseja monitorar.</p><h2>3. Uso Permitido</h2><p>Voce concorda em usar este servico exclusivamente para:</p><ul><li>Monitorar e moderar comentarios em Paginas do Facebook que voce administra</li><li>Melhorar os tempos de resposta ao atendimento ao cliente</li></ul><p>Voce NAO pode usar este servico para:</p><ul><li>Acessar Paginas que voce nao administra</li><li>Fazer scraping ou download em massa de dados de usuarios</li><li>Usar dados de comentarios para treinar modelos de IA/ML</li><li>Compartilhar conteudo de usuarios com terceiros nao autorizados</li></ul><h2>4. Processamento de Dados</h2><p>Todo o processamento de dados ocorre em tempo real. Nao armazenamos dados de usuarios do Facebook em nossos servidores.</p><h2>5. Rescisao</h2><p>Podemos suspender o acesso por violacoes destes termos ou das Politicas da Plataforma do Facebook. Voce pode encerrar o uso a qualquer momento desconectando o aplicativo nas Configuracoes do Facebook.</p><h2>6. Legislacao Aplicavel</h2><p>Estes termos sao regidos pelas leis do Brasil. As disputas serao resolvidas nos tribunais de Navegantes, SC.</p><h2>7. Contato</h2><p>E-mail: <a href="mailto:falecom@mariomello.com.br">falecom@mariomello.com.br</a></p><div class="footer">&copy; 2026 Betelgeuse Servicos de TI - <a href="/">Voltar ao App</a> - <a href="/privacy">Privacidade</a> - <a href="/delete">Exclusao de Dados</a></div></body></html>"""

DELETE_HTML = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Exclusao de Dados - Betelgeuse TI</title><style>body{font-family:Inter,system-ui;max-width:800px;margin:40px auto;padding:0 24px;line-height:1.7;color:#1c1e21}h1{color:#1877f2}h2{color:#333;margin-top:32px;font-size:18px}.badge{background:#ffebee;color:#c62828;padding:4px 12px;border-radius:12px;font-size:12px;font-weight:600}.success{background:#e8f5e9;border:1px solid #a5d6a7;color:#2e7d32;padding:16px;border-radius:12px;margin:16px 0}.footer{margin-top:40px;padding-top:20px;border-top:1px solid #ddd;color:#65676b;font-size:13px}a{color:#1877f2}.btn{background:#1877f2;color:#fff;border:0;padding:12px 24px;border-radius:10px;font-weight:600;cursor:pointer;text-decoration:none;display:inline-block}</style></head><body><h1>Solicitacao de Exclusao de Dados</h1><p><span class="badge">Conforme LGPD / GDPR</span></p><p><strong>Betelgeuse Servicos de TI</strong> - CNPJ 51.770.524/0001-87</p><h2>Como Excluir Seus Dados</h2><div class="success"><strong>Boa noticia:</strong> Nosso aplicativo nao armazena nenhum dado pessoal em nossos servidores. Todos os dados do Facebook sao processados em tempo real e existem apenas durante sua sessao ativa do navegador.</div><h2>Passos Imediatos (Instantaneo)</h2><ol><li><strong>Revogar Acesso do App:</strong> Acesse <a href="https://www.facebook.com/settings?tab=applications" target="_blank">Configuracoes do Facebook -> Aplicativos e Sites</a>, encontre "Betelgeuse TI Moderador de Comentarios" e clique em "Remover".</li><li><strong>Limpar Sessao:</strong> Clique em <a href="/logout" class="btn" style="margin-left:8px">Sair do App</a> para limpar sua sessao atual.</li></ol><h2>Contato para Confirmacao</h2><p>Se desejar confirmacao por escrito de que nenhum dado e retido, entre em contato:</p><ul><li>E-mail: <a href="mailto:falecom@mariomello.com.br">falecom@mariomello.com.br</a></li><li>Assunto: <code>Solicitacao de Exclusao de Dados - [Seu ID ou E-mail do Facebook]</code></li><li>Prazo de resposta: Ate 48 horas (dias uteis)</li></ul><h2>Direitos Legais</h2><p>De acordo com a LGPD brasileira e o GDPR europeu, voce tem o direito ao esquecimento. Como nao armazenamos dados pessoais, o cumprimento e imediato apos a remocao do aplicativo.</p><div class="footer">&copy; 2026 Betelgeuse Servicos de TI - <a href="/">Voltar ao App</a> - <a href="/privacy">Privacidade</a> - <a href="/terms">Termos</a></div></body></html>"""

DATAUSE_HTML = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Acordo de Uso de Dados - Betelgeuse TI</title><style>body{font-family:Inter,system-ui;max-width:800px;margin:40px auto;padding:0 24px;line-height:1.7;color:#1c1e21}h1{color:#1877f2}h2{color:#333;margin-top:32px;font-size:18px}.badge{background:#e8f5e9;color:#2e7d32;padding:4px 12px;border-radius:12px;font-size:12px;font-weight:600}.footer{margin-top:40px;padding-top:20px;border-top:1px solid #ddd;color:#65676b;font-size:13px}a{color:#1877f2}</style></head><body><h1>Acordo de Uso de Dados</h1><p><span class="badge">Termos Suplementares da Plataforma Meta</span></p><p><strong>Betelgeuse Servicos de TI</strong> - CNPJ 51.770.524/0001-87</p><h2>1. Finalidade do Uso de Dados</h2><p>Usamos dados da Plataforma Facebook exclusivamente para <strong>moderacao de comentarios em tempo real em Paginas do Facebook administradas pelo usuario autenticado</strong>.</p><h2>2. Dados que Acessamos</h2><table style="width:100%;border-collapse:collapse;margin:16px 0"><tr style="background:#f5f6f7"><th style="text-align:left;padding:12px;border:1px solid #ddd">Permissao</th><th style="text-align:left;padding:12px;border:1px solid #ddd">Dados Acessados</th><th style="text-align:left;padding:12px;border:1px solid #ddd">Uso</th></tr><tr><td style="padding:12px;border:1px solid #ddd"><code>pages_show_list</code></td><td style="padding:12px;border:1px solid #ddd">Nome, ID e categoria da Pagina</td><td style="padding:12px;border:1px solid #ddd">Exibir lista de Paginas que o usuario gerencia</td></tr><tr><td style="padding:12px;border:1px solid #ddd"><code>pages_read_engagement</code></td><td style="padding:12px;border:1px solid #ddd">ID, mensagem, created_time, permalink da publicacao</td><td style="padding:12px;border:1px solid #ddd">Listar publicacoes para o usuario selecionar</td></tr><tr><td style="padding:12px;border:1px solid #ddd"><code>pages_read_user_content</code></td><td style="padding:12px;border:1px solid #ddd">Nome do autor, ID do autor, mensagem, created_time, like_count do comentario</td><td style="padding:12px;border:1px solid #ddd">Exibir comentarios para moderacao</td></tr></table><h2>3. Usos Proibidos</h2><p>Nos comprometemos expressamente a NAO:</p><ul><li>Armazenar dados de usuarios do Facebook alem da sessao ativa</li><li>Usar dados para fins publicitarios ou de marketing</li><li>Vender, alugar ou transferir dados para terceiros</li><li>Usar conteudo de comentarios para treinar IA ou ML</li><li>Acessar Paginas nao administradas pelo usuario autenticado</li></ul><h2>4. Conformidade</h2><p>Cumprimos os Termos da Plataforma Meta, os Termos de Processamento de Dados Meta, a LGPD brasileira e o GDPR europeu.</p><h2>5. Contato</h2><p>E-mail: <a href="mailto:falecom@mariomello.com.br">falecom@mariomello.com.br</a></p><div class="footer">&copy; 2026 Betelgeuse Servicos de TI - <a href="/">Voltar ao App</a> - <a href="/privacy">Privacidade</a> - <a href="/terms">Termos</a> - <a href="/delete">Exclusao de Dados</a></div></body></html>"""

@app.route("/privacy")
def privacy():
    return PRIVACY_HTML

@app.route("/terms")
def terms():
    return TERMS_HTML

@app.route("/delete")
def delete_data():
    return DELETE_HTML

@app.route("/data-use")
def data_use():
    return DATAUSE_HTML
@app.route('/debug-ssl')
def debug_ssl():
    import subprocess, ssl, socket
    results = {}
    try:
        result = subprocess.run(['openssl', 'version'], capture_output=True, text=True, timeout=5)
        results['openssl_version'] = result.stdout.strip()
    except Exception as e:
        results['openssl_version'] = f"ERROR: {str(e)}"
    results['python_ssl_version'] = ssl.OPENSSL_VERSION
    try:
        sock = socket.create_connection(("graph.facebook.com", 443), timeout=10)
        results['tcp_connect_443'] = "OK"
        sock.close()
    except Exception as e:
        results['tcp_connect_443'] = f"FAILED: {str(e)}"
    try:
        import requests
        resp = requests.get("https://graph.facebook.com/v19.0/me?access_token=TESTE", verify=False, timeout=15)
        results['requests_verify_false'] = f"Status: {resp.status_code} | Body: {resp.text[:100]}"
    except Exception as e:
        results['requests_verify_false'] = f"FAILED: {type(e).__name__}: {str(e)}"
    try:
        import requests
        resp = requests.get("https://graph.facebook.com/v19.0/me?access_token=TESTE", timeout=15)
        results['requests_verify_true'] = f"Status: {resp.status_code}"
    except Exception as e:
        results['requests_verify_true'] = f"FAILED: {type(e).__name__}: {str(e)}"
    token = session.get('tok', 'NO_TOKEN')
    try:
        import requests
        resp = requests.get("https://graph.facebook.com/v19.0/me/accounts", params={"access_token": token, "fields": "name,id"}, timeout=15)
        results['me_accounts_real'] = f"Status: {resp.status_code} | Body: {resp.text[:200]}"
    except Exception as e:
        results['me_accounts_real'] = f"FAILED: {type(e).__name__}: {str(e)}"
    output = "=== DEBUG SSL - Betelgeuse API ===\n\n"
    for key, value in results.items():
        output += f"[{key}]\n{value}\n\n"
    return f"<pre>{output}</pre>", 200, {'Content-Type': 'text/html; charset=utf-8'}

@app.route("/health")
def health():
    return jsonify({"status":"ok","service":"betelgeuse-comment-moderator","version":"3.3","page_id":BETELGEUSE_PAGE_ID})

if __name__=="__main__":
    app.run(host="0.0.0.0",port=7860)
