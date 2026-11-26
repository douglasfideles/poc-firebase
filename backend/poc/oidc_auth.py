"""Login único da própria instituição, por OpenID Connect (Keycloak, ADFS, Shibboleth com OIDC...).

O Firebase só fala OIDC genérico com o upgrade para Identity Platform, que é pago por usuário. Aqui
quem fala com o provedor da instituição é o backend: ele leva a pessoa até lá, recebe o código,
troca pelo ID token e confere a assinatura. O Firebase só recebe o resultado, num custom token, como
no LDAP e na CAFe. A senha nunca passa pelo nosso código: ela é digitada na tela da instituição.

É o fluxo de código de autorização com PKCE. O que se confere no ID token: assinatura com as chaves
publicadas pelo emissor, emissor igual ao cadastrado, audiência igual ao nosso `client_id`, validade
e o `nonce` que este backend gerou para aquele login.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

import httpx
import jwt

from .config import OidcCfg

ALGORITMOS = ("RS256", "RS384", "RS512", "PS256", "ES256", "ES384")  # nunca `none` nem HS*
TEMPO_LIMITE_S = 5
VALIDADE_CACHE_S = 600
TAMANHO_MAXIMO_SUJEITO = 255


class OidcIndisponivel(Exception):
    """O provedor da instituição não respondeu, ou respondeu algo que não dá para usar."""


class OidcInvalido(Exception):
    """O provedor respondeu, mas o login não pode ser aceito."""


@dataclass(frozen=True)
class AtributosOidc:
    sujeito: str  # o `sub`: identificador estável da pessoa naquele provedor
    email: str | None
    email_verificado: bool
    nome: str


def novo_par_pkce() -> tuple[str, str]:
    """(verificador, desafio). O desafio vai na ida; o verificador, só na troca do código."""
    verificador = secrets.token_urlsafe(48)
    resumo = hashlib.sha256(verificador.encode()).digest()
    return verificador, base64.urlsafe_b64encode(resumo).rstrip(b"=").decode()


class ClienteOidc:
    def __init__(self, http: httpx.Client | None = None) -> None:
        # Sem seguir redirecionamento: o provedor não manda o backend para outro endereço.
        self.http = http or httpx.Client(timeout=TEMPO_LIMITE_S, follow_redirects=False)
        self._trava = threading.Lock()
        self._cache: dict[str, tuple[dict, float]] = {}

    # ------------------------------------------------------------------ rede
    def _json(self, endereco: str, chave_cache: str | None = None) -> dict:
        if chave_cache:
            with self._trava:
                guardado = self._cache.get(chave_cache)
            if guardado and guardado[1] > time.monotonic():
                return guardado[0]
        try:
            r = self.http.get(endereco)
            if r.status_code != 200:
                raise OidcIndisponivel(f"HTTP {r.status_code}")
            dados = r.json()
        except OidcIndisponivel:
            raise
        except Exception as e:
            raise OidcIndisponivel(type(e).__name__) from e
        if not isinstance(dados, dict):
            raise OidcIndisponivel("resposta que não é um objeto")
        if chave_cache:
            with self._trava:
                self._cache[chave_cache] = (dados, time.monotonic() + VALIDADE_CACHE_S)
        return dados

    def descoberta(self, cfg: OidcCfg) -> dict:
        """O documento de descoberta do provedor, com os endereços conferidos."""
        doc = self._json(f"{cfg.emissor}/.well-known/openid-configuration",
                         f"descoberta:{cfg.emissor}")
        # Um documento que declara outro emissor é de outro provedor. A barra no fim não conta
        # aqui: há provedor que a publica e provedor que não. No token, o `iss` tem de ser
        # exatamente o que a descoberta publicou (ver `concluir`).
        if not isinstance(doc.get("issuer"), str) or doc["issuer"].rstrip("/") != cfg.emissor:
            raise OidcIndisponivel("o emissor da descoberta não é o cadastrado")
        esquema = urlsplit(cfg.emissor).scheme
        for campo in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            partes = urlsplit(str(doc.get(campo, "")))
            # Com emissor https, nenhum endereço do provedor pode ser http.
            if not partes.hostname or partes.scheme not in ("https", esquema):
                raise OidcIndisponivel(f"{campo} ausente ou inseguro")
        return doc

    def _chave(self, cfg: OidcCfg, doc: dict, id_token: str):
        try:
            cabecalho = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as e:
            raise OidcInvalido("ID token ilegível") from e
        if cabecalho.get("alg") not in ALGORITMOS:
            raise OidcInvalido("algoritmo de assinatura não aceito")
        kid = cabecalho.get("kid")
        chave_cache = f"jwks:{doc['jwks_uri']}"
        for tentativa in (1, 2):
            try:
                chaves = jwt.PyJWKSet.from_dict(self._json(doc["jwks_uri"], chave_cache)).keys
            except jwt.PyJWTError as e:
                raise OidcIndisponivel("chaves do provedor ilegíveis") from e
            candidatas = [k for k in chaves if kid is None or k.key_id == kid]
            if len(candidatas) == 1:
                return candidatas[0].key
            # Chave desconhecida: o provedor pode ter trocado as chaves. Busca de novo, uma vez.
            with self._trava:
                self._cache.pop(chave_cache, None)
        raise OidcInvalido("o ID token não foi assinado por uma chave do provedor")

    # ------------------------------------------------------------------ ida
    def endereco_de_login(self, cfg: OidcCfg, retorno: str, estado: str, nonce: str,
                          desafio: str) -> str:
        doc = self.descoberta(cfg)
        consulta = urlencode({
            "response_type": "code", "client_id": cfg.client_id, "redirect_uri": retorno,
            "scope": cfg.escopos, "state": estado, "nonce": nonce,
            "code_challenge": desafio, "code_challenge_method": "S256",
        })
        separador = "&" if "?" in doc["authorization_endpoint"] else "?"
        return f"{doc['authorization_endpoint']}{separador}{consulta}"

    # ------------------------------------------------------------------ volta
    def concluir(self, cfg: OidcCfg, retorno: str, codigo: str, verificador: str, nonce: str,
                 segredo: str = "") -> AtributosOidc:
        """Troca o código pelo ID token, confere tudo e devolve os dados da pessoa."""
        doc = self.descoberta(cfg)
        corpo = {"grant_type": "authorization_code", "code": codigo, "redirect_uri": retorno,
                 "code_verifier": verificador}
        # Com segredo, o cliente se identifica pelo cabeçalho; sem segredo, pelo corpo (cliente público).
        autenticacao = (cfg.client_id, segredo) if segredo else None
        if not segredo:
            corpo["client_id"] = cfg.client_id
        try:
            r = self.http.post(doc["token_endpoint"], data=corpo, auth=autenticacao)
        except Exception as e:
            raise OidcIndisponivel(type(e).__name__) from e
        if r.status_code >= 500:
            raise OidcIndisponivel(f"HTTP {r.status_code}")
        try:
            resposta = r.json()
        except Exception:
            resposta = {}
        if not isinstance(resposta, dict):
            resposta = {}
        id_token = resposta.get("id_token") if r.status_code == 200 else None
        if not isinstance(id_token, str) or not id_token:
            # O código de erro do provedor (invalid_client, invalid_grant...) ajuda quem configura.
            motivo = "".join(ch for ch in str(resposta.get("error", ""))[:40]
                             if ch.isascii() and (ch.isalnum() or ch == "_"))
            raise OidcInvalido(f"o provedor não entregou o ID token ({motivo or r.status_code})")

        chave = self._chave(cfg, doc, id_token)
        try:
            c = jwt.decode(id_token, chave, algorithms=list(ALGORITMOS), audience=cfg.client_id,
                           issuer=doc["issuer"], leeway=10,
                           options={"require": ["exp", "iat", "iss", "aud", "sub"]})
        except Exception as e:  # assinatura, validade, emissor, audiência, chave de outro tipo
            raise OidcInvalido(type(e).__name__) from e

        # Token com mais de uma audiência só vale se foi emitido para nós (`azp`).
        if isinstance(c["aud"], list) and len(c["aud"]) > 1 and c.get("azp") != cfg.client_id:
            raise OidcInvalido("o ID token foi emitido para outro cliente")
        # O nonce amarra o token ao login que este backend começou.
        if not hmac.compare_digest(str(c.get("nonce", "")).encode(), nonce.encode()):
            raise OidcInvalido("nonce não confere")

        sujeito = str(c["sub"]).strip()
        if not sujeito or len(sujeito) > TAMANHO_MAXIMO_SUJEITO:
            raise OidcInvalido("sujeito ausente ou longo demais")
        email = str(c.get("email") or "").strip().lower() or None
        return AtributosOidc(
            sujeito=sujeito,
            email=email,
            email_verificado=c.get("email_verified") is True,
            nome=str(c.get("name") or c.get("preferred_username") or "").strip(),
        )
