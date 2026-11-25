"""As contas da projeção batem com a tabela de preços."""
import importlib.util
from pathlib import Path

raiz = Path(__file__).resolve().parent.parent.parent
spec = importlib.util.spec_from_file_location("projecao", raiz / "projecao.py")
proj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proj)


def test_ate_cinquenta_mil_usuarios_nao_ha_custo():
    assert proj.custo_t1(50_000) == 0
    assert proj.custo_t1(300 * 100) == 0


def test_acima_da_cota_cobra_por_degraus():
    assert round(proj.custo_t1(60_000), 2) == 55.00            # 10 mil x 0,0055
    assert round(proj.custo_t1(300_000), 2) == 1195.00         # 50 mil x 0,0055 + 200 mil x 0,0046


def test_saml_nativo_reproduz_a_premissa_antiga_de_2_25_por_instituicao():
    # 300 usuários, metade federada: 150 x 0,015 = 2,25. A cota de 50 é do projeto, não da instituição.
    assert round(proj.custo_saml(150 * 100) / 100, 2) == 2.24
