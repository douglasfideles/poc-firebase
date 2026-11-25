"""Login por LDAP: busca a pessoa com a conta de serviço e faz o bind com a senha dela.

O Firebase não fala LDAP. Quem prova a senha é este código; o Firebase só recebe o resultado, na
forma de um custom token. Por isso a senha da pessoa passa pelo nosso backend, e este arquivo é o
único que a toca. Ela nunca é registrada em log nem guardada.
"""
from __future__ import annotations

import ssl
from dataclasses import dataclass

from ldap3 import NONE, SUBTREE, Connection, Server, Tls
from ldap3.core.exceptions import (
    LDAPBindError,
    LDAPInvalidCredentialsResult,
    LDAPSizeLimitExceededResult,
)
from ldap3.utils.conv import escape_filter_chars

from .config import LdapCfg

TAMANHO_MAXIMO_USUARIO = 64
TEMPO_LIMITE_S = 5


class LdapIndisponivel(Exception):
    """O diretório não respondeu. Não conta como senha errada."""


@dataclass(frozen=True)
class AtributosLdap:
    uid: str
    mail: str | None
    nome: str


def _servidor(cfg: LdapCfg) -> Server:
    # TLS obrigatório, com a CA da instituição. Sem CERT_NONE.
    tls = Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=cfg.ca)
    return Server(cfg.url, use_ssl=True, tls=tls, get_info=NONE, connect_timeout=TEMPO_LIMITE_S)


def _conexao(servidor: Server, dn: str, senha: str) -> Connection:
    return Connection(
        servidor,
        user=dn,
        password=senha,
        auto_bind=True,
        raise_exceptions=True,
        read_only=True,
        auto_referrals=False,  # não seguir o diretório para outro servidor
        receive_timeout=TEMPO_LIMITE_S,
    )


def autenticar(cfg: LdapCfg, usuario: str, senha: str, senha_servico: str) -> AtributosLdap | None:
    """Devolve os atributos da pessoa se usuário e senha conferem. None em qualquer outro caso."""
    # Senha vazia viraria um bind sem autenticação, que muitos servidores aceitam.
    if not usuario or not senha or len(usuario) > TAMANHO_MAXIMO_USUARIO:
        return None

    filtro = cfg.filtro.replace("{usuario}", escape_filter_chars(usuario))
    servidor = _servidor(cfg)
    try:
        with _conexao(servidor, cfg.bind_dn, senha_servico) as c:
            c.search(cfg.base, filtro, search_scope=SUBTREE, size_limit=2,
                     attributes=[cfg.attr_uid, cfg.attr_mail, cfg.attr_nome])
            achados = list(c.entries)
    except LDAPSizeLimitExceededResult:
        return None
    except (LDAPBindError, LDAPInvalidCredentialsResult) as e:
        raise LdapIndisponivel("a conta de serviço não conseguiu entrar") from e
    except Exception as e:
        raise LdapIndisponivel(type(e).__name__) from e

    # Exatamente uma entrada. Zero é "não existe"; duas ou mais é ambíguo.
    if len(achados) != 1:
        return None
    entrada = achados[0]

    try:
        _conexao(servidor, entrada.entry_dn, senha).unbind()
    except (LDAPBindError, LDAPInvalidCredentialsResult):
        return None
    except Exception as e:
        raise LdapIndisponivel(type(e).__name__) from e

    def attr(nome: str) -> str | None:
        valor = entrada[nome].value if nome in entrada else None
        if isinstance(valor, list):
            valor = valor[0] if valor else None
        return str(valor) if valor else None

    uid = attr(cfg.attr_uid)
    if not uid:
        return None
    return AtributosLdap(uid=uid, mail=attr(cfg.attr_mail), nome=attr(cfg.attr_nome) or uid)
