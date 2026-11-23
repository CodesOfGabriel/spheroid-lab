"""Descritores morfométricos 2D em pixels, calculados sobre máscaras binárias."""

from __future__ import annotations

from typing import TypedDict

import numpy as np
from skimage import measure

from .segmentacao import Resultado

# descritores de forma, medidos sobre o contorno final
COLUNAS = (
    "area_px", "perimetro_px", "diam_equiv_px", "feret_max_px", "eixo_menor_px",
    "circularidade", "aspect_ratio", "roundness", "solidity",
)

# colunas auxiliares: não são descritores de forma, são qualificadores do
# resultado — ver docstrings abaixo
COLUNAS_AUX = (
    "circularidade_sem_suavizar",
)

# nomes que já foram usados e podem aparecer em registros antigos
RENOMEADAS = {"feret_min_px": "eixo_menor_px"}


class Descritores(TypedDict, total=False):
    area_px: float
    perimetro_px: float
    diam_equiv_px: float
    feret_max_px: float
    eixo_menor_px: float
    circularidade: float
    aspect_ratio: float
    roundness: float
    solidity: float
    circularidade_sem_suavizar: float
    n_objetos: int
    toca_borda: int


def _circularidade(mascara: np.ndarray) -> float | None:
    if mascara is None or not mascara.any():
        return None
    p = measure.regionprops(mascara.astype(int))[0]
    return float(4 * np.pi * p.area / p.perimeter ** 2)


def descrever(res: Resultado | np.ndarray, n_objetos: int | None = None) -> Descritores | None:
    """Mede o contorno final.

    Aceita um `Resultado` da segmentação (preferido, traz os qualificadores) ou
    uma máscara solta com `n_objetos` — este segundo caminho existe só para uso
    pontual e deixa as colunas auxiliares vazias.
    """
    if isinstance(res, Resultado):
        mascara, n_obj = res.final, res.n_objetos
    else:
        mascara, n_obj, res = res, (n_objetos or 0), None

    if mascara is None or not mascara.any():
        return None

    p = measure.regionprops(mascara.astype(int))[0]
    eixo_maior = float(p.axis_major_length)
    eixo_menor = float(p.axis_minor_length)

    # etapa 11: contato com a borda do campo. Objetos que tocam a borda NÃO são
    # descartados — em algumas imagens há células na borda e a exclusão
    # automática jogaria fora o esferoide inteiro. Só ficam marcados.
    minr, minc, maxr, maxc = p.bbox
    toca = int(minr <= 0 or minc <= 0
               or maxr >= mascara.shape[0] or maxc >= mascara.shape[1])

    d: Descritores = {
        "area_px": float(p.area),
        "perimetro_px": float(p.perimeter),
        "diam_equiv_px": float(2 * np.sqrt(p.area / np.pi)),
        "feret_max_px": float(p.feret_diameter_max),
        # NÃO é o MinFeret do ImageJ (menor largura de calibre girando o
        # objeto). É o eixo menor da elipse de momentos de 2ª ordem, como na
        # implementação de referência que gerou a tabela do protocolo. O nome
        # diz isso para ninguém confundir ao comparar com valores de ImageJ.
        "eixo_menor_px": eixo_menor,
        "circularidade": float(4 * np.pi * p.area / p.perimeter ** 2),
        "aspect_ratio": float(eixo_maior / max(eixo_menor, 1.0)),
        "roundness": float(4 * p.area / (np.pi * eixo_maior ** 2)),
        "solidity": float(p.solidity),
        "n_objetos": int(n_obj),
        "toca_borda": toca,
    }

    # --- qualificadores -------------------------------------------------
    if res is not None:
        # Análise de sensibilidade da etapa 9: a suavização σ=6 é uma escala
        # espacial fixa em px e não é neutra ao tamanho do objeto. Guardar as
        # duas versões permite verificar se a conclusão se mantém sem ela.
        d["circularidade_sem_suavizar"] = _circularidade(res.principal)

    return d


def normalizar_nomes(medidas: dict) -> dict:
    """Traduz nomes de colunas antigos em registros já gravados."""
    return {RENOMEADAS.get(k, k): v for k, v in (medidas or {}).items()}
