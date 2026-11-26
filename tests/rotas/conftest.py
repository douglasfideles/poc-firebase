import os
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from poc.app import criar_app
from poc.config import carregar
from poc.provedores import VerificadorJWKS
from tests.apoio import CHAVE, ORIGEM, PROJETO, FirebaseSubstituto

PONTE = "p" * 48


@dataclass
class Ambiente:
    app: object
    fb: FirebaseSubstituto

    def cliente(self, origem: str | None = ORIGEM) -> TestClient:
        """Um navegador: guarda cookies e manda a origem do painel."""
        return TestClient(self.app, base_url=ORIGEM, headers={"Origin": origem} if origem else {})


@pytest.fixture
def amb(monkeypatch, tmp_path) -> Ambiente:
    substituto = FirebaseSubstituto()
    substituto.instalar(monkeypatch)
    chave = tmp_path / "conta.json"
    chave.write_text("{}")
    cfg = carregar({
        "FIREBASE_PROJECT_ID": PROJETO, "GOOGLE_APPLICATION_CREDENTIALS": str(chave),
        "FIREBASE_WEB_API_KEY": "chave-web", "FIREBASE_AUTH_DOMAIN": f"{PROJETO}.firebaseapp.com",
        "GOOGLE_WEB_CLIENT_ID": "cid-google", "MS_CLIENT_ID": "cid-ms",
        "SESSAO_SEGREDO": "s" * 48, "CAFE_PONTE_SEGREDO": PONTE, "ORIGEM_FRONT": ORIGEM,
        "AMBIENTE_DE_TESTE": "1", "DB_CAMINHO": str(tmp_path / "poc.sqlite3"),
        "INSTITUICOES_ARQUIVO": os.environ["INSTITUICOES_ARQUIVO"],
    })
    verificador = VerificadorJWKS("cid-google", "cid-ms", obter_chave=lambda p, t: CHAVE.public_key())
    app = criar_app(cfg, verificador=verificador)
    # O backend fala com o login único simulado por HTTP. Nos testes, esse HTTP cai no próprio app.
    app.state.oidc.http = TestClient(app, base_url=ORIGEM)
    return Ambiente(app, substituto)
