"""Matter-scoped fact review, immutable extraction snapshots and revision history."""
from __future__ import annotations

import json
import uuid

from . import extraction as ex
from .store import now


class ConflictError(ValueError):
    pass


def encode(value):
    return json.dumps(value, ensure_ascii=False)


def init_schema(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS extraction_runs (
            id TEXT PRIMARY KEY, matter_id TEXT NOT NULL REFERENCES matters(id),
            document_id TEXT NOT NULL REFERENCES documents(id), mode TEXT NOT NULL,
            engine TEXT NOT NULL, source_hash TEXT NOT NULL, status TEXT NOT NULL,
            created_at TEXT NOT NULL, finished_at TEXT, added INTEGER NOT NULL DEFAULT 0,
            skipped INTEGER NOT NULL DEFAULT 0, details TEXT NOT NULL DEFAULT '{}', error TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS one_active_extraction
            ON extraction_runs(document_id) WHERE status='running';
        CREATE TABLE IF NOT EXISTS facts (
            id TEXT PRIMARY KEY, matter_id TEXT NOT NULL REFERENCES matters(id),
            document_id TEXT NOT NULL REFERENCES documents(id),
            run_id TEXT REFERENCES extraction_runs(id), fingerprint TEXT NOT NULL,
            original TEXT NOT NULL, current TEXT NOT NULL, evidence TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending','confirmed','uncertain','excluded')),
            reviewer_note TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(matter_id, fingerprint));
        CREATE INDEX IF NOT EXISTS facts_matter ON facts(matter_id);
        CREATE TABLE IF NOT EXISTS fact_history (
            id INTEGER PRIMARY KEY, fact_id TEXT NOT NULL REFERENCES facts(id),
            action TEXT NOT NULL, before_json TEXT, after_json TEXT NOT NULL, created_at TEXT NOT NULL);
    """)


def source_rows(db, matter_id):
    return {row["id"]: dict(row) for row in db.execute("""SELECT u.*, d.name AS document_name,
        d.status AS document_status FROM units u JOIN documents d ON d.id=u.document_id
        WHERE d.matter_id=?""", (matter_id,))}


def source_valid(evidence, sources):
    return all((unit := sources.get(e["unit_id"])) and
        unit["document_status"] in {"ready", "partial"} and
        ex.source_hash(unit) == e["source_hash"] and e["quote"] in unit["text"] for e in evidence)


def decode(row, sources):
    item = dict(row)
    for key in ("original", "current", "evidence"):
        item[key] = json.loads(item[key])
    item["source_valid"] = bool(source_valid(item["evidence"], sources))
    # Even while a reparse is running, no caller sees an eligible confirmed fact.
    item["eligible"] = item["status"] == "confirmed" and item["source_valid"]
    return item


def audit(db, fact_id, action, before, after):
    db.execute("INSERT INTO fact_history(fact_id,action,before_json,after_json,created_at) VALUES (?,?,?,?,?)",
        (fact_id, action, encode(before) if before else None, encode(after), now()))


def invalidate_sources(db, matter_id, document_id):
    sources = source_rows(db, matter_id)
    for row in db.execute("SELECT * FROM facts WHERE document_id=? AND status='confirmed'", (document_id,)).fetchall():
        before = decode(row, sources)
        if not before["source_valid"]:
            db.execute("UPDATE facts SET status='uncertain',version=version+1,updated_at=? WHERE id=?", (now(), row["id"]))
            after = decode(db.execute("SELECT * FROM facts WHERE id=?", (row["id"],)).fetchone(), sources)
            audit(db, row["id"], "source_changed", before, after)


class Review:
    def __init__(self, store):
        self.store = store

    def facts(self, matter_id):
        self.store.matter(matter_id)
        with self.store.db() as db:
            sources = source_rows(db, matter_id)
            items = [decode(r, sources) for r in db.execute("SELECT * FROM facts WHERE matter_id=? ORDER BY created_at,id", (matter_id,))]
            runs = []
            for row in db.execute("SELECT r.*,d.name AS document_name FROM extraction_runs r JOIN documents d ON d.id=r.document_id WHERE r.matter_id=? ORDER BY r.created_at DESC LIMIT 50", (matter_id,)):
                r = dict(row); r["details"] = json.loads(r["details"]); runs.append(r)
        return {"facts": items, "runs": runs, "config": ex.config()}

    @staticmethod
    def row(db, matter_id, fact_id):
        row = db.execute("SELECT * FROM facts WHERE id=? AND matter_id=?", (fact_id, matter_id)).fetchone()
        if not row:
            raise LookupError("当前事项中没有这条记录。")
        return row

    @staticmethod
    def evidence(candidate, sources, document_id=None):
        evidence = []
        for reference in candidate.evidence:
            unit = sources.get(reference.unit_id)
            if not unit or (document_id and unit["document_id"] != document_id):
                raise ValueError("引用必须属于当前文件及事项。")
            if unit["document_status"] not in {"ready", "partial"} or reference.quote not in unit["text"]:
                raise ValueError("引用不是当前可用原文中的连续文字。")
            evidence.append({"unit_id": unit["id"], "document_id": unit["document_id"],
                "document_name": unit["document_name"], "page_number": unit["page_number"],
                "locator": unit["locator"], "quote": reference.quote, "source_hash": ex.source_hash(unit),
                "method": unit["method"], "source_status": unit["status"]})
        return evidence

    def insert(self, db, matter_id, candidate, sources, run_id=None, document_id=None):
        evidence = self.evidence(candidate, sources, document_id)
        current = candidate.model_dump(exclude={"evidence"})
        fingerprint = ex.digest({"kind": candidate.kind, "value": candidate.value, "evidence": evidence})
        existing = db.execute("SELECT id FROM facts WHERE matter_id=? AND fingerprint=?", (matter_id, fingerprint)).fetchone()
        if existing:
            return existing["id"], False
        fact_id = uuid.uuid4().hex
        db.execute("""INSERT INTO facts(id,matter_id,document_id,run_id,fingerprint,original,current,evidence,status,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (fact_id, matter_id, evidence[0]["document_id"], run_id, fingerprint,
            encode(current), encode(current), encode(evidence), "pending", now(), now()))
        audit(db, fact_id, "extracted" if run_id else "manual_add", None, decode(self.row(db, matter_id, fact_id), sources))
        return fact_id, True

    def add(self, matter_id, data):
        candidate = ex.validate(ex.Candidate, data)
        self.store.matter(matter_id)
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            # A manual fact can cite multiple units of one document in this release.
            sources = source_rows(db, matter_id)
            first = sources.get(candidate.evidence[0].unit_id)
            if not first:
                raise ValueError("引用不属于当前事项。")
            fact_id, added = self.insert(db, matter_id, candidate, sources, document_id=first["document_id"])
            return {"fact": decode(self.row(db, matter_id, fact_id), sources), "added": added}

    def edit(self, matter_id, fact_id, data):
        edit = ex.validate(ex.ReviewEdit, data)
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            sources = source_rows(db, matter_id)
            before = decode(self.row(db, matter_id, fact_id), sources)
            if before["version"] != edit.version:
                raise ConflictError("这条记录已被更新，请刷新后再保存，避免覆盖已有修改。")
            if edit.status == "confirmed" and not before["source_valid"]:
                raise ValueError("引用原文已改变或不可用。请重新提取并审核新记录。")
            if edit.status == "uncertain" and not (edit.uncertainty or edit.reviewer_note):
                raise ValueError("请填写不确定原因或审核备注。")
            current = edit.model_dump(exclude={"version", "status", "reviewer_note"})
            db.execute("UPDATE facts SET current=?,status=?,reviewer_note=?,version=version+1,updated_at=? WHERE id=?",
                (encode(current), edit.status, edit.reviewer_note, now(), fact_id))
            after = decode(self.row(db, matter_id, fact_id), sources)
            audit(db, fact_id, "review", before, after)
            return after

    def history(self, matter_id, fact_id):
        with self.store.db() as db:
            self.row(db, matter_id, fact_id)
            result = []
            for row in db.execute("SELECT * FROM fact_history WHERE fact_id=? ORDER BY id DESC", (fact_id,)):
                item = dict(row)
                item["before"] = json.loads(item.pop("before_json") or "null")
                item["after"] = json.loads(item.pop("after_json"))
                result.append(item)
        return result

    def extract(self, matter_id, document_id, mode="local", allow_external=False):
        if not isinstance(mode, str) or mode not in {"local", "glm"}:
            raise ValueError("请选择本地或 GLM 提取。")
        if mode == "glm" and allow_external is not True:
            raise ValueError("模型提取需要明确同意将当前文件的解析文字发送给 GLM。")
        if mode == "glm" and not ex.config()["glm_configured"]:
            raise ValueError("请先配置 GLM_API_KEY 和 MATTERLOOM_GLM_MODEL。")
        self.store.document(matter_id, document_id)
        run_id = uuid.uuid4().hex
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            sources = source_rows(db, matter_id)
            units = [u for u in sources.values() if u["document_id"] == document_id]
            units.sort(key=lambda u: u["sequence"])
            document = dict(db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone())
            if db.execute("SELECT 1 FROM extraction_runs WHERE document_id=? AND status='running'", (document_id,)).fetchone():
                raise ConflictError("这份文件正在提取，请等待本次完成。")
            snapshot = {u["id"]: ex.source_hash(u) for u in units}
            engine = ex.config()["model"] if mode == "glm" else ex.VERSION
            db.execute("INSERT INTO extraction_runs(id,matter_id,document_id,mode,engine,source_hash,status,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (run_id, matter_id, document_id, mode, engine, ex.digest(snapshot), "running", now()))
        try:
            if document["status"] not in {"ready", "partial"}:
                raise ValueError("请先完成文件解析，再提取信息。")
            if not any(u["text"].strip() for u in units):
                raise ValueError("没有可提取的文字。请先完成 OCR，或根据原件另行补充文字材料。")
            if mode == "local":
                candidates, details = ex.local_candidates(units), {"rejected": 0, "batches": 0, "models": []}
            else:
                candidates, details = ex.model_candidates(units)
            details["source_partial"] = document["status"] == "partial"
            details["empty_units"] = sum(not u["text"].strip() for u in units)
            details["schema_version"] = ex.VERSION
            details["prompt_hash"] = ex.digest(ex.PROMPT) if mode == "glm" else None
            if details["rejected"] and not candidates:
                raise ValueError("模型候选均未通过字段或原文校验，没有保存事实。")
            added = skipped = 0
            with self.store.db() as db:
                db.execute("BEGIN IMMEDIATE")
                current_sources = source_rows(db, matter_id)
                current = {uid: ex.source_hash(u) for uid, u in current_sources.items() if u["document_id"] == document_id}
                doc_status = db.execute("SELECT status FROM documents WHERE id=?", (document_id,)).fetchone()[0]
                if current != snapshot or doc_status not in {"ready", "partial"}:
                    raise ConflictError("提取期间原文发生变化，请重新提取；旧审核记录保留。")
                for candidate in candidates:
                    _, created = self.insert(db, matter_id, candidate, current_sources, run_id, document_id)
                    added += int(created); skipped += int(not created)
                status = "partial" if details["rejected"] or details["source_partial"] else "ready"
                db.execute("UPDATE extraction_runs SET status=?,finished_at=?,added=?,skipped=?,details=? WHERE id=?",
                    (status, now(), added, skipped, encode(details), run_id))
            return {"run_id": run_id, "added": added, "skipped": skipped, "status": status, "details": details}
        except Exception as exc:
            message = str(exc) if isinstance(exc, ValueError) else "提取未完成，已有审核结果保留。"
            with self.store.db() as db:
                db.execute("UPDATE extraction_runs SET status='failed',finished_at=?,error=? WHERE id=?", (now(), message, run_id))
            raise ValueError(message) from None
