"""Curvas descritivas do protocolo fatorial de referência, em pixels."""

from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .config import Caminhos

# paleta validada para daltonismo (slots categóricos 1 e 2, superfície clara)
COR = {"C": "#2a78d6", "T": "#eb6834"}
NOME = {"C": "Controle", "T": "Tratado"}
SURF, INK, INK2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, BASE = "#e1e0d9", "#c3c2b7"

plt.rcParams.update({
    "font.family": ["Segoe UI", "DejaVu Sans"],
    "figure.facecolor": SURF, "axes.facecolor": SURF,
    "savefig.facecolor": SURF, "axes.edgecolor": BASE,
    "text.color": INK, "axes.labelcolor": INK2,
    "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.linewidth": 0.8, "font.size": 10,
})

GLI = [("H", "Alta glicose"), ("L", "Baixa glicose")]
SUB = ("mediana e faixa interquartil · traços claros = esferoides individuais · "
       "n1+n2+n3 agrupados")

def painel(ax, sub, metrica, ylab, mostrar_x, rotulo_direto):
    """Trajetórias individuais, mediana e faixa interquartil."""
    for t in ("C", "T"):
        d = sub[sub.trat == t]
        if d.empty:
            continue
        # trajetorias individuais, recessivas
        for _, g in d.groupby("esferoide_uid"):
            g = g.sort_values("dia")
            ax.plot(g.dia, g[metrica], color=COR[t], lw=0.8, alpha=0.16,
                    solid_capstyle="round", zorder=1)
        m = (d.groupby("dia")[metrica]
             .agg(med="median", q1=lambda s: s.quantile(.25),
                  q3=lambda s: s.quantile(.75), n="size").reset_index())
        ax.fill_between(m.dia, m.q1, m.q3, color=COR[t], alpha=0.16,
                        linewidth=0, zorder=2)
        ax.plot(m.dia, m.med, color=COR[t], lw=2.0, marker="o", markersize=5,
                markeredgecolor=SURF, markeredgewidth=1.2, zorder=3,
                label=f"{NOME[t]} (n={int(m.n.iloc[0])})")
        if rotulo_direto and len(m):
            ax.annotate(NOME[t], (m.dia.iloc[-1], m.med.iloc[-1]),
                        xytext=(-4, 13 if t == "C" else -17),
                        textcoords="offset points", color=INK2, fontsize=9,
                        ha="right", fontweight="bold")

    ax.set_xticks([0, 1, 2, 3])
    ax.set_xticklabels(["D0", "D1", "D2", "D3"] if mostrar_x else [])
    ax.set_xlim(-0.2, 3.2)
    ax.grid(axis="y", color=GRID, lw=0.8, zorder=0)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    if ylab:
        ax.set_ylabel(ylab, fontsize=9.5)


def figura(df, cam, nome, metricas, titulo, subtitulo):
    # sharey por linha: os dois niveis de glicose so sao comparaveis na mesma escala
    fig, axes = plt.subplots(len(metricas), 2, figsize=(9.6, 3.3 * len(metricas)),
                             sharex=True, sharey="row")
    axes = np.atleast_2d(axes)
    for i, (met, ylab) in enumerate(metricas):
        for j, (g, gnome) in enumerate(GLI):
            ax = axes[i, j]
            painel(ax, df[df.glicose == g], met, ylab if j == 0 else "",
                   i == len(metricas) - 1, rotulo_direto=(i == 0 and j == 1))
            if i == 0:
                ax.set_title(gnome, fontsize=11, color=INK, pad=9, loc="left",
                             fontweight="bold")
        if met.startswith("area_norm"):
            axes[i, 0].set_ylim(bottom=0)
    h, l = axes[0, 0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=2, frameon=False, fontsize=9.5,
               bbox_to_anchor=(0.5, 0.005))
    fig.suptitle(titulo, x=0.012, y=0.985, ha="left", fontsize=13.5,
                 fontweight="bold", color=INK)
    fig.text(0.012, 0.943, subtitulo, ha="left", fontsize=9.5, color=MUTED)
    fig.tight_layout(rect=[0, 0.05, 1, 0.915])
    destino = cam.figuras / nome
    fig.savefig(destino, dpi=200)
    plt.close(fig)
    print("  ", destino)
    return destino



def executar(cam: Caminhos, usar_final: bool = True,
             somente_conferidas: bool = False) -> list:
    """Gera as três figuras. Usa medidas_final.csv se existir (pós-conferência)."""
    cam.criar_pastas()
    origem = cam.csv_final if (usar_final and cam.csv_final.exists()) else cam.csv_medidas
    df = pd.read_csv(origem)
    aceitos = ["manual"] if somente_conferidas else ["ok", "manual"]
    df = df[(df.status.isin(aceitos)) & (df.grupo.isin(["LC", "LT", "HC", "HT"]))].copy()
    if somente_conferidas:
        print(f"  só linhas conferidas à mão: n={len(df)}")
    df["glicose"] = df.grupo.str[0]
    df["trat"] = df.grupo.str[1]

    saidas = []
    saidas.append(figura(df, cam, "fig1_compactacao.png",
        [("area_norm_D0", "Área normalizada pelo D0"),
         ("diam_equiv_px", "Diâmetro equivalente (px)")],
        "Compactação dos esferoides ao longo de 3 dias", SUB))
    saidas.append(figura(df, cam, "fig2_forma.png",
        [("circularidade", "Circularidade  4\u03c0A/P\u00b2"),
         ("solidity", "Solidity  A / A convexa")],
        "Regularização do contorno ao longo de 3 dias", SUB))
    saidas.append(figura_experimentos(df, cam))
    return saidas


def figura_experimentos(df, cam):
    fig, axes = plt.subplots(2, 3, figsize=(11.5, 6.6), sharex=True, sharey=True)
    for i, (g, gnome) in enumerate(GLI):
        for j, nexp in enumerate(["n1", "n2", "n3"]):
            ax = axes[i, j]
            painel(ax, df[(df.glicose == g) & (df.n_experimento == nexp)],
                   "area_norm_D0", "Área normalizada pelo D0" if j == 0 else "",
                   i == 1, rotulo_direto=False)
            if i == 0:
                ax.set_title(nexp, fontsize=11, color=INK, pad=9, loc="left",
                             fontweight="bold")
            if j == 2:
                ax.annotate(gnome, (1.02, 0.5), xycoords="axes fraction",
                            rotation=270, va="center", ha="left", fontsize=10,
                            color=INK2, fontweight="bold")
    axes[0, 0].set_ylim(bottom=0)
    h, l = axes[0, 0].get_legend_handles_labels()
    fig.legend(h[:2], [NOME["C"], NOME["T"]], loc="lower center", ncol=2,
               frameon=False, fontsize=9.5, bbox_to_anchor=(0.5, 0.005))
    fig.suptitle("Consistência entre os três experimentos", x=0.012, y=0.985,
                 ha="left", fontsize=13.5, fontweight="bold", color=INK)
    fig.text(0.012, 0.945, "área normalizada pelo D0 · " + SUB, ha="left",
             fontsize=9.5, color=MUTED)
    fig.tight_layout(rect=[0, 0.05, 1, 0.92])
    destino = cam.figuras / "fig3_por_experimento.png"
    fig.savefig(destino, dpi=200)
    plt.close(fig)
    return destino
