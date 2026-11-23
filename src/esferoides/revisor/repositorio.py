"""Persistência das decisões de conferência.

Três camadas independentes, em ordem de autoridade:

1. **SQLite** (`revisao.db`, WAL + ``synchronous=FULL``) — cada decisão é uma
   transação: grava inteira ou não grava. A tabela ``historico`` é só-append e
   guarda todas as versões, então nem uma sobrescrita acidental destrói nada.
2. **Diário** (`revisao_journal.jsonl`) — só-append, fora do banco. Nunca é
   reescrito; sobrevive à perda total do ``.db``.
3. **Máscaras** (`mascaras_revisadas/*.png`) — o trabalho de verdade. Todas as
   medidas são deriváveis delas, e é isso que torna a reconstrução possível.

Os arquivos derivados são escritos de forma atômica (``.tmp`` → ``fsync`` →
``os.replace``), porque reescrever um arquivo inteiro a cada clique deixa uma
janela em que uma queda o trunca — e aí se perde tudo de uma vez.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS revisao(
  chave   TEXT PRIMARY KEY,
  status  TEXT NOT NULL,
  medidas TEXT,
  quando  TEXT NOT NULL,
  nota    TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS historico(
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  chave   TEXT NOT NULL,
  status  TEXT NOT NULL,
  medidas TEXT,
  quando  TEXT NOT NULL,
  nota    TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS ix_hist_chave ON historico(chave);
"""

MAX_BACKUPS = 20


def agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def escrever_atomico(caminho: Path, dados: bytes | str) -> None:
    """Grava em .tmp, força para o disco e troca. Nunca deixa arquivo pela metade.

    ``os.replace`` é atômico também no Windows (MoveFileEx com REPLACE_EXISTING).
    """
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(caminho.name + ".tmp")
    binario = isinstance(dados, (bytes, bytearray))
    modo, kwargs = ("wb", {}) if binario else ("w", {"encoding": "utf-8"})
    with open(tmp, modo, **kwargs) as f:
        f.write(dados)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, caminho)


class Repositorio:
    def __init__(self, banco: Path, diario: Path, estado_json: Path,
                 backups: Path | None = None):
        self.banco, self.diario, self.estado_json = banco, diario, estado_json
        self.backups = backups
        self._trava = threading.Lock()
        self.estado: dict[str, dict] = {}
        novo = not banco.exists()
        banco.parent.mkdir(parents=True, exist_ok=True)
        self.cx = sqlite3.connect(banco, timeout=20, check_same_thread=False)
        self.cx.execute("PRAGMA journal_mode=WAL")     # sobrevive a queda no meio
        self.cx.execute("PRAGMA synchronous=FULL")     # confirma no disco antes de responder
        self.cx.executescript(ESQUEMA)
        self.cx.commit()
        if not novo:
            self._fazer_backup()
        self._carregar()

    # ------------------------------------------------------------------
    def _fazer_backup(self) -> Path | None:
        """Backup pela API do sqlite: copiar o .db solto perderia o -wal."""
        if not self.backups:
            return None
        if not self.cx.execute("SELECT count(*) FROM revisao").fetchone()[0]:
            return None
        self.backups.mkdir(parents=True, exist_ok=True)
        destino = self.backups / f"revisao_{datetime.now():%Y%m%d_%H%M%S}.db"
        with sqlite3.connect(destino) as d:
            self.cx.backup(d)
        for antigo in sorted(self.backups.glob("revisao_*.db"))[:-MAX_BACKUPS]:
            antigo.unlink()
        return destino

    def _carregar(self) -> None:
        linhas = self.cx.execute(
            "SELECT chave,status,medidas,quando,nota FROM revisao").fetchall()
        for chave, status, med, quando, nota in linhas:
            self.estado[chave] = {"status": status, "quando": quando,
                                  "nota": nota or "",
                                  "medidas": json.loads(med) if med else None}
        # migração do formato antigo (revisao.json solto)
        if not linhas and self.estado_json.exists():
            antigo = json.loads(self.estado_json.read_text(encoding="utf-8") or "{}")
            for chave, reg in antigo.items():
                reg.setdefault("quando", agora())
                reg.setdefault("nota", "")
                self.estado[chave] = reg
                self.gravar(chave, reg)
            if antigo:
                print(f"  migradas {len(antigo)} revisões do formato antigo")

    def _exportar_json(self) -> None:
        escrever_atomico(self.estado_json,
                         json.dumps(self.estado, ensure_ascii=False, indent=1))

    def _anexar_diario(self, registro: dict) -> None:
        with open(self.diario, "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

    # ------------------------------------------------------------------
    def gravar(self, chave: str, registro: dict) -> None:
        """Uma decisão = uma transação no banco + uma linha no diário."""
        med = json.dumps(registro.get("medidas"), ensure_ascii=False) \
            if registro.get("medidas") else None
        dados = (chave, registro["status"], med,
                 registro.get("quando") or agora(), registro.get("nota", ""))
        with self._trava, self.cx:
            self.cx.execute(
                "INSERT INTO revisao(chave,status,medidas,quando,nota) VALUES(?,?,?,?,?) "
                "ON CONFLICT(chave) DO UPDATE SET status=excluded.status,"
                "medidas=excluded.medidas,quando=excluded.quando,nota=excluded.nota",
                dados)
            self.cx.execute(
                "INSERT INTO historico(chave,status,medidas,quando,nota) VALUES(?,?,?,?,?)",
                dados)
        self.estado[chave] = registro
        self._anexar_diario({"chave": chave, **registro})
        self._exportar_json()

    def remover(self, chave: str) -> None:
        with self._trava, self.cx:
            self.cx.execute("DELETE FROM revisao WHERE chave=?", (chave,))
            self.cx.execute(
                "INSERT INTO historico(chave,status,medidas,quando,nota) "
                "VALUES(?,?,?,?,?)", (chave, "revertido", None, agora(), ""))
        self.estado.pop(chave, None)
        self._anexar_diario({"chave": chave, "status": "revertido", "quando": agora()})
        self._exportar_json()

    def fechar(self) -> None:
        self.cx.close()

    def __enter__(self) -> "Repositorio":
        return self

    def __exit__(self, *_) -> None:
        self.fechar()

    def historico(self, chave: str) -> list[dict]:
        return [{"status": s, "quando": q, "nota": n}
                for s, q, n in self.cx.execute(
                    "SELECT status,quando,nota FROM historico WHERE chave=? "
                    "ORDER BY id", (chave,))]

    # ------------------------------------------------------------------
    def reconstruir(self, mascaras: Path, medir) -> int:
        """Refaz o banco a partir do diário + das máscaras em disco.

        O status vem da última linha do diário; as medidas são **recalculadas**
        das máscaras, não copiadas do diário, de modo que o resultado é sempre
        coerente com o PNG que está lá.
        """
        import numpy as np
        from PIL import Image

        estados: dict[str, dict] = {}
        if self.diario.exists():
            for linha in self.diario.read_text(encoding="utf-8").splitlines():
                if not linha.strip():
                    continue
                try:
                    r = json.loads(linha)
                except json.JSONDecodeError:
                    continue                      # linha truncada por queda
                if r.get("status") == "revertido":
                    estados.pop(r["chave"], None)
                else:
                    estados[r["chave"]] = r
        for png in mascaras.glob("*.png"):        # máscaras sem entrada no diário
            estados.setdefault(png.stem, {
                "status": "manual", "nota": "recuperada da máscara",
                "quando": datetime.fromtimestamp(png.stat().st_mtime)
                .isoformat(timespec="seconds")})

        self.estado.clear()
        for chave, r in estados.items():
            med = None
            arquivo = mascaras / f"{chave}.png"
            if r["status"] != "excluido" and arquivo.exists():
                med = medir(np.asarray(Image.open(arquivo).convert("L")) > 127, chave)
            self.gravar(chave, {"status": r["status"], "medidas": med,
                                "quando": r.get("quando", agora()),
                                "nota": r.get("nota", "")})
        return len(estados)
