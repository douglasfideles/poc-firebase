"""Ponte entre o SP SAML da CAFe (Django, já existe no app) e o Firebase.

O SP atual termina o SAML assinando um JWT HS256 de 120 s com os atributos da pessoa
(`app/backend/auth/base/views.py`, `saml_login_complete`). Aqui esse JWT é validado e a pessoa
recebe um custom token do Firebase. O formato do JWT é o mesmo do app, para o encaixe ser direto.

Diferenças em relação ao `cafe_finish` de hoje: segredo próprio (não o da sessão), cada token só
vale uma vez, e o CPF que o SP envia é descartado.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Callable

import jwt

VALIDADE_MAXIMA_S = 300


class PonteInvalida(Exception):
    pass


@dataclass(frozen=True)
class AtributosCafe:
    eppn: str
    email: str | None
    nome: str
    afiliacao: str


def validar(token: str, segredo: str, registrar_uso: Callable[[str, float], bool]) -> AtributosCafe:
    """Confere assinatura e validade, e recusa o token que já foi usado."""
    try:
        p = jwt.decode(token, segredo, algorithms=["HS256"],
                       options={"require": ["exp", "iat"]})
    except jwt.PyJWTError as e:
        raise PonteInvalida(type(e).__name__) from e

    if float(p["exp"]) - float(p["iat"]) > VALIDADE_MAXIMA_S:
        raise PonteInvalida("validade longa demais")

    eppn = (p.get("username") or "").strip().lower()
    if eppn.count("@") != 1 or eppn.startswith("@") or eppn.endswith("@"):
        raise PonteInvalida("sem eduPersonPrincipalName")

    if not registrar_uso(hashlib.sha256(token.encode()).hexdigest(), float(p["exp"])):
        raise PonteInvalida("token já usado")

    nome = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip() or eppn
    # `br_person_cpf` vem no token do SP e não é lido: o login não precisa do CPF.
    return AtributosCafe(
        eppn=eppn,
        email=(p.get("email") or "").strip().lower() or None,
        nome=nome,
        afiliacao=p.get("edu_person_affiliation") or "",
    )


def emitir_demo(eppn: str, email: str, nome: str, sobrenome: str, segredo: str,
                validade_s: int = 120, agora: float | None = None) -> str:
    """Faz o papel do SP nos testes: emite o JWT no mesmo formato de `saml_login_complete`."""
    agora = time.time() if agora is None else agora
    return jwt.encode(
        {
            "username": eppn,
            "email": email,
            "first_name": nome,
            "last_name": sobrenome,
            "edu_person_affiliation": "member",
            "br_person_cpf": "00000000000",
            "iat": int(agora),
            "exp": int(agora) + validade_s,
        },
        segredo,
        algorithm="HS256",
    )
