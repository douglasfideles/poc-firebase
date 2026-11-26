"""Ponte da CAFe, limite de tentativas, partida do serviço e corte de login antigo. Sem rede."""
import time

import pytest
from fastapi import HTTPException

from poc import firebase as fb
from poc import ponte_cafe
from poc.config import ErroDeConfig, carregar
from poc.limite import Limitador
from poc.sessao import exigir_login_recente

SEGREDO = "s" * 40


def usos():
    vistos = set()
    return lambda h, exp: not (h in vistos or vistos.add(h))


# ---------------------------------------------------------------- ponte da CAFe
def test_ponte_valida_traz_os_atributos_sem_o_cpf():
    t = ponte_cafe.emitir_demo("Ana@UniA.test", "ana@unia.test", "Ana", "Teste", SEGREDO)
    a = ponte_cafe.validar(t, SEGREDO, usos())
    assert (a.eppn, a.email, a.nome) == ("ana@unia.test", "ana@unia.test", "Ana Teste")
    assert not hasattr(a, "cpf") and "00000000000" not in repr(a)


def test_ponte_expirada_e_recusada():
    t = ponte_cafe.emitir_demo("ana@unia.test", "", "Ana", "", SEGREDO, agora=time.time() - 600)
    with pytest.raises(ponte_cafe.PonteInvalida):
        ponte_cafe.validar(t, SEGREDO, usos())


def test_ponte_com_outro_segredo_e_recusada():
    t = ponte_cafe.emitir_demo("ana@unia.test", "", "Ana", "", "x" * 40)
    with pytest.raises(ponte_cafe.PonteInvalida):
        ponte_cafe.validar(t, SEGREDO, usos())


def test_ponte_so_vale_uma_vez():
    t = ponte_cafe.emitir_demo("ana@unia.test", "", "Ana", "", SEGREDO)
    registro = usos()
    ponte_cafe.validar(t, SEGREDO, registro)
    with pytest.raises(ponte_cafe.PonteInvalida):
        ponte_cafe.validar(t, SEGREDO, registro)


def test_ponte_com_validade_longa_e_recusada():
    t = ponte_cafe.emitir_demo("ana@unia.test", "", "Ana", "", SEGREDO, validade_s=86400)
    with pytest.raises(ponte_cafe.PonteInvalida):
        ponte_cafe.validar(t, SEGREDO, usos())


def test_ponte_sem_eppn_e_recusada():
    t = ponte_cafe.emitir_demo("", "ana@unia.test", "Ana", "", SEGREDO)
    with pytest.raises(ponte_cafe.PonteInvalida):
        ponte_cafe.validar(t, SEGREDO, usos())


# ---------------------------------------------------------------- limite de tentativas
def test_limite_deixa_tres_erros_e_depois_dobra_a_espera():
    agora = [1000.0]
    lim = Limitador(livres=3, base_s=2, teto_s=300, relogio=lambda: agora[0])
    for _ in range(3):
        lim.falha("u")
    assert lim.espera("u") == 0
    lim.falha("u")
    assert lim.espera("u") == 2
    agora[0] += 2
    assert lim.espera("u") == 0
    lim.falha("u")
    assert lim.espera("u") == 4
    for _ in range(20):
        lim.falha("u")
    assert lim.espera("u") == 300  # teto: atrasa, não bloqueia para sempre


def test_limite_zera_com_login_certo_e_nao_afeta_outra_pessoa():
    lim = Limitador(livres=0, base_s=10)
    lim.falha("ana")
    assert lim.espera("ana") > 0 and lim.espera("bruno") == 0
    lim.sucesso("ana")
    assert lim.espera("ana") == 0


# ---------------------------------------------------------------- partida do serviço
@pytest.fixture
def ambiente(tmp_path):
    import os
    chave = tmp_path / "conta.json"
    chave.write_text("{}")
    base = {"FIREBASE_PROJECT_ID": "iotedu-teste", "GOOGLE_APPLICATION_CREDENTIALS": str(chave),
            "FIREBASE_WEB_API_KEY": "chave-web", "FIREBASE_AUTH_DOMAIN": "iotedu-teste.firebaseapp.com",
            "GOOGLE_WEB_CLIENT_ID": "g", "MS_CLIENT_ID": "m",
            "SESSAO_SEGREDO": "a" * 40, "CAFE_PONTE_SEGREDO": "b" * 40,
            "INSTITUICOES_ARQUIVO": os.environ["INSTITUICOES_ARQUIVO"],
            "DB_CAMINHO": str(tmp_path / "t.sqlite3")}
    return lambda **mudancas: {**base, **mudancas}


def test_partida_normal(ambiente):
    cfg = carregar(ambiente())
    assert cfg.projeto == "iotedu-teste" and cfg.ambiente_de_teste is False
    assert cfg.avisos == ("unid: o login único simulado só existe no ambiente de teste: desligado.",)


def test_login_unico_simulado_so_existe_no_ambiente_de_teste(ambiente):
    assert "oidc" not in carregar(ambiente()).instituicoes["unid"].metodos
    teste = carregar(ambiente(AMBIENTE_DE_TESTE="1"))
    oidc = teste.instituicoes["unid"].oidc
    assert "oidc" in teste.instituicoes["unid"].metodos and teste.avisos == ()
    assert (oidc.emissor, oidc.client_id, oidc.segredo_env) == (
        "http://localhost:8088/demo/oidc", "iotedu-poc", "")


def test_login_unico_de_verdade_vem_do_ambiente_e_sem_ele_fica_desligado(ambiente):
    assert carregar(ambiente()).instituicoes["unib"].metodos == ("ldap",)
    com = carregar(ambiente(OIDC_EMISSOR="https://sso.unib.test/realms/unib/", OIDC_CLIENT_ID="iotedu"))
    oidc = com.instituicoes["unib"].oidc
    assert com.instituicoes["unib"].metodos == ("ldap", "oidc")
    assert (oidc.emissor, oidc.client_id, oidc.segredo_env) == (
        "https://sso.unib.test/realms/unib", "iotedu", "OIDC_SEGREDO")
    # Emissor http só é aceito no ambiente de teste, que só existe na própria máquina.
    with pytest.raises(ErroDeConfig):
        carregar(ambiente(OIDC_EMISSOR="http://sso.unib.test/realms/unib", OIDC_CLIENT_ID="iotedu"))


def cadastro(tmp_path, bloco: str) -> str:
    arquivo = tmp_path / "instituicoes.yaml"
    arquivo.write_text("instituicoes:\n  x:\n    nome: X\n" + bloco, encoding="utf-8")
    return str(arquivo)


LDAP_AD = """    metodos: [ldap]
    ldap:
      tipo: ad
      url: ldaps://dc1.x.test:636
      base: dc=x,dc=test
      bind_dn: cn=iotedu,ou=servicos,dc=x,dc=test
      senha_env: LDAP_X_SENHA
      ca: /certs/x.crt
"""


def test_active_directory_muda_so_o_filtro_e_os_atributos(ambiente, tmp_path):
    ad = carregar(ambiente(INSTITUICOES_ARQUIVO=cadastro(tmp_path, LDAP_AD))).instituicoes["x"].ldap
    assert "sAMAccountName={usuario}" in ad.filtro and "userAccountControl" in ad.filtro
    assert (ad.attr_uid, ad.attr_nome, ad.attr_mail) == ("sAMAccountName", "displayName", "mail")
    # O que a instituição escrever no cadastro vale mais que o padrão do tipo.
    proprio = LDAP_AD + "      filtro: \"(userPrincipalName={usuario})\"\n      attr_uid: objectGUID\n"
    ad = carregar(ambiente(INSTITUICOES_ARQUIVO=cadastro(tmp_path, proprio))).instituicoes["x"].ldap
    assert (ad.filtro, ad.attr_uid) == ("(userPrincipalName={usuario})", "objectGUID")


@pytest.mark.parametrize("bloco", [
    LDAP_AD.replace("tipo: ad", "tipo: novell"),                    # tipo que não existe
    LDAP_AD.replace("ldaps://", "ldap://"),                         # senha sem TLS
    LDAP_AD + "      filtro: \"(objectClass=user)\"\n",            # filtro que acharia qualquer um
    "    metodos: [oidc]\n",                                        # método ligado sem o bloco
    "    metodos: [oidc]\n    oidc: {emissor: 'http://sso.x.test', client_id: iotedu}\n",
    "    metodos: [oidc]\n    oidc: {emissor: 'https://sso.x.test', client_id: ''}\n",
    "    metodos: [oidc]\n    oidc: {emissor: 'https://sso.x.test', client_id: a, escopos: email}\n",
    # o mesmo provedor em duas instituições: a pessoa escolheria em qual entra aprovada
    "    metodos: [oidc]\n    oidc: {emissor: 'https://sso.x.test', client_id: a}\n"
    "  y:\n    metodos: [oidc]\n    oidc: {emissor: 'https://sso.x.test/', client_id: b}\n",
])
def test_partida_recusa_cadastro_de_instituicao_inseguro(ambiente, tmp_path, bloco):
    with pytest.raises(ErroDeConfig):
        carregar(ambiente(INSTITUICOES_ARQUIVO=cadastro(tmp_path, bloco)))


@pytest.mark.parametrize("mudancas", [
    {"FIREBASE_AUTH_EMULATOR_HOST": "localhost:9099"},   # com o emulador o SDK aceita token sem assinatura
    {"FIREBASE_PROJECT_ID": ""},
    {"FIREBASE_PROJECT_ID": "demo-iotedu"},              # projeto do emulador
    {"GOOGLE_APPLICATION_CREDENTIALS": ""},
    {"GOOGLE_APPLICATION_CREDENTIALS": "/nao/existe.json"},
    {"FIREBASE_WEB_API_KEY": ""},
    {"SESSAO_SEGREDO": "change-me-in-production"},       # segredo padrão
    {"SESSAO_SEGREDO": "curto"},
    {"CAFE_PONTE_SEGREDO": "a" * 40},                    # o mesmo segredo para as duas coisas
    {"AMBIENTE_DE_TESTE": "1", "ORIGEM_FRONT": "https://painel.iotedu.org"},  # teste fora de localhost
])
def test_partida_recusa_configuracao_insegura_ou_incompleta(ambiente, mudancas):
    with pytest.raises(ErroDeConfig):
        carregar(ambiente(**mudancas))


def test_sem_o_client_id_o_login_do_provedor_fica_desligado(ambiente):
    cfg = carregar(ambiente(MS_CLIENT_ID=""))
    assert "microsoft" not in cfg.instituicoes["unia"].metodos
    assert "google" in cfg.instituicoes["unia"].metodos
    assert [a for a in cfg.avisos if "unid" not in a] == [
        "MS_CLIENT_ID não definido: login com microsoft desligado."]


def test_identificadores_reais_vem_do_ambiente_e_nao_do_arquivo(ambiente):
    sem = carregar(ambiente())
    assert sem.instituicoes["unia"].google_hd == ("unia.test",)
    assert sem.ms_tenant is None and len(sem.instituicoes["unia"].microsoft_tid) == 1
    com = carregar(ambiente(GOOGLE_HD="Uni.Edu.BR", MS_TENANT_ID="AAAA-bbbb"))
    assert com.instituicoes["unia"].google_hd == ("unia.test", "uni.edu.br")
    assert "uni.edu.br" in com.instituicoes["unia"].dominios
    assert com.instituicoes["unia"].microsoft_tid[0] == "aaaa-bbbb" and com.ms_tenant == "aaaa-bbbb"


def test_rotas_de_teste_nao_existem_sem_o_ambiente_de_teste(ambiente, monkeypatch):
    from poc import app as modulo
    monkeypatch.setattr(modulo.fb, "iniciar", lambda cfg: None)
    fora = {r.path for r in modulo.criar_app(carregar(ambiente())).routes}
    assert "/api/auth/ldap/login" in fora
    assert not any(c.startswith("/demo") for c in fora)
    dentro = {r.path for r in modulo.criar_app(carregar(ambiente(AMBIENTE_DE_TESTE="1"))).routes}
    assert "/demo/cafe/sp" in dentro and "/demo/oidc/authorize" in dentro


def test_sem_sp_e_sem_ambiente_de_teste_a_cafe_avisa_que_nao_esta_configurada(ambiente, monkeypatch):
    from fastapi.testclient import TestClient
    from poc import app as modulo
    monkeypatch.setattr(modulo.fb, "iniciar", lambda cfg: None)
    c = TestClient(modulo.criar_app(carregar(ambiente())))
    assert c.get("/api/auth/cafe/login", follow_redirects=False).status_code == 503


# ---------------------------------------------------------------- custom token e login antigo
@pytest.mark.parametrize("uid", ["abc123", "google:1", "admin", "ldap", "ldap:" + "x" * 200])
def test_custom_token_so_para_logins_que_o_backend_prova(uid):
    with pytest.raises(ValueError):
        fb.emitir_custom_token(uid)


def test_identificador_longo_demais_vira_resumo_para_caber_no_firebase():
    assert fb.uid_custom("oidc", "unid", " u-1 ") == "oidc:unid:u-1"
    longo = fb.uid_custom("oidc", "unid", "x" * 200)
    assert longo.startswith("oidc:unid:") and len(longo) <= fb.TAMANHO_MAXIMO_UID
    assert longo == fb.uid_custom("oidc", "unid", "x" * 200) != fb.uid_custom("oidc", "unid", "y" * 200)


def test_login_antigo_e_recusado():
    agora = time.time()
    exigir_login_recente(agora - 3600, max_h=12, agora=agora)
    with pytest.raises(HTTPException):
        exigir_login_recente(agora - 13 * 3600, max_h=12, agora=agora)
    with pytest.raises(HTTPException):
        exigir_login_recente(None, max_h=12, agora=agora)
