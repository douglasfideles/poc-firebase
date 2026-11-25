# Navegador sem tela (Chromium) para conferir a página de ponta a ponta.
FROM python:3.11-slim
# libatomic1: o node que vem com o Playwright precisa dela.
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 \
 && pip install --no-cache-dir playwright==1.* httpx==0.28.1 \
 && playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /navegador
COPY conferir.py .
CMD ["python", "conferir.py"]
