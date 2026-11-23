import numpy as np

from esferoides import config, medidas, segmentacao


def test_parametros_do_protocolo():
    seg = config.SEG
    assert (seg.sigma_flat, seg.sigma_desvio, seg.area_min,
            seg.raio_abertura, seg.sigma_contorno) == (60, 3, 15000, 8, 6)


def test_pipeline_em_imagem_sintetica_com_contraste_claro_e_escuro():
    y, x = np.ogrid[:384, :384]
    disco = (x - 192) ** 2 + (y - 192) ** 2 <= 108 ** 2

    for intensidade in (40, 220):
        imagem = np.full(disco.shape, 130.0)
        imagem[disco] = intensidade
        resultado = segmentacao.analisar(imagem)
        assert resultado.n_objetos == 1
        assert resultado.final[192, 192]
        assert not resultado.final[0, 0]
        forma = medidas.descrever(resultado)
        assert 0.85 < forma["circularidade"] < 1.05
        assert (resultado.final & disco).sum() / (resultado.final | disco).sum() > 0.55
