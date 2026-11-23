"""Galeria do projeto e suporte a uma galeria longitudinal preparada localmente."""

import os
import re
from functools import cached_property
from pathlib import Path

from flask import Blueprint, abort, render_template, send_file, url_for

from ..inventario import listar


class Galeria:
    def __init__(self, cam, pagina: Path | None):
        self.cam = cam
        self.pagina = pagina

    @cached_property
    def personalizada(self):
        if self.pagina is None:
            return None
        try:
            origem = Path(os.path.relpath(self.cam.raiz, self.pagina.parent)).as_posix() + "/"
            html = self.pagina.read_text(encoding="utf-8")
        except (ValueError, OSError):
            return None
        return html.replace(f'href="{origem}', 'href="originais/')

    @cached_property
    def recursos(self):
        if self.personalizada is None:
            return {}
        pasta = self.pagina.parent
        nomes = re.findall(r'(?:src|data-contorno)="([^"]+)"', self.personalizada)
        return {nome: arquivo for nome in nomes
                if (arquivo := (pasta / nome).resolve()).is_relative_to(pasta)
                and arquivo.suffix.lower() in {".jpg", ".png", ".jpeg"}}

    @cached_property
    def originais(self):
        return {img.caminho.relative_to(self.cam.raiz).as_posix(): img.caminho
                for img in listar(self.cam) if not img.fora_do_padrao}


def criar_galeria(cam, personalizada: Path | None = None):
    galeria = Galeria(cam, personalizada)
    rotas = Blueprint("galeria", __name__, url_prefix="/galeria")

    @rotas.get("/")
    def pagina():
        if galeria.personalizada is not None:
            tema = url_for("static", filename="galeria-longitudinal.css")
            return re.sub(r"</head\s*>", lambda tag: (
                f'<link rel="stylesheet" href="{tema}">\n{tag.group()}'
            ), galeria.personalizada, count=1, flags=re.IGNORECASE)
        return render_template("galeria.html", fotos=galeria.originais)

    @rotas.get("/originais/<path:nome>")
    def original(nome):
        caminho = galeria.originais.get(nome)
        if caminho is None or not caminho.resolve().is_relative_to(galeria.cam.raiz):
            abort(404)
        return send_file(caminho, mimetype="image/png")

    @rotas.get("/<path:nome>")
    def recurso(nome):
        caminho = galeria.recursos.get(nome)
        if caminho is None or not caminho.is_file():
            abort(404)
        return send_file(caminho)

    return rotas
