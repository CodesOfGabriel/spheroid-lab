import csv
import io
import json
import re
from types import SimpleNamespace
from zipfile import ZipFile

import numpy as np
import pytest
from PIL import Image, PngImagePlugin

from esferoides.config import Caminhos
from esferoides.revisor.app import criar_app
from esferoides.revisor.validacao_amostra import (
    ESTRATOS,
    TAMANHO,
    ler_mascara,
    png_mascara,
    preparar_amostra,
    sha256,
)
from esferoides.revisor.validacao_app import criar_app_validacao
from esferoides.revisor.validacao_banco import BancoValidacao
from esferoides.revisor.validacao_relatorio import comparar, descrever

PREFIXO = "/validacao"
SENHAS = {"admin": "senha-de-teste-admin", "avaliadora": "senha-de-teste-avaliadora"}


def entrar(app, papel):
    cliente = app.test_client()
    pagina = cliente.get(PREFIXO + "/").get_data(as_text=True)
    token = re.search(r'name="csrf" type="hidden" value="([^"]+)', pagina)[1]
    resp = cliente.post(PREFIXO + "/entrar",
                        data=dict(csrf=token, perfil=papel, senha=SENHAS[papel]),
                        follow_redirects=True)
    assert resp.status_code == 200
    token = re.search(r'name="csrf-token" content="([^"]+)', resp.get_data(as_text=True))[1]
    return cliente, {"X-CSRF-Token": token}


def amostras(externa):
    png = png_mascara(externa)
    return [(f"IMG-{i:03}", {"chave": f"n{i}_secreto", "placa": placa.upper(),
                             "dia": f"D{dia}", "grupo": grupo, "arquivo": "secreto.png"},
             png, png) for i, (placa, dia, grupo) in enumerate(ESTRATOS, 1)]


@pytest.fixture
def validacao(tmp_path):
    externa = np.zeros(TAMANHO[::-1], dtype=bool)
    externa[30:110, 60:242] = True
    interna = np.zeros_like(externa)
    interna[45:62, 100:150] = True
    banco = BancoValidacao(tmp_path / 'validacao.db')
    banco.preparar(amostras(externa), {"seed": 9})
    return banco, criar_app_validacao(banco, SENHAS), externa, interna


def salvar(cliente, headers, codigo, externa, interna, status, versao=None, motivo=""):
    return cliente.post(f"{PREFIXO}/api/anotacao/{codigo}", headers=headers, data={
        "externa": (io.BytesIO(png_mascara(externa)), "externa.png"),
        "interna": (io.BytesIO(png_mascara(interna)), "interna.png"),
        "nota": "<img src=x onerror=alert(1)>", "motivo": motivo, "ambigua": "1",
        "status": status, "versao": versao or "",
    })


def test_isolamento_das_rotas_e_do_pacote(validacao):
    _, app, externa, interna = validacao
    avaliadora, _ = entrar(app, "avaliadora")
    admin, credenciais = entrar(app, "admin")
    assert app.test_client().get(PREFIXO + "/api/fila").status_code == 403
    for caminho in ("/api/lista", "/api/foto/0", "/api/resultados?grupos=1",
                    "/api/mascara/0", "/galeria/", "/galeria/originais/n1/d0/D0.png",
                    "/estatico/app.js", PREFIXO + "/estatico/app.js",
                    PREFIXO + "/api/oficial/IMG-001",
                    PREFIXO + "/api/anotacao/IMG-001/1/oficial",
                    PREFIXO + "/api/foto/n1_secreto"):
        assert avaliadora.get(caminho).status_code == 404
    for rota in ("/pacote", "/exportar", "/api/resultados"):
        assert avaliadora.get(PREFIXO + rota).status_code == 403
    for rota in ("encerrar", "preparar"):
        assert avaliadora.post(PREFIXO + "/api/" + rota, headers=credenciais).status_code == 403
    fila = avaliadora.get(PREFIXO + "/api/fila").get_json()["imagens"]
    assert list(fila[0]) == ["codigo", "status"]
    foto = avaliadora.get(PREFIXO + "/api/foto/IMG-001")
    assert foto.status_code == 200 and foto.headers["Cache-Control"] == "no-store"
    assert "Content-Disposition" not in foto.headers
    assert admin.get(PREFIXO + "/api/foto/IMG-001").status_code == 403
    assert salvar(admin, credenciais, "IMG-001", externa, interna, "rascunho").status_code == 403
    assert admin.get(PREFIXO + "/exportar").status_code == 409
    assert admin.get(PREFIXO + "/api/resultados").status_code == 409
    pacote = admin.get(PREFIXO + "/pacote")
    with ZipFile(io.BytesIO(pacote.data)) as z:
        assert z.namelist() == [i["codigo"] + ".png" for i in fila]


def test_validacao_na_mesma_porta_preserva_o_token_do_revisor(validacao, tmp_path):
    _, app_validacao, _, _ = validacao
    ctx = SimpleNamespace(cam=Caminhos(tmp_path), token="token-do-revisor")
    app = criar_app(ctx, validacao=app_validacao)

    cliente = app.test_client()
    assert cliente.get("/?t=token-do-revisor").status_code == 200
    assert cliente.get(PREFIXO + "/api/fila").status_code == 403
    redirecionamento = cliente.get(PREFIXO)
    assert redirecionamento.location == "http://localhost/validacao/"
    avaliadora, _ = entrar(app, "avaliadora")
    assert avaliadora.get(PREFIXO + "/estatico/validacao.js").status_code == 200
    assert len(avaliadora.get(PREFIXO + "/api/fila").json["imagens"]) == 48
    assert avaliadora.get(PREFIXO + "/api/resultados").status_code == 403
    for caminho in ("/", "/api/lista", "/api/foto/0", "/galeria/"):
        assert avaliadora.get(caminho).status_code == 403


def test_reabertura_tem_pixels_exatos_e_fixa_versoes(validacao):
    banco, app, externa, interna = validacao
    cliente, headers = entrar(app, "avaliadora")
    primeira_fila = cliente.get(PREFIXO + "/api/fila").json["imagens"]
    assert salvar(cliente, {}, "IMG-007", externa, interna, "rascunho").status_code == 403
    r = salvar(cliente, headers, "IMG-007", externa, interna, "concluida")
    assert r.status_code == 200
    versao = r.json["versao"]
    reaberta, acesso = entrar(criar_app_validacao(BancoValidacao(banco.caminho), SENHAS), "avaliadora")
    base = PREFIXO + "/api/anotacao/IMG-007"
    assert reaberta.get(base).json["status"] == "concluida"
    for camada, original in (("externa", externa), ("interna", interna)):
        png = reaberta.get(f"{base}/{versao}/{camada}").data
        assert np.array_equal(ler_mascara(png), original)
    segunda_fila = reaberta.get(PREFIXO + "/api/fila").json["imagens"]
    assert [r["codigo"] for r in primeira_fila] == [r["codigo"] for r in segunda_fila]
    assert salvar(reaberta, acesso, "IMG-007", externa, interna, "rascunho").status_code == 409
    errada = externa[:3]
    assert salvar(reaberta, acesso, "IMG-007", errada, interna, "rascunho", versao).status_code == 400
    assert salvar(reaberta, acesso, "IMG-007", externa, interna, "nao_avaliavel", versao,
                  motivo=" ").status_code == 400
    assert reaberta.get(base).json["versao"] == versao


def test_encerramento_e_exportacao(validacao):
    banco, app, externa, interna = validacao
    avaliadora, acesso = entrar(app, "avaliadora")
    admin, credenciais = entrar(app, "admin")
    encerramento = PREFIXO + "/api/encerrar"
    assert admin.post(encerramento, headers=credenciais).status_code == 409
    aprovado = salvar(avaliadora, acesso, "IMG-001", externa, interna, "concluida")
    assert aprovado.status_code == 200
    vazia = np.zeros_like(externa)
    for i in range(2, 49):
        banco.salvar(f"IMG-{i:03}", None, "nao_avaliavel", "", "Fora de foco", False, vazia, vazia)
    assert admin.post(encerramento, headers=credenciais).status_code == 200
    assert admin.post(encerramento, headers=credenciais).status_code == 409
    assert salvar(avaliadora, acesso, "IMG-001", externa, interna, "rascunho",
                  aprovado.json["versao"]).status_code == 409
    assert avaliadora.get(PREFIXO + "/api/resultados").status_code == 403
    resumo = admin.get(PREFIXO + "/api/resultados").json
    assert any(r["estrato"] == "placa" and r["valor"] == "N3" and r["n"] == 0 for r in resumo)
    with ZipFile(io.BytesIO(admin.get(PREFIXO + "/exportar").data)) as z:
        assert z.testzip() is None
        assert np.array_equal(ler_mascara(z.read("mascaras/segmentada/IMG-001.png")),
                              externa & ~interna)
        pares = list(csv.DictReader(io.StringIO(z.read("concordancia.csv").decode("utf-8-sig"))))
        assert [r["comparacao"] for r in pares] == ["segmentada", "silhueta"]
        assert float(pares[0]["dice"]) < 1
        assert float(pares[1]["dice"]) == float(pares[1]["iou"]) == 1
        assert z.read("graficos/segmentada.png").startswith(b"\x89PNG")
        assert z.read("graficos/silhueta.png").startswith(b"\x89PNG")
        assert len(json.loads(z.read("registro.json"))["versoes_finais"]) == 48
        assert len(z.read("chave_reservada.csv").decode("utf-8-sig").splitlines()) == 49
        assert b"Fora de foco" in z.read("relatorio.html")


def test_metricas_exatas_em_mascaras_sinteticas():
    a = np.zeros((10, 10), dtype=bool)
    a[1:5, 1:5] = True
    b = np.zeros_like(a)
    b[2:6, 1:5] = True
    assert comparar(a, a)["dice"] == comparar(a, a)["iou"] == 1
    assert comparar(a, ~a)["dice"] == comparar(a, ~a)["iou"] == 0
    assert comparar(a, b)["dice"] == .75
    assert comparar(a, b)["iou"] == .6
    assert comparar(a, a & b)["erro_relativo_area_pct"] == 25
    assert comparar(~(a | ~a), np.zeros_like(b))["iou"] is None
    assert descrever(a)["area_px2"] == 16
    assert descrever(a)["perimetro_externo_px"] == 12
    assert descrever(a)["solidez"] == 1


def test_manifesto_com_foto_sem_metadados_e_fonte_intacta(tmp_path, monkeypatch):
    from esferoides.revisor import validacao_amostra as modulo

    monkeypatch.setattr(modulo, "TAMANHO", (200, 200))
    cam = Caminhos(tmp_path / "originais")
    cam.criar_pastas()
    mascara = np.zeros((200, 200), dtype=bool)
    mascara[25:170, 32:151] = True
    area = modulo._maior(modulo.filters.gaussian(mascara.astype(float), sigma=6) > .5).sum()
    metadados = PngImagePlugin.PngInfo()
    metadados.add_text("Description", "nome experimental confidencial")
    historico = cam.resultados / "morfometria_imagej.csv"
    manifesto = tmp_path / "selecionadas.csv"
    chaves = []
    fontes = []
    with historico.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Label", "experimento", "dia", "grupo", "status", "Area", "replica"])
        for i, (placa, dia, grupo) in enumerate(ESTRATOS, 1):
            nome = f"D{dia} {grupo}1"
            chave = f"{placa}_{nome.replace(' ', '_')}"
            pasta = cam.pasta_dia(placa, dia)
            pasta.mkdir(exist_ok=True, parents=True)
            foto = pasta / (nome + ".png")
            Image.fromarray(mascara.astype(np.uint8) * 100).save(foto, pnginfo=metadados)
            editada = cam.mascaras_revisadas / (chave + ".png")
            editada.write_bytes(png_mascara(mascara))
            w.writerow([foto.name, placa, dia, grupo, "manual", area, 1])
            chaves.append([f"CEGO{i:03}", chave, placa, grupo, dia])
            fontes.extend([foto, editada])
    with manifesto.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["codigo", "chave", "experimento", "grupo", "dia"])
        w.writerows(reversed(chaves))
    fontes.extend([historico, manifesto])
    hashes = [sha256(f.read_bytes()) for f in fontes]
    ler_original = modulo.ler_mascara
    monkeypatch.setattr(modulo, "ler_mascara", lambda dados: ler_original(dados, (200, 200)))
    amostra, registro = preparar_amostra(cam, manifesto)
    assert registro["metodo"] == "selecao_preservada"
    assert [a[0] for a in amostra] == [c[0] for c in reversed(chaves)]
    assert [a[1]["chave"] for a in amostra] == [c[1] for c in reversed(chaves)]
    with Image.open(io.BytesIO(amostra[0][2])) as foto:
        assert foto.info == {}
        assert np.array_equal(np.asarray(foto), mascara * 100)
    sorteio1, info = preparar_amostra(cam, seed=42)
    sorteio2, _ = preparar_amostra(cam, seed=42)
    assert info["seed"] == 42 and sorteio1 == sorteio2
    assert sorteio1[0][0] == "IMG-001"
    assert len({(a[1]["placa"], a[1]["dia"], a[1]["grupo"]) for a in sorteio1}) == 48
    assert [sha256(f.read_bytes()) for f in fontes] == hashes
