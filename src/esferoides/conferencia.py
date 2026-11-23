"""Imagens de conferência e folhas de contato.

A inspeção visual humana não é automatizável e não deve ser pulada: são estas
imagens que permitem decidir onde o contorno automático errou.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from skimage import morphology, segmentation

_CACHE_FONTE: dict[int, ImageFont.ImageFont] = {}


def fonte(tamanho: int):
    if tamanho not in _CACHE_FONTE:
        for nome in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
            try:
                _CACHE_FONTE[tamanho] = ImageFont.truetype(nome, tamanho)
                break
            except OSError:
                continue
        else:
            _CACHE_FONTE[tamanho] = ImageFont.load_default()
    return _CACHE_FONTE[tamanho]


def imagem_conferencia(origem: Path, mascara: np.ndarray | None, destino: Path,
                       rotulo: str, legenda: str) -> None:
    """Contorno amarelo sobre a foto original, em resolução integral."""
    g = np.asarray(Image.open(origem).convert("L"))
    rgb = np.dstack([g, g, g]).copy()
    if mascara is not None:
        borda = segmentation.find_boundaries(mascara, mode="outer")
        borda = morphology.dilation(borda, morphology.disk(2))
        rgb[borda] = (255, 255, 0)
    im = Image.fromarray(rgb)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, im.width, 84], fill=(0, 0, 0))
    d.text((12, 6), rotulo, fill=(255, 255, 0), font=fonte(34))
    d.text((12, 48), legenda, fill=(255, 255, 255), font=fonte(26))
    destino.parent.mkdir(parents=True, exist_ok=True)
    im.save(destino)


def folha_contato(arquivos: list[Path], destino: Path, titulo: str,
                  colunas: int = 6, largura: int = 380) -> None:
    """Prancha de miniaturas, para triagem visual rápida de um dia inteiro."""
    arquivos = [a for a in arquivos if a.exists()]
    if not arquivos:
        return
    with Image.open(arquivos[0]) as primeira:
        proporcao = primeira.height / primeira.width
    altura = int(largura * proporcao)
    linhas = (len(arquivos) + colunas - 1) // colunas
    folha = Image.new("RGB", (colunas * largura, linhas * altura + 46), (18, 18, 18))
    ImageDraw.Draw(folha).text((10, 12), titulo, fill=(255, 255, 0), font=fonte(28))
    for i, a in enumerate(arquivos):
        with Image.open(a) as im:
            folha.paste(im.resize((largura, altura), Image.BILINEAR),
                        ((i % colunas) * largura, 46 + (i // colunas) * altura))
    destino.parent.mkdir(parents=True, exist_ok=True)
    folha.save(destino)
