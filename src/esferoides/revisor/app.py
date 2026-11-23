"""Servidor de conferência (Flask). Rotas finas: a lógica está no Contexto."""

from __future__ import annotations

import base64
import io
from pathlib import Path

import numpy as np
from flask import Flask, Response, jsonify, render_template, request, send_file
from PIL import Image

from . import cegamento
from .contexto import Contexto
from .galeria import criar_galeria
from .repositorio import agora

WEB = "web"


def _decodificar(data_url: str) -> np.ndarray:
    bruto = base64.b64decode(data_url.split(",", 1)[1])
    return np.asarray(Image.open(io.BytesIO(bruto)).convert("L")) > 127


def _png_bytes(mascara: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray((mascara.astype(np.uint8) * 255)).save(buf, format="PNG")
    return buf.getvalue()


def _png_resposta(mascara: np.ndarray) -> Response:
    return Response(_png_bytes(mascara), mimetype="image/png")


def _data_url(mascara: np.ndarray) -> str:
    return "data:image/png;base64," + base64.b64encode(_png_bytes(mascara)).decode()


def criar_app(
    ctx: Contexto, validacao: Flask | None = None, *,
    nome_projeto: str | None = None, mostrar_validacao: bool = True,
    galeria: Path | None = None,
) -> Flask:
    app = Flask(__name__, static_folder=WEB, static_url_path="/estatico", template_folder=WEB)
    app.register_blueprint(criar_galeria(ctx.cam, galeria))

    if validacao is not None:
        from .validacao_app import PREFIXO

        revisor_wsgi = app.wsgi_app

        def despachar(environ, start_response):
            caminho = environ["PATH_INFO"]
            if caminho == PREFIXO or caminho.startswith(f"{PREFIXO}/"):
                return validacao.wsgi_app(environ, start_response)
            return revisor_wsgi(environ, start_response)

        app.wsgi_app = despachar

    # ---------------------------------------------------------------- auth
    @app.before_request
    def conferir_token():
        if ctx.token is None:
            return None
        if (request.args.get("t") == ctx.token
                or request.cookies.get("revisor_token") == ctx.token):
            return None
        return Response("403 — abra pelo link completo, com ?t=...",
                        status=403, mimetype="text/plain")

    # ---------------------------------------------------------------- páginas
    @app.get("/")
    def index():
        r = Response(render_template("index.html", nome_projeto=nome_projeto,
                                     mostrar_validacao=mostrar_validacao), mimetype="text/html")
        if ctx.token:
            r.set_cookie("revisor_token", ctx.token,
                         max_age=60 * 60 * 24 * 30, samesite="Lax")
        return r

    # ---------------------------------------------------------------- dados
    @app.get("/validacao/")
    def entrar_validacao():
        return Response("Configure as senhas da Validação Cega e reinicie o revisor. "
                        "Consulte docs/validacao-cega.md.", status=503, mimetype="text/plain")

    @app.get("/api/lista")
    def api_lista():
        return jsonify([
            cegamento.para_navegador(it, ctx.repo.estado.get(it["chave"], {}),
                                     i, ctx.cego, ctx.limiares(it))
            for i, it in enumerate(ctx.itens)])

    @app.get("/api/foto/<int:i>")
    def api_foto(i):
        return send_file(ctx.itens[i]["caminho"], mimetype="image/png")

    @app.get("/api/mascara/<int:i>")
    def api_mascara(i):
        return _png_resposta(ctx.mascara(ctx.itens[i]))

    @app.get("/api/desvio/<int:i>")
    def api_desvio(i):
        """Insumo do pincel mágico.

        É o mesmo sinal |flat−1| que a segmentação automática limiariza com Otsu
        global. O cabeçalho X-Otsu leva esse mesmo limiar, de modo que o pincel
        pinta onde o método automático teria pintado — a correção manual continua
        obedecendo ao mesmo critério, não é um contorno tirado de outro lugar.

        `?sigma=` troca a escala do flat-field. Sem o parâmetro sai o mapa do
        protocolo, byte a byte o mesmo de antes.
        """
        sigma = request.args.get("sigma")
        cache, limiar = ctx.mapa_desvio(ctx.itens[i], sigma)
        r = send_file(cache, mimetype="image/png")
        r.headers["X-Otsu"] = str(limiar)
        r.headers["Access-Control-Expose-Headers"] = "X-Otsu"
        return r

    # ---------------------------------------------------------------- ações
    @app.post("/api/medir/<int:i>")
    def api_medir(i):
        """Mede a máscara desenhada SEM alterar nada — painel ao vivo."""
        m = _decodificar(request.get_json()["mascara"])
        return jsonify({"medidas": ctx.medir(m)})

    @app.post("/api/aplicar/<int:i>")
    def api_aplicar(i):
        from .. import medidas as med
        from .. import segmentacao
        bruta = _decodificar(request.get_json()["mascara"])
        res = segmentacao.pos_processar(bruta)
        return jsonify({"mascara": _data_url(res.final),
                        "medidas": med.descrever(res)})

    @app.post("/api/limiar/<int:i>")
    def api_limiar(i):
        """Contorno do protocolo com o corte de Otsu deslocado.

        Não grava nada e não toca no cache automático: é uma proposta de
        contorno para a pessoa aceitar, corrigir por cima ou descartar. Quem
        decide continua sendo quem revisa, e o deslocamento usado vai junto na
        nota do registro quando ela salvar.
        """
        from .. import segmentacao
        dados = request.get_json()
        d = int(dados.get("deslocamento", 0))
        sigma = segmentacao.sigma_fundo_valido(dados.get("sigma_fundo"))
        it = ctx.itens[i]
        mascara, limiar, otsu = ctx.com_limiar(it, d, sigma)
        return jsonify({"mascara": _data_url(mascara),
                        "medidas": ctx.medir(mascara),
                        "limiar": limiar, "otsu": otsu,
                        "sigma_fundo": sigma,
                        "vazia": not bool(mascara.any())})

    @app.post("/api/salvar/<int:i>")
    def api_salvar(i):
        dados = request.get_json()
        it = ctx.itens[i]
        acao = dados["acao"]                      # ok | manual | excluido
        if acao == "excluido":
            registro = {"status": "excluido", "medidas": None,
                        "quando": agora(), "nota": dados.get("nota", "")}
        else:
            # a máscara vai para o disco ANTES da decisão entrar no banco: se
            # cair no meio, sobra um PNG órfão (recuperável), nunca uma linha
            # apontando para uma máscara que não existe
            # guarda a máscara DESENHADA, não a pós-processada: assim a medida é
            # sempre `pos_processar` aplicado uma vez, e reconstruir não suaviza
            # duas vezes nem perde a versão sem suavização
            if dados.get("mascara"):
                mm = _decodificar(dados["mascara"])
                ctx.salvar_mascara(it["chave"], mm)
            else:
                mm = ctx.mascara(it)
            registro = {"status": acao,
                        "medidas": ctx.medir(mm),
                        "quando": agora(), "nota": dados.get("nota", "")}
        ctx.repo.gravar(it["chave"], registro)
        ctx.escrever_csv_final()
        return jsonify({"ok": True, "status": registro["status"],
                        "medidas": registro["medidas"]})

    @app.post("/api/reverter/<int:i>")
    def api_reverter(i):
        it = ctx.itens[i]
        ctx.descartar_mascara(it["chave"])
        ctx.repo.remover(it["chave"])
        ctx.escrever_csv_final()
        return _png_resposta(ctx.mascara(it))

    @app.get("/api/resultados")
    def api_resultados():
        """Resumo do que já foi conferido. `grupos=1` quebra o cegamento."""
        return jsonify(ctx.resultados(por_grupo=request.args.get("grupos") == "1"))

    @app.get("/api/progresso")
    def api_progresso():
        total = len(ctx.itens)
        feitas = sum(1 for it in ctx.itens
                     if ctx.repo.estado.get(it["chave"], {}).get("status"))
        return jsonify({"total": total, "revisadas": feitas, "cego": ctx.cego})

    return app
