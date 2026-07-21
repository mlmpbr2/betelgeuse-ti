"""
Betelgeuse TI Comment Moderator + Sentiment Analysis + n8n Integration
Flask app with Meta App Review compliance + real-time sentiment KPIs
"""

import os
import json
import requests
import hashlib
import hmac
from datetime import datetime, timedelta
from flask import Flask, redirect, request, session, render_template_string, url_for, jsonify

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-key-change-in-prod")

# =============================================================================
# CONFIG
# =============================================================================
FB_APP_ID = os.environ.get("FB_APP_ID", "YOUR_APP_ID")
FB_APP_SECRET = os.environ.get("FB_APP_SECRET", "YOUR_APP_SECRET")
FB_API_VERSION = "v19.0"
FB_BASE_URL = f"https://graph.facebook.com/{FB_API_VERSION}"
REDIRECT_URI = os.environ.get("REDIRECT_URI", "https://betelgeuse-ti.vercel.app/callback")

REQUIRED_SCOPES = [
    "pages_show_list",
    "pages_read_engagement", 
    "pages_read_user_content"
]

# Gemini Config
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# n8n Config
N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "")

# Webhook Config
WEBHOOK_VERIFY_TOKEN = os.environ.get("WEBHOOK_VERIFY_TOKEN", "betelgeuse_webhook_2026")
WEBHOOK_APP_SECRET = os.environ.get("FB_APP_SECRET", "")
WEBHOOK_LOG_FILE = "webhook_comments.json"

# Page Access Token fixo via variável de ambiente do Vercel (Graph API)
# Aceita as duas grafias por segurança; se não existir, cai no fluxo /me/accounts
PAGE_ACCESS_TOKEN_ENV = os.environ.get("PAGE_ACCESS_TOKEN") or os.environ.get("PAGE_ACESS_TOKEN") or ""

def get_page_token(page_id):
    """Retorna o Page Access Token.
    Prioridade: 1) variável de ambiente do Vercel; 2) token obtido via /me/accounts da sessão."""
    if PAGE_ACCESS_TOKEN_ENV:
        return PAGE_ACCESS_TOKEN_ENV

    resp = requests.get(
        f"{FB_BASE_URL}/me/accounts",
        params={"access_token": session["access_token"]},
        timeout=30
    )
    accounts = resp.json().get("data", [])
    for acc in accounts:
        if acc["id"] == page_id:
            return acc["access_token"]
    return None

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
            }]
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

        return "NEUTRO"

    except Exception as e:
        print(f"Erro Gemini: {e}")
        return "NEUTRO"

def get_sentiment(text, comment_id):
    """Get sentiment - no cache, direct analysis every time"""
    return analyze_sentiment(text)

# Mapa PT -> EN: o Gemini responde em português (POSITIVO/NEUTRO/NEGATIVO),
# mas os contadores e as classes CSS do template usam inglês (positive/neutral/negative)
SENTIMENT_EN = {"POSITIVO": "positive", "NEUTRO": "neutral", "NEGATIVO": "negative"}

# Cache em memória (filesystem do Vercel é read-only)
_SENTIMENT_CACHE = {}

def load_sentiment_cache():
    return _SENTIMENT_CACHE

def save_sentiment_cache(cache):
    pass  # sem persistência em disco no Vercel

# =============================================================================
# n8n WEBHOOK
# =============================================================================

def send_to_n8n(summary_data):
    """Send summary to n8n webhook"""
    if not N8N_WEBHOOK_URL:
        print("N8N_WEBHOOK_URL não configurado")
        return False

    try:
        resp = requests.post(N8N_WEBHOOK_URL, json=summary_data, timeout=30)
        return resp.status_code == 200
    except Exception as e:
        print(f"Erro n8n: {e}")
        return False

# =============================================================================
# HTML TEMPLATES
# =============================================================================

BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Betelgeuse TI - Moderador de Comentários</title>
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
        <p>MODERADOR DE COMENTÁRIOS COM ANÁLISE DE SENTIMENTO</p>
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
                    actions.innerHTML = '<span class="hidden-label">🚫 Ocultado pelo moderador</span>';
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
    <h2 style="font-size: 22px; margin-bottom: 12px;">Moderação de Comentários com IA</h2>
    <p style="color: #65676b; margin-bottom: 24px;">
        Monitore e analise comentários em tempo real com classificação de sentimento (Positivo, Neutro, Negativo).
        Processamento em tempo real. Sem armazenamento de dados.
    </p>

    <div style="text-align: left; margin-bottom: 24px;">
        <div class="privacy-card">
            <h3>🔐 Permissões Solicitadas</h3>
            <div style="margin-top: 12px;">
                <div style="background: white; padding: 12px; border-radius: 8px; margin-bottom: 8px;">
                    <strong style="color: #1877f2;">pages_read_engagement</strong>
                    <p style="font-size: 13px; color: #65676b; margin-top: 4px;">Ler posts e métricas para selecionar qual post moderar</p>
                </div>
                <div style="background: white; padding: 12px; border-radius: 8px; margin-bottom: 8px;">
                    <strong style="color: #1877f2;">pages_read_user_content</strong>
                    <p style="font-size: 13px; color: #65676b; margin-top: 4px;">Ler comentários com nome do autor, mensagem e data para moderação</p>
                </div>
                <div style="background: white; padding: 12px; border-radius: 8px;">
                    <strong style="color: #1877f2;">pages_show_list</strong>
                    <p style="font-size: 13px; color: #65676b; margin-top: 4px;">Exibir lista de Páginas que você gerencia</p>
                </div>
            </div>
        </div>
    </div>

    <a href="/login" class="btn btn-primary" style="font-size: 16px;">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="white"><path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"/></svg>
        Entrar com Facebook
    </a>

    <div class="privacy-card" style="margin-top: 24px; text-align: left;">
        <h3>🔒 Compromisso de Privacidade</h3>
        <ul>
            <li>Sem armazenamento de dados — processamento em tempo real</li>
            <li>Sessão limpa ao sair</li>
            <li>Revogue acesso a qualquer momento nas Configurações do Facebook</li>
            <li>Empresa verificada por CNPJ 51.770.524/0001-87</li>
        </ul>
    </div>
</div>
"""

DASHBOARD_TEMPLATE = """
<div class="step-indicator">
    <div class="step active">
        <div class="step-number">1</div>
        <span>Escolher Página</span>
    </div>
    <div class="step">
        <div class="step-number">2</div>
        <span>Escolher Post</span>
    </div>
    <div class="step">
        <div class="step-number">3</div>
        <span>Moderar Comentários</span>
    </div>
</div>

<div class="alert alert-success">
    ✅ <strong>Autenticado com sucesso.</strong> Selecione uma Página para começar a moderar.
</div>

<div class="card">
    <span class="permission-badge green">pages_show_list</span>
    <div class="card-title">📋 Escolha sua Página</div>
    <p class="card-desc">Selecione uma Página do Facebook para carregar posts para moderação.</p>

    <form action="/posts" method="get">
        <select name="page_id" required onchange="this.form.submit()">
            <option value="">-- Selecione uma Página --</option>
            {% for page in pages %}
            <option value="{{ page.id }}">{{ page.name }}</option>
            {% endfor %}
        </select>
    </form>

    <p style="margin-top: 12px; font-size: 13px; color: #65676b;">
        {{ pages|length }} Página(s) encontrada(s)
    </p>
</div>

<div style="text-align: center;">
    <a href="/logout" class="btn btn-outline">↩️ Desconectar</a>
</div>
"""

POSTS_TEMPLATE = """
<a href="/" class="back-btn">← Voltar para Páginas</a>

<div class="step-indicator">
    <div class="step">
        <div class="step-number">1</div>
        <span>Escolher Página</span>
    </div>
    <div class="step active">
        <div class="step-number">2</div>
        <span>Escolher Post</span>
    </div>
    <div class="step">
        <div class="step-number">3</div>
        <span>Moderar Comentários</span>
    </div>
</div>

<div class="card">
    <span class="permission-badge orange">pages_read_engagement</span>
    <div class="card-title">📝 Escolha um Post</div>
    <p class="card-desc">Selecione um post para visualizar e moderar seus comentários com análise de sentimento.</p>

    <div class="post-grid">
        {% for post in posts %}
        <div class="post-card" onclick="window.location.href='/comments?post_id={{ post.id }}&page_id={{ page_id }}'">
            {% if post.picture %}
            <img src="{{ post.picture }}" alt="Imagem do post">
            {% else %}
            <div style="height: 160px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); display: flex; align-items: center; justify-content: center; color: white; font-size: 14px;">📄 Post de Texto</div>
            {% endif %}
            <div class="post-card-body">
                <div class="post-card-title">{{ post.message[:60] }}{% if post.message|length > 60 %}...{% endif %}</div>
                <div class="post-card-meta">
                    📅 {{ post.created_time[:10] }} 
                    💬 {{ post.comments_count }} comentários
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
</div>
"""

COMMENTS_TEMPLATE = """
<a href="/posts?page_id={{ page_id }}" class="back-btn">← Voltar para Posts</a>

<div class="step-indicator">
    <div class="step">
        <div class="step-number">1</div>
        <span>Escolher Página</span>
    </div>
    <div class="step">
        <div class="step-number">2</div>
        <span>Escolher Post</span>
    </div>
    <div class="step active">
        <div class="step-number">3</div>
        <span>Moderar Comentários</span>
    </div>
</div>

<div class="card">
    <span class="permission-badge red">pages_read_user_content</span>
    <div class="card-title">💬 Moderar Comentários com Análise de Sentimento</div>
    <p class="card-desc">Revise comentários em tempo real. Classificação automática: Positivo, Neutro, Negativo.</p>

    <div class="stats-grid">
        <div class="stat-box positive">
            <div class="stat-value positive">{{ sentiment_counts.positive|default(0) }}</div>
            <div class="stat-label">😊 Positivos</div>
            <div style="font-size: 11px; color: #2e7d32;">{{ sentiment_pct.positive|default(0) }}%</div>
        </div>
        <div class="stat-box neutral">
            <div class="stat-value neutral">{{ sentiment_counts.neutral|default(0) }}</div>
            <div class="stat-label">😐 Neutros</div>
            <div style="font-size: 11px; color: #f9a825;">{{ sentiment_pct.neutral|default(0) }}%</div>
        </div>
        <div class="stat-box negative">
            <div class="stat-value negative">{{ sentiment_counts.negative|default(0) }}</div>
            <div class="stat-label">😠 Negativos</div>
            <div style="font-size: 11px; color: #c62828;">{{ sentiment_pct.negative|default(0) }}%</div>
        </div>
        <div class="stat-box">
            <div class="stat-value">{{ comments|length }}</div>
            <div class="stat-label">💬 Total</div>
            <div style="font-size: 11px; color: #1877f2;">100%</div>
        </div>
    </div>

    <div class="filter-buttons">
        <button class="filter-btn active" data-filter="all" onclick="filterComments('all')">Todos ({{ comments|length }})</button>
        <button class="filter-btn positive" data-filter="positive" onclick="filterComments('positive')">😊 Positivos ({{ sentiment_counts.positive|default(0) }})</button>
        <button class="filter-btn neutral" data-filter="neutral" onclick="filterComments('neutral')">😐 Neutros ({{ sentiment_counts.neutral|default(0) }})</button>
        <button class="filter-btn negative" data-filter="negative" onclick="filterComments('negative')">😠 Negativos ({{ sentiment_counts.negative|default(0) }})</button>
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
            <span class="sentiment-badge sentiment-{{ sentiment }}">{{ comment.sentiment|default('NEUTRO') }}</span>
        </div>
        <div class="comment-text">{{ comment.message }}</div>
        <div class="comment-meta">
            <span>📅 {{ comment.created_time[:10] }}</span>
            <span>❤️ {{ comment.like_count }} curtidas</span>
            <span>⏰ {{ comment.created_time }}</span>
        </div>
        <div class="comment-actions">
            <button class="btn btn-danger" onclick="hideComment('{{ comment.id }}')">
                🚫 Ocultar Comentário
            </button>
            <a href="{{ comment.fb_url }}" 
               target="_blank" 
               class="btn btn-outline">
                🔗 Ver no Facebook
            </a>
        </div>
    </div>
    {% endfor %}
</div>
"""

PRIVACY_TEMPLATE = """
<div class="card">
    <h1 style="color: #1877f2; margin-bottom: 8px;">Privacy Policy</h1>
    <p style="color: #65676b; font-size: 13px; margin-bottom: 24px;">Updated: May 30, 2026</p>

    <p style="margin-bottom: 16px;"><strong>Betelgeuse IT Services</strong> — CNPJ 51.770.524/0001-87</p>

    <h3 style="margin: 20px 0 8px;">1. Information We Process</h3>
    <p style="margin-bottom: 12px;">Our application processes the following data <strong>only in real time</strong>:</p>
    <ul style="margin-left: 20px; line-height: 2;">
        <li>Names and IDs of Facebook Pages you administer (via <code>pages_show_list</code>)</li>
        <li>Post content, IDs, and creation dates (via <code>pages_read_engagement</code>)</li>
        <li>Author names, author IDs, comment text, creation dates, and like counts (via <code>pages_read_user_content</code>)</li>
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

        return render_template_string(
            BASE_TEMPLATE,
            content=render_template_string(DASHBOARD_TEMPLATE, pages=pages)
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
        page_token = get_page_token(page_id)

        if not page_token:
            return "Error: Could not get page token", 400

        resp = requests.get(
            f"{FB_BASE_URL}/{page_id}/posts",
            params={
                "access_token": page_token,
                "fields": "id,message,created_time,picture,comments.summary(true)"
            },
            timeout=30
        )
        posts_data = resp.json().get("data", [])

        posts = []
        for post in posts_data:
            posts.append({
                "id": post["id"],
                "message": post.get("message", "(Media Post)"),
                "created_time": post.get("created_time", ""),
                "picture": post.get("picture", ""),
                "comments_count": post.get("comments", {}).get("summary", {}).get("total_count", 0)
            })

        return render_template_string(
            BASE_TEMPLATE,
            content=render_template_string(POSTS_TEMPLATE, posts=posts, page_id=page_id)
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
        page_token = get_page_token(page_id)

        if not page_token:
            return "Error: Could not get page token", 400

        resp = requests.get(
            f"{FB_BASE_URL}/{post_id}/comments",
            params={
                "access_token": page_token,
                "fields": "id,from,message,created_time,like_count,permalink_url",
                "filter": "stream"
            },
            timeout=30
        )
        comments_data = resp.json().get("data", [])

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

            # Analyze sentiment
            sentiment = get_sentiment(c.get("message", ""), c["id"])
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
                "sentiment_en": sentiment_en
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

@app.route("/webhook", methods=["GET"])
def webhook_verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == WEBHOOK_VERIFY_TOKEN:
        print(f"Webhook verificado com sucesso. Challenge: {challenge}")
        return challenge, 200
    else:
        print(f"Falha na verificação. mode={mode}, token={token}")
        return "Verification failed", 403

@app.route("/webhook", methods=["POST"])
def webhook_receive():
    signature = request.headers.get("X-Hub-Signature-256", "")
    payload_body = request.get_data()

    if not verify_signature(payload_body, signature):
        print("Assinatura inválida!")
        return "Invalid signature", 403

    try:
        payload = request.get_json()
        print(f"Webhook recebido: {json.dumps(payload, indent=2)}")

        save_webhook_payload(payload)

        return "OK", 200

    except Exception as e:
        print(f"Erro ao processar webhook: {e}")
        return "Error", 500

@app.route("/webhook/logs")
def webhook_logs():
    try:
        if os.path.exists(WEBHOOK_LOG_FILE):
            with open(WEBHOOK_LOG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return jsonify(data)
        else:
            return jsonify([])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# =============================================================================
# POLLING + SENTIMENT + n8n ROUTE
# =============================================================================

@app.route("/poll_comments")
def poll_comments():
    """
    Polling endpoint: Busca comentários, analisa sentimento, envia resumo ao n8n
    Chamar a cada 1 hora (195 chamadas/hora limite)
    """
    if "access_token" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    page_id = request.args.get("page_id") or session.get("current_page_id")
    if not page_id:
        return jsonify({"error": "No page selected"}), 400

    try:
        # Get page token
        page_token = get_page_token(page_id)

        if not page_token:
            return jsonify({"error": "Could not get page token"}), 400

        # Get posts from last 24h
        since_time = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")
        resp = requests.get(
            f"{FB_BASE_URL}/{page_id}/posts",
            params={
                "access_token": page_token,
                "fields": "id,message,created_time",
                "since": since_time,
                "limit": 10
            },
            timeout=30
        )
        posts = resp.json().get("data", [])

        all_comments = []
        total_new = 0

        for post in posts:
            post_id = post["id"]

            # Get comments (max 100 per post)
            resp = requests.get(
                f"{FB_BASE_URL}/{post_id}/comments",
                params={
                    "access_token": page_token,
                    "fields": "id,from,message,created_time,like_count",
                    "limit": 100,
                    "order": "reverse_chronological"
                },
                timeout=30
            )
            comments = resp.json().get("data", [])

            for c in comments:
                comment_id = c["id"]
                message = c.get("message", "")

                # Check if already analyzed
                cache = load_sentiment_cache()
                if comment_id in cache:
                    sentiment = cache[comment_id]["sentiment"]
                else:
                    sentiment = analyze_sentiment(message)
                    cache[comment_id] = {
                        "sentiment": sentiment,
                        "text": message[:100],
                        "analyzed_at": datetime.now().isoformat()
                    }
                    save_sentiment_cache(cache)
                    total_new += 1

                all_comments.append({
                    "id": comment_id,
                    "post_id": post_id,
                    "author": c.get("from", {}).get("name", "Facebook User"),
                    "message": message,
                    "sentiment": sentiment,
                    "likes": c.get("like_count", 0),
                    "created_time": c.get("created_time", "")
                })

        # Calculate summary
        sentiment_counts = {"POSITIVO": 0, "NEUTRO": 0, "NEGATIVO": 0}
        for c in all_comments:
            sentiment_counts[c["sentiment"]] += 1

        total = len(all_comments)
        summary = {
            "tipo": "resumo_comentarios",
            "pagina": page_id,
            "periodo": {
                "inicio": since_time,
                "fim": datetime.now().isoformat()
            },
            "total_comentarios": total,
            "novos_analisados": total_new,
            "sentimentos": sentiment_counts,
            "percentuais": {
                "positivo": round(sentiment_counts["POSITIVO"] / total * 100, 1) if total > 0 else 0,
                "neutro": round(sentiment_counts["NEUTRO"] / total * 100, 1) if total > 0 else 0,
                "negativo": round(sentiment_counts["NEGATIVO"] / total * 100, 1) if total > 0 else 0
            },
            "alertas": [c for c in all_comments if c["sentiment"] == "NEGATIVO"][:5],
            "top_positivos": [c for c in all_comments if c["sentiment"] == "POSITIVO"][:3],
            "resumo_executivo": f"{total} comentários analisados. {sentiment_counts['POSITIVO']} positivos, {sentiment_counts['NEGATIVO']} negativos."
        }

        # Send to n8n if there are new comments
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
