"""Banco próprio da validação, com revisões imutáveis e fechamento transacional."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime

from .validacao_amostra import TOTAL, png_mascara

AVALIADORA = "Avaliadora"
ESTADOS_FINAIS = ("concluida", "nao_avaliavel")
ESQUEMA = """
CREATE TABLE IF NOT EXISTS sessao (
    id INTEGER PRIMARY KEY CHECK (id = 1), selecao TEXT NOT NULL,
    criada TEXT NOT NULL, encerrada TEXT
);
CREATE TABLE IF NOT EXISTS imagens (
    codigo TEXT PRIMARY KEY, ordem INTEGER UNIQUE NOT NULL, foto BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS reservado (
    codigo TEXT PRIMARY KEY REFERENCES imagens(codigo),
    origem TEXT NOT NULL, oficial BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS anotacoes (
    versao INTEGER PRIMARY KEY AUTOINCREMENT, codigo TEXT NOT NULL REFERENCES imagens(codigo),
    avaliadora TEXT NOT NULL, status TEXT NOT NULL, quando TEXT NOT NULL, conclusao TEXT,
    nota TEXT NOT NULL, motivo TEXT NOT NULL, ambigua INTEGER NOT NULL,
    externa BLOB NOT NULL, interna BLOB NOT NULL, segmentada BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_anotacoes_codigo ON anotacoes(codigo, versao);
CREATE VIEW IF NOT EXISTS atuais AS
    SELECT a.* FROM anotacoes a
    WHERE a.versao = (SELECT max(b.versao) FROM anotacoes b WHERE b.codigo = a.codigo);
CREATE TABLE IF NOT EXISTS finais (
    codigo TEXT PRIMARY KEY REFERENCES imagens(codigo),
    versao INTEGER UNIQUE NOT NULL REFERENCES anotacoes(versao)
);
"""


def agora():
    return datetime.now(UTC).isoformat(timespec="seconds")


class Conflito(ValueError):
    pass


class BancoValidacao:
    def __init__(self, caminho):
        self.caminho = caminho
        caminho.parent.mkdir(parents=True, exist_ok=True)
        with self.conectar() as db:
            db.executescript(ESQUEMA)

    @contextmanager
    def conectar(self):
        db = sqlite3.connect(self.caminho, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys = ON")
            with db:
                yield db
        finally:
            db.close()

    def preparar(self, amostra, registro):
        if len(amostra) != TOTAL:
            raise ValueError(f"São necessárias {TOTAL} imagens.")
        with self.conectar() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM sessao").fetchone():
                raise Conflito("A sessão já foi preparada.")
            db.execute("INSERT INTO sessao VALUES (1, ?, ?, NULL)",
                       (json.dumps(registro, ensure_ascii=False), agora()))
            for ordem, (codigo, origem, foto, oficial) in enumerate(amostra):
                db.execute("INSERT INTO imagens VALUES (?, ?, ?)", (codigo, ordem, foto))
                db.execute("INSERT INTO reservado VALUES (?, ?, ?)",
                           (codigo, json.dumps(origem, ensure_ascii=False), oficial))

    def fila(self):
        with self.conectar() as db:
            db.execute("BEGIN")
            sessao = db.execute("SELECT criada, encerrada FROM sessao").fetchone()
            fila = db.execute("""SELECT i.codigo, coalesce(a.status, 'pendente') AS status
                                 FROM imagens i LEFT JOIN atuais a USING(codigo)
                                 ORDER BY i.ordem""").fetchall()
        return dict(sessao) if sessao else None, [dict(r) for r in fila]

    def foto(self, codigo):
        with self.conectar() as db:
            return db.execute("SELECT foto FROM imagens WHERE codigo = ?", (codigo,)).fetchone()

    def anotacao(self, codigo):
        with self.conectar() as db:
            return db.execute("""SELECT i.codigo, a.status, a.versao, a.nota, a.motivo, a.ambigua,
                                        a.externa, a.interna, a.quando, a.conclusao
                                 FROM imagens i LEFT JOIN atuais a USING(codigo)
                                 WHERE i.codigo = ?""", (codigo,)).fetchone()

    def anotacao_versao(self, codigo, versao):
        with self.conectar() as db:
            return db.execute("""SELECT externa, interna FROM anotacoes
                                 WHERE codigo = ? AND versao = ?""", (codigo, versao)).fetchone()

    def salvar(self, codigo, versao, status, nota, motivo, ambigua, externa, interna):
        segmentada = externa & ~interna
        if status == "concluida" and not segmentada.any():
            raise ValueError("Desenhe uma silhueta com área de agregado antes de concluir.")
        mascaras = [png_mascara(m) for m in (externa, interna, segmentada)]
        with self.conectar() as db:
            db.execute("BEGIN IMMEDIATE")
            sessao = db.execute("SELECT encerrada FROM sessao").fetchone()
            if not sessao or sessao["encerrada"]:
                raise Conflito("A sessão está fechada para edição.")
            atual = db.execute("SELECT versao FROM atuais WHERE codigo = ?", (codigo,)).fetchone()
            if versao != (atual["versao"] if atual else None):
                raise Conflito("Há uma versão mais recente. Reabra a imagem antes de salvar.")
            quando = agora()
            conclusao = quando if status in ESTADOS_FINAIS else None
            cursor = db.execute("""INSERT INTO anotacoes
                (codigo, avaliadora, status, quando, conclusao, nota, motivo, ambigua,
                 externa, interna, segmentada) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (codigo, AVALIADORA, status, quando, conclusao, nota, motivo, ambigua, *mascaras))
            return cursor.lastrowid

    def encerrar(self):
        with self.conectar() as db:
            db.execute("BEGIN IMMEDIATE")
            sessao = db.execute("SELECT encerrada FROM sessao").fetchone()
            if not sessao or sessao["encerrada"]:
                raise Conflito("A sessão precisa estar aberta.")
            cursor = db.execute("""INSERT INTO finais SELECT codigo, versao FROM atuais
                                   WHERE status = 'concluida'
                                      OR (status = 'nao_avaliavel' AND trim(motivo) <> '')""")
            if cursor.rowcount != TOTAL:
                raise Conflito(f"Conclua ou justifique todas as {TOTAL} imagens.")
            db.execute("UPDATE sessao SET encerrada = ?", (agora(),))

    def fotos_anonimas(self):
        with self.conectar() as db:
            return db.execute("SELECT codigo, foto FROM imagens ORDER BY ordem").fetchall()

    def finais(self):
        with self.conectar() as db:
            db.execute("BEGIN")
            sessao = db.execute("SELECT * FROM sessao WHERE encerrada IS NOT NULL").fetchone()
            if not sessao:
                raise Conflito("Encerre a sessão para liberar os resultados.")
            linhas = db.execute("""SELECT a.*, r.origem, r.oficial FROM finais f
                JOIN imagens i USING(codigo) JOIN reservado r USING(codigo)
                JOIN anotacoes a ON a.versao = f.versao ORDER BY i.ordem""").fetchall()
            revisoes = db.execute("""SELECT versao, codigo, avaliadora, status, quando, conclusao,
                                             nota, motivo, ambigua
                                      FROM anotacoes ORDER BY versao""").fetchall()
        return dict(sessao), linhas, revisoes
