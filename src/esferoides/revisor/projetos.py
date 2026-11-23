"""Catálogo local de projetos e importação de conjuntos do revisor."""

from __future__ import annotations

import hashlib
import io
import json
import re
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from threading import Lock, Thread
from uuid import uuid4

import pandas as pd
from flask import Flask, Response, abort, jsonify, redirect, request, send_from_directory, url_for
from PIL import Image, ImageOps

from ..config import Caminhos
from ..inventario import PASTA_DIA, PASTA_EXPERIMENTO, listar
from .app import WEB, criar_app
from .contexto import Contexto
from .repositorio import escrever_atomico

ID = re.compile(r"[a-f0-9]{32}")
ARQUIVO = re.compile(r'[^<>:"/\\|?*\x00-\x1f]+')
CSV_OBRIGATORIAS = {
    "arquivo", "n_experimento", "esferoide_uid", "dia", "grupo", "n_objetos",
    "area_px", "diam_equiv_px", "circularidade", "solidity", "status",
}
SAIDAS = {"resultados", "mascaras_auto", "mascaras_revisadas", "mapas_desvio"}


def _caminho_importado(nome: str) -> tuple[str, PurePosixPath]:
    raiz, _, relativo = nome.partition("/")
    partes = relativo.split("/")
    if not raiz or not all(
        ARQUIVO.fullmatch(parte) and not parte.endswith((".", " "))
        and parte.split(".")[0].upper() not in {"CON", "PRN", "AUX", "NUL"}
        and not re.fullmatch(r"(COM|LPT)[1-9¹²³]", parte.split(".")[0], re.I)
        for parte in partes
    ):
        raise ValueError("Selecione uma pasta de projeto com nomes de arquivo válidos.")
    return raiz, PurePosixPath(*partes)


def _arquivo_do_projeto(caminho: PurePosixPath) -> bool:
    if (len(caminho.parts) == 3 and PASTA_EXPERIMENTO.fullmatch(caminho.parts[0])
            and PASTA_DIA.fullmatch(caminho.parts[1]) and caminho.suffix == ".png"):
        return True
    return (
        len(caminho.parts) >= 3 and caminho.parts[0] == "_analise"
        and caminho.parts[1] in SAIDAS
        and (caminho.suffix in {".csv", ".png", ".json", ".jsonl", ".db"}
             or caminho.name == "revisao.db-wal")
    )


def _preparar_importacao(cam: Caminhos, arquivos) -> None:
    pastas = set()
    for arquivo in arquivos:
        raiz, relativo = _caminho_importado(arquivo.filename or "")
        pastas.add(raiz)
        if len(pastas) > 1:
            raise ValueError("Selecione uma pasta por projeto.")
        if _arquivo_do_projeto(relativo):
            destino = cam.raiz.joinpath(*relativo.parts)
            destino.parent.mkdir(parents=True, exist_ok=True)
            with destino.open("xb") as f:
                arquivo.save(f)

    imagens = listar(cam)
    if not imagens or any(img.fora_do_padrao or img.caminho.parent.name != f"d{img.dia}"
                          for img in imagens):
        raise ValueError("Use PNGs como n1/d0/D0 LC1.png, com o dia correto no nome da foto.")
    for img in imagens:
        with Image.open(img.caminho, formats=["PNG"]) as foto:
            foto.verify()

    if not cam.csv_medidas.exists():
        if cam.csv_final.exists() or cam.banco.exists() or cam.diario.exists() or (
            cam.estado_json.exists() or any(cam.mascaras_revisadas.glob("*.png"))
        ):
            raise ValueError("Para importar revisões, inclua o CSV medidas_esferoides.csv.")
        from ..pipeline import medir_lote

        cam.criar_pastas()
        df = medir_lote(imagens, cam, gerar_conferencia=False)
        df.to_csv(cam.csv_medidas, index=False, encoding="utf-8-sig", float_format="%.4f")
        return

    df = pd.read_csv(cam.csv_medidas)
    if df.empty or not CSV_OBRIGATORIAS.issubset(df.columns):
        raise ValueError("O CSV de medidas precisa ter o formato exportado pelo aplicativo.")
    chaves = {(img.n_experimento, img.dia, img.arquivo) for img in imagens}
    linhas = list(df[["n_experimento", "dia", "arquivo"]].itertuples(index=False, name=None))
    if len(set(linhas)) != len(linhas) or any(linha not in chaves for linha in linhas):
        raise ValueError("Há linhas duplicadas ou fotos do CSV que faltam na pasta selecionada.")
    if df.n_objetos.isna().any() or not pd.api.types.is_numeric_dtype(df.n_objetos):
        raise ValueError("O CSV de medidas precisa ter uma contagem por imagem.")
    if cam.csv_revisar.exists():
        triagem = pd.read_csv(cam.csv_revisar)
        if not {"n_experimento", "arquivo", "motivo"} <= set(triagem.columns) or (
            triagem.arquivo.isna().any() or not all(isinstance(a, str) for a in triagem.arquivo)
        ):
            raise ValueError("O CSV de triagem precisa ter o formato exportado pelo aplicativo.")


class Catalogo:
    def __init__(self, pasta: Path, origem: Caminhos | None, galeria: Path | None):
        self.pasta = pasta.resolve()
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.inicial = self.vincular(origem, galeria) if origem else None

    def vincular(self, cam: Caminhos, galeria: Path | None) -> str:
        codigo = hashlib.sha256(str(cam.raiz).encode("utf-8")).hexdigest()[:32]
        arquivo = self.pasta / codigo / "projeto.json"
        if galeria is not None or not arquivo.exists():
            dados = {"nome": cam.raiz.name, "origem": str(cam.raiz)}
            if galeria is not None:
                dados["galeria"] = str(galeria.resolve())
            escrever_atomico(arquivo, json.dumps(dados, ensure_ascii=False))
        return codigo

    def abrir(self, codigo: str) -> tuple[dict, Caminhos]:
        if not ID.fullmatch(codigo):
            raise FileNotFoundError(codigo)
        pasta = self.pasta / codigo
        dados = json.loads((pasta / "projeto.json").read_text(encoding="utf-8"))
        cam = Caminhos(dados.get("origem", pasta / "arquivos"))
        return dados, cam

    def criar(self, nome: str, arquivos) -> str:
        if not nome or len(nome) > 80:
            raise ValueError("Informe um nome de projeto de até 80 caracteres.")
        codigo = uuid4().hex
        with TemporaryDirectory(prefix=".importando-", dir=self.pasta) as temporaria:
            projeto = Path(temporaria) / codigo
            _preparar_importacao(Caminhos(projeto / "arquivos"), arquivos)
            escrever_atomico(projeto / "projeto.json", json.dumps({"nome": nome}, ensure_ascii=False))
            projeto.rename(self.pasta / codigo)
        return codigo


def criar_app_projetos(
    pasta: Path, *, origem: Caminhos | None = None, token: str | None = None,
    cego: bool = True, somente_sinalizadas: bool = False, aquecer: bool = False,
    validacao: Flask | None = None, galeria: Path | None = None,
) -> Flask:
    app = Flask(__name__, static_folder=WEB, static_url_path="/estatico")
    # Um conjunto completo pode conter centenas de PNGs, máscaras e arquivos auxiliares.
    app.config.update(MAX_CONTENT_LENGTH=4 * 1024**3, MAX_FORM_PARTS=20_000)
    catalogo = Catalogo(pasta, origem, galeria)
    revisores = {}
    trava = Lock()

    @app.before_request
    def conferir_token():
        if token and token not in (request.args.get("t"), request.cookies.get("revisor_token")):
            return Response("Abra o link completo com o token da sessão.", status=403)
        return None

    @app.get("/")
    def inicio():
        resposta = send_from_directory(app.static_folder, "projetos.html")
        if token:
            resposta.set_cookie("revisor_token", token, max_age=30 * 24 * 60 * 60,
                                 httponly=True, samesite="Lax")
        return resposta

    def projeto(codigo):
        try:
            return catalogo.abrir(codigo)
        except FileNotFoundError:
            abort(404)

    @app.get("/api/projetos")
    def listar_projetos():
        cards = []
        for item in catalogo.pasta.glob("*/projeto.json"):
            codigo = item.parent.name
            dados, cam = projeto(codigo)
            imagens = listar(cam)
            disponivel = cam.csv_medidas.is_file() and bool(imagens)
            cards.append({
                "nome": dados["nome"], "fotos": len(imagens), "disponivel": disponivel,
                "url": url_for("abrir_projeto", codigo=codigo) if disponivel else None,
                "capa": url_for("capa", codigo=codigo) if imagens else None,
            })
        return jsonify(sorted(cards, key=lambda card: card["nome"].casefold()))

    @app.post("/api/projetos")
    def importar():
        try:
            codigo = catalogo.criar(request.form.get("nome", "").strip(),
                                    request.files.getlist("arquivos"))
        except FileExistsError:
            return jsonify(erro="A pasta contém nomes de arquivo duplicados."), 400
        except (ValueError, SyntaxError, OSError) as exc:
            mensagem = str(exc) if isinstance(exc, ValueError) else (
                "Confira se os PNGs são válidos e se há espaço livre para importar a pasta."
            )
            return jsonify(erro=mensagem), 400
        return jsonify(url=url_for("abrir_projeto", codigo=codigo)), 201

    @app.get("/projetos/<codigo>/capa")
    def capa(codigo):
        _, cam = projeto(codigo)
        imagens = listar(cam)
        for img in imagens:
            try:
                with Image.open(img.caminho) as foto:
                    miniatura = ImageOps.fit(foto.convert("RGB"), (720, 420))
                    buffer = io.BytesIO()
                    miniatura.save(buffer, "JPEG", quality=87)
                return Response(buffer.getvalue(), mimetype="image/jpeg")
            except OSError:
                continue
        abort(404)

    @app.route("/projetos/<codigo>", methods=["GET"])
    def caminho_projeto(codigo):
        return redirect(url_for("abrir_projeto", codigo=codigo))

    @app.route("/projetos/<codigo>/", defaults={"rota": ""}, methods=["GET", "POST"])
    @app.route("/projetos/<codigo>/<path:rota>", methods=["GET", "POST"])
    def abrir_projeto(codigo, rota):
        with trava:
            if codigo not in revisores:
                dados, cam = projeto(codigo)
                if not cam.csv_medidas.is_file():
                    abort(404)
                ctx = Contexto(cam, cego=cego).montar(somente_sinalizadas=somente_sinalizadas)
                revisores[codigo] = criar_app(
                    ctx, nome_projeto=dados["nome"],
                    mostrar_validacao=validacao is not None and codigo == catalogo.inicial,
                    galeria=Path(dados["galeria"]) if "galeria" in dados else None,
                )
                if aquecer:
                    Thread(target=ctx.aquecer_cache, daemon=True).start()
            revisor = revisores[codigo]
        environ = request.environ.copy()
        environ["SCRIPT_NAME"] += f"/projetos/{codigo}"
        environ["PATH_INFO"] = f"/{rota}"
        return Response.from_app(revisor, environ)

    if validacao is not None:
        from .validacao_app import PREFIXO

        wsgi = app.wsgi_app

        def despachar(environ, start_response):
            caminho = environ["PATH_INFO"]
            if caminho == PREFIXO or caminho.startswith(f"{PREFIXO}/"):
                return validacao.wsgi_app(environ, start_response)
            return wsgi(environ, start_response)

        app.wsgi_app = despachar

    return app
