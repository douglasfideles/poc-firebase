"""Quem está fazendo o pedido.

Dois caminhos, o mesmo resultado:
- cookie de sessão, o contrato que o app já usa (`app/backend/auth/dependencies.py`);
- `Authorization: Bearer <ID token do Firebase>`, o caminho do ADR-0005.

A instituição e o papel saem do token ou da sessão, nunca do pedido (D12). Claim ausente é
pendente, nunca um valor padrão.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from fastapi import HTTPException, Request

from . import firebase as fb
from .regras import ATIVO, PENDENTE
from .repositorio import Repositorio


@dataclass(frozen=True)
class UsuarioAtual:
    uid: str
    usuario_id: int
    email: str | None
    nome: str
    inst: str | None
    papel: str
    estado: str
    via: str  # bearer | cookie


def exigir_login_recente(auth_time: float | int | None, max_h: float, agora: float | None = None) -> None:
    """O refresh token do Firebase não expira. Sem este corte, quem saiu da instituição
    continuaria entrando para sempre com a sessão antiga."""
    agora = time.time() if agora is None else agora
    if not auth_time or agora - float(auth_time) > max_h * 3600:
        raise HTTPException(status_code=401, detail="Login antigo demais. Entre de novo.")


def resolver(request: Request, repo: Repositorio, max_h: float) -> UsuarioAtual:
    cabecalho = request.headers.get("authorization", "")
    sessao = request.session

    if cabecalho.lower().startswith("bearer "):
        try:
            claims = fb.verificar_id_token(cabecalho[7:].strip())
        except fb.TokenInvalido:
            raise HTTPException(status_code=401, detail="Token inválido.")
        uid = claims["uid"]
        # Um pedido com token de uma pessoa e cookie de outra é recusado, não adivinhado.
        if sessao.get("uid") and sessao["uid"] != uid:
            raise HTTPException(status_code=401, detail="Sessão e token são de contas diferentes.")
        auth_time = claims.get("auth_time")
        inst, papel = claims.get("inst"), claims.get("papel") or "USER"
        estado = claims.get("estado") or PENDENTE
        via = "bearer"
    elif sessao.get("uid"):
        uid = sessao["uid"]
        auth_time = sessao.get("auth_time")
        inst, papel = sessao.get("inst"), sessao.get("papel") or "USER"
        estado = sessao.get("estado") or PENDENTE
        via = "cookie"
    else:
        raise HTTPException(status_code=401, detail="Não autenticado.")

    exigir_login_recente(auth_time, max_h)

    usuario = repo.por_firebase_uid(uid)
    if usuario is None:
        raise HTTPException(status_code=401, detail="Conta desconhecida. Entre de novo.")
    if not usuario.is_active:
        raise HTTPException(status_code=403, detail="Conta desativada.")
    if estado != ATIVO:
        inst = None
    return UsuarioAtual(uid, usuario.id, usuario.email, usuario.nome, inst, papel, estado, via)


def exigir_ativo(atual: UsuarioAtual, repo: Repositorio) -> UsuarioAtual:
    """Antes de qualquer ação que altera algo, confere no banco se a pessoa ainda é da instituição."""
    usuario = repo.por_firebase_uid(atual.uid)
    if (atual.estado != ATIVO or usuario is None or usuario.estado != ATIVO
            or usuario.instituicao != atual.inst):
        raise HTTPException(status_code=403, detail="Entrada pendente de aprovação.")
    return atual
