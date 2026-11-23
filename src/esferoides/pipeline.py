"""Medição em lote: percorre o inventário, mede e escreve o CSV bruto."""

from __future__ import annotations

from collections.abc import Callable, Iterable

import numpy as np
import pandas as pd

from . import conferencia, inventario, medidas, segmentacao
from .config import Caminhos
from .inventario import Imagem

COLUNAS = [
    "arquivo", "n_experimento", "dia", "grupo", "replica", "esferoide_id",
    "esferoide_uid", *medidas.COLUNAS, "n_objetos", "toca_borda", "status",
    "area_norm_D0", *medidas.COLUNAS_AUX,
]


def nome_conferencia(img: Imagem) -> str:
    """`CONF_{n}_{arquivo}.png`.

    O protocolo pedia `CONF_{arquivo}.png`; sem o prefixo do experimento os
    nomes colidiriam entre n1, n2 e n3.
    """
    return f"CONF_{img.chave}.png"


def _linha_vazia(img: Imagem, status: str) -> dict:
    return {
        "arquivo": img.arquivo, "n_experimento": img.n_experimento,
        "dia": img.dia, "grupo": img.grupo, "replica": img.replica,
        "esferoide_id": img.esferoide_id, "esferoide_uid": img.esferoide_uid,
        **{c: np.nan for c in (*medidas.COLUNAS, *medidas.COLUNAS_AUX)},
        "n_objetos": 0, "toca_borda": 0, "status": status,
    }


def calcular_area_norm(df: pd.DataFrame) -> pd.Series:
    """area_px dividida pela área do D0 do MESMO esferoide (mesmo experimento)."""
    base = (df[(df.dia == 0) & (df.status != "excluido") & df.area_px.notna()]
            .set_index("esferoide_uid")["area_px"].to_dict())
    return pd.Series(
        [(r.area_px / base[r.esferoide_uid])
         if (r.esferoide_uid in base and pd.notna(r.area_px)) else np.nan
         for r in df.itertuples()],
        index=df.index)


def medir_lote(imagens: Iterable[Imagem], cam: Caminhos,
               progresso: Callable[[int, int, Imagem], None] | None = None,
               gerar_conferencia: bool = True) -> pd.DataFrame:
    imagens = list(imagens)
    linhas: list[dict] = []

    for i, img in enumerate(imagens, 1):
        try:
            res = segmentacao.analisar(segmentacao.carregar(img.caminho))
            mascara, desc = res.final, medidas.descrever(res)
        except Exception as e:                                   # noqa: BLE001
            print(f"  ERRO em {img.caminho}: {e}")
            mascara, desc = None, None

        if desc is None:
            # o protocolo é explícito: falha se reporta, não se conserta.
            # Nada de relaxar o filtro de área para forçar uma detecção.
            linhas.append(_linha_vazia(img, "falha"))
            legenda = "NENHUM OBJETO ACIMA DO FILTRO DE ÁREA  ->  status=falha"
        else:
            linhas.append({**_linha_vazia(img, "ok"), **desc})
            legenda = (f"area={desc['area_px']:.0f} px   "
                       f"d_eq={desc['diam_equiv_px']:.0f} px   "
                       f"circ={desc['circularidade']:.2f}   "
                       f"sol={desc['solidity']:.2f}   "
                       f"n_obj={desc['n_objetos']}   borda={desc['toca_borda']}")

        if gerar_conferencia:
            conferencia.imagem_conferencia(
                img.caminho, mascara, cam.conferencia / nome_conferencia(img),
                img.rotulo, legenda)

        if progresso:
            progresso(i, len(imagens), img)

    df = pd.DataFrame(linhas)
    df["area_norm_D0"] = calcular_area_norm(df)
    return (df[COLUNAS]
            .sort_values(["n_experimento", "grupo", "replica", "dia"])
            .reset_index(drop=True))


def gerar_folhas_contato(df: pd.DataFrame, cam: Caminhos) -> None:
    for n in sorted(df.n_experimento.unique()):
        for dia in sorted(df[df.n_experimento == n].dia.unique()):
            sub = df[(df.n_experimento == n) & (df.dia == dia)]
            arqs = [cam.conferencia / f"CONF_{n}_{a.replace(' ', '_')}.png"
                    for a in sub.arquivo]
            conferencia.folha_contato(
                arqs, cam.folhas_contato / f"contato_{n}_D{dia}.png",
                f"{n}  —  D{dia}  ({len(arqs)} esferoides)")


def executar(cam: Caminhos, limite: int | None = None) -> pd.DataFrame:
    cam.criar_pastas()
    imagens = inventario.listar(cam)
    if limite:
        passo = max(1, len(imagens) // limite)
        imagens = imagens[::passo][:limite]
    print(f"{len(imagens)} imagens a processar", flush=True)

    def progresso(i, total, _img):
        if i % 20 == 0 or i == total:
            print(f"  {i}/{total}", flush=True)

    df = medir_lote(imagens, cam, progresso)
    df.to_csv(cam.csv_medidas, index=False, encoding="utf-8-sig", float_format="%.4f")
    print(f"\nCSV: {cam.csv_medidas}", flush=True)
    gerar_folhas_contato(df, cam)

    fora = [f"{i.n_experimento}/{i.arquivo}" for i in imagens if i.fora_do_padrao]
    if fora:
        print("\nNomes fora do padrão esperado:")
        for x in fora:
            print("  ", x)
    return df
