"""Segmentação dos agregados — etapas 2 a 9 do protocolo.

O ponto que faz este módulo existir: **a aparência do esferoide inverte ao longo
da série.** No D0 o agregado está frouxo e aparece mais CLARO que o fundo, porque
as células soltas espalham luz. Do D1 em diante está compactado e aparece mais
ESCURO, quase preto, porque a massa densa absorve luz.

Qualquer limiar que procure só o escuro, ou só o claro, funciona num extremo da
série e falha no outro. A saída é o critério simétrico `|flat − 1|`: mede o
quanto cada pixel se afasta do fundo, para cima ou para baixo, e portanto pega os
dois casos com a mesma regra.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi
from skimage import filters, measure, morphology

from .config import SEG

# `min_size` está depreciado no scikit-image 0.26, mas o substituto (`max_size`)
# remove objetos com área <= N em vez de < N. Mantemos `min_size` para reproduzir
# a implementação de referência do protocolo bit a bit.
warnings.filterwarnings("ignore", message=".*min_size.*")


def carregar(caminho: str | Path) -> np.ndarray:
    """Cinza de canal único, em ponto flutuante (etapa 1)."""
    return np.asarray(Image.open(caminho).convert("L")).astype(float)


def mapa_desvio(cinza: np.ndarray, sigma_fundo: float | None = None) -> np.ndarray:
    """Etapas 2–4: flat-field, critério simétrico e suavização.

    O poço de fundo em U produz vinhetamento radial forte e anéis concêntricos de
    moldagem do plástico. Dividir pela cópia muito borrada remove esse gradiente
    lento e preserva a textura do agregado.

    `sigma_fundo` é a escala desse borrão. O padrão do protocolo é 60 e é o que
    o pipeline de medição usa sempre; quem passa outro valor é só o revisor, e
    outros valores podem alterar o contorno.
    """
    fundo = filters.gaussian(cinza, sigma=sigma_fundo or SEG.sigma_flat)
    flat = cinza / (fundo + 1e-6)
    return filters.gaussian(np.abs(flat - 1.0), sigma=SEG.sigma_desvio)


def binarizar(desvio: np.ndarray, limiar: float | None = None) -> np.ndarray:
    """Etapas 5–6: Otsu e limpeza, nesta ordem.

    `limiar` troca o corte de Otsu por um valor explícito. Quem passa isso é só o
    revisor, em `analisar_limiar`; o caminho de medição nunca passa.
    """
    m = desvio > (filters.threshold_otsu(desvio) if limiar is None else limiar)
    m = ndi.binary_fill_holes(m)
    m = morphology.remove_small_objects(m, min_size=SEG.area_min)
    m = morphology.opening(m, morphology.disk(SEG.raio_abertura))
    return ndi.binary_fill_holes(m)


def maior_componente(mascara: np.ndarray) -> tuple[np.ndarray | None, int]:
    """Etapas 7–8: conta objetos e fica só com o maior corpo contíguo.

    Fragmentos satélites e células dispersas não entram na medida — e não é
    conservadorismo, é geometria: a solidity divide a área pelo fecho convexo, e
    o fecho convexo de um corpo mais um satélite distante engloba todo o vazio
    entre os dois. Um satélite com 4% da área derruba a solidity em ~40%. A
    circularidade sofre pelo mesmo motivo, com o perímetro somando dois contornos
    enquanto a área quase não muda — e o perímetro entra ao quadrado.

    A presença de mais de um objeto é registrada em `n_objetos`, com o filtro
    de área do protocolo. Não existe contagem de satélites com filtro próprio:
    ela foi retirada por medir desacordo de contorno, não biologia — ver
    docs/decisoes.md.

    O critério operacional não é "o que parece contíguo": a abertura morfológica
    com disco de raio 8 secciona qualquer ponte mais estreita que ~16 px, então a
    regra é "corpo principal mais tudo ligado a ele por uma ponte de pelo menos
    16 px de largura".
    """
    rotulos = measure.label(mascara)
    props = sorted(measure.regionprops(rotulos), key=lambda p: -p.area)
    if not props:
        return None, 0
    return (rotulos == props[0].label), len(props)


def suavizar_contorno(mascara: np.ndarray) -> np.ndarray:
    """Etapa 9.

    O serrilhado de pixel infla o perímetro e, como ele entra ao quadrado na
    fórmula da circularidade, a subestima sistematicamente.

    Atenção ao usar o resultado: esta etapa NÃO é neutra em relação ao tamanho do
    objeto quando o comprimento de onda da rugosidade acompanha o objeto. Como
    os objetos encolhem ao longo da série, o viés anda na mesma direção do efeito
    biológico esperado. Por isso `circularidade_sem_suavizar` é gravada em
    paralelo, como análise de sensibilidade.

    A magnitude do viés ainda não está estabelecida: medi-la sobre os contornos
    automáticos não vale, porque parte deles está errada. Só dá para fechar
    depois da conferência. Ver docs/decisoes.md.
    """
    m = filters.gaussian(mascara.astype(float), sigma=SEG.sigma_contorno) > 0.5
    return ndi.binary_fill_holes(m)


@dataclass
class Resultado:
    """Tudo que uma imagem produz, para as medidas não recalcularem nada."""
    final: np.ndarray | None          # contorno medido (suavizado)
    principal: np.ndarray | None      # maior componente, ANTES da suavização
    n_objetos: int                    # com o filtro do protocolo


def analisar(cinza: np.ndarray) -> Resultado:
    """Pipeline completo sobre a imagem já carregada."""
    desvio = mapa_desvio(cinza)
    principal, n_obj = maior_componente(binarizar(desvio))
    if principal is None:
        return Resultado(None, None, 0)
    final = suavizar_contorno(principal)
    return Resultado(final if final.any() else None, principal, n_obj)


def segmentar_array(cinza: np.ndarray) -> tuple[np.ndarray | None, int]:
    """Compatível com o uso antigo: só a máscara final e a contagem."""
    r = analisar(cinza)
    return r.final, r.n_objetos


def segmentar(caminho: str | Path) -> tuple[np.ndarray | None, int]:
    return segmentar_array(carregar(caminho))


def pos_processar(mascara: np.ndarray) -> Resultado:
    """Aplica as etapas 7–9 a uma máscara já pronta (ex.: desenhada à mão).

    É o que mantém as correções manuais comparáveis às automáticas: mesma regra
    do maior corpo contíguo e mesma suavização de contorno.
    """
    m = ndi.binary_fill_holes(mascara.astype(bool))
    principal, n_obj = maior_componente(m)
    if principal is None:
        vazio = np.zeros_like(m, dtype=bool)
        return Resultado(vazio, vazio, 0)
    return Resultado(suavizar_contorno(principal), principal, n_obj)


DESLOCAMENTO_MAX = 60          # trava do controle de limiar do revisor

# Escalas de fundo que o revisor pode escolher. Lista FECHADA, e não um
# intervalo contínuo, por dois motivos: o cache de mapas em disco fica limitado
# a seis arquivos por imagem, e um valor escolhido de uma lista curta é muito
# mais fácil de auditar depois do que um número qualquer. 60 é o do protocolo.
SIGMAS_FUNDO = (30, 45, 60, 90, 120, 180)


def sigma_fundo_valido(valor) -> float:
    """Devolve o valor da lista mais próximo — nunca um sigma arbitrário."""
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return float(SEG.sigma_flat)
    return float(min(SIGMAS_FUNDO, key=lambda s: abs(s - v)))


def analisar_limiar(desvio8: np.ndarray, otsu: int,
                    deslocamento: int) -> tuple[Resultado, int]:
    """Etapas 5–9 sobre o mapa de 8 bits, com o corte de Otsu **deslocado**.

    Existe para uma coisa só: o controle de limiar do revisor. Não é um caminho
    de medição alternativo — é o mesmo critério `|flat − 1|` do protocolo, com o
    corte movido, para a pessoa ver na hora onde o contorno cairia e decidir.

    Por que na escala de 8 bits e não no mapa em ponto flutuante: é a escala que
    o navegador recebe em `/api/desvio`, então o número que aparece no controle
    significa a mesma coisa dos dois lados. O preço é a quantização — com
    `deslocamento=0` o resultado fica muito perto do automático, mas **não é
    idêntico a ele**, e por isso a máscara automática de disco nunca é
    sobrescrita por esta função.

    O deslocamento é travado em ±`DESLOCAMENTO_MAX`: fora dessa faixa o corte
    deixa de ser "o Otsu daquela imagem, um pouco para lá" e vira um limiar
    arbitrário.

    Devolve o `Resultado` sem estatística de satélite — quem tem o mapa em ponto
    flutuante em cache é o chamador, que completa (ver `Contexto.com_limiar`).
    A escala do fundo já está embutida no `desvio8` que chega aqui.
    """
    d = int(np.clip(deslocamento, -DESLOCAMENTO_MAX, DESLOCAMENTO_MAX))
    limiar = int(np.clip(otsu + d, 1, 254))
    principal, n_obj = maior_componente(
        binarizar(desvio8.astype(float), limiar=limiar))
    if principal is None:
        return Resultado(None, None, 0), limiar
    final = suavizar_contorno(principal)
    return Resultado(final if final.any() else None, principal, n_obj), limiar


def desvio_8bits(cinza: np.ndarray,
                 sigma_fundo: float | None = None) -> tuple[np.ndarray, int]:
    """Mapa de desvio em 8 bits + o limiar global de Otsu nessa escala.

    É o insumo do pincel mágico do revisor e da vista do mapa. Normaliza pelo
    percentil 99,5 para que faíscas isoladas não achatem o resto da escala.
    """
    d = mapa_desvio(cinza, sigma_fundo)
    alto = np.percentile(d, 99.5)
    d8 = (np.clip(d / max(alto, 1e-9), 0, 1) * 255).astype(np.uint8)
    return d8, int(filters.threshold_otsu(d8))
