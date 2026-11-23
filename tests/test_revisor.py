"""Persistência das decisões e cegamento da fila."""

import json
import sqlite3

import numpy as np
import pytest

from esferoides.revisor import cegamento
from esferoides.revisor.repositorio import Repositorio, escrever_atomico


@pytest.fixture
def repo(tmp_path):
    with Repositorio(tmp_path / "revisao.db", tmp_path / "diario.jsonl",
                     tmp_path / "estado.json", tmp_path / "backups") as r:
        yield r


# --------------------------------------------------------------- persistência
def test_decisao_fica_no_disco_antes_de_a_chamada_retornar(repo, tmp_path):
    """Com synchronous=FULL, outra conexão tem que enxergar a linha na hora."""
    repo.gravar("n1_D0_HC1", {"status": "manual", "medidas": {"area_px": 123.0},
                              "quando": "2026-09-02T00:00:00", "nota": ""})
    outra = sqlite3.connect(f"file:{tmp_path / 'revisao.db'}?mode=ro", uri=True)
    linha = outra.execute("SELECT status FROM revisao WHERE chave=?",
                          ("n1_D0_HC1",)).fetchone()
    assert linha == ("manual",)


def test_historico_e_so_append(repo):
    for status in ("ok", "manual", "excluido"):
        repo.gravar("n1_D0_HC1", {"status": status, "medidas": None,
                                  "quando": "2026-09-02T00:00:00", "nota": ""})
    hist = repo.historico("n1_D0_HC1")
    assert [h["status"] for h in hist] == ["ok", "manual", "excluido"]
    assert repo.estado["n1_D0_HC1"]["status"] == "excluido"


def test_reverter_remove_do_estado_mas_deixa_rastro(repo):
    repo.gravar("n1_D0_HC1", {"status": "manual", "medidas": None,
                              "quando": "x", "nota": ""})
    repo.remover("n1_D0_HC1")
    assert "n1_D0_HC1" not in repo.estado
    assert repo.historico("n1_D0_HC1")[-1]["status"] == "revertido"


def test_escrita_atomica_nao_deixa_arquivo_truncado(tmp_path):
    alvo = tmp_path / "saida.csv"
    escrever_atomico(alvo, "conteudo original")
    escrever_atomico(alvo, "conteudo novo, mais longo")
    assert alvo.read_text(encoding="utf-8") == "conteudo novo, mais longo"
    assert not list(tmp_path.glob("*.tmp")), "sobrou arquivo temporário"


def test_reconstroi_a_partir_do_diario_e_das_mascaras(tmp_path):
    mascaras = tmp_path / "mascaras"
    mascaras.mkdir()

    from PIL import Image
    m = np.zeros((60, 60), np.uint8)
    m[20:40, 20:40] = 255
    Image.fromarray(m).save(mascaras / "n1_D0_HC1.png")

    with Repositorio(tmp_path / "r.db", tmp_path / "d.jsonl", tmp_path / "e.json") as r:
        r.gravar("n1_D0_HC1", {"status": "manual", "medidas": {"area_px": 400.0},
                               "quando": "x", "nota": ""})
        r.gravar("n1_D0_HC9", {"status": "excluido", "medidas": None,
                               "quando": "x", "nota": ""})

    # perde o banco, sobram o diário e as máscaras
    for sufixo in ("", "-wal", "-shm"):
        (tmp_path / f"r.db{sufixo}").unlink(missing_ok=True)

    with Repositorio(tmp_path / "r.db", tmp_path / "d.jsonl", tmp_path / "e2.json") as novo:
        n = novo.reconstruir(mascaras, lambda mask, chave: {"area_px": float(mask.sum())})
        assert n == 2
        # as medidas são RECALCULADAS da máscara, não copiadas do diário
        assert novo.estado["n1_D0_HC1"]["medidas"]["area_px"] == 400.0
        # e o medidor recebe a chave, para buscar a estatística da imagem certa
        assert novo.estado["n1_D0_HC9"]["status"] == "excluido"


def test_diario_com_linha_truncada_nao_derruba_a_reconstrucao(tmp_path):
    diario = tmp_path / "d.jsonl"
    diario.write_text('{"chave":"a","status":"manual","quando":"x"}\n'
                      '{"chave":"b","stat\n', encoding="utf-8")
    vazio = tmp_path / "mascaras"
    vazio.mkdir()
    with Repositorio(tmp_path / "r.db", diario, tmp_path / "e.json") as repo:
        assert repo.reconstruir(vazio, lambda m, chave: None) == 1


# ------------------------------------------------------------------ cegamento
def _item(chave, dia=0):
    return {"chave": chave, "rotulo": f"n1 · {chave}", "arquivo": chave,
            "n_experimento": "n1", "esferoide_uid": "n1_HC1", "dia": dia,
            "grupo": "HC", "motivo": "teste",
            "auto": {"area_px": 1.0, "diam_equiv_px": 1.0,
                     "circularidade": 1.0, "solidity": 1.0}}


def test_navegador_nao_recebe_nenhum_campo_de_identidade():
    it = cegamento.embaralhar([_item("n1_D0_HC1")], 1)[0]
    linha = cegamento.para_navegador(it, {}, 0, cego=True, limiares=(0.7, 0.3))
    vazados = [c for c in cegamento.CAMPOS_SENSIVEIS if c in linha]
    assert not vazados, f"cegamento vazou: {vazados}"
    assert linha["codigo"] == "#001"


def test_sem_cegamento_os_campos_voltam():
    it = cegamento.embaralhar([_item("n1_D0_HC1")], 1)[0]
    linha = cegamento.para_navegador(it, {}, 0, cego=False, limiares=(0.7, 0.3))
    assert linha["rotulo"] == "n1 · n1_D0_HC1"
    assert linha["dia"] == 0


def test_embaralhamento_e_estavel_entre_execucoes():
    itens = [_item(f"n1_D0_HC{i}") for i in range(30)]
    a = [x["chave"] for x in cegamento.embaralhar(list(itens), 20260902)]
    b = [x["chave"] for x in cegamento.embaralhar(list(itens), 20260902)]
    assert a == b
    assert a != [x["chave"] for x in itens], "a fila não foi embaralhada"


def test_embaralhamento_separa_os_dias_do_mesmo_esferoide():
    """Em ordem natural os 4 dias viriam em sequência e entregariam a série."""
    itens = [_item(f"n1_D{d}_HC{i}", dia=d) for i in range(20) for d in range(4)]
    fila = cegamento.embaralhar(itens, 20260902)
    seguidos = sum(
        1 for a, b in zip(fila, fila[1:])
        if a["chave"].split("_")[-1] == b["chave"].split("_")[-1])
    assert seguidos < len(fila) * 0.15, "muitos dias do mesmo esferoide ficaram juntos"


def test_chave_de_decegamento_tem_todas_as_linhas(tmp_path):
    itens = cegamento.embaralhar([_item(f"n1_D0_HC{i}") for i in range(5)], 1)
    destino = tmp_path / "cegamento.csv"
    cegamento.salvar_chave(itens, destino)
    linhas = destino.read_text(encoding="utf-8-sig").strip().splitlines()
    assert len(linhas) == 6                       # cabeçalho + 5
    assert linhas[0].startswith("codigo,")


# ------------------------------------------------------- rota do limiar
@pytest.fixture
def cliente(tmp_path):
    """Um Contexto mínimo, montado à mão, com uma imagem sintética.

    Não usa `montar()` de propósito: ele precisa do CSV de medidas inteiro, e o
    que está sob teste aqui é a rota, não a leitura da planilha.
    """
    from PIL import Image

    from esferoides.config import Caminhos
    from esferoides.revisor.app import criar_app
    from esferoides.revisor.contexto import Contexto
    from esferoides.revisor.repositorio import Repositorio

    h, w, raio = 1038, 1368, 260
    y, x = np.ogrid[:h, :w]
    img = np.full((h, w), 150.0)
    img[(y - h/2)**2 + (x - w/2)**2 <= raio**2] = 45.0

    cam = Caminhos(tmp_path)
    cam.criar_pastas()
    (cam.raiz / "n1" / "d1").mkdir(parents=True, exist_ok=True)
    foto = cam.raiz / "n1" / "d1" / "D1 HC1.png"
    Image.fromarray(img.astype(np.uint8)).save(foto)

    ctx = Contexto(cam=cam, cego=True, token=None)
    ctx.itens = [{"chave": "n1_D1_HC1", "codigo": "#001", "caminho": str(foto),
                  "dia": 1, "grupo": "HC", "rotulo": "n1 · D1 HC1", "motivo": "",
                  "arquivo": "D1 HC1", "n_experimento": "n1",
                  "esferoide_uid": "n1_HC1", "n_objetos": 1,
                  "auto": {"area_px": 0.0, "diam_equiv_px": 0.0,
                           "circularidade": 0.0, "solidity": 0.0}}]
    ctx.repo = Repositorio(cam.banco, cam.diario, cam.estado_json, cam.backups)
    with ctx.repo:
        yield criar_app(ctx).test_client(), ctx


def test_rota_do_limiar_devolve_mascara_e_medidas(cliente):
    c, _ = cliente
    r = c.post("/api/limiar/0", json={"deslocamento": 0})
    assert r.status_code == 200
    corpo = r.get_json()
    assert corpo["mascara"].startswith("data:image/png;base64,")
    assert corpo["limiar"] == corpo["otsu"]
    assert not corpo["vazia"]
    assert corpo["medidas"]["area_px"] > 0


def test_deslocar_o_limiar_pela_rota_encolhe_o_contorno(cliente):
    c, _ = cliente
    areas = [c.post("/api/limiar/0", json={"deslocamento": d})
             .get_json()["medidas"]["area_px"] for d in (-30, 0, 30)]
    assert areas[0] > areas[1] > areas[2], f"não é monótono pela rota: {areas}"


def test_a_rota_do_limiar_nao_grava_nada(cliente):
    """É uma proposta de contorno, não uma decisão. Nada de máscara revisada
    aparecendo no disco sem a pessoa ter clicado em salvar."""
    c, ctx = cliente
    c.post("/api/limiar/0", json={"deslocamento": -40})
    assert not list(ctx.cam.mascaras_revisadas.glob("*.png"))
    assert ctx.repo.estado == {}


def test_a_escala_do_fundo_muda_o_contorno_pela_rota(cliente):
    """É o motivo de o controle existir: o limiar só move o corte, a escala do
    fundo muda o formato do mapa. Se as três derem a mesma área, o parâmetro
    não chegou ao pipeline."""
    c, _ = cliente
    areas = [c.post("/api/limiar/0", json={"deslocamento": 0, "sigma_fundo": s})
             .get_json()["medidas"]["area_px"] for s in (30, 60, 120)]
    assert len(set(areas)) == 3, f"a escala do fundo não teve efeito: {areas}"


def test_a_rota_recusa_um_sigma_fora_da_lista(cliente):
    """Lista fechada: um valor qualquer viraria um parâmetro arbitrário por
    imagem, e ainda encheria o cache de mapas em disco."""
    from esferoides import segmentacao

    c, _ = cliente
    for pedido in (77, -5, 10_000, "abacaxi", None):
        devolvido = c.post("/api/limiar/0",
                           json={"deslocamento": 0, "sigma_fundo": pedido}) \
                     .get_json()["sigma_fundo"]
        assert devolvido in segmentacao.SIGMAS_FUNDO


def test_o_mapa_do_protocolo_fica_num_cache_separado(cliente):
    """O PNG de nome limpo é o do protocolo, e é o que o pincel mágico usa por
    padrão. As variações do revisor não podem sobrescrevê-lo."""
    c, ctx = cliente
    c.get("/api/desvio/0")
    c.get("/api/desvio/0?sigma=120")
    nomes = sorted(p.name for p in ctx.cam.mapas_desvio.glob("*.png"))
    assert nomes == ["n1_D1_HC1.png", "n1_D1_HC1_s120.png"]


def test_o_cabecalho_otsu_acompanha_a_escala_do_fundo(cliente):
    """O navegador desloca o limiar a partir desse número. Se ele não mudasse
    junto com o mapa, a prévia local cortaria na altura errada."""
    c, _ = cliente
    padrao = c.get("/api/desvio/0").headers["X-Otsu"]
    outro = c.get("/api/desvio/0?sigma=180").headers["X-Otsu"]
    assert padrao != outro
