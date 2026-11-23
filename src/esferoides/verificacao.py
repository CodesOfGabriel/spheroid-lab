"""As quatro checagens obrigatórias do protocolo, mais a triagem visual.

Nenhuma linha é descartada por causa do valor medido. Exclusão só por qualidade
de imagem, e sempre registrada — o que acontece na conferência manual, não aqui.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import (Caminhos, FAIXA_DEQ, LIMIAR_CIRC, LIMIAR_SOLIDITY,
                     QUEDA_MAX_D1, SUBIDA_TOL)


class Relatorio:
    def __init__(self):
        self.linhas: list[str] = []

    def __call__(self, s: str = "") -> None:
        print(s)
        self.linhas.append(str(s))

    def salvar(self, destino) -> None:
        destino.write_text("\n".join(self.linhas), encoding="utf-8")


def _monotonicidade(df: pd.DataFrame) -> list[tuple[str, dict, list[str]]]:
    problemas = []
    for uid, g in df[df.status == "ok"].groupby("esferoide_uid"):
        serie = dict(zip(g.sort_values("dia").dia, g.sort_values("dia").area_norm_D0))
        motivos = []
        if 0 not in serie:
            motivos.append("sem D0 de referência")
        if len(serie) < 4:
            motivos.append(f"série incompleta ({sorted(serie)})")
        if 1 in serie and pd.notna(serie[1]) and serie[1] >= QUEDA_MAX_D1:
            motivos.append(f"queda fraca no D1 (norm={serie[1]:.3f})")
        dias = sorted(d for d in serie if d >= 1 and pd.notna(serie[d]))
        for a, b in zip(dias, dias[1:]):
            if serie[a] > 0 and (serie[b] - serie[a]) / serie[a] > SUBIDA_TOL:
                motivos.append(f"sobe {100*(serie[b]-serie[a])/serie[a]:.0f}% de D{a} para D{b}")
        if motivos:
            problemas.append((uid, serie, motivos))
    return sorted(problemas)


def executar(cam: Caminhos) -> pd.DataFrame:
    P = Relatorio()
    df = pd.read_csv(cam.csv_medidas)

    P("=" * 78)
    P("VERIFICAÇÃO OBRIGATÓRIA")
    P("=" * 78)

    # ------------------------------------------------------------ 1. contagem
    P("\n[1] CONTAGEM")
    n_ok = int((df.status == "ok").sum())
    n_falha = int((df.status == "falha").sum())
    P(f"    arquivos processados ........ {len(df)}")
    P(f"    linhas status = ok .......... {n_ok}")
    P(f"    linhas status = falha ....... {n_falha}")
    P(f"    {'BATE' if n_ok == len(df) else 'NÃO BATE — ver lista abaixo'}")
    for r in df[df.status == "falha"].itertuples():
        P(f"      falha: {r.n_experimento}/{r.arquivo}")
    P("\n    por experimento e dia:")
    tabela = df.pivot_table(index="n_experimento", columns="dia",
                            values="arquivo", aggfunc="count", fill_value=0)
    for linha in tabela.to_string().splitlines():
        P("      " + linha)

    # ------------------------------------------------------ 2. monotonicidade
    P("\n[2] MONOTONICIDADE  (area_norm_D0 deve cair de D0 para D1 e estabilizar)")
    problemas = _monotonicidade(df)
    P(f"    esferoides avaliados ........ {df[df.status=='ok'].esferoide_uid.nunique()}")
    P(f"    fora do padrão esperado ..... {len(problemas)}")
    for uid, serie, motivos in problemas:
        s = "  ".join(f"D{d}={serie[d]:.3f}" for d in sorted(serie) if pd.notna(serie[d]))
        P(f"      {uid:12} {s}")
        for m in motivos:
            P(f"                   -> {m}")

    # ------------------------------------------------------ 3. faixa plausível
    P("\n[3] FAIXA PLAUSÍVEL DE DIÂMETRO EQUIVALENTE")
    ok = df[df.status == "ok"].copy()
    ok["lim_min"] = ok.dia.map(lambda d: FAIXA_DEQ.get(d, (0, 1e9))[0])
    ok["lim_max"] = ok.dia.map(lambda d: FAIXA_DEQ.get(d, (0, 1e9))[1])
    P("\n    distribuição observada por dia:")
    for d, g in ok.groupby("dia"):
        P(f"      D{d}:  n={len(g):3d}   mediana={g.diam_equiv_px.median():6.0f}   "
          f"min={g.diam_equiv_px.min():6.0f}   max={g.diam_equiv_px.max():6.0f}   "
          f"IQR={g.diam_equiv_px.quantile(.25):.0f}-{g.diam_equiv_px.quantile(.75):.0f}")
    fora = ok[(ok.diam_equiv_px < ok.lim_min) | (ok.diam_equiv_px > ok.lim_max)]
    graves = fora[(fora.diam_equiv_px < fora.lim_min * 0.75)
                  | (fora.diam_equiv_px > fora.lim_max * 1.25)]
    P(f"\n    fora da faixa: {len(fora)} de {len(ok)} ({100*len(fora)/max(len(ok),1):.1f}%)")
    P(f"    desvios grandes (>25% fora do limite): {len(graves)}")
    for r in graves.sort_values("diam_equiv_px").itertuples():
        P(f"      {r.n_experimento}/{r.arquivo:12} d_eq={r.diam_equiv_px:6.0f} px  "
          f"(limite {r.lim_min:.0f}-{r.lim_max:.0f})  circ={r.circularidade:.2f} "
          f"sol={r.solidity:.2f}")

    # -------------------------------------------------------- 4. fragmentação
    P("\n[4] FRAGMENTAÇÃO E CONTATO COM A BORDA")
    frag, borda = ok[ok.n_objetos > 1], ok[ok.toca_borda == 1]
    P(f"    imagens com n_objetos > 1 ... {len(frag)} de {len(ok)} "
      f"({100*len(frag)/max(len(ok),1):.1f}%)")
    P(f"    imagens com toca_borda = 1 .. {len(borda)}")
    P("\n    n_objetos por dia:")
    for d, g in ok.groupby("dia"):
        P(f"      D{d}:  mediana={g.n_objetos.median():.0f}   max={g.n_objetos.max():.0f}   "
          f"com fragmentos={int((g.n_objetos>1).sum())}/{len(g)}")
    if len(borda):
        P("\n    tocam a borda do campo:")
        for r in borda.itertuples():
            P(f"      {r.n_experimento}/{r.arquivo:12} d_eq={r.diam_equiv_px:6.0f} "
              f"circ={r.circularidade:.2f} sol={r.solidity:.2f}")

    # ----------------------------------------------------------- triagem
    P("\n" + "=" * 78)
    P("TRIAGEM PARA INSPEÇÃO VISUAL HUMANA")
    P("=" * 78)
    P("\n    limiares por dia (o D0 é mais frouxo: no plaqueamento o agregado")
    P("    ainda não aderiu nem compactou, então frouxo e irregular é o esperado):")
    for d in sorted(LIMIAR_SOLIDITY):
        P(f"      D{d}:  solidity < {LIMIAR_SOLIDITY[d]:.2f}   "
          f"circularidade < {LIMIAR_CIRC[d]:.2f}")

    sus = df.copy()
    sus["motivo"] = ""
    lim_sol = sus.dia.map(LIMIAR_SOLIDITY).fillna(0.85)
    lim_circ = sus.dia.map(LIMIAR_CIRC).fillna(0.35)
    dmin = sus.dia.map(lambda d: FAIXA_DEQ.get(d, (0, 1e9))[0] * 0.75)
    dmax = sus.dia.map(lambda d: FAIXA_DEQ.get(d, (0, 1e9))[1] * 1.25)

    def marca(mask, txt):
        sus.loc[mask, "motivo"] = (sus.loc[mask, "motivo"] + "; " + txt).str.strip("; ")

    ok_m = sus.status == "ok"
    marca(sus.status == "falha", "sem objeto detectado")
    marca(ok_m & ((sus.diam_equiv_px < dmin) | (sus.diam_equiv_px > dmax)),
          "d_eq fora da faixa")
    marca(ok_m & (sus.solidity < lim_sol), "solidity baixa p/ o dia")
    marca(ok_m & (sus.circularidade < lim_circ), "circularidade baixa p/ o dia")
    marca(sus.toca_borda == 1, "toca a borda")
    marca(sus.esferoide_uid.isin({u for u, _, _ in problemas}), "série não monotônica")

    rev = sus[sus.motivo != ""].copy()
    rev["imagem_conferencia"] = [
        f"CONF_{r.n_experimento}_{r.arquivo.replace(' ', '_')}.png"
        for r in rev.itertuples()]
    rev[["n_experimento", "arquivo", "esferoide_uid", "dia", "grupo", "status",
         "area_px", "diam_equiv_px", "circularidade", "solidity", "n_objetos",
         "toca_borda", "motivo", "imagem_conferencia"]].to_csv(
        cam.csv_revisar, index=False, encoding="utf-8-sig", float_format="%.3f")
    P(f"\n    {len(rev)} imagens sinalizadas ({100*len(rev)/max(len(df),1):.1f}% do total)")
    P(f"    lista: {cam.csv_revisar}")
    P("\n    NÃO são erros confirmados — são candidatas. A inspeção visual humana")
    P("    não é automatizável e não deve ser pulada.")

    # ----------------------------------------------------------- resumo
    resumo = (df[df.status == "ok"].groupby(["dia", "grupo"]).agg(
        n=("area_px", "size"),
        area_media=("area_px", "mean"), area_dp=("area_px", "std"),
        dequiv_medio=("diam_equiv_px", "mean"), dequiv_dp=("diam_equiv_px", "std"),
        norm_media=("area_norm_D0", "mean"), norm_dp=("area_norm_D0", "std"),
        circ_media=("circularidade", "mean"), circ_dp=("circularidade", "std"),
        sol_media=("solidity", "mean"), sol_dp=("solidity", "std"),
        ar_medio=("aspect_ratio", "mean")).round(4).reset_index())
    resumo.to_csv(cam.csv_resumo, index=False, encoding="utf-8-sig")

    P("\n" + "=" * 78)
    P("RESUMO DESCRITIVO POR GRUPO  (média ± desvio padrão)")
    P("=" * 78)
    P(f"\n{'dia':<4}{'grupo':<7}{'n':>4}{'area_px':>20}{'area_norm_D0':>18}"
      f"{'circularidade':>18}{'solidity':>16}")
    for r in resumo.itertuples():
        P(f"D{r.dia:<3}{r.grupo:<7}{r.n:>4}"
          f"{r.area_media:>12.0f} ±{np.nan_to_num(r.area_dp):<7.0f}"
          f"{np.nan_to_num(r.norm_media):>10.3f} ±{np.nan_to_num(r.norm_dp):<7.3f}"
          f"{r.circ_media:>10.3f} ±{np.nan_to_num(r.circ_dp):<7.3f}"
          f"{r.sol_media:>8.3f} ±{np.nan_to_num(r.sol_dp):<6.3f}")

    P.salvar(cam.relatorio)
    print(f"\n\nRelatório salvo em: {cam.relatorio}")
    return rev
