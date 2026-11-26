"""Regra de entrada: quem prova pelo login que é da instituição entra na hora; os outros ficam pendentes.

Sem I/O. É a decisão D33 do resumo de decisões, com uma prova diferente para cada provedor:

- Google: o claim `hd` do ID token do Google (domínio do Workspace). O e-mail sozinho não serve.
- Microsoft: o `tid` (diretório do Entra ID). Nunca o e-mail: o diretório de qualquer organização
  pode afirmar qualquer e-mail.
- LDAP: o bind deu certo no diretório cadastrado para aquela instituição.
- CAFe: o escopo do eduPersonPrincipalName (o que vem depois do @).
- Login único da instituição (OIDC): o token veio assinado pelo emissor cadastrado para ela.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .config import Instituicao

ATIVO = "ativo"
PENDENTE = "pendente"
RECUSADO = "recusado"

# Diretório das contas Microsoft pessoais (outlook.com, hotmail.com). Não é de instituição nenhuma.
TID_CONTA_PESSOAL = "9188040d-6c67-4c5b-b112-36a304b66dad"


@dataclass(frozen=True)
class ProvaLogin:
    provedor: str  # google | microsoft | ldap | cafe | oidc
    sujeito: str  # identificador estável dentro do provedor
    nome: str = ""
    email: str | None = None
    email_verificado: bool = False
    hd: str | None = None
    tid: str | None = None
    inst_ldap: str | None = None
    eppn: str | None = None
    inst_oidc: str | None = None


@dataclass(frozen=True)
class Decisao:
    estado: str
    inst: str | None
    motivo: str
    # E-mail que o login provou. None quando o provedor só afirmou o e-mail.
    email_provado: str | None = None


def _dominio(endereco: str | None) -> str | None:
    if not endereco or endereco.count("@") != 1:
        return None
    return endereco.rsplit("@", 1)[1].strip().lower() or None


def _email_da_instituicao(email: str | None, inst: Instituicao) -> str | None:
    """Só aceita como provado o e-mail que está num domínio da própria instituição."""
    return email.strip().lower() if _dominio(email) in inst.dominios else None


def _achar(insts: Mapping[str, Instituicao], campo: str, valor: str | None) -> Instituicao | None:
    if not valor:
        return None
    valor = valor.strip().lower()
    for inst in insts.values():
        if valor in getattr(inst, campo):
            return inst
    return None


def decidir(prova: ProvaLogin, insts: Mapping[str, Instituicao]) -> Decisao:
    p = prova.provedor

    if p == "google":
        inst = _achar(insts, "google_hd", prova.hd)
        if inst is None:
            return Decisao(PENDENTE, None, "conta Google sem domínio de instituição cadastrada")
        if "google" not in inst.metodos:
            return Decisao(RECUSADO, inst.slug, "login com Google desligado para a instituição")
        if not prova.email_verificado:
            return Decisao(PENDENTE, None, "e-mail não verificado pelo Google")
        return Decisao(ATIVO, inst.slug, "domínio do Workspace confere",
                       _email_da_instituicao(prova.email, inst))

    if p == "microsoft":
        if (prova.tid or "").lower() == TID_CONTA_PESSOAL:
            return Decisao(PENDENTE, None, "conta Microsoft pessoal")
        inst = _achar(insts, "microsoft_tid", prova.tid)
        if inst is None:
            return Decisao(PENDENTE, None, "diretório Microsoft não cadastrado")
        if "microsoft" not in inst.metodos:
            return Decisao(RECUSADO, inst.slug, "login com Microsoft desligado para a instituição")
        return Decisao(ATIVO, inst.slug, "diretório do Entra ID confere",
                       _email_da_instituicao(prova.email, inst))

    if p == "ldap":
        inst = insts.get(prova.inst_ldap or "")
        if inst is None or inst.ldap is None or "ldap" not in inst.metodos:
            return Decisao(RECUSADO, None, "instituição sem login LDAP")
        return Decisao(ATIVO, inst.slug, "bind no diretório da instituição",
                       _email_da_instituicao(prova.email, inst))

    if p == "cafe":
        inst = _achar(insts, "cafe_escopos", _dominio(prova.eppn))
        if inst is None:
            return Decisao(PENDENTE, None, "escopo da CAFe não cadastrado")
        if "cafe" not in inst.metodos:
            return Decisao(RECUSADO, inst.slug, "login pela CAFe desligado para a instituição")
        return Decisao(ATIVO, inst.slug, "escopo da CAFe confere",
                       _email_da_instituicao(prova.email, inst))

    if p == "oidc":
        inst = insts.get(prova.inst_oidc or "")
        if inst is None or inst.oidc is None or "oidc" not in inst.metodos:
            return Decisao(RECUSADO, None, "instituição sem login único")
        # O provedor é da instituição, mas pode deixar a pessoa digitar o próprio e-mail.
        # Só o e-mail que ele diz ter verificado liga este login a uma pessoa que já existe.
        email = prova.email if prova.email_verificado else None
        return Decisao(ATIVO, inst.slug, "login único da instituição",
                       _email_da_instituicao(email, inst))

    return Decisao(RECUSADO, None, "provedor não aceito")
