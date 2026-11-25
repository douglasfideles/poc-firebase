"""Projeção de uso e custo do Firebase Authentication para o IoTEdu.

Uso:
    python3 projecao.py                               # imprime as tabelas
    python3 projecao.py --relatorio ANALISE-FIREBASE.md   # preenche os blocos <!-- tabela:NOME -->

O Firebase não conta autenticações: conta usuários ativos (quem entrou pelo menos uma vez no
período). Entrar 1 ou 30 vezes no mês dá o mesmo número. Cada premissa abaixo diz de onde veio;
mudar uma premissa aqui refaz as tabelas.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

# ------------------------------------------------------------------ premissas
P = {
    "usuarios_inst": (300, "usuários ativos por mês, por instituição",
                      "premissa do projeto (v7, PROJECAO-POR-INSTITUICOES.md)"),
    "usuarios_inst_alto": (3000, "o mesmo, hipótese alta",
                           "hipótese desta análise: dez vezes a premissa do projeto"),
    "gratis_t1": (50_000, "usuários ativos por mês sem custo, faixa comum (com o upgrade, plano Blaze)",
                  "cloud.google.com/identity-platform/pricing"),
    "dau_spark": (3_000, "usuários ativos por dia, faixa comum (com o upgrade, sem cartão)",
                  "firebase.google.com/docs/auth"),
    "gratis_saml": (50, "usuários ativos por mês sem custo, SAML e OIDC (com o upgrade, plano Blaze)",
                    "cloud.google.com/identity-platform/pricing"),
    "usd_saml": (0.015, "US$ por usuário ativo por mês, SAML e OIDC, acima da cota",
                 "cloud.google.com/identity-platform/pricing"),
    "dias_uso": (22, "dias de uso por mês, por pessoa",
                 "hipótese desta análise: dias úteis; com o corte de 12 horas, é um login por dia de uso"),
    "frac_dia": (0.30, "parte dos usuários do mês que entra no dia mais cheio",
                 "hipótese desta análise"),
    "frac_hora": (0.20, "parte dos usuários do mês que entra na hora mais cheia",
                  "hipótese desta análise"),
    "lim_custom_min": (45_000, "logins com custom token por minuto, por projeto",
                       "firebase.google.com/docs/auth/limits"),
    "lim_troca_min": (18_000, "renovações de token por minuto, por projeto",
                      "firebase.google.com/docs/auth/limits"),
    "lim_contas_ip_h": (100, "contas novas por hora, por endereço IP",
                        "firebase.google.com/docs/auth/limits"),
}

# US$ por usuário ativo por mês na faixa comum (e-mail, Google, Microsoft, custom token), com o upgrade.
FAIXAS_T1 = [(50_000, 0.0), (100_000, 0.0055), (1_000_000, 0.0046), (10_000_000, 0.0032),
             (math.inf, 0.0025)]

# (rótulo, instituições, usuários ativos no mês). As duas primeiras linhas são o que existe hoje.
HOJE = [("UFRGS, hoje", 1, 8), ("Unipampa, hoje", 1, 13)]
CENARIOS = [6, 10, 50, 100, 1000]


def v(k):
    return P[k][0]


def custo_t1(mau: int) -> float:
    """Custo mensal na faixa comum, por degraus."""
    total, piso = 0.0, 0
    for teto, usd in FAIXAS_T1:
        if mau > piso:
            total += (min(mau, teto) - piso) * usd
        piso = teto
    return total


def custo_saml(mau_saml: int) -> float:
    """Custo mensal se o login da CAFe passasse pelo SAML nativo do Firebase."""
    return max(0, mau_saml - v("gratis_saml")) * v("usd_saml")


def pico_dia(mau: int) -> int:
    return math.ceil(mau * v("frac_dia"))


def pico_min(mau: int) -> float:
    return mau * v("frac_hora") / 60


# ------------------------------------------------------------------ saída
def br(x: float, casas: int = 0) -> str:
    s = f"{x:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def tabela(cab: list[str], linhas: list[list[str]], alinhar: str) -> str:
    sep = {"l": ":---", "r": "---:"}
    out = ["| " + " | ".join(cab) + " |", "|" + "|".join(sep[a] for a in alinhar) + "|"]
    out += ["| " + " | ".join(l) + " |" for l in linhas]
    return "\n".join(out)


def linhas_cenarios(por_inst: int):
    for rotulo, n, mau in HOJE:
        yield rotulo, n, mau
    for n in CENARIOS:
        yield f"{br(n)} instituições", n, n * por_inst


def tabelas() -> dict[str, str]:
    T = {}

    T["premissas"] = tabela(
        ["Premissa", "Valor", "De onde vem"],
        [[d, br(val, 3 if isinstance(val, float) and val < 1 and k.startswith("usd") else
              (2 if isinstance(val, float) else 0)), f] for k, (val, d, f) in P.items()],
        "lrl")

    for nome, por_inst in (("uso", v("usuarios_inst")), ("uso_alto", v("usuarios_inst_alto"))):
        linhas = []
        for rotulo, n, mau in linhas_cenarios(por_inst):
            linhas.append([
                rotulo, br(mau),
                "0,00",
                "cabe" if pico_dia(mau) <= v("dau_spark") else "não cabe",
                br(custo_t1(mau), 2),
                br(custo_saml(mau // 2), 2),
            ])
        T[nome] = tabela(
            ["Cenário", "Usuários ativos no mês",
             "Sem o upgrade, como na PoC (US$/mês)",
             "Com o upgrade, sem cartão (teto de 3.000 por dia)",
             "Com o upgrade, com cartão (US$/mês)",
             "A mais, se a CAFe fosse SAML nativo (US$/mês)"], linhas, "lrrrrr")

    limite_gratis = v("gratis_t1") // v("usuarios_inst")
    limite_dia = math.floor(v("dau_spark") / v("frac_dia") / v("usuarios_inst"))
    T["limiares"] = tabela(
        ["Limite", "Com 300 usuários por instituição", "Com 3.000 por instituição"],
        [["Cota mensal sem custo (50 mil usuários ativos, com cartão)",
          f"até {br(limite_gratis)} instituições",
          f"até {br(v('gratis_t1') // v('usuarios_inst_alto'))} instituições"],
         ["Teto diário sem cartão (3.000 usuários ativos por dia)",
          f"até {br(limite_dia)} instituições",
          f"até {br(math.floor(v('dau_spark') / v('frac_dia') / v('usuarios_inst_alto')))} instituições"]],
        "lrr")

    linhas = []
    for rotulo, n, mau in linhas_cenarios(v("usuarios_inst")):
        pm = pico_min(mau)
        linhas.append([rotulo, br(mau), br(mau * v("dias_uso")), br(pm, 1),
                       f"{br(100 * pm / v('lim_custom_min'), 3)}%",
                       f"{br(100 * (mau / 60) / v('lim_troca_min'), 3)}%"])
    T["pico"] = tabela(
        ["Cenário", "Usuários ativos no mês", "Logins no mês (teto)",
         "Logins por minuto na hora mais cheia", "Parte do limite de 45.000 por minuto",
         "Renovações por minuto com todos logados, sobre 18.000"], linhas, "lrrrrr")
    return T


def preencher(md: Path, T: dict[str, str]) -> None:
    s = md.read_text(encoding="utf-8")
    for nome, txt in T.items():
        s, k = re.subn(rf"(<!-- tabela:{nome} -->\n).*?(<!-- /tabela -->)",
                       lambda m: m.group(1) + txt + "\n" + m.group(2), s, flags=re.S)
        print(f"  {nome}: {'preenchida' if k else 'bloco não encontrado'}")
    md.write_text(s, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    T = tabelas()
    if "--relatorio" in sys.argv:
        preencher(Path(sys.argv[sys.argv.index("--relatorio") + 1]), T)
    else:
        for nome, txt in T.items():
            print(f"\n### {nome}\n\n{txt}")
