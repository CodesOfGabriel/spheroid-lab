"""Parâmetros e caminhos.

Os valores de `Segmentacao` são os do protocolo e **não devem ser ajustados por
imagem** — ajustar parâmetro até o contorno ficar bonito destrói a objetividade
da medida. Eles estão reunidos aqui justamente para que qualquer mudança seja
visível numa linha do diff.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
#  Segmentação — validado contra a tabela de referência do protocolo.
#  Ver tests/test_referencia.py: mudar qualquer valor aqui quebra o teste.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Segmentacao:
    sigma_flat: float = 60      # gaussiano do fundo, para o flat-field
    sigma_desvio: float = 3     # suavização de |flat - 1|
    area_min: int = 15_000      # px, remoção de objetos pequenos
    raio_abertura: int = 8      # raio do disco da abertura morfológica
    sigma_contorno: float = 6   # suavização do contorno final


SEG = Segmentacao()

# --------------------------------------------------------------------------
#  Triagem visual. NÃO alteram nenhuma medida — decidem só o que entra na fila
#  de conferência.
#
#  No D0 as células acabaram de ser plaqueadas: ainda não aderiram nem
#  compactaram, então um agregado frouxo e irregular é o resultado biológico
#  esperado, não um erro de contorno. Por isso o limiar de solidez do D0 é bem
#  mais permissivo — e a circularidade pesa mais que a solidez, porque nas
#  falhas conferidas visualmente (contorno em crescente) a solidez cai de forma
#  contínua junto com os agregados legitimamente frouxos, enquanto a
#  circularidade separa os dois grupos com folga.
# --------------------------------------------------------------------------
LIMIAR_SOLIDITY = {0: 0.70, 1: 0.85, 2: 0.85, 3: 0.85}
LIMIAR_CIRC = {0: 0.30, 1: 0.35, 2: 0.35, 3: 0.35}

# Faixas esperadas de diâmetro equivalente (px), usadas só nas checagens.
FAIXA_DEQ = {0: (700, 900), 1: (330, 450), 2: (330, 450), 3: (330, 450)}

# Monotonicidade esperada da série
QUEDA_MAX_D1 = 0.75   # area_norm_D0 no D1 deve cair abaixo disto
SUBIDA_TOL = 0.20     # aumento relativo tolerado entre dias >= D1

# Semente do embaralhamento do cegamento. Fixa para o código de cada imagem
# não mudar entre sessões.
SEMENTE_CEGAMENTO = 20260902

GRUPOS = ("LC", "LT", "HC", "HT")


# --------------------------------------------------------------------------
#  Caminhos. A raiz dos dados fica FORA do repositório: são centenas de MB de
#  PNG que não devem entrar no git. Aponte com a variável de ambiente
#  ESFEROIDES_DADOS ou com --dados na linha de comando.
# --------------------------------------------------------------------------
VAR_AMBIENTE = "ESFEROIDES_DADOS"


@dataclass
class Caminhos:
    raiz: Path
    saida: Path = field(init=False)

    def __post_init__(self):
        self.raiz = Path(self.raiz).expanduser().resolve()
        self.saida = self.raiz / "_analise"

    # --- entradas -------------------------------------------------------
    def pasta_dia(self, n_experimento: str, dia: int) -> Path:
        return self.raiz / n_experimento / f"d{dia}"

    # --- saídas ---------------------------------------------------------
    @property
    def resultados(self) -> Path:
        return self.saida / "resultados"

    @property
    def conferencia(self) -> Path:
        return self.saida / "conferencia"

    @property
    def folhas_contato(self) -> Path:
        return self.saida / "folhas_contato"

    @property
    def figuras(self) -> Path:
        return self.saida / "figuras"

    @property
    def mascaras_auto(self) -> Path:
        return self.saida / "mascaras_auto"

    @property
    def mascaras_revisadas(self) -> Path:
        return self.saida / "mascaras_revisadas"

    @property
    def mapas_desvio(self) -> Path:
        return self.saida / "mapas_desvio"

    @property
    def backups(self) -> Path:
        return self.resultados / "backups"

    # --- arquivos -------------------------------------------------------
    @property
    def csv_medidas(self) -> Path:
        return self.resultados / "medidas_esferoides.csv"

    @property
    def csv_final(self) -> Path:
        return self.resultados / "medidas_final.csv"

    @property
    def csv_revisar(self) -> Path:
        return self.resultados / "imagens_para_revisar.csv"

    @property
    def csv_resumo(self) -> Path:
        return self.resultados / "resumo_por_grupo.csv"

    @property
    def csv_cegamento(self) -> Path:
        return self.resultados / "cegamento.csv"

    @property
    def banco(self) -> Path:
        return self.resultados / "revisao.db"

    @property
    def diario(self) -> Path:
        return self.resultados / "revisao_journal.jsonl"

    @property
    def estado_json(self) -> Path:
        return self.resultados / "revisao.json"

    @property
    def relatorio(self) -> Path:
        return self.resultados / "verificacao.txt"

    def criar_pastas(self) -> "Caminhos":
        for p in (self.resultados, self.conferencia, self.folhas_contato,
                  self.figuras, self.mascaras_auto, self.mascaras_revisadas,
                  self.mapas_desvio, self.backups):
            p.mkdir(parents=True, exist_ok=True)
        return self


def caminhos(raiz: str | Path | None = None) -> Caminhos:
    """Resolve a raiz dos dados: argumento > variável de ambiente > erro."""
    escolhida = raiz or os.environ.get(VAR_AMBIENTE)
    if not escolhida:
        raise SystemExit(
            "Não sei onde estão as imagens.\n"
            f"  Defina a variável {VAR_AMBIENTE} ou passe --dados CAMINHO.\n"
            "  Ex.: $env:ESFEROIDES_DADOS = '../meu-experimento'")
    p = Path(escolhida).expanduser()
    if not p.is_dir():
        raise SystemExit(f"Pasta de dados não encontrada: {p}")
    return Caminhos(p)
