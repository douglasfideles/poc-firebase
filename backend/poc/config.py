"""Configuração da prova de conceito. Lê o ambiente e o cadastro das instituições.

O serviço só fala com um projeto Firebase de verdade. A partida falha fechada: sem projeto e
sem chave de serviço ele não sobe, com o emulador do Firebase configurado ele não sobe, e
segredo curto ou padrão não é aceito. Ver `validar`.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

import yaml

SEGREDOS_PROIBIDOS = {
    "change-me-in-production",
    "changeme",
    "secret",
    "segredo",
    "troque-este-segredo",
}
TAMANHO_MINIMO_SEGREDO = 32
# O login único simulado do ambiente de teste (ver `demo_oidc.py`).
EMISSOR_SIMULADO = "simulado"  # o que se escreve no cadastro para usá-lo
CAMINHO_OIDC_SIMULADO = "/demo/oidc"
CLIENTE_OIDC_SIMULADO = "iotedu-poc"


class ErroDeConfig(RuntimeError):
    """A configuração é insegura ou incoerente; o serviço não deve subir."""


# O que muda de um diretório para outro é o filtro e o nome dos atributos. `tipo` escolhe o padrão;
# qualquer campo escrito no cadastro vale mais que o padrão.
TIPOS_LDAP = {
    "openldap": {
        "filtro": "(&(objectClass=inetOrgPerson)(uid={usuario}))",
        "attr_uid": "uid", "attr_mail": "mail", "attr_nome": "cn",
    },
    # Active Directory: a pessoa digita o nome de logon; conta desativada não é achada.
    "ad": {
        "filtro": ("(&(objectCategory=person)(objectClass=user)(sAMAccountName={usuario})"
                   "(!(userAccountControl:1.2.840.113556.1.4.803:=2)))"),
        "attr_uid": "sAMAccountName", "attr_mail": "mail", "attr_nome": "displayName",
    },
}


@dataclass(frozen=True)
class LdapCfg:
    url: str
    base: str
    filtro: str
    bind_dn: str
    senha_env: str
    ca: str
    attr_uid: str = "uid"
    attr_mail: str = "mail"
    attr_nome: str = "cn"
    tipo: str = "openldap"


@dataclass(frozen=True)
class OidcCfg:
    """O login único da própria instituição (Keycloak, ADFS, Shibboleth com OIDC e parecidos)."""
    emissor: str  # o `issuer`; a descoberta fica em <emissor>/.well-known/openid-configuration
    client_id: str
    segredo_env: str = ""  # vazio: cliente público, só com PKCE
    escopos: str = "openid email profile"
    rotulo: str = "Login da instituição"


@dataclass(frozen=True)
class Instituicao:
    slug: str
    nome: str
    dominios: tuple[str, ...] = ()
    metodos: tuple[str, ...] = ()
    google_hd: tuple[str, ...] = ()
    microsoft_tid: tuple[str, ...] = ()
    cafe_escopos: tuple[str, ...] = ()
    ldap: LdapCfg | None = None
    oidc: OidcCfg | None = None


@dataclass(frozen=True)
class Config:
    projeto: str
    credencial: str
    sessao_segredo: str
    ponte_segredo: str
    origem_front: str
    max_idade_login_h: float
    db_caminho: str
    google_client_id: str | None
    ms_client_id: str | None
    ms_tenant: str | None  # diretório para onde a página manda o login da Microsoft
    web_api_key: str
    auth_domain: str
    cafe_sp_login_url: str | None
    # Liga a "CAFe simulada" e a limpeza usada pelos testes. Só em localhost.
    ambiente_de_teste: bool = False
    instituicoes: Mapping[str, Instituicao] = field(default_factory=dict)
    avisos: tuple[str, ...] = ()


_VARIAVEL = re.compile(r"^\$\{([A-Z0-9_]+)\}$")


def carregar_instituicoes(caminho: str | Path,
                          env: Mapping[str, str] | None = None) -> dict[str, Instituicao]:
    """Lê o cadastro. Um item escrito como `${NOME}` vem da variável de ambiente NOME.

    Serve para os identificadores reais de quem testa (diretório Microsoft, domínio do Workspace,
    endereço do login único) ficarem no `.env`, fora do git. Variável vazia ou ausente: o item
    some da lista.
    """
    env = os.environ if env is None else env

    def _tupla(valor) -> tuple[str, ...]:
        itens = []
        for v in (valor or ()):
            v = str(v).strip()
            m = _VARIAVEL.match(v)
            if m:
                v = (env.get(m.group(1)) or "").strip()
            if v:
                itens.append(v.lower())
        return tuple(itens)

    def _texto(valor, padrao: str = "") -> str:
        v = str(valor if valor is not None else "").strip()
        m = _VARIAVEL.match(v)
        if m:
            v = (env.get(m.group(1)) or "").strip()
        return v or padrao

    bruto = yaml.safe_load(Path(caminho).read_text(encoding="utf-8")) or {}
    saida: dict[str, Instituicao] = {}
    for slug, d in (bruto.get("instituicoes") or {}).items():
        ldap = None
        if d.get("ldap"):
            l = d["ldap"]
            tipo = str(l.get("tipo", "openldap")).strip().lower()
            if tipo not in TIPOS_LDAP:
                raise ErroDeConfig(f"{slug}: tipo de LDAP desconhecido ({tipo}). Use openldap ou ad.")
            padrao = TIPOS_LDAP[tipo]
            ldap = LdapCfg(
                url=l["url"],
                base=l["base"],
                filtro=l.get("filtro", padrao["filtro"]),
                bind_dn=l["bind_dn"],
                senha_env=l["senha_env"],
                ca=l["ca"],
                attr_uid=l.get("attr_uid", padrao["attr_uid"]),
                attr_mail=l.get("attr_mail", padrao["attr_mail"]),
                attr_nome=l.get("attr_nome", padrao["attr_nome"]),
                tipo=tipo,
            )
        oidc = None
        if d.get("oidc"):
            o = d["oidc"]
            oidc = OidcCfg(
                emissor=_texto(o.get("emissor")).rstrip("/"),
                client_id=_texto(o.get("client_id")),
                segredo_env=_texto(o.get("segredo_env")),
                escopos=_texto(o.get("escopos"), "openid email profile"),
                rotulo=_texto(o.get("rotulo"), "Login da instituição"),
            )
        saida[slug] = Instituicao(
            slug=slug,
            nome=d.get("nome", slug),
            dominios=_tupla(d.get("dominios")),
            metodos=_tupla(d.get("metodos")),
            google_hd=_tupla(d.get("google_hd")),
            microsoft_tid=_tupla(d.get("microsoft_tid")),
            cafe_escopos=_tupla(d.get("cafe_escopos")),
            ldap=ldap,
            oidc=oidc,
        )
    return saida


def carregar(env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    # O Admin SDK aceita token sem assinatura quando esta variável existe. Aqui ela é proibida.
    if (env.get("FIREBASE_AUTH_EMULATOR_HOST") or "").strip():
        raise ErroDeConfig("FIREBASE_AUTH_EMULATOR_HOST definido: este serviço não usa o emulador.")

    insts = carregar_instituicoes(env.get("INSTITUICOES_ARQUIVO", "instituicoes.yaml"), env)
    google = (env.get("GOOGLE_WEB_CLIENT_ID") or "").strip() or None
    microsoft = (env.get("MS_CLIENT_ID") or "").strip() or None

    # Sem o client id não há como conferir o token do provedor: o método fica desligado.
    avisos = []
    for metodo, client_id, variavel in (("google", google, "GOOGLE_WEB_CLIENT_ID"),
                                         ("microsoft", microsoft, "MS_CLIENT_ID")):
        if not client_id and any(metodo in i.metodos for i in insts.values()):
            avisos.append(f"{variavel} não definido: login com {metodo} desligado.")
            insts = {k: replace(i, metodos=tuple(m for m in i.metodos if m != metodo))
                     for k, i in insts.items()}

    origem = env.get("ORIGEM_FRONT", "http://localhost:8088").rstrip("/")
    de_teste = (env.get("AMBIENTE_DE_TESTE") or "").strip() == "1"
    for slug, i in list(insts.items()):
        if "oidc" not in i.metodos or i.oidc is None:
            continue
        if i.oidc.emissor == EMISSOR_SIMULADO and de_teste:
            insts[slug] = replace(i, oidc=replace(
                i.oidc, emissor=f"{origem}{CAMINHO_OIDC_SIMULADO}", client_id=CLIENTE_OIDC_SIMULADO,
                segredo_env=""))
        elif i.oidc.emissor == EMISSOR_SIMULADO:
            avisos.append(f"{slug}: o login único simulado só existe no ambiente de teste: desligado.")
            insts[slug] = replace(i, metodos=tuple(m for m in i.metodos if m != "oidc"))
        elif not i.oidc.emissor:
            # O emissor vem de uma variável que está vazia: a instituição fica sem este login.
            insts[slug] = replace(i, metodos=tuple(m for m in i.metodos if m != "oidc"))

    cfg = Config(
        projeto=(env.get("FIREBASE_PROJECT_ID") or "").strip(),
        credencial=(env.get("GOOGLE_APPLICATION_CREDENTIALS") or "").strip(),
        sessao_segredo=env.get("SESSAO_SEGREDO", ""),
        ponte_segredo=env.get("CAFE_PONTE_SEGREDO", ""),
        origem_front=origem,
        max_idade_login_h=float(env.get("MAX_IDADE_LOGIN_H", "12")),
        db_caminho=env.get("DB_CAMINHO", "/dados/poc.sqlite3"),
        google_client_id=google,
        ms_client_id=microsoft,
        ms_tenant=(env.get("MS_TENANT_ID") or "").strip().lower() or None,
        web_api_key=(env.get("FIREBASE_WEB_API_KEY") or "").strip(),
        auth_domain=(env.get("FIREBASE_AUTH_DOMAIN") or "").strip(),
        cafe_sp_login_url=(env.get("CAFE_SP_LOGIN_URL") or "").strip() or None,
        ambiente_de_teste=de_teste,
        instituicoes=insts,
        avisos=tuple(avisos),
    )
    validar(cfg)
    return cfg


def _validar_segredo(nome: str, valor: str) -> None:
    if len(valor) < TAMANHO_MINIMO_SEGREDO:
        raise ErroDeConfig(f"{nome} precisa de pelo menos {TAMANHO_MINIMO_SEGREDO} caracteres.")
    if valor.strip().lower() in SEGREDOS_PROIBIDOS:
        raise ErroDeConfig(f"{nome} está com um valor padrão conhecido.")


def validar(cfg: Config) -> None:
    """Recusa a configuração incompleta ou insegura, com a mensagem do que falta."""
    if not cfg.projeto:
        raise ErroDeConfig("Defina FIREBASE_PROJECT_ID com o id do projeto Firebase.")
    if cfg.projeto.startswith("demo-"):
        raise ErroDeConfig("Projeto 'demo-' é do emulador. Use um projeto Firebase de verdade.")
    if not cfg.credencial:
        raise ErroDeConfig("Defina GOOGLE_APPLICATION_CREDENTIALS com a chave de serviço do projeto.")
    if not Path(cfg.credencial).is_file():
        raise ErroDeConfig(f"Chave de serviço não encontrada em {cfg.credencial}.")
    if not cfg.web_api_key or not cfg.auth_domain:
        raise ErroDeConfig("Defina FIREBASE_WEB_API_KEY e FIREBASE_AUTH_DOMAIN (app Web do projeto).")

    _validar_segredo("SESSAO_SEGREDO", cfg.sessao_segredo)
    _validar_segredo("CAFE_PONTE_SEGREDO", cfg.ponte_segredo)
    if cfg.sessao_segredo == cfg.ponte_segredo:
        raise ErroDeConfig("SESSAO_SEGREDO e CAFE_PONTE_SEGREDO não podem ser iguais.")

    # As rotas de teste criam logins sem SAML de verdade: só valem na própria máquina.
    if cfg.ambiente_de_teste and urlsplit(cfg.origem_front).hostname not in ("localhost", "127.0.0.1"):
        raise ErroDeConfig("AMBIENTE_DE_TESTE=1 só é aceito com o painel em localhost.")

    provedores_oidc: dict[str, str] = {}
    for inst in cfg.instituicoes.values():
        if "ldap" in inst.metodos:
            if inst.ldap is None:
                raise ErroDeConfig(f"{inst.slug}: método ldap ligado sem bloco ldap.")
            if not inst.ldap.url.lower().startswith("ldaps://"):
                raise ErroDeConfig(f"{inst.slug}: o LDAP precisa ser ldaps://.")
            if "{usuario}" not in inst.ldap.filtro:
                raise ErroDeConfig(f"{inst.slug}: o filtro do LDAP precisa conter {{usuario}}.")
        if "oidc" in inst.metodos:
            if inst.oidc is None:
                raise ErroDeConfig(f"{inst.slug}: método oidc ligado sem bloco oidc.")
            if not inst.oidc.client_id or "openid" not in inst.oidc.escopos.split():
                raise ErroDeConfig(f"{inst.slug}: o bloco oidc precisa de client_id e do escopo openid.")
            if not endereco_seguro(inst.oidc.emissor, cfg.ambiente_de_teste):
                raise ErroDeConfig(f"{inst.slug}: o emissor do oidc precisa ser https://.")
            # O token só prova o provedor. Com o mesmo provedor em duas instituições, a pessoa
            # escolheria em qual delas entra aprovada.
            outra = provedores_oidc.setdefault(inst.oidc.emissor, inst.slug)
            if outra != inst.slug:
                raise ErroDeConfig(f"{inst.slug}: o emissor do oidc já é o de {outra}.")


def endereco_seguro(endereco: str, ambiente_de_teste: bool) -> bool:
    """https sempre. http só no ambiente de teste, que só existe na própria máquina."""
    partes = urlsplit(endereco)
    if not partes.hostname:
        return False
    return partes.scheme == "https" or (ambiente_de_teste and partes.scheme == "http")
