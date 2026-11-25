"""Confere a página `pagina/` num Chromium de verdade, sem tela, com o Firebase de verdade.

Roda dentro da rede do backend (network_mode: service:backend), então `localhost:8088` é o
backend, como no navegador de quem testa à mão. O SDK web fala direto com o Firebase.

Cobre LDAP e CAFe (com o SP simulado). Google e Microsoft ficam para a conferência manual: as
telas de login deles não aceitam navegador automatizado.
"""
import os
import sys

import httpx
from playwright.sync_api import sync_playwright

PAINEL = "http://localhost:8088"
SENHA = os.environ["LDAP_SENHA_PESSOAS"]


def do_zero():
    httpx.post(f"{PAINEL}/demo/reset", timeout=60).raise_for_status()


def nova_pagina(navegador):
    contexto = navegador.new_context()
    pagina = contexto.new_page()
    erros = []
    pagina.on("pageerror", lambda e: erros.append(str(e)))
    pagina.goto(PAINEL)
    pagina.wait_for_selector("#inst option", state="attached")
    return contexto, pagina, erros


def esperar_resultado(pagina):
    pagina.wait_for_selector("#resultado:not([hidden])", timeout=30000)
    return pagina.inner_text("#resumo"), pagina.inner_text("#respostas"), pagina.inner_text("#claims")


def ldap(navegador):
    contexto, pagina, erros = nova_pagina(navegador)
    pagina.select_option("#inst", "unib")
    pagina.fill("#usuario", "ana")
    pagina.fill("#senha", SENHA)
    pagina.click("#ldap button")
    resumo, respostas, claims = esperar_resultado(pagina)
    assert "Entrou em unib" in resumo, resumo
    assert '"via": "cookie"' in respostas and '"via": "bearer"' in respostas, respostas
    assert '"inst": "unib"' in claims and "securetoken.google.com" in claims, claims
    assert pagina.input_value("#senha") == ""  # a senha some do formulário
    pagina.click("#sair")
    pagina.wait_for_selector("#resultado", state="hidden")
    assert not erros, erros
    contexto.close()


def ldap_senha_errada(navegador):
    contexto, pagina, erros = nova_pagina(navegador)
    pagina.select_option("#inst", "unib")
    pagina.fill("#usuario", "ana")
    pagina.fill("#senha", "senha-errada")
    pagina.click("#ldap button")
    pagina.wait_for_selector("#erro:not([hidden])", timeout=30000)
    assert "inválidos" in pagina.inner_text("#erro")
    assert pagina.is_hidden("#resultado")
    contexto.close()


def cafe(navegador):
    contexto, pagina, erros = nova_pagina(navegador)
    pagina.select_option("#inst", "unia")
    with pagina.expect_popup() as info:
        pagina.click("#cafe")
    popup = info.value
    popup.wait_for_selector("form button")  # a "CAFe simulada"
    popup.click("form button")
    resumo, respostas, claims = esperar_resultado(pagina)
    assert "Entrou em unia" in resumo, resumo
    assert "ana@unia.test" in respostas
    assert not erros, erros
    contexto.close()


CASOS = [
    ("LDAP: entra, mostra cookie e Bearer, sai", ldap),
    ("LDAP: senha errada mostra o erro e não entra", ldap_senha_errada),
    ("CAFe: popup, aviso entre janelas e troca do código", cafe),
]

if __name__ == "__main__":
    falhas = 0
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        print(f"Chromium {navegador.version}")
        for nome, caso in CASOS:
            do_zero()
            try:
                caso(navegador)
                print(f"PASSOU  {nome}")
            except Exception as e:  # noqa: BLE001
                falhas += 1
                print(f"FALHOU  {nome}\n        {type(e).__name__}: {str(e)[:400]}")
        do_zero()
        navegador.close()
    print(f"{len(CASOS) - falhas} de {len(CASOS)} passaram")
    sys.exit(1 if falhas else 0)
