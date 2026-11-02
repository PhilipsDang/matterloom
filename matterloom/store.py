"""SQLite metadata and immutable originals, scoped to each matter."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import parsing

MAX_FILE_BYTES = 20 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "originals").mkdir(exist_ok=True)
        self.db_path = self.root / "matterloom.sqlite3"
        with self.db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS matters (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                    sample_key TEXT UNIQUE, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, matter_id TEXT NOT NULL REFERENCES matters(id),
                    name TEXT NOT NULL, kind TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL,
                    status TEXT NOT NULL, page_count INTEGER, parser TEXT, warnings TEXT NOT NULL DEFAULT '[]',
                    error TEXT, created_at TEXT NOT NULL, parsed_at TEXT,
                    UNIQUE(matter_id, sha256));
                CREATE TABLE IF NOT EXISTS units (
                    id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
                    sequence INTEGER NOT NULL, page_number INTEGER, locator TEXT NOT NULL,
                    text TEXT NOT NULL, method TEXT NOT NULL, status TEXT NOT NULL, note TEXT NOT NULL,
                    ocr_lines TEXT NOT NULL DEFAULT '[]', UNIQUE(document_id, sequence));
            """)

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create_matter(self, name, description="", sample_key=None):
        name = str(name).strip()
        if not name or len(name) > 100:
            raise ValueError("事项名称需为 1–100 个字符。")
        if len(description) > 1000:
            raise ValueError("事项说明最多 1000 个字符。")
        with self.db() as db:
            if sample_key:
                existing = db.execute("SELECT id FROM matters WHERE sample_key=?", (sample_key,)).fetchone()
                if existing:
                    return existing["id"]
            matter_id = uuid.uuid4().hex
            db.execute("INSERT INTO matters VALUES (?,?,?,?,?)", (matter_id, name, description, sample_key, now()))
        return matter_id

    def matters(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("""SELECT m.*, COUNT(d.id) AS document_count,
                COALESCE(SUM(d.page_count),0) AS page_count,
                SUM(CASE WHEN d.status='ready' THEN 1 ELSE 0 END) AS ready_count
                FROM matters m LEFT JOIN documents d ON d.matter_id=m.id GROUP BY m.id
                ORDER BY m.created_at DESC""")]

    def matter(self, matter_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM matters WHERE id=?", (matter_id,)).fetchone()
        if not row:
            raise LookupError("事项不存在。")
        return dict(row)

    def documents(self, matter_id):
        self.matter(matter_id)
        with self.db() as db:
            rows = db.execute("SELECT * FROM documents WHERE matter_id=? ORDER BY name, created_at", (matter_id,)).fetchall()
        return [self.decode_document(row) for row in rows]

    @staticmethod
    def decode_document(row):
        result = dict(row)
        result["warnings"] = json.loads(result["warnings"])
        return result

    def document(self, matter_id, document_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM documents WHERE id=? AND matter_id=?", (document_id, matter_id)).fetchone()
        if not row:
            raise LookupError("当前事项中没有这份文件。")
        return self.decode_document(row)

    def original(self, document):
        return self.root / "originals" / f"{document['id']}.{document['kind']}"

    def ingest(self, matter_id, name, content, use_ocr=True):
        self.matter(matter_id)
        name = Path(str(name).replace("\\", "/")).name.strip()
        if not name or len(name) > 240:
            raise ValueError("文件名为空或过长。")
        kind = Path(name).suffix.lower().lstrip(".")
        if kind not in {"pdf", "docx"}:
            raise ValueError("目前支持 PDF 和 DOCX 文件。")
        if not content or len(content) > MAX_FILE_BYTES:
            raise ValueError("请上传非空且不超过 20 MB 的文件。")
        digest = hashlib.sha256(content).hexdigest()
        doc_id = uuid.uuid4().hex
        path = self.root / "originals" / f"{doc_id}.{kind}"
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM documents WHERE matter_id=? AND sha256=?", (matter_id, digest)).fetchone()
            if existing:
                return {"document": self.decode_document(existing), "duplicate": True}
            path.write_bytes(content)
            try:
                db.execute("""INSERT INTO documents
                    (id,matter_id,name,kind,sha256,bytes,status,created_at)
                    VALUES (?,?,?,?,?,?,?,?)""", (doc_id, matter_id, name, kind, digest, len(content), "pending", now()))
            except Exception:
                path.unlink(missing_ok=True)
                raise
        return {"document": self.reparse(matter_id, doc_id, use_ocr), "duplicate": False}

    def reparse(self, matter_id, document_id, use_ocr=True):
        document = self.document(matter_id, document_id)
        with self.db() as db:
            changed = db.execute("UPDATE documents SET status='parsing', error=NULL WHERE id=? AND status!='parsing'", (document_id,)).rowcount
        if not changed:
            raise ValueError("文件正在解析，请稍后刷新。")
        try:
            result = parsing.parse(self.original(document), document["kind"], use_ocr)
            with self.db() as db:
                db.execute("DELETE FROM units WHERE document_id=?", (document_id,))
                for unit in result["units"]:
                    # Stable source identifiers when the same original is reprocessed.
                    unit_id = f"{document_id}:{unit['sequence']}"
                    db.execute("INSERT INTO units VALUES (?,?,?,?,?,?,?,?,?,?)", (
                        unit_id, document_id, unit["sequence"], unit["page_number"], unit["locator"],
                        unit["text"], unit["method"], unit["status"], unit["note"], json.dumps(unit["ocr_lines"], ensure_ascii=False)))
                db.execute("""UPDATE documents SET status=?,page_count=?,parser=?,warnings=?,parsed_at=?,error=NULL
                    WHERE id=?""", (result["status"], result["page_count"], result["parser"], json.dumps(result["warnings"], ensure_ascii=False), now(), document_id))
        except Exception as exc:
            message = str(exc) if isinstance(exc, ValueError) else "无法解析这份文件。请确认文件未损坏，且后缀与实际格式一致。"
            with self.db() as db:
                db.execute("DELETE FROM units WHERE document_id=?", (document_id,))
                db.execute("UPDATE documents SET status='failed',error=?,page_count=NULL,warnings='[]',parsed_at=? WHERE id=?", (message, now(), document_id))
        return self.document(matter_id, document_id)

    def recover_interrupted(self):
        with self.db() as db:
            db.execute("UPDATE documents SET status='pending',error='上次解析被中断，请重新解析。' WHERE status='parsing'")

    def units(self, matter_id, document_id):
        self.document(matter_id, document_id)
        with self.db() as db:
            result = [dict(row) for row in db.execute("SELECT * FROM units WHERE document_id=? ORDER BY sequence", (document_id,))]
        for row in result:
            row["ocr_lines"] = json.loads(row["ocr_lines"])
        return result
