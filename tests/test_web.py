"""Checagens estáticas do cliente web.

Não substituem teste de navegador, mas prendem defeitos que já aconteceram e
que passam despercebidos porque HTML, CSS e JS são editados em arquivos
separados.
"""

import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src" / "esferoides" / "revisor" / "web"


@pytest.fixture(scope="module")
def web():
    return {n: (WEB / n).read_text(encoding="utf-8")
            for n in ("index.html", "estilo.css", "app.js")}


def test_todo_seletor_de_id_do_js_existe_no_html(web):
    ids = set(re.findall(r'id="([^"]+)"', web["index.html"]))
    usados = set(re.findall(r"\$\('#([A-Za-z0-9_-]+)'\)", web["app.js"]))
    assert not (usados - ids), f"JS busca ids inexistentes: {sorted(usados - ids)}"


def test_controles_sobre_o_stage_nao_iniciam_pincelada(web):
    """Defeito real: o pointerdown no botão do painel borbulhava até o #stage,
    que capturava o ponteiro. O `click` nunca disparava e ainda começava uma
    pincelada por baixo do painel."""
    js = web["app.js"]
    assert "data-ui" in js, "o botão sobreposto precisa ser marcado"
    assert js.count("closest('[data-ui]')") >= 2, (
        "faltou a guarda de [data-ui] em pointerdown e/ou pointermove do stage")
    inicio = js.index("stage.addEventListener('pointerdown'")
    guarda = js.index("closest('[data-ui]')", inicio)
    captura = js.index("setPointerCapture", inicio)
    assert guarda < captura, "a guarda tem que vir ANTES da captura do ponteiro"


def test_painel_recolhido_pode_ser_escondido_pelo_atributo_hidden(web):
    """Defeito real: #painelConferencia tinha display:flex, que vence o
    display:none do atributo hidden e travava a troca de abas."""
    css = web["estilo.css"]
    for alvo in ("#painelConferencia",):
        if f"{alvo}{{display:flex" in css.replace(" ", ""):
            assert f"{alvo}[hidden]" in css, f"{alvo} precisa de regra [hidden]"


def test_listener_do_painel_e_delegado(web):
    """O innerHTML do painel é reescrito a cada medida; um listener preso ao
    botão morreria no primeiro re-render."""
    js = web["app.js"]
    assert "$('#hud').addEventListener('click'" in js
    assert "onclick=" not in js, "handler inline não sobrevive ao re-render"


def test_nenhum_recurso_externo(web):
    """A página é servida localmente e tem que funcionar sem internet."""
    for nome, txt in web.items():
        for url in re.findall(r'(?:src|href)="(https?://[^"]+)"', txt):
            pytest.fail(f"{nome} referencia recurso externo: {url}")


# ------------------------------------------------- card de ajuste rápido
def test_o_card_de_ajustes_inteiro_e_data_ui(web):
    """Ele fica SOBRE o #stage. Sem [data-ui] no elemento raiz, o pointerdown
    borbulha, o stage captura o ponteiro e uma pincelada começa por baixo do
    card — o mesmo defeito que o painel de métricas já teve."""
    html = web["index.html"]
    abertura = re.search(r'<div class="ajustes"[^>]*>', html)
    assert abertura, "o card de ajustes sumiu do HTML"
    assert "data-ui" in abertura.group(0), "o card precisa de [data-ui] na raiz"


def test_exposicao_e_contraste_so_alcancam_a_foto(web):
    """A separação que sustenta o card: eles mudam o que se vê, nunca o que se
    mede. O flat-field cancela ganho — medido, exposição move a área em 0,00% —
    então se um filtro chegasse ao canvas da máscara seria por engano."""
    filtros = set(re.findall(r"(\w+)\.style\.filter", web["app.js"]))
    assert filtros == {"photo"}, f"filtro aplicado fora da foto: {filtros}"


def test_o_card_separa_o_que_ve_do_que_mede(web):
    """As duas metades têm consequências diferentes e precisam estar rotuladas
    como tal — foi confundi-las que motivou o card a ser refeito."""
    html = web["index.html"]
    secoes = re.findall(r'<div class="secao([^"]*)"', html)
    assert len(secoes) == 2, f"esperava duas seções, achei {secoes}"
    assert " muda" in secoes[1], "a seção que altera o contorno precisa da marca"


def test_os_controles_de_segmentacao_voltam_ao_padrao_a_cada_imagem(web):
    """Um limiar ou uma escala de fundo esquecidos vazando para a imagem
    seguinte enviesariam uma fila inteira sem ninguém perceber."""
    js = web["app.js"]
    corpo = js[js.index("async function abrir(i)"):]
    corpo = corpo[:corpo.index("\n}")]
    assert "zerarSegmentacao()" in corpo, "abrir() tem que zerar os controles"

    zerar = js[js.index("function zerarSegmentacao()"):]
    zerar = zerar[:zerar.index("\n}")]
    assert "limOff = 0" in zerar and "iSigma = I_SIGMA_PADRAO" in zerar


def test_os_ajustes_usados_vao_na_nota_do_registro(web):
    """Sem isso não dá para, depois, checar se os contornos ajustados diferem
    sistematicamente dos demais."""
    js = web["app.js"]
    corpo = js[js.index("async function enviar(acao)"):]
    corpo = corpo[:corpo.index("\n}")]
    assert "notaDosAjustes()" in corpo and "corpo.nota" in corpo

    nota = js[js.index("function notaDosAjustes()"):]
    nota = nota[:nota.index("\n}")]
    assert "limOff" in nota and "sigmaAtual()" in nota, (
        "a nota tem que registrar os DOIS controles de segmentação")


def test_a_lista_de_escalas_de_fundo_do_js_bate_com_a_do_python(web):
    """O JS espelha `segmentacao.SIGMAS_FUNDO`. Se as duas listas divergirem, o
    índice do controle aponta para um sigma e o servidor calcula outro."""
    from esferoides import segmentacao
    from esferoides.config import SEG

    achado = re.search(r"const SIGMAS = \[([^\]]+)\]", web["app.js"])
    assert achado, "a lista de escalas sumiu do JS"
    do_js = tuple(int(x) for x in achado.group(1).split(","))
    assert do_js == segmentacao.SIGMAS_FUNDO

    i_padrao = int(re.search(r"const I_SIGMA_PADRAO = (\d+)", web["app.js"]).group(1))
    assert do_js[i_padrao] == SEG.sigma_flat, (
        "a posição padrão do controle tem que ser o sigma do protocolo")


def test_a_vista_do_mapa_usa_o_mapa_ja_baixado(web):
    """Ela existe para tornar o limiar legível na hora. Se fosse buscar o mapa
    no servidor a cada troca deixaria de ser instantânea — e o dado já está no
    navegador, baixado para o pincel mágico."""
    js = web["app.js"]
    corpo = js[js.index("function desenharMapa()"):]
    corpo = corpo[:corpo.index("\n}")]
    assert "mapaDesvio" in corpo
    assert "fetch" not in corpo, "a vista do mapa não pode ir ao servidor"


def test_a_escala_do_fundo_so_age_ao_soltar(web):
    """Um gaussiano de σ até 180 em 1,4 milhão de pixels não roda por quadro.
    O controle age no `change` (ao soltar), não no `input`."""
    js = web["app.js"]
    assert "$('#aSigma').addEventListener('change'" in js
    entrada = js[js.index("$('#aSigma').addEventListener('input'"):]
    entrada = entrada[:entrada.index("});")]
    assert "mexerSigma" not in entrada, (
        "o evento `input` do sigma só pode atualizar o rótulo")


def test_zerar_tudo_zera_os_dois_controles(web):
    """Defeito real, pego dirigindo a interface: com um `else if`, apertar
    "Zerar tudo" com o limiar E a escala fora do padrão zerava só a escala e
    deixava o limiar de pé — que é justamente quando mais se aperta o botão."""
    js = web["app.js"]
    corpo = js[js.index("$('#bAjustesZerar').addEventListener"):]
    corpo = corpo[:corpo.index(chr(10) + "});")]
    assert "limOff = 0" in corpo, "o botão tem que zerar o limiar sempre"
    assert "else if (limOff)" not in corpo, "o `else if` era exatamente o defeito"


def test_a_previa_do_limiar_sai_marcada_como_previa(web):
    """A prévia local não faz a abertura de disco 8 nem a suavização σ=6. Ela
    orienta o arrasto; o número medido vem do servidor."""
    js = web["app.js"]
    corpo = js[js.index("function agendarPreviaLimiar()"):]
    corpo = corpo[:corpo.index("\n}\n")]
    assert re.search(r"atualizarHud\(.*true\)", corpo, re.S), (
        "a prévia do limiar tem que chamar atualizarHud com previa=true")
