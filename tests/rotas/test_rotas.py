"""As rotas de ponta a ponta dentro do backend: regra de entrada, banco, sessão e o OpenLDAP de teste.

O Firebase é um substituto (ver `tests/apoio.py`). Cada teste faz o que o navegador faria.
"""
import os
import re
from urllib.parse import parse_qs, urlsplit

import pytest

from poc import ldap_auth, ponte_cafe
from poc.config import LdapCfg
from tests.apoio import TID_UNIA, claims_de, token_google, token_microsoft
from poc.firebase import uid_custom as fb_uid
from tests.rotas.conftest import PONTE

SENHA = os.environ.get("LDAP_SENHA_PESSOAS", "")
OUTRO_TID = "99999999-9999-4999-8999-999999999999"


def google(amb, sub="g-ana", email="ana@unia.test", hd="unia.test", verificado=True):
    uid = f"fb-{sub}"
    return {"localId": uid, "idToken": amb.fb.id_token(uid, "google.com", {"google.com": [sub]}),
            "provedor_id_token": token_google(sub, email, hd, verificado)}


def microsoft(amb, oid="o-ana", email="ana@unia.test", tid=TID_UNIA):
    uid = f"fb-{oid}"
    return {"localId": uid, "idToken": amb.fb.id_token(uid, "microsoft.com", {"microsoft.com": [oid]}),
            "provedor_id_token": token_microsoft(oid, email, tid)}


def abrir_sessao(c, login, com_token_do_provedor=True):
    return c.post("/api/auth/firebase/session", json={
        "id_token": login["idToken"],
        "provedor_id_token": login.get("provedor_id_token") if com_token_do_provedor else None})


def ldap(c, usuario, senha, inst="unib"):
    return c.post("/api/auth/ldap/login", json={"inst": inst, "usuario": usuario, "senha": senha})


def cafe(c, eppn="ana@unia.test", email="ana@unia.test"):
    """O caminho do popup: começa o login e volta do SP com o JWT de ponte."""
    c.get("/api/auth/cafe/login", follow_redirects=False)
    token = ponte_cafe.emitir_demo(eppn, email, "Ana", "Teste", PONTE)
    return c.get("/api/auth/cafe/finish", params={"token": token})


def oidc_ida(c, inst="unid"):
    """Começa o login único: devolve o pedido que o backend mandou ao provedor."""
    r = c.get("/api/auth/oidc/login", params={"inst": inst}, follow_redirects=False)
    assert r.status_code == 303, r.text
    destino = urlsplit(r.headers["location"])
    assert destino.path == "/demo/oidc/authorize"
    return {k: v[0] for k, v in parse_qs(destino.query).items()}


def oidc(c, sub="d-0001", email="davi@unid.test", verificado=True, inst="unid"):
    """O caminho do popup: vai ao provedor, a pessoa entra lá, e o provedor devolve ao backend."""
    tela = c.get("/demo/oidc/authorize", params=oidc_ida(c, inst))  # a tela de login
    assert tela.status_code == 200
    # Como o navegador: o formulário manda só os campos que a tela trouxe.
    formulario = {**dict(re.findall(r"<input type='hidden' name='([^']+)' value='([^']*)'>", tela.text)),
                  "sub": sub, "nome": "Davi Teste", "email": email}
    if verificado:
        formulario["verificado"] = "on"
    r = c.post("/demo/oidc/authorize", data=formulario, follow_redirects=False)
    assert r.status_code == 303, r.text
    return c.get(r.headers["location"])


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


# =============================================================== Google
def test_google_com_conta_da_instituicao_entra_e_usa_o_painel(amb):
    c = amb.cliente()
    r = abrir_sessao(c, google(amb))
    assert r.status_code == 200, r.text
    assert r.json() == {"estado": "ativo", "inst": "unia", "papel": "USER",
                        "nome": "Ana Teste", "email": "ana@unia.test"}
    assert c.get("/api/me").json()["via"] == "cookie"
    assert c.get("/api/painel").json()["inst"] == "unia"


def test_backend_grava_os_claims_e_o_token_seguinte_vale_sem_cookie(amb):
    login = google(amb)
    abrir_sessao(amb.cliente(), login)
    assert amb.fb.claims[login["localId"]] == {"inst": "unia", "papel": "USER", "estado": "ativo"}
    novo = amb.fb.id_token(login["localId"], "google.com", {"google.com": ["g-ana"]})
    sem_cookie = amb.cliente()
    r = sem_cookie.get("/api/me", headers=bearer(novo))
    assert r.status_code == 200 and (r.json()["via"], r.json()["inst"]) == ("bearer", "unia")
    assert sem_cookie.get("/api/painel", headers=bearer(novo)).status_code == 200


def test_token_sem_claims_e_tratado_como_pendente(amb):
    login = google(amb)
    abrir_sessao(amb.cliente(), login)
    # O token de antes dos claims ainda vale por uma hora: não pode abrir o painel.
    c = amb.cliente()
    assert c.get("/api/me", headers=bearer(login["idToken"])).json()["estado"] == "pendente"
    assert c.get("/api/painel", headers=bearer(login["idToken"])).status_code == 403


def test_google_pessoal_com_email_da_universidade_fica_pendente(amb):
    c = amb.cliente()
    r = abrir_sessao(c, google(amb, hd=None))
    assert r.status_code == 200 and r.json()["estado"] == "pendente"
    assert r.json()["inst"] is None and r.json()["email"] is None
    assert c.get("/api/painel").status_code == 403


def test_google_sem_o_token_do_provedor_fica_pendente(amb):
    r = abrir_sessao(amb.cliente(), google(amb), com_token_do_provedor=False)
    assert r.json()["estado"] == "pendente"


def test_google_desligado_para_a_instituicao_e_recusado(amb):
    c = amb.cliente()
    assert abrir_sessao(c, google(amb, sub="g-c", email="x@unic.test", hd="unic.test")).status_code == 403
    assert c.get("/api/me").status_code == 401


def test_token_do_provedor_de_outra_conta_e_recusado(amb):
    ana, intruso = google(amb), google(amb, sub="g-intruso", email="i@gmail.com", hd=None)
    r = amb.cliente().post("/api/auth/firebase/session", json={
        "id_token": intruso["idToken"], "provedor_id_token": ana["provedor_id_token"]})
    assert r.status_code == 401


def test_token_do_provedor_forjado_e_recusado(amb):
    login = google(amb)
    login["provedor_id_token"] = login["provedor_id_token"][:-6] + "AAAAAA"
    assert abrir_sessao(amb.cliente(), login).status_code == 401


# =============================================================== Microsoft
def test_microsoft_do_diretorio_da_instituicao_entra(amb):
    c = amb.cliente()
    r = abrir_sessao(c, microsoft(amb))
    assert r.status_code == 200 and (r.json()["estado"], r.json()["inst"]) == ("ativo", "unia")
    assert c.get("/api/painel").status_code == 200


def test_microsoft_de_outro_diretorio_com_email_da_universidade_nao_entra(amb):
    c = amb.cliente()
    r = abrir_sessao(c, microsoft(amb, oid="o-x", email="reitoria@unia.test", tid=OUTRO_TID))
    assert r.json()["estado"] == "pendente" and r.json()["email"] is None
    assert c.get("/api/painel").status_code == 403


def test_microsoft_conta_pessoal_fica_pendente(amb):
    r = abrir_sessao(amb.cliente(), microsoft(amb, oid="o-p", email="a@outlook.com",
                                              tid="9188040d-6c67-4c5b-b112-36a304b66dad"))
    assert r.json()["estado"] == "pendente"


# =============================================================== LDAP (OpenLDAP de teste)
def test_ldap_com_senha_certa_entra_pelo_custom_token(amb):
    c = amb.cliente()
    r = ldap(c, "ana", SENHA)
    assert r.status_code == 200, r.text
    # A conta e os claims existem antes de o custom token sair, e a conta não leva o e-mail.
    assert amb.fb.contas == {"ldap:unib:ana": "Ana Teste"}
    assert amb.fb.claims["ldap:unib:ana"] == {"inst": "unib", "papel": "USER", "estado": "ativo"}
    login = amb.fb.trocar_custom(r.json()["custom_token"])
    assert claims_de(login["idToken"])["inst"] == "unib"
    assert abrir_sessao(c, login).json() == {"estado": "ativo", "inst": "unib", "papel": "USER",
                                             "nome": "Ana Teste", "email": "ana@unib.test"}
    assert c.get("/api/painel").json()["inst"] == "unib"


def test_ldap_senha_errada_e_usuario_inexistente_dao_a_mesma_resposta(amb):
    c = amb.cliente()
    errada, inexistente = ldap(c, "ana", "senha-errada"), ldap(c, "ninguem", "senha-errada")
    assert errada.status_code == inexistente.status_code == 401
    assert errada.json() == inexistente.json()
    assert amb.fb.contas == {}


def test_ldap_senha_vazia_e_recusada(amb):
    assert ldap(amb.cliente(), "ana", "").status_code == 401


@pytest.mark.parametrize("usuario", ["*", "a*", "ana)(uid=*", "*)(objectClass=*", "ana\x00"])
def test_ldap_nao_aceita_injecao_no_filtro(amb, usuario):
    assert ldap(amb.cliente(), usuario, SENHA).status_code == 401


def test_ldap_atrasa_depois_de_erros_seguidos_ate_para_a_senha_certa(amb):
    c = amb.cliente()
    for _ in range(4):  # três livres; o quarto erro liga a espera
        assert ldap(c, "bruno", "errada").status_code == 401
    r = ldap(c, "bruno", SENHA)
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    assert ldap(c, "ana", SENHA).status_code == 200  # outra pessoa não é afetada


def test_ldap_email_de_outra_instituicao_nao_e_aceito_como_prova(amb):
    # O diretório da Universidade B diz que a Carla é reitoria@unia.test.
    c = amb.cliente()
    s = abrir_sessao(c, amb.fb.trocar_custom(ldap(c, "carla", SENHA).json()["custom_token"])).json()
    assert (s["estado"], s["inst"], s["email"]) == ("ativo", "unib", None)


def test_ldap_em_instituicao_sem_ldap_e_recusado(amb):
    assert ldap(amb.cliente(), "ana", SENHA, inst="unia").status_code == 400


def _cfg_ldap(ca):
    return LdapCfg(url="ldaps://ldap:636", base="ou=pessoas,dc=unib,dc=test",
                   filtro="(&(objectClass=inetOrgPerson)(uid={usuario}))",
                   bind_dn="cn=leitor,ou=servicos,dc=unib,dc=test", senha_env="", ca=ca)


def test_ldap_exige_o_certificado_assinado_pela_ca_da_instituicao():
    servico = os.environ["LDAP_UNIB_SENHA"]
    assert ldap_auth.autenticar(_cfg_ldap("/certs-pub/ca.crt"), "ana", SENHA, servico).uid == "ana"
    # Com outra CA (aqui, as do sistema), a conexão não é feita e a senha não é enviada.
    with pytest.raises(ldap_auth.LdapIndisponivel):
        ldap_auth.autenticar(_cfg_ldap("/etc/ssl/certs/ca-certificates.crt"), "ana", SENHA, servico)


def test_ldap_sem_tls_nao_aceita_senha():
    from ldap3 import Connection, Server
    c = Connection(Server("ldap://ldap:389"), user="uid=ana,ou=pessoas,dc=unib,dc=test",
                   password=SENHA)
    assert c.bind() is False  # o servidor de teste recusa bind simples fora de TLS


# =============================================================== CAFe (SP simulado)
def test_conferencia_do_ldap_passa_com_o_diretorio_de_teste_e_diz_onde_parou(monkeypatch):
    from poc.conferir_ldap import conferir
    linhas: list[str] = []
    assert conferir("unib", "ana", ler_senha=lambda _: SENHA, saida=linhas.append) is True
    assert [l[:6] for l in linhas if l.startswith(("PASSOU", "FALHOU"))] == ["PASSOU"] * 4
    assert SENHA not in "\n".join(linhas)

    linhas.clear()
    assert conferir("unib", "ana", ler_senha=lambda _: "errada", saida=linhas.append) is False
    assert linhas[-1].startswith("FALHOU  login")

    linhas.clear()
    assert conferir("unib", "ninguem", ler_senha=lambda _: SENHA, saida=linhas.append) is False
    assert linhas[-1].startswith("FALHOU  busca")

    linhas.clear()
    monkeypatch.setenv("LDAP_UNIB_SENHA", "senha-errada-da-conta-de-servico")
    assert conferir("unib", None, saida=linhas.append) is False
    assert linhas[-1].startswith("FALHOU  conexão ou conta de serviço")


def test_cafe_do_sp_ate_o_painel(amb):
    c = amb.cliente()
    r = cafe(c)
    assert r.status_code == 200 and '"cafe-ok"' in r.text
    # A página do popup não carrega token nenhum e só fala com a origem do painel.
    assert '"*"' not in r.text and "eyJ" not in r.text and "custom:" not in r.text
    troca = c.post("/api/auth/cafe/token", json={})
    assert troca.status_code == 200
    login = amb.fb.trocar_custom(troca.json()["custom_token"])
    assert login["localId"] == "cafe:ana@unia.test"
    s = abrir_sessao(c, login).json()
    assert (s["estado"], s["inst"], s["email"]) == ("ativo", "unia", "ana@unia.test")
    assert c.get("/api/painel").status_code == 200


def test_cafe_link_de_fora_sem_ter_comecado_o_login_e_recusado(amb):
    token = ponte_cafe.emitir_demo("ana@unia.test", "ana@unia.test", "Ana", "Teste", PONTE)
    c = amb.cliente()
    r = c.get("/api/auth/cafe/finish", params={"token": token})
    assert r.status_code == 400 and "cafe_troca" not in r.cookies
    assert amb.fb.contas == {}


def test_cafe_token_de_ponte_so_vale_uma_vez(amb):
    token = ponte_cafe.emitir_demo("ana@unia.test", "ana@unia.test", "Ana", "Teste", PONTE)
    for esperado in (200, 400):
        c = amb.cliente()
        c.get("/api/auth/cafe/login", follow_redirects=False)
        assert c.get("/api/auth/cafe/finish", params={"token": token}).status_code == esperado


def test_cafe_token_assinado_com_outro_segredo_e_recusado(amb):
    token = ponte_cafe.emitir_demo("ana@unia.test", "", "Ana", "", "x" * 48)
    c = amb.cliente()
    c.get("/api/auth/cafe/login", follow_redirects=False)
    assert c.get("/api/auth/cafe/finish", params={"token": token}).status_code == 400


def test_cafe_codigo_de_troca_so_vale_uma_vez_e_so_no_navegador_que_fez_o_login(amb):
    c = amb.cliente()
    cafe(c)
    assert c.post("/api/auth/cafe/token", json={}).status_code == 200
    assert c.post("/api/auth/cafe/token", json={}).status_code == 401
    assert amb.cliente().post("/api/auth/cafe/token", json={}).status_code == 401


def test_cafe_de_instituicao_nao_cadastrada_fica_pendente(amb):
    c = amb.cliente()
    cafe(c, eppn="joao@outra.test", email="joao@outra.test")
    login = amb.fb.trocar_custom(c.post("/api/auth/cafe/token", json={}).json()["custom_token"])
    assert abrir_sessao(c, login).json()["estado"] == "pendente"
    assert c.get("/api/painel").status_code == 403


def test_cafe_simulada_gera_o_mesmo_token_que_o_sp(amb):
    c = amb.cliente()
    r = c.get("/api/auth/cafe/login", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/demo/cafe/sp"
    r = c.post("/demo/cafe/sp", content="eppn=ana%40unia.test&email=ana%40unia.test&nome=Ana&sobrenome=Teste",
               headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200 and '"cafe-ok"' in r.text
    assert c.post("/api/auth/cafe/token", json={}).status_code == 200


# =============================================================== a mesma pessoa, dois logins
# =============================================================== login único da instituição (OIDC)
def test_login_unico_do_provedor_ate_o_painel(amb):
    c = amb.cliente()
    r = oidc(c)
    assert r.status_code == 200 and '"oidc-ok"' in r.text
    assert "custom:" not in r.text  # o custom token não vai pela janela
    troca = c.post("/api/auth/oidc/token", json={})
    assert troca.status_code == 200
    login = amb.fb.trocar_custom(troca.json()["custom_token"])
    assert login["localId"] == "oidc:unid:d-0001"
    assert amb.fb.claims[login["localId"]] == {"inst": "unid", "papel": "USER", "estado": "ativo"}
    s = abrir_sessao(c, login)
    assert s.status_code == 200 and (s.json()["inst"], s.json()["email"]) == ("unid", "davi@unid.test")
    assert c.get("/api/painel").json()["inst"] == "unid"


def test_login_unico_a_ida_leva_pkce_e_nada_que_sirva_para_concluir_sozinho(amb):
    c = amb.cliente()
    pedido = oidc_ida(c)
    assert pedido["code_challenge_method"] == "S256" and pedido["response_type"] == "code"
    assert pedido["redirect_uri"] == "http://localhost:8088/api/auth/oidc/callback"
    # O navegador leva só o estado, assinado. O nonce e o verificador ficam no backend.
    cookie = c.cookies.get("oidc_estado")
    assert cookie and pedido["nonce"] not in cookie and "code_verifier" not in pedido


def test_login_unico_link_de_fora_sem_ter_comecado_o_login_e_recusado(amb):
    vitima, atacante = amb.cliente(), amb.cliente()
    pedido = oidc_ida(atacante)
    r = atacante.post("/demo/oidc/authorize", data={**pedido, "sub": "x", "email": "x@unid.test"},
                      follow_redirects=False)
    # O atacante manda à vítima o link de volta do provedor, com o código dele.
    r = vitima.get(r.headers["location"])
    assert r.status_code == 400 and '"oidc-erro"' in r.text and "oidc_troca" not in r.cookies


def test_login_unico_com_estado_trocado_e_recusado(amb):
    c = amb.cliente()
    pedido = oidc_ida(c)
    r = c.post("/demo/oidc/authorize", data={**pedido, "sub": "d-0001"}, follow_redirects=False)
    codigo = parse_qs(urlsplit(r.headers["location"]).query)["code"][0]
    r = c.get("/api/auth/oidc/callback", params={"code": codigo, "state": "outro-estado"})
    assert r.status_code == 400 and "oidc_troca" not in r.cookies


def test_login_unico_a_volta_so_vale_uma_vez(amb):
    c = amb.cliente()
    pedido = oidc_ida(c)
    r = c.post("/demo/oidc/authorize", data={**pedido, "sub": "d-0001"}, follow_redirects=False)
    volta = r.headers["location"]
    cookie = c.cookies.get("oidc_estado")
    assert c.get(volta).status_code == 200
    c.cookies.set("oidc_estado", cookie, domain="localhost", path="/api/auth/oidc")
    assert c.get(volta).status_code == 400


def test_login_unico_codigo_que_o_provedor_nao_emitiu_e_recusado(amb):
    c = amb.cliente()
    pedido = oidc_ida(c)
    r = c.get("/api/auth/oidc/callback", params={"code": "inventado", "state": pedido["state"]})
    assert r.status_code == 401 and "oidc_troca" not in r.cookies


@pytest.mark.parametrize("mudancas", [
    {"iss": "http://localhost:8088/demo/outro"},
    {"aud": "outro-sistema"},
    {"nonce": "de-outro-login"},
    {"exp": 1},
])
def test_login_unico_token_do_provedor_com_claim_errado_e_recusado(amb, mudancas):
    simulado = amb.app.state.sso_simulado
    original = simulado.id_token
    simulado.id_token = lambda pedido: original(pedido, **mudancas)
    c = amb.cliente()
    r = oidc(c)
    assert r.status_code == 401 and '"oidc-erro"' in r.text
    assert c.post("/api/auth/oidc/token", json={}).status_code == 401
    assert amb.fb.contas == {}  # nenhuma conta foi criada no Firebase


def test_login_unico_token_assinado_por_outra_chave_e_recusado(amb):
    from cryptography.hazmat.primitives.asymmetric import rsa
    c = amb.cliente()
    oidc(c)  # o backend guarda as chaves publicadas pelo provedor
    # Alguém assina com outra chave, usando o mesmo identificador de chave do provedor.
    amb.app.state.sso_simulado.chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert oidc(amb.cliente(), sub="d-0002").status_code == 401
    assert "oidc:unid:d-0002" not in amb.fb.contas


def test_login_unico_em_instituicao_sem_ele_e_recusado(amb):
    c = amb.cliente()
    for inst in ("unia", "unib", "nao-existe", ""):
        r = c.get("/api/auth/oidc/login", params={"inst": inst}, follow_redirects=False)
        assert r.status_code == 400


def test_login_unico_codigo_de_troca_so_vale_uma_vez_e_nao_serve_na_rota_da_cafe(amb):
    c = amb.cliente()
    oidc(c)
    codigo = c.cookies.get("oidc_troca")
    c.cookies.set("cafe_troca", codigo, domain="localhost", path="/api/auth/cafe")
    assert c.post("/api/auth/cafe/token", json={}).status_code == 401
    assert c.post("/api/auth/oidc/token", json={}).status_code == 200
    assert c.post("/api/auth/oidc/token", json={}).status_code == 401
    assert amb.cliente().post("/api/auth/oidc/token", json={}).status_code == 401


def test_login_unico_email_nao_verificado_nao_assume_a_conta_de_quem_ja_existe(amb):
    def entrar(sub, verificado):
        c = amb.cliente()
        oidc(c, sub=sub, email="davi@unid.test", verificado=verificado)
        login = amb.fb.trocar_custom(c.post("/api/auth/oidc/token", json={}).json()["custom_token"])
        abrir_sessao(c, login)
        return c.get("/api/me").json()

    dono = entrar("d-0001", True)
    outro = entrar("d-0666", False)  # digitou o e-mail do dono no cadastro do provedor
    assert dono["email"] == "davi@unid.test"
    assert outro["usuario_id"] != dono["usuario_id"] and outro["email"] is None
    assert outro["inst"] == "unid"  # é da instituição, mas é outra pessoa


def test_login_unico_identificador_igual_em_outra_instituicao_e_outra_conta(amb):
    assert fb_uid("oidc", "unid", "d-0001") != fb_uid("oidc", "outra", "d-0001")


@pytest.mark.parametrize("teto", ["MAXIMO_IDAS_OIDC", "MAXIMO_IDAS_OIDC_POR_IP"])
def test_login_unico_tem_teto_de_logins_em_andamento(amb, monkeypatch, teto):
    from poc import app as modulo
    monkeypatch.setattr(modulo, teto, 3)
    c = amb.cliente()
    respostas = [c.get("/api/auth/oidc/login", params={"inst": "unid"},
                       follow_redirects=False).status_code for _ in range(5)]
    assert respostas == [303, 303, 303, 503, 503]


def test_login_unico_quem_desiste_na_tela_do_provedor_libera_a_vaga(amb, monkeypatch):
    from poc import app as modulo
    monkeypatch.setattr(modulo, "MAXIMO_IDAS_OIDC", 1)
    c = amb.cliente()
    pedido = oidc_ida(c)
    # O provedor devolve o navegador sem código, com o erro.
    r = c.get("/api/auth/oidc/callback", params={"error": "access_denied", "state": pedido["state"]})
    assert r.status_code == 400 and '"oidc-erro"' in r.text
    assert c.get("/api/auth/oidc/login", params={"inst": "unid"},
                 follow_redirects=False).status_code == 303


def test_login_unico_estado_fora_do_ascii_e_recusado_sem_quebrar(amb):
    c = amb.cliente()
    oidc_ida(c)
    r = c.get("/api/auth/oidc/callback", params={"code": "x", "state": "não-é-o-nosso"})
    assert r.status_code == 400 and '"oidc-erro"' in r.text


def test_limpeza_dos_testes_nao_aceita_pedido_vindo_de_outra_pagina(amb):
    assert amb.cliente(origem="https://outro.test").post("/demo/reset").status_code == 403
    assert amb.cliente().post("/demo/reset").status_code == 200
    assert amb.cliente(origem=None).post("/demo/reset").status_code == 200  # os testes, sem navegador


def test_login_unico_provedor_fora_do_ar_avisa_sem_abrir_nada(amb):
    import httpx
    def fora_do_ar(pedido):
        raise httpx.ConnectError("sem rota")
    amb.app.state.oidc.http = httpx.Client(transport=httpx.MockTransport(fora_do_ar))
    r = amb.cliente().get("/api/auth/oidc/login", params={"inst": "unid"}, follow_redirects=False)
    assert r.status_code == 503 and '"oidc-erro"' in r.text


def test_google_e_cafe_da_mesma_pessoa_viram_um_usuario_so(amb):
    a = amb.cliente()
    abrir_sessao(a, google(amb))
    b = amb.cliente()
    cafe(b)
    abrir_sessao(b, amb.fb.trocar_custom(b.post("/api/auth/cafe/token", json={}).json()["custom_token"]))
    eu_google, eu_cafe = a.get("/api/me").json(), b.get("/api/me").json()
    assert eu_google["email"] == eu_cafe["email"] == "ana@unia.test"
    assert eu_google["usuario_id"] == eu_cafe["usuario_id"]


def test_email_so_afirmado_nao_assume_a_conta_de_quem_ja_existe(amb):
    a = amb.cliente()
    abrir_sessao(a, google(amb))
    b = amb.cliente()  # outro diretório Microsoft afirma ser ana@unia.test
    abrir_sessao(b, microsoft(amb, oid="o-falsa", tid=OUTRO_TID))
    ana, falsa = a.get("/api/me").json(), b.get("/api/me").json()
    assert falsa["usuario_id"] != ana["usuario_id"]
    assert (falsa["estado"], falsa["email"], falsa["inst"]) == ("pendente", None, None)


# =============================================================== tokens que não podem valer
def test_token_que_o_firebase_recusa_nao_abre_nada(amb):
    c = amb.cliente()
    recusado = amb.fb.id_token("fb-x", "google.com", {"google.com": ["x"]}, aud="outro-projeto")
    assert c.get("/api/me", headers=bearer(recusado)).status_code == 401
    assert c.post("/api/auth/firebase/session", json={"id_token": recusado}).status_code == 401


def test_login_feito_ha_mais_de_doze_horas_e_recusado_mesmo_com_token_novo(amb):
    import time
    login = google(amb)
    abrir_sessao(amb.cliente(), login)
    antigo = amb.fb.id_token(login["localId"], "google.com", {"google.com": ["g-ana"]},
                             auth_time=int(time.time()) - 13 * 3600)
    c = amb.cliente()
    assert c.get("/api/me", headers=bearer(antigo)).status_code == 401
    assert c.post("/api/auth/firebase/session", json={"id_token": antigo}).status_code == 401


def test_conta_que_nunca_passou_pelo_backend_e_recusada(amb):
    nunca = amb.fb.id_token("fb-nunca", "google.com", {"google.com": ["n"]})
    assert amb.cliente().get("/api/me", headers=bearer(nunca)).status_code == 401


def test_login_por_senha_do_firebase_nao_e_aceito(amb):
    senha = amb.fb.id_token("fb-s", "password", {"email": ["a@b.test"]})
    assert amb.cliente().post("/api/auth/firebase/session", json={"id_token": senha}).status_code == 403


def test_custom_token_de_conta_que_o_backend_nao_criou_e_recusado(amb):
    forjado = amb.fb.id_token("ldap:unib:ninguem", "custom", {})
    assert amb.cliente().post("/api/auth/firebase/session", json={"id_token": forjado}).status_code == 401


def test_token_e_cookie_de_contas_diferentes_sao_recusados(amb):
    c = amb.cliente()
    abrir_sessao(c, google(amb))
    outra = google(amb, sub="g-bia", email="bia@unia.test")
    assert c.get("/api/me", headers=bearer(outra["idToken"])).status_code == 401


# =============================================================== sessão
def test_sem_login_nao_ha_acesso(amb):
    c = amb.cliente()
    assert c.get("/api/me").status_code == 401 and c.get("/api/painel").status_code == 401


def test_pedido_de_outra_origem_e_recusado(amb):
    c = amb.cliente(origem="https://site-malicioso.test")
    assert abrir_sessao(c, google(amb)).status_code == 403


def test_pedido_que_nao_e_json_e_recusado(amb):
    r = amb.cliente().post("/api/auth/ldap/login",
                           data={"inst": "unib", "usuario": "ana", "senha": SENHA})
    assert r.status_code in (415, 422)


def test_sair_encerra_a_sessao_e_pede_ao_firebase_para_invalidar_a_renovacao(amb):
    login = google(amb)
    c = amb.cliente()
    abrir_sessao(c, login)
    assert c.post("/api/auth/logout", json={}).status_code == 200
    assert c.get("/api/me").status_code == 401
    assert amb.fb.revogados == [login["localId"]]


def test_a_senha_nunca_aparece_na_resposta_de_erro(amb):
    r = amb.cliente().post("/api/auth/ldap/login", json={
        "inst": "unib", "usuario": "ana", "senha": {"valor": "nao-e-texto-SEGREDO"}})
    assert r.status_code == 422 and "SEGREDO" not in r.text


def test_pagina_recebe_a_configuracao_sem_segredo_nenhum(amb):
    r = amb.cliente().get("/config.js")
    assert r.status_code == 200 and "chave-web" in r.text and "iotedu-teste" in r.text
    assert "s" * 48 not in r.text and PONTE not in r.text and "conta.json" not in r.text
