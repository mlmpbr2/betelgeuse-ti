import os
import logging
from flask import Flask, redirect, request, session, render_template_string, send_from_directory, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix
import requests
import pandas as pd
from datetime import datetime

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(message)s', handlers=[logging.StreamHandler()])
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.secret_key = os.environ.get("SECRET_KEY", "Betelgeuse-2026-Secure")

APP_ID = os.environ.get("META_APP_ID", "877709481915236")
APP_SECRET = os.environ.get("META_APP_SECRET", "3bf01b88362dac1be1bb62999af4a5e2")
GRAPH = "https://graph.facebook.com/v19.0"

# ============================================================
# ROTA DE DIAGNÓSTICO — TESTA CONECTIVIDADE COM FACEBOOK
# ============================================================
@app.route("/diagnostico")
def diagnostico():
    import socket
    import urllib.request
    import time
    import json

    resultados = []

    # Teste 1: DNS resolution
    try:
        ip = socket.gethostbyname('graph.facebook.com')
        resultados.append(f"✅ DNS: graph.facebook.com -> {ip}")
    except Exception as e:
        resultados.append(f"❌ DNS FAIL: {e}")
        ip = None

    # Teste 2: TCP connection na porta 443
    if ip:
        try:
            s = socket.create_connection((ip, 443), timeout=5)
            resultados.append("✅ TCP 443: conexão aberta com sucesso")
            s.close()
        except Exception as e:
            resultados.append(f"❌ TCP 443 FAIL: {e}")
    else:
        resultados.append("⚠️ TCP 443: pulado (DNS falhou)")

    # Teste 3: HTTPS GET com timing
    try:
        req = urllib.request.Request('https://graph.facebook.com/v19.0/me?access_token=test', method='GET')
        start = time.time()
        with urllib.request.urlopen(req, timeout=10) as resp:
            elapsed = time.time() - start
            body = resp.read(300).decode('utf-8', errors='replace')
            resultados.append(f"✅ HTTPS: status={resp.status} em {elapsed:.2f}s")
            resultados.append(f"   Body: {body[:200]}")
    except urllib.error.HTTPError as e:
        elapsed = time.time() - start if 'start' in dir() else 0
        resultados.append(f"⚠️ HTTPS HTTPError: {e.code} em ~{elapsed:.2f}s (isso é NORMAL — token era inválido)")
    except Exception as e:
        resultados.append(f"❌ HTTPS FAIL: {type(e).__name__}: {str(e)[:200]}")

    # Teste 4: requests library (a mesma usada no app)
    try:
        start = time.time()
        r = requests.get("https://graph.facebook.com/v19.0/me", params={"access_token": "test"}, timeout=10)
        elapsed = time.time() - start
        resultados.append(f"⚠️ requests: status={r.status_code} em {elapsed:.2f}s (token inválido = esperado)")
    except requests.exceptions.Timeout:
        resultados.append(f"❌ requests TIMEOUT após 10s")
    except requests.exceptions.ConnectionError as e:
        resultados.append(f"❌ requests CONNECTION ERROR: {str(e)[:150]}")
    except Exception as e:
        resultados.append(f"❌ requests FAIL: {type(e).__name__}: {str(e)[:150]}")

    # Teste 5: Variáveis de ambiente
    resultados.append(f"📋 APP_ID: {'✅ configurado' if os.getenv('META_APP_ID') else '❌ ausente'}")
    resultados.append(f"📋 APP_SECRET: {'✅ configurado' if os.getenv('META_APP_SECRET') else '❌ ausente'}")
    resultados.append(f"📋 REDIRECT_URI: {os.environ.get('REDIRECT_URI', 'usando default do request')}")

    # Teste 6: Info do request atual
    resultados.append(f"📋 Host do request: {request.host}")
    resultados.append(f"📋 Scheme: {request.scheme}")
    resultados.append(f"📋 X-Forwarded-Proto: {request.headers.get('X-Forwarded-Proto', 'n/a')}")

    return "<h2>🔬 Diagnóstico NavegAI / Betelgeuse</h2><hr>" + "<br>".join(resultados)


# ============================================================
# ROTAS ORIGINAIS DO APP (preservadas)
# ============================================================

@app.route("/")
def index():
    """Página inicial com link de login."""
    user = session.get("user")
    if user:
        return render_template_string("""
            <h2>✅ Logado como {{ user.name }}</h2>
            <p><a href="/dashboard">Ir para Dashboard</a></p>
            <p><a href="/logout">Sair</a></p>
        """, user=user)
    return render_template_string("""
        <h2>🔐 NavegAI / Betelgeuse — Login</h2>
        <p><a href="/login">Entrar com Facebook</a></p>
        <p><a href="/diagnostico">🔬 Diagnóstico de Conexão</a></p>
    """)


@app.route("/login")
def login():
    """Inicia fluxo OAuth com Facebook."""
    redirect_uri = os.environ.get("REDIRECT_URI")
    if not redirect_uri:
        # Fallback: constrói a partir do request
        redirect_uri = request.url_root.rstrip("/") + "/login/callback"

    logger.info(f"LOGIN: redirect_uri={redirect_uri}")

    scope = "pages_read_engagement,pages_read_user_content,public_profile"
    auth_url = (
        f"https://www.facebook.com/v19.0/dialog/oauth"
        f"?client_id={APP_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={scope}"
    )

    logger.info(f"LOGIN: full_url={auth_url[:120]}...")
    return redirect(auth_url)


@app.route("/login/callback")
def callback():
    """Recebe o code do Facebook e troca por access_token."""
    error = request.args.get("error")
    error_code = request.args.get("error_code")
    error_message = request.args.get("error_message")

    logger.info("=== CALLBACK ===")

    redirect_uri = os.environ.get("REDIRECT_URI")
    if not redirect_uri:
        redirect_uri = request.url_root.rstrip("/") + "/login/callback"

    logger.info(f"redirect_uri used: {redirect_uri}")
    logger.info(f"Full URL: {request.url}")
    logger.info(f"Args: {dict(request.args)}")
    logger.info(f"Headers: Host={request.headers.get('Host')}, X-Fwd-Host={request.headers.get('X-Forwarded-Host')}, X-Fwd-Proto={request.headers.get('X-Forwarded-Proto')}")

    if error or error_code:
        logger.error(f"Facebook error: {error_code} - {error_message}")
        return f"<h2>❌ Erro Facebook</h2><p>Código: {error_code}</p><p>{error_message}</p><p><a href='/'>Voltar</a></p>", 400

    code = request.args.get("code")
    if not code:
        return "<h2>❌ Código de autorização não recebido</h2><p><a href='/'>Voltar</a></p>", 400

    # Troca code por access_token
    token_url = f"{GRAPH}/oauth/access_token"
    params = {
        "client_id": APP_ID,
        "client_secret": APP_SECRET,
        "redirect_uri": redirect_uri,
        "code": code,
    }

    try:
        logger.info(f"Trocando code por token...")
        resp = requests.get(token_url, params=params, timeout=30)
        logger.info(f"Token response: {resp.status_code}")
        data = resp.json()

        if "access_token" not in data:
            logger.error(f"Token error: {data}")
            return f"<h2>❌ Falha ao obter token</h2><pre>{data}</pre>", 400

        session["access_token"] = data["access_token"]

        # Busca info do usuário
        me_resp = requests.get(
            f"{GRAPH}/me",
            params={"access_token": data["access_token"], "fields": "id,name"},
            timeout=30
        )
        user = me_resp.json()
        session["user"] = user
        logger.info(f"Usuário logado: {user.get('name', 'unknown')}")

        return redirect("/dashboard")

    except requests.exceptions.Timeout:
        logger.error("TIMEOUT ao trocar code por token")
        return "<h2>⏱️ Timeout</h2><p>A conexão com Facebook demorou demais. Tente novamente.</p><p><a href='/diagnostico'>Ver diagnóstico</a></p>", 504
    except Exception as e:
        logger.error(f"Erro no callback: {e}")
        return f"<h2>❌ Erro interno</h2><p>{e}</p>", 500


@app.route("/dashboard")
def dashboard():
    """Dashboard principal após login."""
    if "access_token" not in session:
        return redirect("/")

    token = session["access_token"]
    user = session.get("user", {})

    try:
        # Busca páginas do usuário
        pages_resp = requests.get(
            f"{GRAPH}/me/accounts",
            params={"access_token": token},
            timeout=30
        )
        pages = pages_resp.json().get("data", [])

        return render_template_string("""
            <h2>📊 Dashboard — {{ user.name }}</h2>
            <h3>Páginas gerenciadas:</h3>
            <ul>
            {% for page in pages %}
                <li><a href="/page/{{ page.id }}">{{ page.name }}</a></li>
            {% else %}
                <li>Nenhuma página encontrada</li>
            {% endfor %}
            </ul>
            <p><a href="/logout">Sair</a></p>
        """, user=user, pages=pages)

    except Exception as e:
        logger.error(f"Erro no dashboard: {e}")
        return f"<h2>❌ Erro ao carregar dashboard</h2><p>{e}</p>", 500


@app.route("/page/<page_id>")
def page_detail(page_id):
    """Detalhes de uma página com comentários."""
    if "access_token" not in session:
        return redirect("/")

    token = session["access_token"]

    try:
        # Busca posts da página
        posts_resp = requests.get(
            f"{GRAPH}/{page_id}/posts",
            params={"access_token": token, "fields": "id,message,created_time"},
            timeout=30
        )
        posts = posts_resp.json().get("data", [])

        # Busca comentários de cada post
        all_comments = []
        for post in posts[:5]:  # Limita a 5 posts
            comments_resp = requests.get(
                f"{GRAPH}/{post['id']}/comments",
                params={"access_token": token, "fields": "id,message,from,created_time"},
                timeout=30
            )
            comments = comments_resp.json().get("data", [])
            for c in comments:
                all_comments.append({
                    "post_id": post["id"],
                    "post_message": post.get("message", "")[:100],
                    "comment_id": c["id"],
                    "comment_message": c.get("message", ""),
                    "from": c.get("from", {}).get("name", "Anônimo"),
                    "created_time": c.get("created_time", "")
                })

        df = pd.DataFrame(all_comments)

        return render_template_string("""
            <h2>💬 Comentários da Página</h2>
            <p>Total de comentários: {{ count }}</p>
            <table border="1" cellpadding="5">
                <tr><th>De</th><th>Comentário</th><th>Post</th><th>Data</th></tr>
                {% for _, row in df.iterrows() %}
                <tr>
                    <td>{{ row.from }}</td>
                    <td>{{ row.comment_message }}</td>
                    <td>{{ row.post_message }}</td>
                    <td>{{ row.created_time }}</td>
                </tr>
                {% endfor %}
            </table>
            <p><a href="/dashboard">Voltar</a></p>
        """, df=df, count=len(all_comments))

    except Exception as e:
        logger.error(f"Erro na página {page_id}: {e}")
        return f"<h2>❌ Erro</h2><p>{e}</p>", 500


@app.route("/logout")
def logout():
    """Limpa a sessão."""
    session.clear()
    return redirect("/")


# ============================================================
# EXECUÇÃO
# ============================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860, debug=True)