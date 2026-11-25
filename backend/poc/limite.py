"""Limite de tentativas de senha, com atraso crescente.

Não é bloqueio rígido: travar a conta depois de N erros deixaria qualquer um impedir o login de
outra pessoa. As primeiras tentativas são livres; depois, cada erro dobra a espera, até um teto.

Fica em memória, o que serve para um processo. Com mais de uma cópia da API, o contador vai para
o cache compartilhado (é o tipo de dado que pode se perder sem mudar nenhum resultado).
"""
from __future__ import annotations

import threading
import time
from typing import Callable


class Limitador:
    def __init__(
        self,
        livres: int = 3,
        base_s: float = 2.0,
        teto_s: float = 300.0,
        esquecer_s: float = 3600.0,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._livres = livres
        self._base = base_s
        self._teto = teto_s
        self._esquecer = esquecer_s
        self._relogio = relogio
        self._trava = threading.Lock()
        self._falhas: dict[str, tuple[int, float, float]] = {}  # chave -> (n, liberado_em, ultima)

    def espera(self, chave: str) -> float:
        """Segundos que faltam até poder tentar de novo. Zero se pode tentar agora."""
        with self._trava:
            reg = self._falhas.get(chave)
            if reg is None:
                return 0.0
            n, liberado_em, ultima = reg
            agora = self._relogio()
            if agora - ultima > self._esquecer:
                del self._falhas[chave]
                return 0.0
            return max(0.0, liberado_em - agora)

    def falha(self, chave: str) -> None:
        with self._trava:
            agora = self._relogio()
            n = self._falhas.get(chave, (0, 0.0, 0.0))[0] + 1
            atraso = 0.0
            if n > self._livres:
                atraso = min(self._teto, self._base * 2 ** (n - self._livres - 1))
            self._falhas[chave] = (n, agora + atraso, agora)

    def sucesso(self, chave: str) -> None:
        with self._trava:
            self._falhas.pop(chave, None)

    def limpar(self) -> None:
        with self._trava:
            self._falhas.clear()
