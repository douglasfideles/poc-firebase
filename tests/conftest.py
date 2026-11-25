import os
import sys
from pathlib import Path

import pytest

# Permite rodar os unitários fora do container: python -m pytest tests/unit
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
os.environ.setdefault("INSTITUICOES_ARQUIVO",
                      str(Path(__file__).resolve().parent.parent / "instituicoes.yaml"))


@pytest.fixture
def insts():
    from poc.config import carregar_instituicoes
    return carregar_instituicoes(os.environ["INSTITUICOES_ARQUIVO"])
