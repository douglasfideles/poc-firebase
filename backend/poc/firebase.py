"""Tudo o que fala com o Firebase Authentication passa por aqui (Admin SDK).

Quatro operações: verificar o ID token, garantir a conta, gravar os claims e emitir o custom token.
"""
from __future__ import annotations

import hashlib

import firebase_admin
from firebase_admin import auth, credentials

from .config import Config

# O backend só emite custom token para os logins que ele mesmo prova.
PREFIXOS_CUSTOM = ("ldap:", "cafe:", "oidc:")
TAMANHO_MAXIMO_UID = 128  # limite do Firebase


class TokenInvalido(Exception):
    pass


_app: firebase_admin.App | None = None


def iniciar(cfg: Config) -> None:
    """Inicia o Admin SDK com a chave de serviço do projeto."""
    global _app
    if _app is None:
        _app = firebase_admin.initialize_app(
            credentials.Certificate(cfg.credencial), options={"projectId": cfg.projeto})


def verificar_id_token(token: str) -> dict:
    """Confere assinatura, emissor, audiência e validade do ID token do Firebase.

    A verificação é local, com as chaves públicas do Google em cache: não gasta cota.
    A folga de 10 s cobre a diferença de relógio entre este servidor e o Google.
    """
    try:
        claims = auth.verify_id_token(token, app=_app, clock_skew_seconds=10)
    except Exception as e:
        raise TokenInvalido(type(e).__name__) from e
    if not claims.get("uid"):
        raise TokenInvalido("sem uid")
    return claims


def uid_custom(metodo: str, inst: str, sujeito: str) -> str:
    """O uid da conta no Firebase para um login que o backend prova: `metodo:instituição:sujeito`.

    O identificador que vem de fora pode ser longo demais para o Firebase; nesse caso entra o resumo.
    """
    sujeito = sujeito.strip()
    uid = f"{metodo}:{inst}:{sujeito}"
    if len(uid) > TAMANHO_MAXIMO_UID:
        uid = f"{metodo}:{inst}:{hashlib.sha256(sujeito.encode()).hexdigest()}"
    return uid


def garantir_usuario(uid: str, nome: str) -> None:
    """Cria a conta no Firebase se ainda não existe.

    Sem e-mail, de propósito: o e-mail de um login LDAP, CAFe ou do login único fica só no nosso
    banco, para o Firebase não fundir essa conta com um login Google ou Microsoft do mesmo endereço.
    """
    try:
        atual = auth.get_user(uid, app=_app)
        if nome and atual.display_name != nome:
            auth.update_user(uid, display_name=nome, app=_app)
    except auth.UserNotFoundError:
        auth.create_user(uid=uid, display_name=nome or None, app=_app)


def gravar_claims(uid: str, inst: str | None, papel: str, estado: str) -> None:
    """Grava a instituição ativa, o papel e o estado na conta. Entram no próximo ID token.

    Limite do Firebase: 1.000 bytes. Aqui vão três campos curtos.
    """
    auth.set_custom_user_claims(uid, {"inst": inst, "papel": papel, "estado": estado}, app=_app)


def emitir_custom_token(uid: str) -> str:
    """Emite o token que o navegador troca por uma sessão do Firebase (vale 1 hora, uso único).

    Sem claims dentro dele: claims embutidos no custom token passariam por cima dos gravados.
    """
    if not uid.startswith(PREFIXOS_CUSTOM) or len(uid) > TAMANHO_MAXIMO_UID:
        raise ValueError("custom token só para uid ldap:, cafe: ou oidc:")
    return _assinar_custom_token(uid)


def _assinar_custom_token(uid: str) -> str:
    token = auth.create_custom_token(uid, app=_app)
    return token.decode() if isinstance(token, bytes) else token


def encerrar_sessoes(uid: str) -> None:
    """Invalida os refresh tokens da conta: o navegador não consegue mais renovar o ID token."""
    auth.revoke_refresh_tokens(uid, app=_app)


def apagar_contas(uids: list[str]) -> None:
    """Apaga contas criadas pelos testes. Só as que o backend criou (ldap:, cafe: e oidc:)."""
    alvo = [u for u in uids if u.startswith(PREFIXOS_CUSTOM)]
    for i in range(0, len(alvo), 1000):
        auth.delete_users(alvo[i:i + 1000], app=_app)
