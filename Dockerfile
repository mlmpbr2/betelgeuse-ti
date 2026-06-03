# Betelgeuse TI – Comment Moderation
# Docker Space para Hugging Face
# Porta padrão: 7860

FROM python:3.11-slim

# Evita prompts interativos
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Instala dependências do sistema + SSL atualizado
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    ca-certificates \
    openssl \
    libssl-dev \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Cria usuário não-root (requerido para Dev Mode no HF)
RUN useradd -m -u 1000 user

# Diretório de trabalho
WORKDIR /app

# Copia e instala dependências primeiro (cache Docker)
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# Copia o restante do código
COPY --chown=user . /app

# Cria pasta assets se não existir
RUN mkdir -p /app/assets

# Forçar certificados SSL atualizados para Python/requests
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# Porta exposta
EXPOSE 7860

# Switch para usuário não-root
USER user

# Variáveis de ambiente do usuário
ENV HOME=/home/user
ENV PATH=/home/user/.local/bin:$PATH

# Comando de inicialização com Gunicorn (produção)
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "--workers", "2", "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-", "app:app"]