from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from applyflow.config import DB_PATH, ensure_app_dir
from applyflow.models import Application, Job


def _connect() -> sqlite3.Connection:
    ensure_app_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                external_id TEXT NOT NULL,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT,
                url TEXT,
                apply_url TEXT,
                description TEXT,
                tags TEXT,
                ats TEXT,
                posted_at TEXT,
                score INTEGER DEFAULT 0,
                career_level TEXT,
                tailored_path TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(source, external_id)
            );

            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                method TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            );
            """
        )
        cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        if "career_level" not in cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN career_level TEXT")
        if "tailored_path" not in cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN tailored_path TEXT")


def upsert_job(job: Job) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        row = conn.execute(
            "SELECT id, tailored_path FROM jobs WHERE source = ? AND external_id = ?",
            (job.source, job.external_id),
        ).fetchone()
        if row:
            tailored = job.tailored_path or (row["tailored_path"] or "")
            conn.execute(
                """
                UPDATE jobs SET
                    title=?, company=?, location=?, url=?, apply_url=?,
                    description=?, tags=?, ats=?, posted_at=?, score=?,
                    career_level=?, tailored_path=?
                WHERE id=?
                """,
                (
                    job.title,
                    job.company,
                    job.location,
                    job.url,
                    job.apply_url,
                    job.description,
                    ",".join(job.tags),
                    job.ats,
                    job.posted_at,
                    job.score,
                    job.career_level,
                    tailored,
                    row["id"],
                ),
            )
            return int(row["id"])
        cur = conn.execute(
            """
            INSERT INTO jobs (
                external_id, source, title, company, location, url, apply_url,
                description, tags, ats, posted_at, score, career_level, tailored_path, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.external_id,
                job.source,
                job.title,
                job.company,
                job.location,
                job.url,
                job.apply_url,
                job.description,
                ",".join(job.tags),
                job.ats,
                job.posted_at,
                job.score,
                job.career_level,
                job.tailored_path,
                now,
            ),
        )
        return int(cur.lastrowid)


def list_jobs(limit: int = 50, min_score: int = 0, unmatched: bool = False) -> list[Job]:
    sql = "SELECT * FROM jobs WHERE score >= ?"
    params: list[Any] = [min_score]
    if unmatched:
        sql += """
            AND id NOT IN (
                SELECT job_id FROM applications WHERE status IN ('applied', 'submitted')
            )
        """
    sql += " ORDER BY score DESC, id DESC LIMIT ?"
    params.append(limit)
    with db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_job_from_row(row) for row in rows]


def get_job(job_id: int) -> Job | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _job_from_row(row) if row else None


def record_application(job_id: int, status: str, method: str, notes: str = "") -> None:
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO applications (job_id, status, method, notes, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job_id, status, method, notes, now),
        )


def already_applied(job_id: int) -> bool:
    with db() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM applications
            WHERE job_id = ? AND status IN ('applied', 'submitted')
            LIMIT 1
            """,
            (job_id,),
        ).fetchone()
    return row is not None


def list_applications(limit: int = 50) -> list[Application]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT a.*, j.title, j.company, j.source
            FROM applications a
            JOIN jobs j ON j.id = a.job_id
            ORDER BY a.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        Application(
            id=row["id"],
            job_id=row["job_id"],
            status=row["status"],
            method=row["method"] or "",
            notes=row["notes"] or "",
            created_at=row["created_at"],
            title=row["title"],
            company=row["company"],
            source=row["source"],
        )
        for row in rows
    ]


def _job_from_row(row: sqlite3.Row) -> Job:
    tags = [t for t in (row["tags"] or "").split(",") if t]
    return Job(
        id=row["id"],
        external_id=row["external_id"],
        source=row["source"],
        title=row["title"],
        company=row["company"],
        location=row["location"] or "",
        url=row["url"] or "",
        apply_url=row["apply_url"] or "",
        description=row["description"] or "",
        tags=tags,
        ats=row["ats"] or "",
        posted_at=row["posted_at"] or "",
        score=row["score"] or 0,
        career_level=(row["career_level"] or "") if "career_level" in row.keys() else "",
        tailored_path=(row["tailored_path"] or "") if "tailored_path" in row.keys() else "",
    )
