"""Ponta a ponta contra o projeto Firebase de verdade.

Precisa do backend no ar com a chave de serviço do projeto e do `FIREBASE_WEB_API_KEY`. Aqui os
tokens são emitidos e assinados pelo Firebase, e as trocas passam pela API pública dele, a mesma
que o SDK web usa. Os logins são LDAP e CAFe (com o SP simulado), porque são os que dispensam uma
pessoa digitando a senha numa tela do Google ou da Microsoft.

As contas criadas (`ldap:...`, `cafe:...`) são apagadas do projeto antes e depois de cada teste.
"""
import base64
import json
import os
import time

import httpx
import pytest

from poc import ponte_cafe

BACKEND = os.environ.get("BACKEND_URL", "http://backend:8088")
ORIGEM = os.environ.get("ORIGEM_FRONT", "http://localhost:8088")
CHAVE_WEB = os.environ.get("FIREBASE_WEB_API_KEY", "")
PROJETO = os.environ.get("FIREBASE_PROJECT_ID", "")
SENHA = os.environ.get("LDAP_SENHA_PESSOAS", "")
PONTE = os.environ.get("CAFE_PONTE_SEGREDO", "")
IDK = "https://identitytoolkit.googleapis.com/v1"

pytestmark = pytest.mark.skipif(not CHAVE_WEB, reason="sem FIREBASE_WEB_API_KEY: projeto real não configurado")


def limpar():
    httpx.post(f"{BACKEND}/demo/reset", timeout=60).raise_for_status()


@pytest.fixture(autouse=True)
def do_zero():
    limpar()
    yield
    limpar()


def cliente() -> httpx.Client:
    return httpx.Client(base_url=BACKEND, headers={"Origin": ORIGEM}, timeout=30)


def trocar_custom(custom_token: str) -> httpx.Response:
    """O que o `signInWithCustomToken` do SDK web faz: troca o custom token no Firebase."""
    return httpx.post(f"{IDK}/accounts:signInWithCustomToken", params={"key": CHAVE_WEB},
                      json={"token": custom_token, "returnSecureToken": True}, timeout=30)


def renovar(refresh_token: str) -> httpx.Response:
    return httpx.post("https://securetoken.googleapis.com/v1/token", params={"key": CHAVE_WEB},
                      data={"grant_type": "refresh_token", "refresh_token": refresh_token}, timeout=30)


def claims_de(id_token: str) -> dict:
    meio = id_token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(meio + "=" * (-len(meio) % 4)))


def entrar_ldap(c: httpx.Client, usuario: str = "ana") -> dict:
    r = c.post("/api/auth/ldap/login", json={"inst": "unib", "usuario": usuario, "senha": SENHA})
    assert r.status_code == 200, r.text
    troca = trocar_custom(r.json()["custom_token"])
    assert troca.status_code == 200, troca.text
    return troca.json()


def abrir_sessao(c: httpx.Client, id_token: str) -> httpx.Response:
    return c.post("/api/auth/firebase/session", json={"id_token": id_token})


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_ldap_de_ponta_a_ponta_com_token_assinado_pelo_firebase():
    with cliente() as c:
        login = entrar_ldap(c)
        claims = claims_de(login["idToken"])
        assert claims["aud"] == PROJETO and claims["user_id"] == "ldap:unib:ana"
        assert claims["firebase"]["sign_in_provider"] == "custom"
        # Os claims gravados antes do custom token já vêm no primeiro ID token.
        assert (claims["inst"], claims["papel"], claims["estado"]) == ("unib", "USER", "ativo")
        assert "email" not in claims  # o e-mail do LDAP não foi para o Firebase
        s = abrir_sessao(c, login["idToken"])
        assert s.status_code == 200 and s.json()["inst"] == "unib"
        assert c.get("/api/painel").status_code == 200


def test_o_token_do_firebase_vale_sozinho_no_cabecalho():
    with cliente() as c:
        login = entrar_ldap(c)
        abrir_sessao(c, login["idToken"])
    r = httpx.get(f"{BACKEND}/api/me", headers=bearer(login["idToken"]), timeout=30)
    assert r.status_code == 200 and (r.json()["via"], r.json()["inst"]) == ("bearer", "unib")


def test_cafe_de_ponta_a_ponta_com_o_sp_simulado():
    with cliente() as c:
        c.get("/api/auth/cafe/login")
        token = ponte_cafe.emitir_demo("ana@unia.test", "ana@unia.test", "Ana", "Teste", PONTE)
        assert c.get("/api/auth/cafe/finish", params={"token": token}).status_code == 200
        troca = trocar_custom(c.post("/api/auth/cafe/token", json={}).json()["custom_token"])
        assert troca.status_code == 200, troca.text
        claims = claims_de(troca.json()["idToken"])
        assert (claims["user_id"], claims["inst"]) == ("cafe:ana@unia.test", "unia")
        assert abrir_sessao(c, troca.json()["idToken"]).json()["email"] == "ana@unia.test"


def test_token_com_assinatura_adulterada_e_recusado():
    with cliente() as c:
        token = entrar_ldap(c)["idToken"]
        cabeca, corpo, assinatura = token.split(".")
        trocado = "A" if assinatura[10] != "A" else "B"
        adulterado = f"{cabeca}.{corpo}.{assinatura[:10]}{trocado}{assinatura[11:]}"
        assert httpx.get(f"{BACKEND}/api/me", headers=bearer(adulterado), timeout=30).status_code == 401
        assert abrir_sessao(c, adulterado).status_code == 401


def test_token_com_o_conteudo_trocado_e_recusado():
    with cliente() as c:
        token = entrar_ldap(c)["idToken"]
    cabeca, corpo, assinatura = token.split(".")
    claims = claims_de(token)
    claims.update({"inst": "unia", "papel": "SUPERUSER"})
    novo = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    r = httpx.get(f"{BACKEND}/api/me", headers=bearer(f"{cabeca}.{novo}.{assinatura}"), timeout=30)
    assert r.status_code == 401


def test_token_sem_assinatura_e_recusado():
    b64 = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    agora = int(time.time())
    falso = b64({"alg": "none", "typ": "JWT"}) + "." + b64({
        "iss": f"https://securetoken.google.com/{PROJETO}", "aud": PROJETO, "sub": "ldap:unib:ana",
        "user_id": "ldap:unib:ana", "iat": agora, "exp": agora + 3600, "auth_time": agora,
        "inst": "unib", "estado": "ativo",
        "firebase": {"sign_in_provider": "custom", "identities": {}}}) + "."
    assert httpx.get(f"{BACKEND}/api/me", headers=bearer(falso), timeout=30).status_code == 401


def test_o_firebase_recusa_custom_token_que_o_backend_nao_assinou():
    with cliente() as c:
        r = c.post("/api/auth/ldap/login", json={"inst": "unib", "usuario": "ana", "senha": SENHA})
    cabeca, corpo, assinatura = r.json()["custom_token"].split(".")
    claims = claims_de(r.json()["custom_token"])
    claims["uid"] = "ldap:unib:bruno"  # tentar virar outra pessoa
    novo = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    assert trocar_custom(f"{cabeca}.{novo}.{assinatura}").status_code == 400


def test_renovar_o_token_mantem_os_claims():
    with cliente() as c:
        login = entrar_ldap(c)
    r = renovar(login["refreshToken"])
    assert r.status_code == 200, r.text
    assert claims_de(r.json()["id_token"])["inst"] == "unib"


def test_depois_de_sair_o_firebase_nao_renova_mais_o_token():
    with cliente() as c:
        login = entrar_ldap(c)
        abrir_sessao(c, login["idToken"])
        time.sleep(1.5)  # a invalidação vale para tokens emitidos até o segundo anterior
        assert c.post("/api/auth/logout", json={}).status_code == 200
        assert c.get("/api/me").status_code == 401
    assert renovar(login["refreshToken"]).status_code == 400
