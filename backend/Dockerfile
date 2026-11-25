# Contexto de build: a raiz do repositório.
FROM python:3.11-slim AS base
WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/srv/backend
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/poc backend/poc
COPY pagina web
COPY instituicoes.yaml .
RUN useradd -r -u 10001 poc && mkdir /dados && chown poc /dados
USER poc
EXPOSE 8088
CMD ["uvicorn", "poc.main:app", "--host", "0.0.0.0", "--port", "8088"]

FROM base AS testes
USER root
COPY backend/requirements-dev.txt backend/requirements-dev.txt
RUN pip install --no-cache-dir -r backend/requirements-dev.txt
COPY tests tests
COPY projecao.py .
USER poc
CMD ["pytest", "-q", "-p", "no:cacheprovider", "tests/unit", "tests/rotas"]
