"""O cliente do login único (OIDC) contra um provedor de mentira, em memória. Sem rede.

O provedor responde a descoberta, as chaves e a troca do código. Cada teste muda uma coisa no que
ele entrega e confere que o login é recusado.
"""
import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from poc import oidc_auth
from poc.config import OidcCfg

EMISSOR = "https://sso.unid.test/realms/unid"
RETORNO = "https://painel.test/api/auth/oidc/callback"
CHAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OUTRA_CHAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
CFG = OidcCfg(emissor=EMISSOR, client_id="iotedu")


class Provedor:
    """Guarda o que o backend mandou e devolve o ID token montado pelo teste."""

    def __init__(self, **mudancas) -> None:
        self.claims = mudancas
        self.chave = CHAVE
        self.algoritmo = "RS256"
        self.descoberta = {"issuer": EMISSOR, "authorization_endpoint": f"{EMISSOR}/auth",
                           "token_endpoint": f"{EMISSOR}/token", "jwks_uri": f"{EMISSOR}/certs"}
        self.status_token = 200
        self.pedidos: list[httpx.Request] = []
        self.token_pronto: str | None = None

    def id_token(self) -> str:
        if self.token_pronto is not None:
            return self.token_pronto
        agora = int(time.time())
        c = {"iss": EMISSOR, "aud": "iotedu", "sub": "u-1", "email": "Davi@UniD.test",
             "email_verified": True, "name": "Davi Teste", "nonce": "n-1", "iat": agora,
             "exp": agora + 300}
        c.update(self.claims)
        chave = self.chave if self.algoritmo != "HS256" else "segredo-qualquer-de-32-caracteres!!"
        return jwt.encode({k: v for k, v in c.items() if v is not None}, chave,
                          algorithm=self.algoritmo, headers={"kid": "k1"})

    def responder(self, pedido: httpx.Request) -> httpx.Response:
        self.pedidos.append(pedido)
        caminho = pedido.url.path
        if caminho.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json=self.descoberta)
        if caminho.endswith("/certs"):
            jwk = jwt.algorithms.RSAAlgorithm.to_jwk(CHAVE.public_key(), as_dict=True)
            return httpx.Response(200, json={"keys": [{**jwk, "kid": "k1"}]})
        if caminho.endswith("/token"):
            if self.status_token != 200:
                return httpx.Response(self.status_token, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"id_token": self.id_token(), "access_token": "a"})
        return httpx.Response(404)

    def cliente(self) -> oidc_auth.ClienteOidc:
        return oidc_auth.ClienteOidc(httpx.Client(transport=httpx.MockTransport(self.responder)))


def concluir(provedor: Provedor, cfg: OidcCfg = CFG, segredo: str = ""):
    return provedor.cliente().concluir(cfg, RETORNO, "codigo-1", "verificador-1", "n-1", segredo)


# ---------------------------------------------------------------- o caminho certo
def test_login_certo_traz_os_dados_da_pessoa():
    a = concluir(Provedor())
    assert (a.sujeito, a.email, a.email_verificado, a.nome) == ("u-1", "davi@unid.test", True,
                                                                "Davi Teste")


def test_ida_leva_estado_nonce_e_desafio_pkce_e_nunca_o_verificador():
    verificador, desafio = oidc_auth.novo_par_pkce()
    assert desafio == base64.urlsafe_b64encode(
        hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()
    endereco = Provedor().cliente().endereco_de_login(CFG, RETORNO, "e-1", "n-1", desafio)
    q = {k: v[0] for k, v in parse_qs(urlsplit(endereco).query).items()}
    assert endereco.startswith(f"{EMISSOR}/auth?")
    assert q == {"response_type": "code", "client_id": "iotedu", "redirect_uri": RETORNO,
                 "scope": "openid email profile", "state": "e-1", "nonce": "n-1",
                 "code_challenge": desafio, "code_challenge_method": "S256"}
    assert verificador not in endereco


def test_troca_do_codigo_manda_o_verificador_e_o_segredo_vai_no_cabecalho():
    publico, com_segredo = Provedor(), Provedor()
    concluir(publico)
    concluir(com_segredo, segredo="s3gredo")
    troca = [p for p in publico.pedidos if p.url.path.endswith("/token")][0]
    corpo = {k: v[0] for k, v in parse_qs(troca.content.decode()).items()}
    assert corpo == {"grant_type": "authorization_code", "code": "codigo-1",
                     "redirect_uri": RETORNO, "code_verifier": "verificador-1",
                     "client_id": "iotedu"}
    assert "authorization" not in troca.headers
    troca = [p for p in com_segredo.pedidos if p.url.path.endswith("/token")][0]
    assert troca.headers["authorization"] == "Basic " + base64.b64encode(b"iotedu:s3gredo").decode()
    assert "s3gredo" not in troca.content.decode()


def test_a_descoberta_e_as_chaves_ficam_em_cache():
    p = Provedor()
    c = p.cliente()
    for _ in range(3):
        c.concluir(CFG, RETORNO, "codigo-1", "verificador-1", "n-1")
    caminhos = [x.url.path.rsplit("/", 1)[1] for x in p.pedidos]
    assert caminhos.count("openid-configuration") == 1 and caminhos.count("certs") == 1
    assert caminhos.count("token") == 3


# ---------------------------------------------------------------- o que é recusado
@pytest.mark.parametrize("mudancas", [
    {"iss": "https://outro.test/realms/unid"},   # assinado por quem é, mas declara outro emissor
    {"aud": "outro-cliente"},                    # emitido para outro sistema
    {"aud": ["iotedu", "outro"], "azp": "outro"},
    {"nonce": "n-de-outro-login"},               # token de outro login, reaproveitado
    {"nonce": None},
    {"exp": int(time.time()) - 3600},
    {"sub": None},
    {"sub": "x" * 300},
])
def test_id_token_com_claim_errado_e_recusado(mudancas):
    with pytest.raises(oidc_auth.OidcInvalido):
        concluir(Provedor(**mudancas))


def test_id_token_assinado_por_outra_chave_e_recusado():
    p = Provedor()
    p.chave = OUTRA_CHAVE
    with pytest.raises(oidc_auth.OidcInvalido):
        concluir(p)


def test_id_token_sem_assinatura_ou_com_segredo_compartilhado_e_recusado():
    b64 = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    agora = int(time.time())
    sem_assinatura = Provedor()
    sem_assinatura.token_pronto = b64({"alg": "none", "kid": "k1"}) + "." + b64({
        "iss": EMISSOR, "aud": "iotedu", "sub": "u-1", "nonce": "n-1", "iat": agora,
        "exp": agora + 300}) + "."
    hs = Provedor()
    hs.algoritmo = "HS256"
    for p in (sem_assinatura, hs):
        with pytest.raises(oidc_auth.OidcInvalido):
            concluir(p)


def test_emissor_com_barra_no_fim_e_aceito_e_o_token_tem_de_trazer_o_emissor_publicado():
    # Há provedor (Authentik, Auth0) cujo emissor termina em barra. O cadastro guarda sem a barra.
    com_barra = Provedor(iss=EMISSOR + "/")
    com_barra.descoberta["issuer"] = EMISSOR + "/"
    assert concluir(com_barra).sujeito == "u-1"
    # O provedor publica com barra e o token vem sem: não é o mesmo emissor.
    divergente = Provedor()
    divergente.descoberta["issuer"] = EMISSOR + "/"
    with pytest.raises(oidc_auth.OidcInvalido):
        concluir(divergente)


def test_token_com_algoritmo_de_outra_familia_que_a_chave_e_recusado_sem_quebrar():
    from cryptography.hazmat.primitives.asymmetric import ec
    p = Provedor()
    p.chave = ec.generate_private_key(ec.SECP256R1())
    p.algoritmo = "ES256"  # as chaves publicadas pelo provedor são RSA
    with pytest.raises(oidc_auth.OidcInvalido):
        concluir(p)


def test_nonce_com_caracteres_fora_do_ascii_e_recusado_sem_quebrar():
    with pytest.raises(oidc_auth.OidcInvalido):
        concluir(Provedor(nonce="não-é-o-nosso"))


def test_email_so_conta_como_verificado_com_true_de_verdade():
    assert concluir(Provedor(email_verified="true")).email_verificado is False
    assert concluir(Provedor(email_verified=None)).email_verificado is False


def test_provedor_que_recusa_o_codigo_nao_entra():
    p = Provedor()
    p.status_token = 400
    with pytest.raises(oidc_auth.OidcInvalido):
        concluir(p)


def test_provedor_fora_do_ar_nao_e_confundido_com_login_recusado():
    p = Provedor()
    p.status_token = 503
    with pytest.raises(oidc_auth.OidcIndisponivel):
        concluir(p)


@pytest.mark.parametrize("mudancas", [
    {"issuer": "https://outro.test/realms/unid"},       # a descoberta é de outro provedor
    {"token_endpoint": "http://sso.unid.test/token"},   # emissor https, endereço http
    {"jwks_uri": ""},
])
def test_descoberta_incoerente_ou_insegura_e_recusada(mudancas):
    p = Provedor()
    p.descoberta.update(mudancas)
    with pytest.raises(oidc_auth.OidcIndisponivel):
        concluir(p)
    with pytest.raises(oidc_auth.OidcIndisponivel):
        p.cliente().endereco_de_login(CFG, RETORNO, "e", "n", "d")
