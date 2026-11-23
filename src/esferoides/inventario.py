"""Leitura dos nomes de arquivo e montagem do inventário de imagens.

Os arquivos reais seguem `D{dia} {GRUPO}{replica}.png` (com espaço), dentro de
`n1/d0/`, `n2/d1/`, … Alguns fogem do padrão e são tratados aqui em vez de
espalhar exceções pelo resto do código.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import Caminhos

# "D0 HC1" | "D0 LC1_T" | "D0 C1"
_RE = re.compile(r"^D(?P<dia>\d+)[ _]+(?P<grupo>[A-Za-z]+)(?P<replica>\d+)(?P<sufixo>.*)$")
PASTA_EXPERIMENTO = re.compile(r"n[1-9][0-9]*")
PASTA_DIA = re.compile(r"d(?:0|[1-9][0-9]*)")


@dataclass(frozen=True)
class Imagem:
    caminho: Path
    n_experimento: str          # n1 | n2 | n3
    arquivo: str                # "D0 HC1"  (sem extensão)
    dia: int
    grupo: str                  # LC | LT | HC | HT  (ou outro, se fora do padrão)
    replica: int
    sufixo: str = ""

    @property
    def esferoide_id(self) -> str:
        """Identificador dentro do experimento, como no protocolo."""
        return f"{self.grupo}{self.replica}"

    @property
    def esferoide_uid(self) -> str:
        """Identificador único de verdade.

        `HC2` se repete em n1, n2 e n3, então só o par experimento+esferoide
        identifica um esferoide. É esta a chave que normaliza a area_norm_D0.
        """
        return f"{self.n_experimento}_{self.esferoide_id}"

    @property
    def chave(self) -> str:
        """Chave estável de uma IMAGEM (não do esferoide). Usada no banco."""
        return f"{self.n_experimento}_{self.arquivo.replace(' ', '_')}"

    @property
    def rotulo(self) -> str:
        return f"{self.n_experimento} · {self.arquivo}"

    @property
    def fora_do_padrao(self) -> bool:
        return self.dia < 0 or self.replica < 0


def interpretar(caminho: Path, n_experimento: str) -> Imagem:
    base = caminho.stem
    m = _RE.match(base)
    if not m:
        return Imagem(caminho, n_experimento, base, -1, "??", -1)
    return Imagem(
        caminho=caminho,
        n_experimento=n_experimento,
        arquivo=base,
        dia=int(m.group("dia")),
        grupo=m.group("grupo").upper(),
        replica=int(m.group("replica")),
        sufixo=m.group("sufixo"),
    )


def listar(cam: Caminhos) -> list[Imagem]:
    """Todas as imagens, em ordem determinística (experimento, dia, nome)."""
    imagens: list[Imagem] = []
    if not cam.raiz.is_dir():
        return imagens
    experimentos = [p for p in cam.raiz.iterdir() if p.is_dir()
                    and PASTA_EXPERIMENTO.fullmatch(p.name)]
    for experimento in sorted(experimentos, key=lambda p: int(p.name[1:])):
        dias = [p for p in experimento.iterdir() if p.is_dir() and PASTA_DIA.fullmatch(p.name)]
        for pasta in sorted(dias, key=lambda p: int(p.name[1:])):
            for f in sorted(pasta.glob("*.png")):
                imagens.append(interpretar(f, experimento.name))
    return imagens
