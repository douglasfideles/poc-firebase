"""Login único simulado. Só existe com AMBIENTE_DE_TESTE=1.

Faz o papel do provedor OIDC de uma instituição (o Keycloak dela, por exemplo): publica a
descoberta e as chaves, mostra uma tela de login, entrega o código e o troca por um ID token
assinado. O protocolo é o de verdade, com PKCE; a pessoa e a senha é que são de mentira.

Serve para o `oidc_auth.py` ser exercitado de ponta a ponta sem depender de um provedor externo.
"""
from __future__ import annotations

import base64
import hashlib
import html
import secrets
import threading
import time
from urllib.parse import parse_qs, urlencode

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .config import CAMINHO_OIDC_SIMULADO, CLIENTE_OIDC_SIMULADO, Config

VALIDADE_CODIGO_S = 60
KID = "simulado-1"


class ProvedorSimulado:
    def __init__(self, cfg: Config) -> None:
        self.emissor = f"{cfg.origem_front}{CAMINHO_OIDC_SIMULADO}"
        self.retorno = f"{cfg.origem_front}/api/auth/oidc/callback"
        self.chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._trava = threading.Lock()
        self._codigos: dict[str, tuple[dict, float]] = {}

    def jwks(self) -> dict:
        jwk = jwt.algorithms.RSAAlgorithm.to_jwk(self.chave.public_key(), as_dict=True)
        return {"keys": [{**jwk, "kid": KID, "use": "sig", "alg": "RS256"}]}

    def guardar(self, pedido: dict) -> str:
        codigo = secrets.token_urlsafe(24)
        with self._trava:
            self._codigos[codigo] = (pedido, time.time() + VALIDADE_CODIGO_S)
        return codigo

    def resgatar(self, codigo: str) -> dict | None:
        """Cada código vale uma vez."""
        with self._trava:
            pedido, expira = self._codigos.pop(codigo, ({}, 0.0))
        return pedido if pedido and expira >= time.time() else None

    def id_token(self, pedido: dict, **mudancas) -> str:
        agora = int(time.time())
        corpo = {"iss": self.emissor, "aud": pedido["client_id"], "sub": pedido["sub"],
                 "email": pedido["email"], "email_verified": pedido["email_verificado"],
                 "name": pedido["nome"], "nonce": pedido["nonce"], "iat": agora, "exp": agora + 300}
        corpo.update(mudancas)
        return jwt.encode(corpo, self.chave, algorithm="RS256", headers={"kid": KID})

    def limpar(self) -> None:
        with self._trava:
            self._codigos.clear()


def instalar(app: FastAPI, cfg: Config) -> ProvedorSimulado:
    p = ProvedorSimulado(cfg)
    base = CAMINHO_OIDC_SIMULADO

    @app.get(f"{base}/.well-known/openid-configuration")
    def descoberta() -> dict:
        return {"issuer": p.emissor, "authorization_endpoint": f"{p.emissor}/authorize",
                "token_endpoint": f"{p.emissor}/token", "jwks_uri": f"{p.emissor}/jwks",
                "response_types_supported": ["code"], "subject_types_supported": ["public"],
                "id_token_signing_alg_values_supported": ["RS256"],
                "code_challenge_methods_supported": ["S256"]}

    @app.get(f"{base}/jwks")
    def jwks() -> dict:
        return p.jwks()

    def conferir_pedido(q) -> dict:
        if (q.get("client_id") != CLIENTE_OIDC_SIMULADO or q.get("redirect_uri") != p.retorno
                or q.get("response_type") != "code" or q.get("code_challenge_method") != "S256"
                or not q.get("code_challenge") or not q.get("state") or not q.get("nonce")):
            raise HTTPException(status_code=400, detail="Pedido de login inválido.")
        return {k: q[k] for k in ("response_type", "client_id", "redirect_uri", "state", "nonce",
                                  "code_challenge", "code_challenge_method")}

    @app.get(f"{base}/authorize", response_class=HTMLResponse)
    def tela(request: Request) -> str:
        pedido = conferir_pedido(request.query_params)
        ocultos = "".join(f"<input type='hidden' name='{html.escape(k)}' value='{html.escape(v)}'>"
                          for k, v in pedido.items())
        return ("<!doctype html><meta charset='utf-8'><title>Login único simulado</title>"
                "<body style='font-family:sans-serif;max-width:28rem;margin:2rem auto'>"
                "<h1>Login único simulado</h1><p>Esta tela só existe no ambiente de teste. Ela faz o "
                "papel do login único de uma universidade (um Keycloak, por exemplo).</p>"
                f"<form method='post'>{ocultos}"
                "<p><label>Identificador (sub)<br><input name='sub' value='d-0001' size='32'>"
                "</label></p><p><label>Nome<br><input name='nome' value='Davi Teste' size='32'>"
                "</label></p><p><label>E-mail<br><input name='email' value='davi@unid.test' "
                "size='32'></label></p><p><label><input type='checkbox' name='verificado' checked "
                "style='width:auto'> E-mail verificado pela universidade</label></p>"
                "<button>Entrar</button></form></body>")

    @app.post(f"{base}/authorize")
    async def entrar(request: Request) -> RedirectResponse:
        f = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}
        pedido = conferir_pedido(f)
        if not f.get("sub"):
            raise HTTPException(status_code=400, detail="Falta o identificador.")
        pedido.update(sub=f["sub"], nome=f.get("nome", ""), email=f.get("email", ""),
                      email_verificado="verificado" in f)
        codigo = p.guardar(pedido)
        return RedirectResponse(
            f"{p.retorno}?{urlencode({'code': codigo, 'state': pedido['state']})}", status_code=303)

    @app.post(f"{base}/token")
    async def token(request: Request) -> JSONResponse:
        f = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}
        pedido = p.resgatar(f.get("code", ""))
        desafio = base64.urlsafe_b64encode(
            hashlib.sha256(f.get("code_verifier", "").encode()).digest()).rstrip(b"=").decode()
        if (pedido is None or f.get("grant_type") != "authorization_code"
                or f.get("client_id") != pedido["client_id"]
                or f.get("redirect_uri") != pedido["redirect_uri"]
                or desafio != pedido["code_challenge"]):
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        return JSONResponse({"token_type": "Bearer", "expires_in": 300,
                             "access_token": secrets.token_urlsafe(16),
                             "id_token": p.id_token(pedido)})

    return p
