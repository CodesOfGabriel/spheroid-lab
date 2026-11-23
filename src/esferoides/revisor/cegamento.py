"""Cegamento da fila de conferência.

Quem revisa não deve saber experimento, grupo nem dia: sabendo, tende a desenhar
o contorno que "deveria" dar. A interface recebe só um código anônimo, e a fila
vai **embaralhada** — em ordem natural os quatro dias do mesmo esferoide viriam
em sequência e o delineamento inteiro seria dedutível só pela ordem.

Limite honesto: o *dia* não é ocultável na prática. Um agregado de D0 é claro,
granulado e ~3× maior; um esferoide de D1–D3 é escuro e compacto — isso se vê na
própria imagem. O que de fato enviesaria a comparação (controle vs. tratado,
glicose alta vs. baixa) fica completamente oculto.

A correspondência código → arquivo fica no servidor e em `cegamento.csv`. A
exportação continua com os nomes verdadeiros.
"""

from __future__ import annotations

import csv
import io
import math
import random
from pathlib import Path

from .repositorio import escrever_atomico

# campos que NUNCA podem chegar ao navegador com o cegamento ligado
CAMPOS_SENSIVEIS = ("chave", "rotulo", "arquivo", "motivo", "dia", "grupo",
                    "n_experimento", "esferoide_id", "esferoide_uid",
                    "lim_sol", "lim_circ")


def embaralhar(itens: list[dict], semente: int) -> list[dict]:
    """Embaralha com semente fixa e atribui os códigos anônimos.

    A semente é fixa para que o código de cada imagem não mude entre sessões.
    Trocar o conjunto de imagens (ex.: passar da fila sinalizada para todas)
    reatribui os códigos — o que não afeta dado nenhum, porque o banco é
    indexado pela `chave`, não pelo código.
    """
    itens = list(itens)
    random.Random(semente).shuffle(itens)
    for n, it in enumerate(itens, 1):
        it["codigo"] = f"#{n:03d}"
    return itens


def salvar_chave(itens: list[dict], destino: Path) -> None:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["codigo", "n_experimento", "arquivo", "chave", "dia", "grupo",
                "esferoide_uid", "motivo_da_triagem"])
    for it in itens:
        w.writerow([it["codigo"], it["n_experimento"], it["arquivo"], it["chave"],
                    it["dia"], it["grupo"], it["esferoide_uid"], it.get("motivo", "")])
    escrever_atomico(destino, buf.getvalue().encode("utf-8-sig"))


def para_navegador(item: dict, estado: dict, indice: int, cego: bool,
                   limiares: tuple[float, float]) -> dict:
    """Monta a linha que a interface recebe, filtrando o que é sensível."""
    auto = {campo: valor if valor is not None and math.isfinite(valor) else None
            for campo, valor in item["auto"].items()}
    linha = {
        "i": indice,
        "codigo": item["codigo"],
        "status": estado.get("status", "pendente"),
        "sinalizada": bool(item.get("motivo")),
        "auto": auto,
        "medidas": estado.get("medidas") or auto,
    }
    if not cego:
        # sem cegamento volta tudo: útil para auditoria depois da revisão
        lim_sol, lim_circ = limiares
        linha.update({k: item.get(k) for k in
                      ("chave", "rotulo", "arquivo", "motivo", "dia", "grupo")})
        linha.update({"lim_sol": lim_sol, "lim_circ": lim_circ})
    return linha
