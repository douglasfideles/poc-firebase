"""Banco da prova de conceito: SQLite da biblioteca padrão.

`usuarios` espelha o `User` do app (`app/backend/db/models.py`). A diferença que importa é a
tabela `identidades`: a chave de quem entra é (provedor, sujeito), não o e-mail. Um e-mail só
liga um login novo a uma pessoa que já existe quando o login provou esse e-mail.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from .regras import ATIVO, Decisao, ProvaLogin

ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE,             -- só e-mail provado pelo login
    email_informado TEXT,          -- o que o provedor afirmou, sem valor de prova
    nome TEXT NOT NULL DEFAULT '',
    instituicao TEXT,
    papel TEXT NOT NULL DEFAULT 'USER',
    estado TEXT NOT NULL,          -- ativo | pendente | recusado
    is_active INTEGER NOT NULL DEFAULT 1,
    ultimo_login TEXT
);
CREATE TABLE IF NOT EXISTS identidades (
    provedor TEXT NOT NULL,
    sujeito TEXT NOT NULL,
    firebase_uid TEXT NOT NULL UNIQUE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    PRIMARY KEY (provedor, sujeito)
);
CREATE TABLE IF NOT EXISTS ponte_usada (
    hash TEXT PRIMARY KEY,
    expira REAL NOT NULL
);
"""


@dataclass(frozen=True)
class Usuario:
    id: int
    email: str | None
    nome: str
    instituicao: str | None
    papel: str
    estado: str
    is_active: bool


class Repositorio:
    def __init__(self, caminho: str) -> None:
        self._db = sqlite3.connect(caminho, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._trava = threading.Lock()
        # WAL: uma gravação por login não espera o disco sincronizar a cada passo.
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(ESQUEMA)

    @staticmethod
    def _usuario(l: sqlite3.Row | None) -> Usuario | None:
        if l is None:
            return None
        return Usuario(l["id"], l["email"], l["nome"], l["instituicao"], l["papel"], l["estado"],
                       bool(l["is_active"]))

    def por_firebase_uid(self, uid: str) -> Usuario | None:
        with self._trava:
            l = self._db.execute(
                "SELECT u.* FROM usuarios u JOIN identidades i ON i.usuario_id = u.id "
                "WHERE i.firebase_uid = ?", (uid,)).fetchone()
        return self._usuario(l)

    def upsert(self, prova: ProvaLogin, decisao: Decisao, firebase_uid: str) -> Usuario:
        """Acha a pessoa pela identidade; se não há, liga por e-mail provado; senão cria."""
        agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._trava:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                l = self._db.execute(
                    "SELECT u.* FROM usuarios u JOIN identidades i ON i.usuario_id = u.id "
                    "WHERE i.provedor = ? AND i.sujeito = ?",
                    (prova.provedor, prova.sujeito)).fetchone()

                if l is None and decisao.email_provado:
                    # Mesma pessoa, outro provedor: só com e-mail provado e na mesma instituição.
                    l = self._db.execute(
                        "SELECT * FROM usuarios WHERE email = ? AND instituicao = ?",
                        (decisao.email_provado, decisao.inst)).fetchone()
                    if l is not None:
                        self._db.execute(
                            "INSERT INTO identidades (provedor, sujeito, firebase_uid, usuario_id) "
                            "VALUES (?, ?, ?, ?)",
                            (prova.provedor, prova.sujeito, firebase_uid, l["id"]))

                if l is None:
                    email = decisao.email_provado
                    if email and self._db.execute(
                            "SELECT 1 FROM usuarios WHERE email = ?", (email,)).fetchone():
                        email = None  # já é de outra pessoa, em outra instituição
                    cur = self._db.execute(
                        "INSERT INTO usuarios (email, email_informado, nome, instituicao, estado, "
                        "ultimo_login) VALUES (?, ?, ?, ?, ?, ?)",
                        (email, prova.email, prova.nome, decisao.inst, decisao.estado, agora))
                    self._db.execute(
                        "INSERT INTO identidades (provedor, sujeito, firebase_uid, usuario_id) "
                        "VALUES (?, ?, ?, ?)",
                        (prova.provedor, prova.sujeito, firebase_uid, cur.lastrowid))
                    uid_usuario = cur.lastrowid
                else:
                    uid_usuario = l["id"]
                    # Quem estava pendente e agora prova que é da instituição passa a ativo.
                    # Quem foi recusado ou desativado não volta sozinho por este caminho.
                    if l["estado"] == "pendente" and decisao.estado == ATIVO:
                        self._db.execute(
                            "UPDATE usuarios SET estado = ?, instituicao = ? WHERE id = ?",
                            (ATIVO, decisao.inst, uid_usuario))
                    self._db.execute(
                        "UPDATE usuarios SET nome = CASE WHEN ? <> '' THEN ? ELSE nome END, "
                        "ultimo_login = ? WHERE id = ?",
                        (prova.nome, prova.nome, agora, uid_usuario))
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
            l = self._db.execute("SELECT * FROM usuarios WHERE id = ?", (uid_usuario,)).fetchone()
        return self._usuario(l)  # type: ignore[return-value]

    def registrar_ponte(self, hash_token: str, expira: float) -> bool:
        """Marca o token de ponte da CAFe como usado. False se ele já tinha sido usado."""
        with self._trava:
            self._db.execute("DELETE FROM ponte_usada WHERE expira < ?", (time.time(),))
            try:
                self._db.execute("INSERT INTO ponte_usada (hash, expira) VALUES (?, ?)",
                                 (hash_token, expira))
                return True
            except sqlite3.IntegrityError:
                return False

    def desativar(self, usuario_id: int) -> None:
        with self._trava:
            self._db.execute("UPDATE usuarios SET is_active = 0 WHERE id = ?", (usuario_id,))

    def uids_custom(self) -> list[str]:
        """Contas do Firebase que o backend criou (LDAP, CAFe e login único)."""
        with self._trava:
            return [l["firebase_uid"] for l in self._db.execute(
                "SELECT firebase_uid FROM identidades WHERE provedor IN ('ldap', 'cafe', 'oidc')")]

    def limpar(self) -> None:
        """Só para os testes."""
        with self._trava:
            self._db.execute("BEGIN")
            for t in ("identidades", "usuarios", "ponte_usada"):
                self._db.execute(f"DELETE FROM {t}")
            self._db.execute("COMMIT")
