"""Quem entra na hora, quem fica pendente e quem é recusado. Sem rede."""
from poc.regras import ATIVO, PENDENTE, RECUSADO, TID_CONTA_PESSOAL, ProvaLogin, decidir

TID_UNIA = "11111111-1111-4111-8111-111111111111"


def test_google_com_dominio_da_instituicao_entra_ativo(insts):
    d = decidir(ProvaLogin("google", "g1", email="ana@unia.test", email_verificado=True,
                           hd="unia.test"), insts)
    assert (d.estado, d.inst, d.email_provado) == (ATIVO, "unia", "ana@unia.test")


def test_google_sem_hd_fica_pendente_mesmo_com_email_do_dominio(insts):
    # Conta Google pessoal criada com o e-mail da universidade: o e-mail sozinho não prova nada.
    d = decidir(ProvaLogin("google", "g1", email="ana@unia.test", email_verificado=True), insts)
    assert (d.estado, d.inst, d.email_provado) == (PENDENTE, None, None)


def test_google_com_email_nao_verificado_fica_pendente(insts):
    d = decidir(ProvaLogin("google", "g1", email="ana@unia.test", hd="unia.test"), insts)
    assert d.estado == PENDENTE


def test_google_desligado_para_a_instituicao_recusa(insts):
    d = decidir(ProvaLogin("google", "g1", email="x@unic.test", email_verificado=True,
                           hd="unic.test"), insts)
    assert (d.estado, d.inst) == (RECUSADO, "unic")


def test_microsoft_com_diretorio_cadastrado_entra_ativo(insts):
    d = decidir(ProvaLogin("microsoft", "o1", email="ana@unia.test", tid=TID_UNIA), insts)
    assert (d.estado, d.inst) == (ATIVO, "unia")


def test_microsoft_email_do_dominio_em_outro_diretorio_nao_entra(insts):
    # Qualquer organização cria no próprio diretório uma conta com o e-mail que quiser.
    d = decidir(ProvaLogin("microsoft", "o1", email="reitoria@unia.test",
                           tid="99999999-9999-4999-8999-999999999999"), insts)
    assert (d.estado, d.inst, d.email_provado) == (PENDENTE, None, None)


def test_microsoft_conta_pessoal_fica_pendente(insts):
    d = decidir(ProvaLogin("microsoft", "o1", email="a@outlook.com", tid=TID_CONTA_PESSOAL), insts)
    assert d.estado == PENDENTE


def test_ldap_entra_na_instituicao_do_diretorio(insts):
    d = decidir(ProvaLogin("ldap", "unib:ana", email="ana@unib.test", inst_ldap="unib"), insts)
    assert (d.estado, d.inst, d.email_provado) == (ATIVO, "unib", "ana@unib.test")


def test_ldap_email_de_outra_instituicao_nao_vale_como_prova(insts):
    d = decidir(ProvaLogin("ldap", "unib:carla", email="reitoria@unia.test", inst_ldap="unib"),
                insts)
    assert (d.estado, d.inst, d.email_provado) == (ATIVO, "unib", None)


def test_ldap_em_instituicao_sem_ldap_recusa(insts):
    assert decidir(ProvaLogin("ldap", "unia:x", inst_ldap="unia"), insts).estado == RECUSADO


def test_cafe_com_escopo_cadastrado_entra_ativo(insts):
    d = decidir(ProvaLogin("cafe", "ana@unia.test", eppn="ana@unia.test"), insts)
    assert (d.estado, d.inst) == (ATIVO, "unia")


def test_cafe_com_escopo_desconhecido_fica_pendente(insts):
    d = decidir(ProvaLogin("cafe", "x@outra.test", eppn="x@outra.test"), insts)
    assert (d.estado, d.inst) == (PENDENTE, None)


def test_provedor_desconhecido_recusa(insts):
    assert decidir(ProvaLogin("senha", "x"), insts).estado == RECUSADO


def test_login_unico_entra_na_instituicao_do_provedor_que_assinou(insts):
    d = decidir(ProvaLogin("oidc", "unid:u-1", email="davi@unid.test", email_verificado=True,
                           inst_oidc="unid"), insts)
    assert (d.estado, d.inst, d.email_provado) == (ATIVO, "unid", "davi@unid.test")


def test_login_unico_so_prova_email_verificado_e_do_dominio_da_instituicao(insts):
    nao_verificado = decidir(ProvaLogin("oidc", "unid:u-1", email="davi@unid.test",
                                        inst_oidc="unid"), insts)
    de_fora = decidir(ProvaLogin("oidc", "unid:u-1", email="reitoria@unia.test",
                                 email_verificado=True, inst_oidc="unid"), insts)
    assert (nao_verificado.estado, nao_verificado.email_provado) == (ATIVO, None)
    assert (de_fora.estado, de_fora.email_provado) == (ATIVO, None)


def test_login_unico_em_instituicao_sem_ele_e_recusado(insts):
    for inst in ("unia", "nao-existe", None):
        assert decidir(ProvaLogin("oidc", "x:u-1", inst_oidc=inst), insts).estado == RECUSADO
