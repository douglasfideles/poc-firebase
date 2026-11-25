"""Apoio dos testes de rota: um substituto do Firebase e os tokens que o navegador traria.

Os testes de `tests/rotas` exercitam o backend inteiro (rotas, regra de entrada, banco, LDAP de
teste), mas não o Firebase: as quatro chamadas ao Admin SDK são trocadas por `FirebaseSubstituto`.
Eles provam o nosso código. O que o Firebase faz de verdade é provado em `tests/firebase_real`.

Os tokens do Google e da Microsoft são assinados com uma chave RSA local e conferidos pelo
verificador de produção.
"""
from __future__ import annotations

import base64
import json
import time

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from poc import firebase as fb

PROJETO = "iotedu-teste"
ORIGEM = "http://localhost:8088"
TID_UNIA = "11111111-1111-4111-8111-111111111111"
CHAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _b64(d: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()


def claims_de(id_token: str) -> dict:
    meio = id_token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(meio + "=" * (-len(meio) % 4)))


class FirebaseSubstituto:
    """Guarda o que o backend pediu ao Firebase e emite ID tokens como o Firebase emitiria."""

    def __init__(self) -> None:
        self.contas: dict[str, str] = {}
        self.claims: dict[str, dict] = {}
        self.revogados: list[str] = []

    # ---- o que o backend chama (no lugar do Admin SDK)
    def verificar(self, token: str) -> dict:
        try:
            c = claims_de(token)
        except Exception as e:
            raise fb.TokenInvalido("ilegível") from e
        if c.get("aud") != PROJETO or float(c.get("exp", 0)) <= time.time():
            raise fb.TokenInvalido("recusado")
        return {**c, "uid": c["sub"]}

    def garantir(self, uid: str, nome: str) -> None:
        self.contas[uid] = nome

    def gravar(self, uid: str, inst, papel: str, estado: str) -> None:
        self.claims[uid] = {"inst": inst, "papel": papel, "estado": estado}

    def assinar(self, uid: str) -> str:
        return f"custom:{uid}"

    def encerrar(self, uid: str) -> None:
        self.revogados.append(uid)

    # ---- o que o navegador receberia do Firebase
    def id_token(self, uid: str, provedor: str, identidades: dict, com_claims: bool = True,
                 **mudancas) -> str:
        agora = int(time.time())
        corpo = {"iss": f"https://securetoken.google.com/{PROJETO}", "aud": PROJETO, "sub": uid,
                 "user_id": uid, "iat": agora, "exp": agora + 3600, "auth_time": agora,
                 "firebase": {"sign_in_provider": provedor, "identities": identidades}}
        if com_claims:
            corpo.update(self.claims.get(uid, {}))
        corpo.update(mudancas)
        return f"{_b64({'alg': 'RS256', 'typ': 'JWT'})}.{_b64(corpo)}.assinatura"

    def trocar_custom(self, custom_token: str) -> dict:
        """O `signInWithCustomToken` do SDK web: devolve o ID token da conta."""
        uid = custom_token.removeprefix("custom:")
        assert uid in self.contas, "o backend emitiu custom token sem criar a conta"
        return {"idToken": self.id_token(uid, "custom", {}), "localId": uid}

    def instalar(self, monkeypatch) -> None:
        monkeypatch.setattr(fb, "iniciar", lambda cfg: None)
        monkeypatch.setattr(fb, "verificar_id_token", self.verificar)
        monkeypatch.setattr(fb, "garantir_usuario", self.garantir)
        monkeypatch.setattr(fb, "gravar_claims", self.gravar)
        monkeypatch.setattr(fb, "_assinar_custom_token", self.assinar)
        monkeypatch.setattr(fb, "encerrar_sessoes", self.encerrar)
        monkeypatch.setattr(fb, "apagar_contas", lambda uids: None)


def token_google(sub: str, email: str, hd: str | None, verificado: bool = True) -> str:
    agora = int(time.time())
    c = {"iss": "https://accounts.google.com", "aud": "cid-google", "sub": sub, "email": email,
         "email_verified": verificado, "name": "Ana Teste", "iat": agora, "exp": agora + 600}
    if hd:
        c["hd"] = hd
    return jwt.encode(c, CHAVE, algorithm="RS256")


def token_microsoft(oid: str, email: str, tid: str) -> str:
    agora = int(time.time())
    return jwt.encode(
        {"iss": f"https://login.microsoftonline.com/{tid}/v2.0", "aud": "cid-ms", "sub": "s-" + oid,
         "oid": oid, "tid": tid, "email": email, "name": "Ana Teste", "iat": agora,
         "exp": agora + 600}, CHAVE, algorithm="RS256")
