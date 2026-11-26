"""Confere o cadastro LDAP de uma instituição, passo a passo, e diz em qual passo parou.

    python -m poc.conferir_ldap <instituição> [usuário]

Serve para o primeiro contato com o diretório de uma instituição de verdade: endereço, certificado,
conta de serviço, filtro e atributos. Com o usuário, pede a senha dele (não aparece na tela nem é
guardada) e testa o login inteiro, pelo mesmo código que a rota usa.
"""
from __future__ import annotations

import getpass
import os
import sys

from ldap3 import SUBTREE
from ldap3.utils.conv import escape_filter_chars

from . import ldap_auth
from .config import carregar_instituicoes


def conferir(slug: str, usuario: str | None, ler_senha=getpass.getpass, saida=print) -> bool:
    insts = carregar_instituicoes(os.environ.get("INSTITUICOES_ARQUIVO", "instituicoes.yaml"))
    inst = insts.get(slug)
    if inst is None or inst.ldap is None:
        saida(f"FALHOU  cadastro: a instituição {slug!r} não tem bloco ldap.")
        return False
    cfg = inst.ldap
    saida(f"        {cfg.url}  tipo {cfg.tipo}  base {cfg.base}")
    if not cfg.url.lower().startswith("ldaps://"):
        saida("FALHOU  endereço: precisa ser ldaps://.")
        return False
    senha_servico = os.environ.get(cfg.senha_env, "")
    if not senha_servico:
        saida(f"FALHOU  conta de serviço: a variável {cfg.senha_env} está vazia.")
        return False

    # 1 e 2: conexão com TLS, certificado conferido com a CA informada, e a conta de serviço entra.
    servidor = ldap_auth._servidor(cfg)
    try:
        conexao = ldap_auth._conexao(servidor, cfg.bind_dn, senha_servico)
    except Exception as e:  # noqa: BLE001
        saida(f"FALHOU  conexão ou conta de serviço: {type(e).__name__}. Confira o endereço, a CA "
              f"({cfg.ca}), o DN {cfg.bind_dn} e a senha em {cfg.senha_env}.")
        return False
    saida("PASSOU  TLS com o certificado conferido, e a conta de serviço entrou")

    with conexao as c:
        # 3: a base existe e a conta de serviço consegue ler nela.
        try:
            c.search(cfg.base, "(objectClass=*)", search_scope=SUBTREE, size_limit=1,
                     attributes=[cfg.attr_uid])
        except Exception as e:  # noqa: BLE001
            # Limite de tamanho atingido quer dizer que há entradas: é o esperado.
            if "SizeLimit" not in type(e).__name__:
                saida(f"FALHOU  base: {type(e).__name__}. Confira {cfg.base}.")
                return False
        saida("PASSOU  a conta de serviço lê a base")
        if not usuario:
            saida("        Para testar um login: python -m poc.conferir_ldap "
                  f"{slug} <usuário>")
            return True

        # 4: o filtro acha exatamente uma pessoa, com os atributos esperados.
        filtro = cfg.filtro.replace("{usuario}", escape_filter_chars(usuario))
        try:
            c.search(cfg.base, filtro, search_scope=SUBTREE, size_limit=2,
                     attributes=[cfg.attr_uid, cfg.attr_mail, cfg.attr_nome])
            achados = list(c.entries)
        except Exception as e:  # noqa: BLE001
            saida(f"FALHOU  busca: {type(e).__name__}. Filtro usado: {filtro}")
            return False
    if len(achados) != 1:
        saida(f"FALHOU  busca: o filtro achou {len(achados)} entradas (tem de ser uma). "
              f"Filtro usado: {filtro}")
        return False
    entrada = achados[0]
    presentes = {a: (a in entrada and bool(entrada[a].value))
                 for a in (cfg.attr_uid, cfg.attr_mail, cfg.attr_nome)}
    saida(f"PASSOU  o filtro achou uma pessoa: {entrada.entry_dn}")
    for nome, tem in presentes.items():
        saida(f"        atributo {nome}: {'presente' if tem else 'AUSENTE'}")
    if not presentes[cfg.attr_uid]:
        saida(f"FALHOU  atributos: sem {cfg.attr_uid} não há como identificar a pessoa.")
        return False

    # 5: o login inteiro, pelo mesmo código da rota.
    attrs = ldap_auth.autenticar(cfg, usuario, ler_senha(f"Senha de {usuario}: "), senha_servico)
    if attrs is None:
        saida("FALHOU  login: a senha não conferiu.")
        return False
    dominio = (attrs.mail or "").rsplit("@", 1)[-1].lower()
    saida(f"PASSOU  login: {attrs.uid} ({attrs.nome})")
    if attrs.mail and dominio not in inst.dominios:
        saida(f"AVISO   o e-mail é de {dominio}, que não está em `dominios` de {slug}: a pessoa "
              "entra, mas esse e-mail não vale como prova.")
    return True


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    sys.exit(0 if conferir(sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else None) else 1)
