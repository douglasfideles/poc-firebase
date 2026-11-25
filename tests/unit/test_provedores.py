"""O verificador de produção dos tokens do Google e da Microsoft, com uma chave RSA local."""
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from poc.provedores import TokenDeProvedorInvalido, VerificadorJWKS

CHAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OUTRA = rsa.generate_private_key(public_exponent=65537, key_size=2048)
TID = "11111111-1111-4111-8111-111111111111"


def verificador():
    return VerificadorJWKS("cid-google", "cid-ms", obter_chave=lambda p, t: CHAVE.public_key())


def google(chave=CHAVE, **mudancas):
    agora = int(time.time())
    c = {"iss": "https://accounts.google.com", "aud": "cid-google", "sub": "g-1",
         "email": "ana@unia.test", "email_verified": True, "hd": "unia.test",
         "iat": agora, "exp": agora + 600}
    c.update(mudancas)
    return jwt.encode(c, chave, algorithm="RS256")


def microsoft(**mudancas):
    agora = int(time.time())
    c = {"iss": f"https://login.microsoftonline.com/{TID}/v2.0", "aud": "cid-ms", "sub": "s-1",
         "oid": "o-1", "tid": TID, "preferred_username": "ana@unia.test",
         "iat": agora, "exp": agora + 600}
    c.update(mudancas)
    return jwt.encode(c, CHAVE, algorithm="RS256")


def test_google_valido_traz_o_dominio():
    c = verificador().verificar("google.com", google())
    assert (c.provedor, c.sujeito, c.hd, c.email_verificado) == ("google", "g-1", "unia.test", True)


def test_google_feito_para_outro_aplicativo_e_recusado():
    with pytest.raises(TokenDeProvedorInvalido):
        verificador().verificar("google.com", google(aud="outro-app"))


def test_google_com_assinatura_de_outra_chave_e_recusado():
    with pytest.raises(TokenDeProvedorInvalido):
        verificador().verificar("google.com", google(chave=OUTRA))


def test_google_expirado_e_recusado():
    with pytest.raises(TokenDeProvedorInvalido):
        verificador().verificar("google.com", google(exp=int(time.time()) - 10))


def test_google_de_outro_emissor_e_recusado():
    with pytest.raises(TokenDeProvedorInvalido):
        verificador().verificar("google.com", google(iss="https://exemplo.test"))


def test_token_sem_assinatura_e_recusado_em_producao():
    sem = jwt.encode({"sub": "g-1", "aud": "cid-google"}, key="", algorithm="none")
    with pytest.raises(TokenDeProvedorInvalido):
        verificador().verificar("google.com", sem)


def test_microsoft_valido_traz_o_diretorio_e_usa_o_oid():
    c = verificador().verificar("microsoft.com", microsoft())
    assert (c.provedor, c.sujeito, c.tid) == ("microsoft", "o-1", TID)
    assert c.email_verificado is False


def test_microsoft_com_emissor_de_outro_diretorio_e_recusado():
    with pytest.raises(TokenDeProvedorInvalido):
        verificador().verificar("microsoft.com", microsoft(
            iss="https://login.microsoftonline.com/99999999-9999-4999-8999-999999999999/v2.0"))


def test_microsoft_sem_oid_e_recusado():
    with pytest.raises(TokenDeProvedorInvalido):
        verificador().verificar("microsoft.com", microsoft(oid=None))


def test_provedor_fora_da_lista_e_recusado():
    with pytest.raises(TokenDeProvedorInvalido):
        verificador().verificar("facebook.com", google())
