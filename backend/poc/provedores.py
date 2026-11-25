"""Verifica o ID token do provedor (Google ou Microsoft) que o navegador envia junto com o do Firebase.

O ID token do Firebase não carrega o `hd` do Google nem o `tid` da Microsoft, que são as provas
de que a conta é da instituição. O navegador recebe o ID token do provedor no popup e o envia ao
backend, que só o aceita com assinatura, `aud`, `iss` e `exp` conferidos.

O verificador usa as chaves públicas do provedor. Não existe caminho que aceite token sem assinatura.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

import jwt
from jwt import PyJWKClient

JWKS_GOOGLE = "https://www.googleapis.com/oauth2/v3/certs"
JWKS_MICROSOFT = "https://login.microsoftonline.com/common/discovery/v2.0/keys"
EMISSORES_GOOGLE = ("https://accounts.google.com", "accounts.google.com")

# Nome do provedor para o Firebase -> nome usado nas regras.
PROVEDORES = {"google.com": "google", "microsoft.com": "microsoft"}


class TokenDeProvedorInvalido(Exception):
    pass


@dataclass(frozen=True)
class ClaimsProvedor:
    provedor: str
    sujeito: str  # tem de ser igual ao id federado que o Firebase guardou
    email: str | None
    email_verificado: bool
    hd: str | None
    tid: str | None
    nome: str


class VerificadorProvedor(Protocol):
    def verificar(self, provedor_firebase: str, id_token: str) -> ClaimsProvedor: ...


def _montar(provedor_firebase: str, c: dict, sujeito: str) -> ClaimsProvedor:
    return ClaimsProvedor(
        provedor=PROVEDORES[provedor_firebase],
        sujeito=sujeito,
        email=(c.get("email") or c.get("preferred_username") or None),
        email_verificado=bool(c.get("email_verified")),
        hd=(c.get("hd") or None),
        tid=(c.get("tid") or None),
        nome=c.get("name") or "",
    )


class VerificadorJWKS:
    """Confere assinatura, audiência, emissor e validade com as chaves do provedor."""

    def __init__(
        self,
        google_client_id: str | None,
        ms_client_id: str | None,
        obter_chave: Callable[[str, str], object] | None = None,
    ) -> None:
        self._aud = {"google.com": google_client_id, "microsoft.com": ms_client_id}
        self._clientes = {
            "google.com": PyJWKClient(JWKS_GOOGLE, cache_keys=True),
            "microsoft.com": PyJWKClient(JWKS_MICROSOFT, cache_keys=True),
        }
        self._obter_chave = obter_chave or self._chave_do_jwks

    def _chave_do_jwks(self, provedor_firebase: str, id_token: str):
        return self._clientes[provedor_firebase].get_signing_key_from_jwt(id_token).key

    def verificar(self, provedor_firebase: str, id_token: str) -> ClaimsProvedor:
        if provedor_firebase not in PROVEDORES:
            raise TokenDeProvedorInvalido("provedor não aceito")
        aud = self._aud[provedor_firebase]
        if not aud:
            raise TokenDeProvedorInvalido("client id do provedor não configurado")
        try:
            chave = self._obter_chave(provedor_firebase, id_token)
            c = jwt.decode(
                id_token,
                chave,
                algorithms=["RS256"],
                audience=aud,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except Exception as e:  # assinatura, validade, audiência, chave desconhecida
            raise TokenDeProvedorInvalido(type(e).__name__) from e

        if provedor_firebase == "google.com":
            if c["iss"] not in EMISSORES_GOOGLE:
                raise TokenDeProvedorInvalido("emissor não é o Google")
            return _montar(provedor_firebase, c, c["sub"])

        # Microsoft: o emissor tem de ser o do próprio diretório que o token declara.
        tid = c.get("tid")
        if not tid or c["iss"] != f"https://login.microsoftonline.com/{tid}/v2.0":
            raise TokenDeProvedorInvalido("emissor não bate com o diretório (tid)")
        oid = c.get("oid")
        if not oid:
            raise TokenDeProvedorInvalido("token da Microsoft sem oid")
        # O Firebase guarda o `oid` como id federado da conta Microsoft, não o `sub`.
        return _montar(provedor_firebase, c, oid)
