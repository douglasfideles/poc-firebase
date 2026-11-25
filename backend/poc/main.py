"""Ponto de entrada do uvicorn: `uvicorn poc.main:app`."""
import os

from .app import criar_app
from .config import carregar

app = criar_app(carregar(), web_dir=os.environ.get("WEB_DIR", "/srv/web"))
