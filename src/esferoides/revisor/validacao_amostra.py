"""Seleção auditável e leitura dos insumos históricos da validação."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import re
from itertools import product
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage
from skimage import filters, measure

from ..config import GRUPOS

TAMANHO = (1368, 1038)
ESTRATOS = tuple(product(("n1", "n2", "n3"), range(4), sorted(GRUPOS)))
TOTAL = len(ESTRATOS)
SEMENTE = 20261119


def sha256(dados):
    return hashlib.sha256(dados).hexdigest()


def png(imagem):
    buf = io.BytesIO()
    # Uma imagem nova descarta texto, EXIF, perfis, DPI e outros chunks da origem.
    Image.frombytes(imagem.mode, imagem.size, imagem.tobytes()).save(buf, format="PNG")
    return buf.getvalue()


def png_mascara(mascara):
    return png(Image.fromarray(mascara.astype(np.uint8) * 255))


def ler_mascara(dados, tamanho=TAMANHO):
    with Image.open(io.BytesIO(dados), formats=["PNG"]) as im:
        if im.size != tamanho or getattr(im, "n_frames", 1) != 1:
            raise ValueError("Dimensão ou número de quadros inválido.")
        if im.mode not in ("1", "L", "RGB", "RGBA"):
            raise ValueError("Envie um PNG binário em tons de cinza.")
        pixels = np.asarray(im)
        if im.mode in ("RGB", "RGBA"):
            cinza = pixels[:, :, 0]
            if (np.any(pixels[:, :, 1:3] != cinza[:, :, None])
                    or (im.mode == "RGBA" and np.any(pixels[:, :, 3] != 255))):
                raise ValueError("A máscara deve ser opaca e em tons de cinza.")
            pixels = cinza
        elif im.mode == "1":
            return pixels
        if np.any((pixels != 0) & (pixels != 255)):
            raise ValueError("A máscara deve conter somente pixels 0 e 255.")
        return pixels != 0


def _csv(dados):
    return list(csv.DictReader(io.StringIO(dados.decode("utf-8-sig"), newline="")))


def _maior(mascara):
    rotulos = measure.label(mascara, connectivity=2)
    contagens = np.bincount(rotulos.ravel())
    if len(contagens) == 1:
        raise ValueError("Máscara oficial vazia.")
    return rotulos == (1 + contagens[1:].argmax())


def _foto_anonima(dados):
    with Image.open(io.BytesIO(dados), formats=["PNG"]) as im:
        if im.size != TAMANHO or getattr(im, "n_frames", 1) != 1:
            raise ValueError("Micrografia com dimensão ou número de quadros inválido.")
        if im.mode not in ("L", "RGB", "RGBA", "I;16", "I;16B"):
            im = im.convert("RGB")
        return png(im)


def _insumos(cam, linha, versoes, foto_arquivada=None):
    placa, dia, grupo = linha["estrato"]
    arquivo, chave = linha["arquivo"], linha["chave"]
    if linha["status"] != "manual" or not linha["area"]:
        raise ValueError("Observação sem medida histórica válida.")
    foto = cam.pasta_dia(placa, dia) / arquivo
    foto_bruta = foto.read_bytes()
    foto_anonima = _foto_anonima(foto_bruta)
    if foto_arquivada and foto_arquivada.is_file():
        arquivada = foto_arquivada.read_bytes()
        if arquivada != foto_bruta and _foto_anonima(arquivada) != foto_anonima:
            raise ValueError(f"A micrografia atual diverge da seleção arquivada: {chave}.")

    editada = (cam.mascaras_revisadas / f"{chave}.png").read_bytes()
    arquivos = sorted((versoes / chave).glob("*/final_segmentada.png")) if versoes else []
    if arquivos:
        correspondentes = []
        for caminho in arquivos:
            origem = json.loads(caminho.with_name("proveniencia.json").read_text("utf-8"))
            hashes = origem["sha256"]
            # Na reconciliação, original.png é a primeira máscara automática.
            if hashes["editada"] == sha256(editada):
                oficiais = caminho.read_bytes()
                if hashes["final_segmentada"] != sha256(oficiais):
                    raise ValueError("Hash da máscara final versionada divergente.")
                correspondentes.append((oficiais, origem["revisao"], caminho))
        if len(correspondentes) != 1:
            raise ValueError("Não há uma versão oficial unívoca para a foto e a edição atuais.")
        oficial, versao, caminho_oficial = correspondentes[0]
        mascara = ler_mascara(oficial)
    else:
        # Reconstrução histórica documentada, conferida com a área do artigo.
        # O pipeline corrente do revisor pode preencher vazios antes de suavizar.
        principal = _maior(ler_mascara(editada))
        mascara = _maior(filters.gaussian(principal.astype(float), sigma=6) > 0.5)
        oficial = png_mascara(mascara)
        versao = "reconstrucao-historica-gauss6"
        caminho_oficial = None

    if mascara.sum() != float(linha["area"]) or not mascara.any():
        raise ValueError("Área da máscara segmentada diverge da tabela histórica.")
    origem = {
        "chave": chave, "placa": placa.upper(), "dia": f"D{dia}", "grupo": grupo,
        "replica": linha["replica"], "arquivo": arquivo,
        "micrografia": foto.relative_to(cam.raiz).as_posix(),
        "versao_oficial": versao,
        "mascara_versionada": str(caminho_oficial) if caminho_oficial else "",
        "sha256_original": sha256(foto_bruta), "sha256_foto_anonima": sha256(foto_anonima),
        "sha256_editada": sha256(editada), "sha256_oficial": sha256(oficial),
    }
    return origem, foto_anonima, oficial


def _encontrar_manifesto(cam):
    candidatos = sorted(cam.saida.glob("reconciliacao_*/entrega/qc/reservado/chave_cegamento.csv"))
    if len(candidatos) > 1:
        raise ValueError("Há mais de uma seleção arquivada. Indique o CSV em --manifesto.")
    return next(iter(candidatos), None)


def preparar_amostra(cam, manifesto=None, seed=SEMENTE):
    """Mantém uma seleção existente ou sorteia um candidato válido por estrato."""
    manifesto = Path(manifesto) if manifesto else _encontrar_manifesto(cam)
    historico = cam.resultados / "morfometria_imagej.csv"
    dados = historico.read_bytes()
    linhas = {}
    for r in _csv(dados):
        estrato = (r["experimento"].lower(), int(r["dia"]), r["grupo"].upper())
        if estrato not in ESTRATOS:
            continue
        arquivo = r["Label"]
        if Path(arquivo).name != arquivo or Path(arquivo).suffix != ".png":
            raise ValueError("Nome de micrografia inválido na tabela histórica.")
        chave = f"{estrato[0]}_{Path(arquivo).stem.replace(' ', '_')}"
        if chave in linhas:
            raise ValueError(f"Identificação duplicada na tabela histórica: {chave}")
        linhas[chave] = dict(estrato=estrato, arquivo=arquivo, chave=chave,
                             status=r["status"], area=r["Area"], replica=r["replica"])
    registro = {"fonte_historica": str(historico), "sha256_historico": sha256(dados),
                "exclusoes": [], "substituicoes": [], "versao_selecao": 1}

    if manifesto:
        dados_manifesto = manifesto.read_bytes()
        selecao = _csv(dados_manifesto)
        arquitetura = manifesto.parent.parent
        versoes = arquitetura.parent / "mascaras_versionadas"
        if (len(selecao) != TOTAL or len({r["chave"] for r in selecao}) != TOTAL
                or len({r["codigo"] for r in selecao}) != TOTAL
                or not all(re.fullmatch(r"(?:CEGO|IMG-)[0-9]{3}", r["codigo"]) for r in selecao)):
            raise ValueError(f"O manifesto deve ter {TOTAL} chaves e códigos únicos.")
        registro.update(metodo="selecao_preservada", manifesto=str(manifesto),
                        sha256_manifesto=sha256(dados_manifesto),
                        seed=SEMENTE if manifesto.name == "chave_cegamento.csv"
                        and (arquitetura.parent / "PROTOCOLO_VALIDACAO_CEGA.md").is_file()
                        and f"semente {SEMENTE}" in (arquitetura.parent / "PROTOCOLO_VALIDACAO_CEGA.md")
                        .read_text(encoding="utf-8") else None)
        amostra = []
        for r in selecao:
            linha = linhas[r["chave"]]
            if (r["experimento"].lower(), int(r["dia"]), r["grupo"].upper()) != linha["estrato"]:
                raise ValueError(f"Estrato divergente para {r['codigo']}.")
            foto_arquivada = arquitetura / "cego" / "imagens" / f"{r['codigo']}.png"
            amostra.append((r["codigo"], *_insumos(cam, linha, versoes, foto_arquivada)))
        return amostra, registro

    rng = random.Random(seed)
    registro.update(metodo="sorteio_estratificado", seed=seed)
    amostra = []
    for estrato in ESTRATOS:
        candidatos = [r for _, r in sorted(linhas.items()) if r["estrato"] == estrato]
        rng.shuffle(candidatos)
        recusados = []
        for linha in candidatos:
            try:
                insumos = _insumos(cam, linha, None)
            except (OSError, ValueError) as exc:
                recusados.append(linha["chave"])
                registro["exclusoes"].append({"chave": linha["chave"], "motivo": str(exc)})
                continue
            amostra.append(insumos)
            if recusados:
                registro["substituicoes"].append({"recusados": recusados, "selecionado": linha["chave"]})
            break
        else:
            raise ValueError(f"Nenhuma imagem válida para {estrato}.")
    rng.shuffle(amostra)
    return [(f"IMG-{i:03}", *a) for i, a in enumerate(amostra, 1)], registro


def silhueta(mascara):
    return ndimage.binary_fill_holes(mascara)
