"""O critério simétrico tem que pegar os dois extremos da série.

Este é o teste que guarda a ideia central: no D0 o agregado é mais CLARO que o
fundo, do D1 em diante é mais ESCURO. Um limiar que procure só um dos dois
funciona num extremo e falha no outro.
"""

import numpy as np
import pytest

from esferoides import segmentacao


# O tamanho tem que ser o real: sigma_flat=60 é calibrado para 1368×1038. Num
# campo pequeno esse sigma fica proporcionalmente enorme, o flat-field não
# achata a vinheta e sobra no fundo um desvio da mesma ordem do objeto.
TAMANHO = (1038, 1368)
RAIO = 200


def campo(valor_objeto: int, raio: int = RAIO, tamanho=TAMANHO,
          vinheta: bool = True, textura: float = 0.0) -> np.ndarray:
    """Fundo cinza (com vinhetamento radial, como no poço fundo-U) + um disco."""
    h, w = tamanho
    y, x = np.ogrid[:h, :w]
    img = np.full((h, w), 128.0)
    if vinheta:
        rr = np.hypot(y - h / 2, x - w / 2) / np.hypot(h / 2, w / 2)
        img *= 1.0 - 0.45 * rr ** 2          # canto ~45% mais escuro
    disco = (y - h / 2) ** 2 + (x - w / 2) ** 2 <= raio ** 2
    img[disco] = valor_objeto * (img[disco] / 128.0)
    if textura:
        rng = np.random.default_rng(0)
        img[disco] += rng.normal(0, textura, disco.sum())
    return np.clip(img, 0, 255)


@pytest.mark.parametrize("rotulo,valor", [
    ("agregado claro do D0", 205),
    ("esferoide escuro do D1-D3", 40),
])
def test_detecta_os_dois_sentidos_de_contraste(rotulo, valor):
    """O que este fantasma testemunha: o objeto é achado nos dois sentidos.

    Ele NÃO serve para aferir área absoluta. Um disco sintético tem borda em
    degrau perfeito, e a zona de transição do flat-field (σ=60) infla o raio
    em ~20% de forma reprodutível — medido: razão 1,34 a 1,65 com e sem
    textura. Imagem real tem borda gradual (halo de fase, desfoque) e não se
    comporta assim. A exatidão da medida é garantida por test_referencia.py,
    contra a tabela de valores reais.
    """
    verdade = disco_verdadeiro()
    m, n_obj = segmentacao.segmentar_array(campo(valor))
    assert m is not None, f"não detectou o {rotulo}"
    assert n_obj >= 1

    cobertura = (m & verdade).sum() / verdade.sum()
    assert cobertura > 0.98, f"{rotulo}: cobriu só {100*cobertura:.0f}% do objeto"
    assert m.sum() < 2 * verdade.sum(), f"{rotulo}: máscara absurdamente grande"

    cy, cx = np.argwhere(m).mean(axis=0)
    assert abs(cy - TAMANHO[0] / 2) < 20 and abs(cx - TAMANHO[1] / 2) < 20, (
        f"{rotulo}: máscara descentrada em relação ao objeto")


def disco_verdadeiro(raio: int = RAIO, tamanho=TAMANHO) -> np.ndarray:
    h, w = tamanho
    y, x = np.ogrid[:h, :w]
    return (y - h / 2) ** 2 + (x - w / 2) ** 2 <= raio ** 2


def test_flat_field_remove_o_vinhetamento():
    """Sem a correção o gradiente do poço dominaria o limiar."""
    com = segmentacao.mapa_desvio(campo(40, vinheta=True))
    sem = segmentacao.mapa_desvio(campo(40, vinheta=False))
    # fora do objeto o desvio tem que ficar próximo de zero nos dois casos
    borda = np.s_[:40, :40]
    assert com[borda].mean() < 0.05
    assert sem[borda].mean() < 0.05


def test_fica_so_com_o_maior_corpo_contiguo():
    img = campo(40)
    # fragmento satélite, acima do filtro de área (raio 90 -> ~25 000 px)
    h, w = TAMANHO
    y, x = np.ogrid[:h, :w]
    sy, sx = 170, 220
    img[(y - sy) ** 2 + (x - sx) ** 2 <= 90 ** 2] *= 40 / 128
    m, n_obj = segmentacao.segmentar_array(img)
    assert n_obj == 2, "o satélite deveria ser contado em n_objetos"
    # ...mas o contorno medido é só o maior corpo contíguo
    assert not m[sy, sx], "o satélite entrou na medida"
    assert m[h // 2, w // 2], "o objeto principal saiu da medida"


def test_suavizacao_do_contorno_nao_muda_a_area_de_forma_relevante():
    img = campo(40)
    bruta, _ = segmentacao.maior_componente(
        segmentacao.binarizar(segmentacao.mapa_desvio(img)))
    suave = segmentacao.suavizar_contorno(bruta)
    variacao = abs(suave.sum() - bruta.sum()) / bruta.sum()
    assert variacao < 0.03, f"suavização mudou a área em {100*variacao:.1f}%"


def test_pos_processar_e_idempotente():
    """Aprovar uma máscara sem editar não pode alterar a medida."""
    m, _ = segmentacao.segmentar_array(campo(40))
    uma = segmentacao.pos_processar(m).final
    duas = segmentacao.pos_processar(uma).final
    assert abs(int(duas.sum()) - int(uma.sum())) / uma.sum() < 0.005


# ------------------------------------------------------- limiar deslocado
def test_deslocar_o_limiar_move_a_borda_de_forma_monotona():
    """O controle de limiar do revisor tem que ser previsível.

    Subir o corte só pode encolher o corpo, descer só pode inflá-lo. Se a
    relação não fosse monótona, quem arrasta o controle veria a área pular para
    os dois lados e não teria como julgar onde parar.
    """
    d8, otsu = segmentacao.desvio_8bits(campo(40))
    areas = []
    for d in (-40, -20, 0, 20, 40):
        res, limiar = segmentacao.analisar_limiar(d8, otsu, d)
        assert limiar == otsu + d
        areas.append(int(res.final.sum()))
    assert areas == sorted(areas, reverse=True), f"não é monótono: {areas}"


def test_limiar_deslocado_de_zero_reproduz_o_automatico():
    """Com deslocamento 0 o contorno é o do protocolo — a menos da quantização.

    `analisar_limiar` trabalha na escala de 8 bits (a que o navegador recebe) e
    o pipeline de medição trabalha em ponto flutuante. Medido: a diferença fica
    abaixo de 0,5% da área. Isso é o suficiente para o controle ser honesto na
    tela, e é a razão de esta função NUNCA sobrescrever a máscara automática de
    disco: quem mede é sempre o caminho em ponto flutuante.
    """
    cinza = campo(40)
    automatico = segmentacao.analisar(cinza).final.sum()
    d8, otsu = segmentacao.desvio_8bits(cinza)
    res, _ = segmentacao.analisar_limiar(d8, otsu, 0)
    assert abs(int(res.final.sum()) - automatico) / automatico < 0.005


def test_o_deslocamento_do_limiar_e_travado():
    """Fora de ±60 o corte deixa de ser 'o Otsu daquela imagem, um pouco para
    lá' e vira um limiar arbitrário — que é o que config.py proíbe."""
    d8, otsu = segmentacao.desvio_8bits(campo(40))
    for exagero, esperado in ((999, segmentacao.DESLOCAMENTO_MAX),
                              (-999, -segmentacao.DESLOCAMENTO_MAX)):
        _, limiar = segmentacao.analisar_limiar(d8, otsu, exagero)
        assert limiar == otsu + esperado


def test_quando_nada_sobrevive_o_resultado_vem_vazio_em_vez_de_estourar():
    """O revisor precisa poder dizer 'nenhum objeto sobrou' sem a rota quebrar.

    Um borrão de 400 px fica muito abaixo do `area_min` de 15 000: nada passa
    pela limpeza e `final` tem que voltar None, não uma exceção.
    """
    d8 = np.zeros(TAMANHO, np.uint8)
    d8[500:520, 600:620] = 200
    res, _ = segmentacao.analisar_limiar(d8, 100, 0)
    assert res.final is None
    assert res.n_objetos == 0
