"""Versioned SQLite persistence. Every connection enforces foreign keys."""
from contextlib import contextmanager
import os
import sqlite3


@contextmanager
def database():
    db = sqlite3.connect(os.environ['SQLITE_PATH'], timeout=2)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize():
    with database() as db:
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, 1):
            raise RuntimeError('Unsupported database schema')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS identities (
          id TEXT PRIMARY KEY, issuer TEXT NOT NULL, subject TEXT NOT NULL,
          username TEXT NOT NULL, UNIQUE(issuer,subject));
        CREATE TABLE IF NOT EXISTS login_transactions (
          id_hash TEXT PRIMARY KEY, state TEXT NOT NULL, nonce TEXT NOT NULL,
          verifier TEXT NOT NULL, expires_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (
          id_hash TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES identities(id),
          csrf TEXT NOT NULL, expires_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS documents (
          id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES identities(id),
          filename TEXT NOT NULL, sha256 TEXT NOT NULL, byte_length INTEGER NOT NULL,
          state TEXT NOT NULL CHECK(state IN ('processing','ready','failed')),
          error_code TEXT, object_key TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS documents_owner ON documents(owner_id);
        CREATE INDEX IF NOT EXISTS documents_owner_created_id ON documents(owner_id,created_at DESC,id DESC);
        CREATE TABLE IF NOT EXISTS extractions (
          document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
          normalized TEXT NOT NULL, raw TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS fields (
          id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
          name TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(document_id,id), UNIQUE(document_id,name));
        CREATE TABLE IF NOT EXISTS entities (
          id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
          kind TEXT NOT NULL, UNIQUE(document_id,id));
        CREATE TABLE IF NOT EXISTS relationships (
          id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
          kind TEXT NOT NULL, source_id TEXT NOT NULL, target_id TEXT NOT NULL,
          UNIQUE(document_id,id),
          FOREIGN KEY(document_id,source_id) REFERENCES entities(document_id,id),
          FOREIGN KEY(document_id,target_id) REFERENCES entities(document_id,id));
        CREATE TABLE IF NOT EXISTS entity_evidence (
          document_id TEXT NOT NULL, entity_id TEXT NOT NULL, attribute TEXT NOT NULL, field_id TEXT NOT NULL,
          PRIMARY KEY(entity_id,attribute),
          FOREIGN KEY(document_id,entity_id) REFERENCES entities(document_id,id),
          FOREIGN KEY(document_id,field_id) REFERENCES fields(document_id,id));
        CREATE TABLE IF NOT EXISTS relationship_evidence (
          document_id TEXT NOT NULL, relationship_id TEXT NOT NULL, field_id TEXT NOT NULL,
          PRIMARY KEY(relationship_id,field_id),
          FOREIGN KEY(document_id,relationship_id) REFERENCES relationships(document_id,id),
          FOREIGN KEY(document_id,field_id) REFERENCES fields(document_id,id));
        PRAGMA user_version=1;
        ''')
