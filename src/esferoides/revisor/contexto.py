"""Estado do servidor de conferência: fila de imagens, máscaras e repositório."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

from .. import medidas, segmentacao
from ..config import (SEG, Caminhos, GRUPOS, LIMIAR_CIRC, LIMIAR_SOLIDITY,
                      SEMENTE_CEGAMENTO)
from . import cegamento
from .repositorio import Repositorio, escrever_atomico


def _png(mascara: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray((mascara.astype(np.uint8) * 255)).save(buf, format="PNG")
    return buf.getvalue()


@dataclass
class Contexto:
    cam: Caminhos
    cego: bool = True
    token: str | None = None
    itens: list[dict] = field(default_factory=list)
    repo: Repositorio | None = None

    # ------------------------------------------------------------------
    def montar(self, somente_sinalizadas: bool = False) -> "Contexto":
        self.cam.criar_pastas()
        df = pd.read_csv(self.cam.csv_medidas)

        motivos: dict[str, str] = {}
        if self.cam.csv_revisar.exists():
            r = pd.read_csv(self.cam.csv_revisar)
            motivos = {f"{a.n_experimento}_{a.arquivo.replace(' ', '_')}": a.motivo
                       for a in r.itertuples()}

        itens = []
        for a in df.itertuples():
            chave = f"{a.n_experimento}_{a.arquivo.replace(' ', '_')}"
            if somente_sinalizadas and chave not in motivos:
                continue
            itens.append({
                "chave": chave,
                "rotulo": f"{a.n_experimento} · {a.arquivo}",
                "arquivo": a.arquivo,
                "n_experimento": a.n_experimento,
                "esferoide_uid": a.esferoide_uid,
                "motivo": motivos.get(chave, ""),
                "caminho": str(self.cam.pasta_dia(a.n_experimento, int(a.dia))
                               / f"{a.arquivo}.png"),
                "n_objetos": int(a.n_objetos),
                "dia": int(a.dia),
                "grupo": a.grupo,
                "auto": {"area_px": a.area_px, "diam_equiv_px": a.diam_equiv_px,
                         "circularidade": a.circularidade, "solidity": a.solidity},
            })

        self.itens = cegamento.embaralhar(itens, SEMENTE_CEGAMENTO)
        cegamento.salvar_chave(self.itens, self.cam.csv_cegamento)
        self.repo = Repositorio(self.cam.banco, self.cam.diario,
                                self.cam.estado_json, self.cam.backups)
        return self

    # ------------------------------------------------------------------
    def limiares(self, item: dict) -> tuple[float, float]:
        return (LIMIAR_SOLIDITY.get(item["dia"], 0.85),
                LIMIAR_CIRC.get(item["dia"], 0.35))

    def caminho_auto(self, chave: str) -> Path:
        return self.cam.mascaras_auto / f"{chave}.png"

    def caminho_revisada(self, chave: str) -> Path:
        return self.cam.mascaras_revisadas / f"{chave}.png"

    def mascara(self, item: dict) -> np.ndarray:
        """Preferência: máscara revisada > cache automático > calcular agora."""
        rev = self.caminho_revisada(item["chave"])
        if rev.exists():
            return np.asarray(Image.open(rev).convert("L")) > 127
        auto = self.caminho_auto(item["chave"])
        if auto.exists():
            return np.asarray(Image.open(auto).convert("L")) > 127
        foto = segmentacao.carregar(item["caminho"])
        m, _ = segmentacao.maior_componente(segmentacao.binarizar(segmentacao.mapa_desvio(foto)))
        if m is None:
            m = np.zeros_like(foto, dtype=bool)
        escrever_atomico(auto, _png(m))
        return m

    def salvar_mascara(self, chave: str, mascara: np.ndarray) -> None:
        escrever_atomico(self.caminho_revisada(chave), _png(mascara))

    def descartar_mascara(self, chave: str) -> None:
        """Não apaga: move para .descartadas/ com carimbo de hora.

        Nenhum trabalho manual deve ser destruído por um clique de "voltar ao
        automático".
        """
        from datetime import datetime
        antiga = self.caminho_revisada(chave)
        if not antiga.exists():
            return
        lixo = self.cam.mascaras_revisadas / ".descartadas"
        lixo.mkdir(exist_ok=True)
        antiga.replace(lixo / f"{chave}_{datetime.now():%Y%m%d_%H%M%S}.png")

    def mapa_desvio(self, item: dict,
                    sigma_fundo: float | None = None) -> tuple[Path, int]:
        """PNG do mapa |flat−1| + o limiar global de Otsu nessa escala.

        O cache do protocolo (sigma 60) fica no nome limpo, e as outras escalas
        em arquivos com sufixo. Assim o mapa que o pincel mágico usa por padrão
        continua sendo exatamente o mesmo de antes, e as variações do revisor
        não se misturam com ele.
        """
        sigma = segmentacao.sigma_fundo_valido(
            SEG.sigma_flat if sigma_fundo is None else sigma_fundo)
        padrao = sigma == float(SEG.sigma_flat)
        nome = item["chave"] + ("" if padrao else f"_s{int(sigma)}")
        cache = self.cam.mapas_desvio / f"{nome}.png"
        if not cache.exists():
            d8, _ = segmentacao.desvio_8bits(
                segmentacao.carregar(item["caminho"]), None if padrao else sigma)
            buf = io.BytesIO()
            Image.fromarray(d8).save(buf, format="PNG")
            escrever_atomico(cache, buf.getvalue())
        from skimage import filters
        return cache, int(filters.threshold_otsu(np.asarray(Image.open(cache))))

    def desvio(self, item: dict) -> np.ndarray:
        """Mapa |flat−1| da imagem, em cache por item."""
        if "_desvio" not in item:
            item["_desvio"] = segmentacao.mapa_desvio(
                segmentacao.carregar(item["caminho"]))
        return item["_desvio"]

    def com_limiar(self, item: dict, deslocamento: int,
                   sigma_fundo: float | None = None) -> tuple[np.ndarray, int, int]:
        """Contorno do protocolo com o corte de Otsu deslocado, para o revisor.

        Lê o mapa de 8 bits do cache — o mesmo PNG que o navegador baixa —, de
        modo que o número do controle significa a mesma coisa nos dois lados.

        Devolve `(mascara_final, limiar_absoluto, otsu)`.
        """
        cache, otsu = self.mapa_desvio(item, sigma_fundo)
        d8 = np.asarray(Image.open(cache).convert("L"))
        res, limiar = segmentacao.analisar_limiar(d8, otsu, deslocamento)
        final = res.final if res.final is not None else np.zeros(d8.shape, bool)
        return final, limiar, otsu

    def medir(self, mascara: np.ndarray):
        """Mede uma máscara desenhada, com o MESMO pós-processamento das automáticas.

        Só depende do traço. Recebia também o `item` da fila, para o passe de
        satélites ir buscar o mapa de desvio da imagem; sem esse passe, nenhuma
        medida precisa mais da foto.
        """
        return medidas.descrever(segmentacao.pos_processar(mascara))

    # ------------------------------------------------------------------
    def escrever_csv_final(self) -> None:
        """medidas_final.csv = medidas automáticas + o que a revisão alterou."""
        from ..pipeline import calcular_area_norm
        df = pd.read_csv(self.cam.csv_medidas)
        df["chave"] = df.n_experimento + "_" + df.arquivo.str.replace(" ", "_", regex=False)
        df["revisado_em"] = ""
        for chave, e in self.repo.estado.items():
            idx = df.index[df.chave == chave]
            if not len(idx):
                continue
            i = idx[0]
            df.loc[i, "status"] = e["status"]
            df.loc[i, "revisado_em"] = e.get("quando", "")
            if e["status"] == "excluido":
                for c in (*medidas.COLUNAS, *medidas.COLUNAS_AUX, "area_norm_D0"):
                    if c in df.columns:
                        df.loc[i, c] = np.nan
            elif e.get("medidas"):
                # registros antigos podem trazer `feret_min_px`; traduz na leitura
                for k, v in medidas.normalizar_nomes(e["medidas"]).items():
                    if k in df.columns:
                        df.loc[i, k] = v
        df["area_norm_D0"] = calcular_area_norm(df)
        escrever_atomico(self.cam.csv_final,
                         df.drop(columns=["chave"])
                         .to_csv(index=False, float_format="%.4f").encode("utf-8-sig"))

    # ------------------------------------------------------------------
    def resultados(self, por_grupo: bool = False) -> dict:
        """Resumo do que já foi conferido à mão.

        Só entram linhas com status "manual": um contorno automático não
        conferido não é uma medida confiável, e é justamente isso que esta aba
        existe para não misturar.

        `area_norm_D0` exige que o D0 do MESMO esferoide também esteja conferido
        — normalizar por um D0 automático herdaria o erro dele, e o D0 é o dia
        com mais falha de segmentação.

        Com `por_grupo`, sai também o desenho fatorial 2x2 completo em `grupos4`:
        glicose (L/H) x tratamento (C/T). O agregado C vs T continua em `grupos`
        porque tem o dobro do n; os dois convivem porque respondem a perguntas
        diferentes — `grupos` mede o efeito principal do tratamento, `grupos4`
        mostra se esse efeito depende do nível de glicose (a interação), que é
        exatamente o que o agregado esconde.
        """
        linhas = []
        for it in self.itens:
            e = self.repo.estado.get(it["chave"], {})
            if e.get("status") != "manual" or not e.get("medidas"):
                continue
            m = medidas.normalizar_nomes(e["medidas"])
            grupo = it["grupo"]
            linhas.append({"dia": it["dia"], "grupo": grupo,
                           # C/T é a comparação que responde à pergunta de pesquisa;
                           # as duas glicoses entram agregadas neste resumo
                           "trat": grupo[-1] if grupo in GRUPOS else "?",
                           "uid": it["esferoide_uid"], **m})
        df = pd.DataFrame(linhas)

        total_por_dia = {}
        for it in self.itens:
            total_por_dia[it["dia"]] = total_por_dia.get(it["dia"], 0) + 1
        base = {
            "n_conferidas": len(df),
            "n_total": len(self.itens),
            "por_dia": {int(d): {"conferidas": int((df.dia == d).sum()) if len(df) else 0,
                                 "total": int(n)}
                        for d, n in sorted(total_por_dia.items())},
            "series": [], "grupos": None, "grupos4": None,
            "n_series_completas": 0,
        }
        if df.empty:
            return base

        # normalização só onde o D0 do mesmo esferoide também foi conferido
        d0 = df[df.dia == 0].set_index("uid")["area_px"].to_dict()
        df["area_norm_D0"] = [
            (r.area_px / d0[r.uid]) if r.uid in d0 else None for r in df.itertuples()]
        dias = set(total_por_dia)
        completas = {u for u, serie in df.groupby("uid") if set(serie.dia) == dias}
        base["n_series_completas"] = len(completas)

        metricas = ["area_norm_D0", "diam_equiv_px", "circularidade", "solidity",
                    "circularidade_sem_suavizar"]

        def resumir(sub):
            saida = {}
            for met in metricas:
                if met not in sub:
                    continue
                v = pd.to_numeric(sub[met], errors="coerce").dropna()
                saida[met] = {"n": int(len(v)),
                              "mediana": float(v.median()) if len(v) else None,
                              "q1": float(v.quantile(.25)) if len(v) else None,
                              "q3": float(v.quantile(.75)) if len(v) else None}
            return saida

        base["series"] = [{"dia": int(d), **resumir(g)}
                          for d, g in df.groupby("dia")]
        if por_grupo:
            base["grupos"] = [
                {"dia": int(d), "trat": str(t), **resumir(g)}
                for (d, t), g in df[df.trat.isin(["C", "T"])].groupby(["dia", "trat"])]
            base["grupos4"] = [
                {"dia": int(d), "grupo": str(gr), **resumir(g)}
                for (d, gr), g in df[df.grupo.isin(GRUPOS)].groupby(["dia", "grupo"])]
        return base

    def aquecer_cache(self, com_desvio: bool = True) -> None:
        """Pré-gera máscaras e mapas: sem isso cada imagem demora ~1 s ao abrir."""
        for n, it in enumerate(self.itens, 1):
            try:
                self.mascara(it)
                if com_desvio:
                    self.mapa_desvio(it)
            except Exception:                                    # noqa: BLE001
                pass
            if n % 25 == 0:
                print(f"  cache: {n}/{len(self.itens)}", flush=True)
        print("  cache de máscaras pronto", flush=True)
