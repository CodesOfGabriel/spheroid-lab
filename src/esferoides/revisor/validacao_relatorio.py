"""Concordância descritiva e exportação científica da sessão encerrada."""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from html import escape
from importlib.metadata import version
from threading import Lock
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
from matplotlib.figure import Figure
from skimage.measure import regionprops

from .validacao_amostra import ler_mascara, sha256, silhueta

DESCRITORES = ("area_px2", "perimetro_externo_px", "circularidade", "solidez")
COMPARACOES = ("segmentada", "silhueta")
PLOT_LOCK = Lock()


def descrever(mascara):
    regiao = regionprops(mascara.astype(np.uint8))[0]
    perimetro = regionprops(silhueta(mascara).astype(np.uint8))[0].perimeter
    return {"area_px2": int(regiao.area), "perimetro_externo_px": float(perimetro),
            "circularidade": float(4 * np.pi * regiao.area / perimetro**2) if perimetro else None,
            "solidez": float(regiao.solidity)}


def comparar(oficial, humana):
    area_o, area_h = int(oficial.sum()), int(humana.sum())
    inter = int((oficial & humana).sum())
    uniao = area_o + area_h - inter
    return {"dice": 2 * inter / (area_o + area_h) if uniao else None,
            "iou": inter / uniao if uniao else None,
            "diferenca_area_humana_menos_oficial_px2": area_h - area_o,
            "erro_relativo_area_pct": 100 * abs(area_h - area_o) / area_o if area_o else None}


def _comparacoes(linhas):
    chaves, individuais, pares = [], [], []
    for linha in linhas:
        origem = json.loads(linha["origem"])
        base = {"codigo": linha["codigo"], **{k: origem[k] for k in ("placa", "dia", "grupo")}}
        registro = {k: linha[k] for k in ("status", "avaliadora", "versao", "conclusao",
                                         "nota", "motivo", "ambigua")}
        chaves.append({"codigo": linha["codigo"], **origem,
                       **{f"sha256_humana_{k}": sha256(linha[k])
                          for k in ("segmentada", "externa", "interna")}})
        oficial_segmentada = ler_mascara(linha["oficial"])
        for tipo, humana_png in zip(COMPARACOES, (linha["segmentada"], linha["externa"]), strict=True):
            item = {**base, "comparacao": tipo}
            oficial = silhueta(oficial_segmentada) if tipo == "silhueta" else oficial_segmentada
            med_o = descrever(oficial)
            individuais.append({**item, **registro, "metodo": "oficial", **med_o})
            if linha["status"] != "concluida":
                individuais.append({**item, **registro, "metodo": "humana"})
                continue
            humana = ler_mascara(humana_png)
            med_h = descrever(humana)
            individuais.append({**item, **registro, "metodo": "humana", **med_h})
            pares.append({**item, **comparar(oficial, humana),
                          **{f"{k}_{m}": d[k] for m, d in (("oficial", med_o), ("humana", med_h))
                             for k in DESCRITORES},
                          **{f"diferenca_absoluta_{k}": abs(med_h[k] - med_o[k])
                             if med_h[k] is not None else None for k in DESCRITORES}})
    return chaves, individuais, pares


def resumir(pares, chaves):
    campos = ("dice", "iou", "erro_relativo_area_pct",
              *(f"diferenca_absoluta_{d}" for d in DESCRITORES))
    resumo = []
    for tipo in COMPARACOES:
        linhas = [p for p in pares if p["comparacao"] == tipo]
        estratos = [("global", "Todas", linhas)]
        for campo in ("dia", "placa", "grupo"):
            valores = sorted({c[campo] for c in chaves})
            estratos.extend((campo, valor, [p for p in linhas if p[campo] == valor])
                            for valor in valores)
        for estrato, valor, grupo in estratos:
            for campo in campos:
                dados = [p[campo] for p in grupo if p[campo] is not None]
                q1, mediana, q3 = np.percentile(dados, [25, 50, 75]) if dados else (None,) * 3
                resumo.append(dict(comparacao=tipo, estrato=estrato, valor=valor, n=len(dados),
                                   metrica=campo, mediana=mediana, q1=q1, q3=q3))
    return resumo


def _bland_altman(pares):
    if not pares:
        return None, None, None
    diferencas = [p["diferenca_area_humana_menos_oficial_px2"] for p in pares]
    vies = float(np.mean(diferencas))
    if len(pares) < 2:
        return vies, None, None
    amplitude = 1.96 * float(np.std(diferencas, ddof=1))
    return vies, vies - amplitude, vies + amplitude


def _graficos(pares, tipo):
    x = [p["area_px2_oficial"] for p in pares]
    y = [p["area_px2_humana"] for p in pares]
    medias = [(a + b) / 2 for a, b in zip(x, y, strict=True)]
    erros = [b - a for a, b in zip(x, y, strict=True)]
    vies, inferior, superior = _bland_altman(pares)
    menores = {p["codigo"] for p in sorted(pares, key=lambda p: p["dice"])[:5]}
    for p, erro in zip(pares, erros, strict=True):
        p["entre_5_menores_dice"] = int(p["codigo"] in menores)
        p["fora_limites_bland_altman"] = (
            int(erro < inferior or erro > superior) if inferior is not None else None)

    with PLOT_LOCK:
        fig = Figure(figsize=(11, 4.7), layout="constrained")
        fig.suptitle(f"Comparação por imagem · {tipo}")
        a, b = fig.subplots(1, 2)
        a.set(title="Concordância de área", xlabel="Oficial (px²)", ylabel="Humana (px²)")
        b.set(title="Bland–Altman", xlabel="Média do par (px²)", ylabel="Humana − oficial (px²)")
        for ax in (a, b):
            ax.grid(alpha=.2)
        a.scatter(x, y, color="#007f84")
        b.scatter(medias, erros, color="#007f84")
        if pares:
            limites = [min(x + y), max(x + y)]
            a.plot(limites, limites, "--", color="#666")
            b.axhline(vies, color="#404040")
            for limite in (inferior, superior):
                if limite is not None:
                    b.axhline(limite, linestyle="--", color="#9d4128")
            for i, p in enumerate(pares):
                if p["entre_5_menores_dice"]:
                    a.annotate(p["codigo"], (x[i], y[i]), fontsize=7, xytext=(4, 4),
                               textcoords="offset points")
                if p["fora_limites_bland_altman"]:
                    b.annotate(p["codigo"], (medias[i], erros[i]), fontsize=7, xytext=(4, 4),
                               textcoords="offset points")
        else:
            for ax in (a, b):
                ax.text(.5, .5, "Sem pares avaliáveis", ha="center", transform=ax.transAxes)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150)
    return buf.getvalue()


def _csv(linhas, campos=()):
    buf = io.StringIO(newline="")
    colunas = list(dict.fromkeys([*campos, *(k for linha in linhas for k in linha)]))
    writer = csv.DictWriter(buf, fieldnames=colunas)
    writer.writeheader()
    for linha in linhas:
        # Mantém textos livres como texto quando o CSV é aberto em planilhas.
        writer.writerow({k: "'" + v if k in ("nota", "motivo") and isinstance(v, str)
                         and v.lstrip().startswith(("=", "+", "-", "@")) else v
                         for k, v in linha.items()})
    return buf.getvalue().encode("utf-8-sig")


def _html(linhas, resumo, pares):
    def numero(v):
        return "—" if v is None else f"{v:.3f}"

    def tabela(cabecalho, linhas):
        ths = "".join(f"<th>{escape(h)}</th>" for h in cabecalho)
        trs = "".join("<tr>" + "".join(f"<td>{escape(str(v))}</td>" for v in linha)
                      + "</tr>" for linha in linhas)
        return f"<table><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>"

    status = Counter(r["status"] for r in linhas)
    partes = [f"""<!doctype html><html lang="pt-BR"><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
<title>Concordância · Validação Cega</title>
    <style>
    body{{font:16px/1.5 system-ui;max-width:1080px;margin:32px auto;padding:0 20px;color:#172026}}
    table{{border-collapse:collapse}} td,th{{padding:6px 12px;border-bottom:1px solid #dde2e5}}
    th{{text-align:left}} img{{max-width:100%}}
    </style>
<h1>Concordância da Validação Cega</h1>
    <p>{len(linhas)} imagens previstas, {status['concluida']} comparadas e
    {status['nao_avaliavel']} não avaliáveis.</p>
<p>As micrografias foram anotadas independentemente. A comparação usa
    a máscara oficial revisada como referência documental. Estimar concordância entre dois
    avaliadores humanos independentes exigiria duas anotações sob o mesmo protocolo cego.</p>
    <p>As máscaras finais são comparadas pixel a pixel. A máscara humana segmentada corresponde
    à silhueta subtraída das regiões internas anotadas como fundo. A silhueta oficial é obtida
    preenchendo vazios da máscara oficial. A área conta pixels de primeiro plano, o perímetro
    externo usa regionprops sobre a máscara preenchida, a circularidade é 4πA/P² e a solidez
    divide a área pela área da envoltória convexa discreta. A mesma regra se aplica a ambos
    os métodos em cada comparação. O erro relativo usa a área oficial como denominador.</p>
    <p>Os limites de Bland–Altman são descritivos (viés ± 1,96 desvios-padrão amostrais).
    As linhas por placa descrevem três placas de duas execuções, com N2 e N3 na mesma execução.
    A aparência das imagens pode sugerir o estágio de cultivo.</p>"""]
    for tipo in COMPARACOES:
        dados = [p for p in pares if p["comparacao"] == tipo]
        vies, inferior, superior = _bland_altman(dados)
        discrepantes = ", ".join(p["codigo"] for p in dados if p["fora_limites_bland_altman"]) or "—"
        menores = ", ".join(p["codigo"] for p in sorted(dados, key=lambda p: p["dice"])[:5]) or "—"
        partes.append(f"""<h2>{tipo.capitalize()}</h2>
        <img src="graficos/{tipo}.png" alt="Gráficos de concordância e Bland–Altman">
        <p>Viés (px²) {numero(vies)}. Limites {numero(inferior)} a {numero(superior)}.
        Fora dos limites {escape(discrepantes)}. Menores Dice, até cinco casos {escape(menores)}.</p>""")
        partes.append(tabela(
            ("Estrato", "Valor", "Métrica", "n", "Mediana", "Q1", "Q3"),
            ((r["estrato"], r["valor"], r["metrica"], r["n"],
              *(numero(r[k]) for k in ("mediana", "q1", "q3")))
             for r in resumo if r["comparacao"] == tipo)))
    excluidas = [(r["codigo"], r["motivo"]) for r in linhas if r["status"] == "nao_avaliavel"]
    if excluidas:
        partes.extend(["<h2>Imagens não avaliáveis</h2>", tabela(("Código", "Justificativa"), excluidas)])
    return "".join(partes) + "</html>"


def calcular_resultados(banco):
    sessao, linhas, revisoes = banco.finais()
    chaves, individuais, pares = _comparacoes(linhas)
    return sessao, linhas, revisoes, chaves, individuais, pares, resumir(pares, chaves)


def exportar(resultados):
    sessao, linhas, revisoes, chaves, individuais, dados_pares, resumo = resultados
    pares = [p.copy() for p in dados_pares]
    buf = io.BytesIO()
    with ZipFile(buf, "w", ZIP_DEFLATED) as zipado:
        for tipo in COMPARACOES:
            zipado.writestr(f"graficos/{tipo}.png",
                            _graficos([p for p in pares if p["comparacao"] == tipo], tipo))
        for linha in linhas:
            if linha["status"] == "concluida":
                for camada in ("segmentada", "externa", "interna"):
                    zipado.writestr(f"mascaras/{camada}/{linha['codigo']}.png", linha[camada])
        zipado.writestr("medidas_individuais.csv", _csv(individuais))
        zipado.writestr("concordancia.csv", _csv(pares, (
            "codigo", "placa", "dia", "grupo", "comparacao", "dice", "iou",
            "diferenca_area_humana_menos_oficial_px2", "erro_relativo_area_pct",
            *(f"{k}_{m}" for m in ("oficial", "humana") for k in DESCRITORES),
            *(f"diferenca_absoluta_{k}" for k in DESCRITORES),
            "entre_5_menores_dice", "fora_limites_bland_altman")))
        zipado.writestr("resumo_estratificado.csv", _csv(resumo))
        zipado.writestr("chave_reservada.csv", _csv(chaves))
        zipado.writestr("historico_revisoes.csv", _csv([dict(r) for r in revisoes]))
        zipado.writestr("registro.json", json.dumps({
            **json.loads(sessao["selecao"]), "criada": sessao["criada"],
            "encerrada": sessao["encerrada"], "versao_analise": 1,
            "dependencias": {p: version(p) for p in ("numpy", "scipy", "scikit-image", "matplotlib")},
            "versoes_finais": [{k: r[k] for k in ("codigo", "versao", "status", "motivo")}
                              for r in linhas],
        }, ensure_ascii=False, indent=2))
        zipado.writestr("relatorio.html", _html(linhas, resumo, pares))
    buf.seek(0)
    return buf
