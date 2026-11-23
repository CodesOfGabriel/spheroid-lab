"""Leitura dos nomes de arquivo e sanidade dos descritores."""

from pathlib import Path

import numpy as np
import pytest

from esferoides import medidas
from esferoides.inventario import interpretar


@pytest.mark.parametrize("nome,dia,grupo,replica", [
    ("D0 HC1", 0, "HC", 1),
    ("D3 LT8", 3, "LT", 8),
    ("D2 LC12", 2, "LC", 12),
    ("D0 LC1_T", 0, "LC", 1),      # sufixo solto no nome real de n2
    ("D0 C1", 0, "C", 1),          # fora do padrão de grupo, mas legível
])
def test_interpreta_os_nomes_reais(nome, dia, grupo, replica):
    img = interpretar(Path(f"{nome}.png"), "n1")
    assert (img.dia, img.grupo, img.replica) == (dia, grupo, replica)
    assert not img.fora_do_padrao


def test_nome_ilegivel_e_marcado_em_vez_de_estourar():
    img = interpretar(Path("foto sem padrao.png"), "n1")
    assert img.fora_do_padrao


def test_esferoide_uid_distingue_experimentos():
    """HC2 se repete em n1, n2 e n3 — só o par experimento+id identifica."""
    a = interpretar(Path("D0 HC2.png"), "n1")
    b = interpretar(Path("D0 HC2.png"), "n2")
    assert a.esferoide_id == b.esferoide_id == "HC2"
    assert a.esferoide_uid != b.esferoide_uid


def test_chave_da_imagem_e_estavel_e_sem_espaco():
    img = interpretar(Path("D0 HC1.png"), "n1")
    assert img.chave == "n1_D0_HC1"


# ------------------------------------------------------------------- medidas
def disco(raio=80, tamanho=300):
    y, x = np.ogrid[:tamanho, :tamanho]
    return (y - tamanho // 2) ** 2 + (x - tamanho // 2) ** 2 <= raio ** 2


def test_descritores_de_um_disco_perfeito():
    d = medidas.descrever(disco(), n_objetos=1)
    assert d["area_px"] == pytest.approx(np.pi * 80 ** 2, rel=0.01)
    assert d["diam_equiv_px"] == pytest.approx(160, rel=0.01)
    assert d["circularidade"] == pytest.approx(1.0, abs=0.12)  # perímetro poligonal
    assert d["solidity"] > 0.97
    assert d["aspect_ratio"] == pytest.approx(1.0, abs=0.02)
    assert d["toca_borda"] == 0


def test_marca_contato_com_a_borda_sem_descartar():
    m = np.zeros((300, 300), bool)
    m[0:100, 0:100] = True                      # encostado no canto
    d = medidas.descrever(m, n_objetos=1)
    assert d["toca_borda"] == 1
    assert d["area_px"] > 0, "objeto na borda não pode ser descartado, só marcado"


def test_mascara_vazia_devolve_none():
    assert medidas.descrever(np.zeros((50, 50), bool), n_objetos=0) is None
    assert medidas.descrever(None, n_objetos=0) is None


def test_nenhum_descritor_de_intensidade():
    """Os descritores publicados são geométricos."""
    proibidos = ("mean", "intensity", "densidade", "cinza", "gray", "od")
    for coluna in (*medidas.COLUNAS, *medidas.COLUNAS_AUX):
        assert not any(p in coluna.lower() for p in proibidos), coluna


def test_nome_da_coluna_nao_promete_minferet_do_imagej():
    """É o eixo menor da elipse, não a menor largura de calibre."""
    assert "eixo_menor_px" in medidas.COLUNAS
    assert "feret_min_px" not in medidas.COLUNAS


def test_traduz_nome_antigo_em_registro_ja_gravado():
    antigo = {"area_px": 10.0, "feret_min_px": 3.0}
    assert medidas.normalizar_nomes(antigo) == {"area_px": 10.0, "eixo_menor_px": 3.0}


# ------------------------------------------------- maior corpo contíguo
def _campo_com_satelite(area_satelite_frac=0.20):
    """Corpo principal + um satélite separado, ambos escuros.

    A fração padrão é grande de propósito: o satélite precisa sobreviver ao
    `area_min` de 15 000 px do protocolo, senão o teste passa por acidente —
    a limpeza removeria o objeto antes de `maior_componente` ter o que decidir.
    """
    h, w = 1038, 1368
    y, x = np.ogrid[:h, :w]
    img = np.full((h, w), 128.0)
    img[(y - h // 2) ** 2 + (x - w // 2) ** 2 <= 200 ** 2] = 40
    r = int(200 * np.sqrt(area_satelite_frac))
    img[(y - 180) ** 2 + (x - 260) ** 2 <= r ** 2] = 40
    return img


def test_satelite_nao_entra_no_contorno_medido():
    """A regra do protocolo, que é também a prática da literatura de morfometria
    de esferoides: fragmentos soltos ficam FORA da medida de forma. Um satélite
    com 4% da área derruba a solidity em ~40%, porque o fecho convexo engole o
    vazio entre os dois corpos.

    Não existe mais contagem de satélites — ela media desacordo de contorno, não
    biologia (docs/decisoes.md). O que sobrou, e que este teste guarda, é a
    exclusão.
    """
    from esferoides import segmentacao
    res = segmentacao.analisar(_campo_com_satelite())
    assert res.n_objetos == 2, "o satélite não sobreviveu ao filtro do protocolo"
    assert not res.final[180, 260], "o satélite entrou no contorno medido"
    assert res.final[1038 // 2, 1368 // 2], "o corpo principal saiu do contorno"


def test_o_halo_do_flat_field_nao_vira_um_segundo_objeto():
    """Um disco sozinho tem que dar n_objetos == 1.

    O flat-field deixa um anel claro em volta de um corpo escuro, e ele aparece
    no mapa `|flat - 1|`. Se o `area_min` do protocolo deixasse esse anel passar
    como objeto próprio, toda imagem teria um objeto fantasma — foi exatamente
    esse anel que inflou a contagem de satélites que acabou retirada.
    """
    from esferoides import segmentacao
    h, w = 1038, 1368
    y, x = np.ogrid[:h, :w]
    img = np.full((h, w), 128.0)
    img[(y - h // 2) ** 2 + (x - w // 2) ** 2 <= 200 ** 2] = 40
    assert segmentacao.analisar(img).n_objetos == 1


def test_etapa9_aumenta_a_circularidade_de_um_contorno_serrilhado():
    """A etapa 9 age sobre o serrilhado de PIXEL da máscara binária.

    Ela é aplicada à máscara, não à imagem — testar por uma imagem ondulada não
    funciona, porque o σ=3 do mapa de desvio já alisa a ondulação antes da
    binarização e a etapa 9 fica sem nada para remover.
    """
    from skimage import measure

    from esferoides import segmentacao

    def circ(m):
        p = measure.regionprops(m.astype(int))[0]
        return 4 * np.pi * p.area / p.perimeter ** 2

    m = disco(raio=200, tamanho=600)
    rng = np.random.default_rng(3)
    from scipy import ndimage as ndi
    casca = m ^ ndi.binary_erosion(m, iterations=3)
    rugosa = m.copy()
    rugosa[casca] = rng.random(casca.sum()) > 0.45

    antes, depois = circ(rugosa), circ(segmentacao.suavizar_contorno(rugosa))
    assert depois > antes + 0.3, f"etapa 9 quase não agiu: {antes:.3f} -> {depois:.3f}"
    # e sem inventar área: o ganho vem do perímetro, não do tamanho
    variacao = abs(segmentacao.suavizar_contorno(rugosa).sum() - rugosa.sum()) / rugosa.sum()
    assert variacao < 0.02


def test_as_duas_circularidades_sao_gravadas():
    from esferoides import segmentacao
    h, w = 1038, 1368
    y, x = np.ogrid[:h, :w]
    img = np.full((h, w), 128.0)
    img[(y - h // 2) ** 2 + (x - w // 2) ** 2 <= 200 ** 2] = 40
    d = medidas.descrever(segmentacao.analisar(img))
    assert d["circularidade_sem_suavizar"] is not None
    assert d["circularidade"] is not None
