from io import BytesIO

import pandas as pd
from PIL import Image

from esferoides.config import Caminhos
from esferoides.revisor.projetos import criar_app_projetos


def _foto():
    dados = BytesIO()
    Image.new("L", (64, 48), 120).save(dados, "PNG")
    dados.seek(0)
    return dados


def test_varios_projetos_mantem_as_revisoes_separadas_apos_reiniciar(tmp_path):
    pasta = tmp_path / "catalogo"
    app = criar_app_projetos(pasta, token="teste")
    cliente = app.test_client()
    assert cliente.get("/api/projetos").status_code == 403
    inicio = cliente.get("/?t=teste")
    assert inicio.status_code == 200
    assert "<title>Projetos · Spheroid Lab</title>" in inicio.get_data(as_text=True)
    assert 'id="abaConf"' not in inicio.get_data(as_text=True)
    assert cliente.get("/api/projetos").json == []

    urls = []
    for nome in ("Primeiro", "Segundo"):
        resposta = cliente.post("/api/projetos", data={
            "nome": nome, "arquivos": (_foto(), "Pasta/n4/d10/D10 A1.png"),
        })
        assert resposta.status_code == 201
        urls.append(resposta.json["url"])

    primeiro, segundo = urls
    assert "Primeiro" in cliente.get(primeiro).get_data(as_text=True)
    assert cliente.get(primeiro + "api/foto/0").data == _foto().getvalue()
    lista = cliente.get(primeiro + "api/lista")
    assert b"NaN" not in lista.data
    assert lista.json[0]["auto"]["area_px"] is None
    with Image.open(BytesIO(cliente.get(primeiro + "api/mascara/0").data)) as mascara:
        assert mascara.size == (64, 48)
    assert cliente.get(primeiro + "galeria/").status_code == 200
    assert cliente.get(primeiro + "capa").mimetype == "image/jpeg"
    assert cliente.post(primeiro + "api/salvar/0", json={"acao": "excluido"}).status_code == 200

    reaberto = criar_app_projetos(pasta).test_client()
    assert [p["nome"] for p in reaberto.get("/api/projetos").json] == ["Primeiro", "Segundo"]
    assert reaberto.get(primeiro + "api/progresso").json["revisadas"] == 1
    assert reaberto.get(segundo + "api/progresso").json["revisadas"] == 0


def test_importar_pasta_copia_csv_e_revisoes_existentes(tmp_path):
    cliente = criar_app_projetos(tmp_path).test_client()
    base = pd.DataFrame([{
        "arquivo": "D0 LC1", "n_experimento": "n1", "dia": 0, "grupo": "LC",
        "esferoide_uid": "n1_LC1", "n_objetos": 1, "status": "ok", "area_px": 20000,
        "diam_equiv_px": 160, "circularidade": 0.99, "solidity": 0.98,
    }]).to_csv(index=False).encode()
    estado = b'{"n1_D0_LC1": {"status": "excluido", "nota": "historico"}}'
    resposta = cliente.post("/api/projetos", data={
        "nome": "Histórico",
        "arquivos": [
            (_foto(), "Pasta/n1/d0/D0 LC1.png"),
            (BytesIO(base), "Pasta/_analise/resultados/medidas_esferoides.csv"),
            (BytesIO(estado), "Pasta/_analise/resultados/revisao.json"),
        ],
    })
    assert resposta.status_code == 201
    url = resposta.json["url"]
    cam = Caminhos(tmp_path / url.split("/")[-2] / "arquivos")
    assert cam.csv_medidas.read_bytes() == base
    assert cliente.get(url + "api/progresso").json["revisadas"] == 1
