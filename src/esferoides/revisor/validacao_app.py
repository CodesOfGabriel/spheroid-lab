"""Aplicação Flask da validação, isolada do revisor histórico."""

from __future__ import annotations

import binascii
import io
import secrets
from functools import lru_cache, wraps
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

import numpy as np
from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)
from PIL import Image

from .validacao_amostra import TOTAL, ler_mascara
from .validacao_banco import AVALIADORA, ESTADOS_FINAIS, Conflito

PREFIXO = "/validacao"
WEB = Path(__file__).with_name("web")
MAX_PNG = 6 * 1024 * 1024


def criar_app_validacao(banco, senhas, preparar=None, cookie_secure=False):
    if (set(senhas) != {"admin", "avaliadora"} or min(map(len, senhas.values())) < 16
            or senhas["admin"] == senhas["avaliadora"]):
        raise ValueError("Defina senhas distintas de pelo menos 16 caracteres para os dois perfis.")
    app = Flask(__name__, static_folder=None, template_folder=str(WEB))
    app.config.update(SECRET_KEY=secrets.token_bytes(32), MAX_CONTENT_LENGTH=2 * MAX_PNG + 65536,
                      MAX_FORM_MEMORY_SIZE=65536, SESSION_COOKIE_NAME="spheroid_lab_validacao",
                      SESSION_COOKIE_PATH=f"{PREFIXO}/", SESSION_COOKIE_SAMESITE="Strict",
                      SESSION_COOKIE_SECURE=cookie_secure)

    def csrf():
        token = session.get("csrf")
        informado = request.headers.get("X-CSRF-Token") or request.form.get("csrf", "")
        if not token or not secrets.compare_digest(token.encode(), informado.encode()):
            abort(403)

    def perfil(papel=None):
        def decorar(func):
            @wraps(func)
            def rota(*args, **kwargs):
                atual = session.get("perfil")
                if atual not in senhas or (papel and atual != papel):
                    abort(403)
                if request.method == "POST":
                    csrf()
                return func(*args, **kwargs)
            return rota
        return decorar

    @app.after_request
    def proteger(resposta):
        resposta.headers.update({
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'self'; img-src 'self' blob:; "
            "style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        })
        return resposta

    @app.errorhandler(Conflito)
    def conflito(exc):
        return jsonify(erro=str(exc)), 409

    @app.get("/")
    def raiz():
        return redirect(url_for("pagina"))

    @app.get("/favicon.ico")
    def favicon():
        return "", 204

    @app.get(f"{PREFIXO}/")
    def pagina():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(24)
        return render_template("validacao.html", papel=session.get("perfil"), csrf=session["csrf"],
                               avaliadora=AVALIADORA, total=TOTAL)

    @app.post(f"{PREFIXO}/entrar")
    def entrar():
        csrf()
        papel = request.form.get("perfil")
        senha = request.form.get("senha", "")
        if papel not in senhas or not secrets.compare_digest(senha.encode(), senhas[papel].encode()):
            return render_template("validacao.html", csrf=session["csrf"],
                                   erro="Confira o perfil e a senha."), 401
        session.clear()
        session.update(perfil=papel, csrf=secrets.token_urlsafe(24))
        return redirect(url_for("pagina"), code=303)

    @app.post(f"{PREFIXO}/sair")
    @perfil()
    def sair():
        session.clear()
        return redirect(url_for("pagina"), code=303)

    @app.get(f"{PREFIXO}/estatico/<nome>")
    def estatico(nome):
        if nome not in {"estilo.css", "validacao.css", "validacao.js", "validacao_canvas.js"}:
            abort(404)
        return send_from_directory(WEB, nome)

    @app.get(f"{PREFIXO}/api/fila")
    @perfil()
    def fila():
        estado, imagens = banco.fila()
        return jsonify(sessao=estado, imagens=imagens)

    @app.get(f"{PREFIXO}/api/foto/<codigo>")
    @perfil("avaliadora")
    def foto(codigo):
        dados = banco.foto(codigo)
        if dados is None:
            abort(404)
        return send_file(io.BytesIO(dados["foto"]), mimetype="image/png")

    @app.get(f"{PREFIXO}/api/anotacao/<codigo>")
    @perfil("avaliadora")
    def anotacao(codigo):
        dados = banco.anotacao(codigo)
        if dados is None:
            abort(404)
        return jsonify({k: dados[k] for k in
                        ("codigo", "status", "versao", "nota", "motivo", "ambigua", "conclusao")})

    @app.get(f"{PREFIXO}/api/anotacao/<codigo>/<int:versao>/<camada>")
    @perfil("avaliadora")
    def camada_anotada(codigo, versao, camada):
        if camada not in ("externa", "interna"):
            abort(404)
        dados = banco.anotacao_versao(codigo, versao)
        if not dados:
            abort(404)
        return send_file(io.BytesIO(dados[camada]), mimetype="image/png")

    @app.post(f"{PREFIXO}/api/anotacao/<codigo>")
    @perfil("avaliadora")
    def salvar(codigo):
        if banco.anotacao(codigo) is None:
            abort(404)
        campos = request.form
        status = campos.get("status")
        motivo, nota = campos.get("motivo", "").strip(), campos.get("nota", "").strip()
        if (status not in ("rascunho", *ESTADOS_FINAIS) or len(nota) > 2000 or len(motivo) > 1000
                or (status == "nao_avaliavel" and not motivo)):
            return jsonify(erro="Confira o status e informe uma justificativa para a exclusão."), 400
        try:
            versao = int(campos["versao"]) if campos.get("versao") else None
            externa, interna = (ler_mascara(request.files[k].read(MAX_PNG + 1))
                                 for k in ("externa", "interna"))
            if status == "concluida" and np.any(interna & ~externa):
                raise ValueError("Apague as regiões internas desenhadas fora da silhueta.")
            salva = banco.salvar(codigo, versao, status, nota,
                                 motivo if status == "nao_avaliavel" else "",
                                 campos.get("ambigua") == "1", externa, interna)
        except Conflito:
            raise
        except (binascii.Error, OSError, ValueError, KeyError, Image.DecompressionBombError) as exc:
            return jsonify(erro=str(exc) if type(exc) is ValueError
                           else "Envie as duas máscaras binárias na resolução original."), 400
        return jsonify(versao=salva, status=status)

    @app.post(f"{PREFIXO}/api/preparar")
    @perfil("admin")
    def preparar_sessao():
        if preparar is None:
            abort(404)
        if banco.fila()[0]:
            raise Conflito("A sessão já foi preparada.")
        try:
            banco.preparar(*preparar())
        except Conflito:
            raise
        except (OSError, ValueError, KeyError) as exc:
            return jsonify(erro=f"Não foi possível preparar a amostra. {exc}"), 422
        return jsonify(ok=True)

    @app.get(f"{PREFIXO}/pacote")
    @perfil("admin")
    def pacote():
        fotos = banco.fotos_anonimas()
        if not fotos:
            abort(404)
        buf = io.BytesIO()
        with ZipFile(buf, "w", ZIP_STORED) as zipado:
            for dados in fotos:
                zipado.writestr(f"{dados['codigo']}.png", dados["foto"])
        buf.seek(0)
        return send_file(buf, mimetype="application/zip", as_attachment=True,
                         download_name="micrografias_anonimizadas.zip")

    @app.post(f"{PREFIXO}/api/encerrar")
    @perfil("admin")
    def encerrar():
        banco.encerrar()
        return jsonify(ok=True)

    @lru_cache(maxsize=1)
    def calcular():
        from .validacao_relatorio import calcular_resultados
        return calcular_resultados(banco)

    @app.get(f"{PREFIXO}/api/resultados")
    @perfil("admin")
    def resumo():
        return jsonify(calcular()[-1])

    @app.get(f"{PREFIXO}/exportar")
    @perfil("admin")
    def resultados():
        from .validacao_relatorio import exportar
        return send_file(exportar(calcular()), mimetype="application/zip", as_attachment=True,
                         download_name="validacao_cega_resultados.zip")

    return app
