"""Neon Postgres and Neon Object Storage adapters."""
from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import pandas as pd

QUESTION_COLUMNS = ["year", "topic", "subtopic", "question_type", "question_text", "marks", "answer"]
VALID_QUESTION_TYPES = {
    "MCQ", "Assertion-Reason", "Output-Prediction", "Fix-the-Code",
    "Case-Study", "Short-Answer", "Long-Answer",
}
_initialized = False
_initialize_lock = threading.Lock()


def _database_url() -> str:
    value = os.environ.get("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is required. Configure the Neon Postgres connection in .env.")
    return value


def _connect():
    import psycopg

    return psycopg.connect(_database_url(), connect_timeout=10, sslmode="require")


def _bucket_name() -> str:
    name = os.environ.get("AWS_BUCKET_NAME", "").strip()
    if not name:
        raise RuntimeError("AWS_BUCKET_NAME is required. Set it to the Neon Object Storage bucket name.")
    return name


@lru_cache(maxsize=1)
def _s3_client():
    import boto3
    from botocore.config import Config

    endpoint = os.environ.get("AWS_ENDPOINT_URL_S3", "").strip()
    region = os.environ.get("AWS_REGION", "").strip()
    access_key = os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
    missing = [name for name, value in {
        "AWS_ENDPOINT_URL_S3": endpoint,
        "AWS_REGION": region,
        "AWS_ACCESS_KEY_ID": access_key,
        "AWS_SECRET_ACCESS_KEY": secret_key,
    }.items() if not value]
    if missing:
        raise RuntimeError("Missing Neon Object Storage settings: " + ", ".join(missing))

    return boto3.client(
        "s3", endpoint_url=endpoint, region_name=region,
        aws_access_key_id=access_key, aws_secret_access_key=secret_key,
        config=Config(
            s3={"addressing_style": "path"},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


def initialize_storage() -> None:
    """Create application tables if absent and verify both cloud connections."""
    global _initialized
    if _initialized:
        return
    with _initialize_lock:
        if _initialized:
            return
        with _connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pyq_questions (
                    id BIGSERIAL PRIMARY KEY,
                    year INTEGER NOT NULL,
                    topic TEXT NOT NULL,
                    subtopic TEXT NOT NULL DEFAULT '',
                    question_type TEXT NOT NULL,
                    question_text TEXT NOT NULL UNIQUE,
                    marks INTEGER,
                    answer TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS practice_session_logs (
                    student_session TEXT PRIMARY KEY,
                    topics_missed TEXT[] NOT NULL DEFAULT '{}',
                    is_synthetic BOOLEAN NOT NULL DEFAULT false,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            conn.execute("ALTER TABLE practice_session_logs ADD COLUMN IF NOT EXISTS is_synthetic BOOLEAN NOT NULL DEFAULT false")
            conn.execute("""
                UPDATE practice_session_logs SET is_synthetic = true
                WHERE student_session = ANY(%s)
            """, ([f"s{i}" for i in range(1, 16)],))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS student_attempts (
                    attempt_id UUID PRIMARY KEY,
                    session_id UUID NOT NULL,
                    topic TEXT NOT NULL,
                    is_correct BOOLEAN NOT NULL,
                    answered BOOLEAN NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS student_attempts_session_created_idx ON student_attempts (session_id, created_at)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_id UUID PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT 'New conversation',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id BIGSERIAL PRIMARY KEY,
                    session_id UUID NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS chat_messages_session_id_idx ON chat_messages (session_id, id)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS stored_objects (
                    object_key TEXT PRIMARY KEY,
                    original_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    size_bytes BIGINT NOT NULL,
                    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS stored_objects_category_uploaded_idx ON stored_objects (category, uploaded_at DESC)")
        # A harmless bucket metadata request confirms credentials, endpoint and bucket.
        _s3_client().head_bucket(Bucket=_bucket_name())
        _initialized = True


def load_questions() -> pd.DataFrame:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT year, topic, subtopic, question_type, question_text, marks, answer "
            "FROM pyq_questions ORDER BY id"
        ).fetchall()
    return validate_question_rows(pd.DataFrame(rows, columns=QUESTION_COLUMNS))


def validate_question_rows(rows: pd.DataFrame) -> pd.DataFrame:
    """Validate editor, import, and database rows against the question-bank schema."""
    missing = [column for column in QUESTION_COLUMNS if column not in rows.columns]
    if missing:
        raise ValueError("Question data is missing required columns: " + ", ".join(missing))
    frame = rows.loc[:, QUESTION_COLUMNS].copy()
    if frame.empty:
        return frame

    for column in ("topic", "question_type", "question_text"):
        if frame[column].isna().any():
            raise ValueError(f"Question field '{column}' cannot be empty.")
        frame[column] = frame[column].astype(str).str.strip()
        if frame[column].eq("").any():
            raise ValueError(f"Question field '{column}' cannot be empty.")
    invalid_types = sorted(set(frame["question_type"]) - VALID_QUESTION_TYPES)
    if invalid_types:
        raise ValueError("Unsupported question type(s): " + ", ".join(invalid_types))

    years = pd.to_numeric(frame["year"], errors="coerce")
    if years.isna().any() or ((years < 1900) | (years > 2100)).any():
        raise ValueError("Question years must be whole years from 1900 through 2100.")
    if ((years % 1) != 0).any():
        raise ValueError("Question years must be whole numbers.")
    frame["year"] = years.astype(int)

    marks = frame["marks"]
    has_marks = marks.notna() & marks.astype(str).str.strip().ne("")
    numeric_marks = pd.to_numeric(marks.where(has_marks), errors="coerce")
    if ((has_marks & numeric_marks.isna()).any()
            or ((numeric_marks < 0) | (numeric_marks > 100)).any()
            or (has_marks & ((numeric_marks % 1) != 0)).any()):
        raise ValueError("Marks must be whole numeric values from 0 through 100.")
    frame["marks"] = numeric_marks

    for column in ("subtopic", "answer"):
        frame[column] = frame[column].fillna("").astype(str).str.strip()
    if frame["topic"].str.len().gt(200).any() or frame["question_text"].str.len().gt(20_000).any():
        raise ValueError("Topic names are limited to 200 characters and question text to 20,000 characters.")
    return frame.reset_index(drop=True)


def upsert_questions(rows: pd.DataFrame) -> dict:
    validated = validate_question_rows(rows)
    records = []
    for row in validated.to_dict(orient="records"):
        records.append((
            int(row["year"]), str(row["topic"]).strip(), str(row["subtopic"]).strip(),
            str(row["question_type"]).strip(), str(row["question_text"]).strip(),
            int(row["marks"]) if pd.notna(row["marks"]) else None,
            str(row["answer"]).strip(),
        ))
    with _connect() as conn:
        added = 0
        if records:
            with conn.cursor() as cursor:
                insert_sql = """
                    INSERT INTO pyq_questions (year, topic, subtopic, question_type, question_text, marks, answer)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (question_text) DO NOTHING
                """
                for record in records:
                    cursor.execute(insert_sql, record)
                    added += cursor.rowcount
        total = conn.execute("SELECT count(*) FROM pyq_questions").fetchone()[0]
    return {"added": added, "total": total, "duplicates_skipped": len(records) - added}


def load_session_logs(include_synthetic: bool = False) -> pd.DataFrame:
    with _connect() as conn:
        if include_synthetic:
            rows = conn.execute("SELECT student_session, topics_missed FROM practice_session_logs ORDER BY created_at").fetchall()
        else:
            rows = conn.execute("SELECT student_session, topics_missed FROM practice_session_logs WHERE NOT is_synthetic ORDER BY created_at").fetchall()
    return pd.DataFrame(
        [(session, ",".join(topics or [])) for session, topics in rows],
        columns=["student_session", "topics_missed"],
    )


def log_session_mistakes(student_session: str, topics_missed: list[str], *, is_synthetic: bool = False) -> None:
    clean_topics = [str(topic).strip() for topic in topics_missed if str(topic).strip()]
    with _connect() as conn:
        conn.execute("""
            INSERT INTO practice_session_logs (student_session, topics_missed, is_synthetic)
            VALUES (%s, %s, %s)
            ON CONFLICT (student_session) DO UPDATE
            SET topics_missed = EXCLUDED.topics_missed,
                is_synthetic = EXCLUDED.is_synthetic
        """, (student_session, clean_topics, is_synthetic))


def record_student_attempts(session_id: str, attempts: list[dict]) -> None:
    rows = []
    for attempt in attempts:
        topic = str(attempt.get("topic", "")).strip()
        if not topic:
            raise ValueError("Attempt topic cannot be empty.")
        rows.append((uuid.uuid4(), uuid.UUID(session_id), topic,
                     bool(attempt.get("correct", False)), bool(attempt.get("answered", True))))
    if not rows:
        return
    missed_topics = sorted({topic for _, _, topic, correct, answered in rows if answered and not correct})
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.executemany("""
                INSERT INTO student_attempts (attempt_id, session_id, topic, is_correct, answered)
                VALUES (%s, %s, %s, %s, %s)
            """, rows)
        if missed_topics:
            conn.execute("""
                INSERT INTO practice_session_logs (student_session, topics_missed, is_synthetic)
                VALUES (%s, %s, false)
            """, (f"quiz-{uuid.uuid4().hex}", missed_topics))


def load_student_attempts(session_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("""
            SELECT topic, is_correct FROM student_attempts
            WHERE session_id = %s AND answered
            ORDER BY created_at, attempt_id
        """, (uuid.UUID(session_id),)).fetchall()
    return [{"topic": topic, "correct": correct} for topic, correct in rows]


def load_chat_messages(session_id: str, limit: int = 200) -> list[dict]:
    """Load the most recent messages for an opaque, anonymous chat session."""
    session_uuid = uuid.UUID(str(session_id))
    limit = max(1, min(int(limit), 500))
    with _connect() as conn:
        conn.execute("""
            INSERT INTO chat_sessions (session_id) VALUES (%s)
            ON CONFLICT (session_id) DO NOTHING
        """, (session_uuid,))
        rows = conn.execute("""
            SELECT role, content FROM chat_messages
            WHERE session_id = %s ORDER BY id DESC LIMIT %s
        """, (session_uuid, limit)).fetchall()
    return [{"role": role, "content": content} for role, content in reversed(rows)]


def save_chat_turn(session_id: str, user_message: str, assistant_message: str) -> None:
    """Persist a user prompt and response together as one database transaction."""
    session_uuid = uuid.UUID(str(session_id))
    if not isinstance(user_message, str) or not user_message.strip() or len(user_message) > 20_000:
        raise ValueError("Chat prompts must contain 1 to 20,000 characters.")
    if not isinstance(assistant_message, str) or len(assistant_message) > 50_000:
        raise ValueError("Chat responses cannot exceed 50,000 characters.")
    title = user_message.strip().replace("\n", " ")[:120]
    with _connect() as conn:
        conn.execute("""
            INSERT INTO chat_sessions (session_id, title) VALUES (%s, %s)
            ON CONFLICT (session_id) DO UPDATE SET
                updated_at = now(),
                title = CASE WHEN chat_sessions.title = 'New conversation'
                             THEN EXCLUDED.title ELSE chat_sessions.title END
        """, (session_uuid, title))
        with conn.cursor() as cursor:
            cursor.executemany("""
                INSERT INTO chat_messages (session_id, role, content)
                VALUES (%s, %s, %s)
            """, [
                (session_uuid, "user", user_message.strip()),
                (session_uuid, "assistant", assistant_message),
            ])
        # Bound database growth while retaining a useful recent conversation.
        conn.execute("""
            DELETE FROM chat_messages
            WHERE session_id = %s AND id NOT IN (
                SELECT id FROM chat_messages WHERE session_id = %s
                ORDER BY id DESC LIMIT 500
            )
        """, (session_uuid, session_uuid))


def delete_chat_session(session_id: str) -> None:
    """Delete a chat and all of its messages; quiz progress is stored separately."""
    with _connect() as conn:
        conn.execute("DELETE FROM chat_sessions WHERE session_id = %s", (uuid.UUID(str(session_id)),))


def get_active_syllabus_key() -> str | None:
    with _connect() as conn:
        row = conn.execute("""
            SELECT setting_value FROM app_settings WHERE setting_key = 'active_syllabus_key'
        """).fetchone()
        if not row:
            return None
        exists = conn.execute("""
            SELECT 1 FROM stored_objects WHERE object_key = %s AND category = 'syllabus'
              AND content_type = 'application/pdf'
        """, (row[0],)).fetchone()
    return row[0] if exists else None


def set_active_syllabus_key(object_key: str) -> None:
    with _connect() as conn:
        exists = conn.execute("""
            SELECT 1 FROM stored_objects WHERE object_key = %s AND category = 'syllabus'
              AND content_type = 'application/pdf'
        """, (object_key,)).fetchone()
        if not exists:
            raise ValueError("Choose a PDF stored in the syllabus category.")
        conn.execute("""
            INSERT INTO app_settings (setting_key, setting_value)
            VALUES ('active_syllabus_key', %s)
            ON CONFLICT (setting_key) DO UPDATE SET
                setting_value = EXCLUDED.setting_value, updated_at = now()
        """, (object_key,))


def clear_active_syllabus() -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM app_settings WHERE setting_key = 'active_syllabus_key'")


def put_object(object_key: str, body: bytes, *, original_name: str,
               category: str, content_type: str,
               uploaded_at: datetime | None = None) -> None:
    """Upload an object first, then commit its searchable metadata to Postgres."""
    if not isinstance(body, bytes) or not body:
        raise ValueError("Uploaded file must contain data.")
    if len(body) > 20 * 1024 * 1024:
        raise ValueError("Uploads are limited to 20 MiB.")
    if content_type == "application/pdf" and not body.startswith(b"%PDF-"):
        raise ValueError("The uploaded file does not have a valid PDF signature.")
    _s3_client().put_object(
        Bucket=_bucket_name(), Key=object_key, Body=body, ContentType=content_type,
    )
    try:
        with _connect() as conn:
            conn.execute("""
                INSERT INTO stored_objects (object_key, original_name, category, content_type, size_bytes, uploaded_at)
                VALUES (%s, %s, %s, %s, %s, COALESCE(%s, now()))
                ON CONFLICT (object_key) DO UPDATE SET
                    original_name = EXCLUDED.original_name,
                    category = EXCLUDED.category,
                    content_type = EXCLUDED.content_type,
                    size_bytes = EXCLUDED.size_bytes,
                    uploaded_at = EXCLUDED.uploaded_at
            """, (object_key, original_name, category, content_type, len(body), uploaded_at))
    except Exception:
        # Leave the uploaded object in place if metadata storage fails. Deleting
        # here could destroy a previously valid object when a key was replaced.
        raise


def put_file(path: str | Path, object_key: str, *, category: str,
             original_name: str | None = None, content_type: str = "application/octet-stream") -> None:
    path = Path(path)
    put_object(object_key, path.read_bytes(), original_name=original_name or path.name,
               category=category, content_type=content_type,
               uploaded_at=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc))


def get_object_bytes(object_key: str) -> bytes:
    response = _s3_client().get_object(Bucket=_bucket_name(), Key=object_key)
    return response["Body"].read()


def list_objects(category: str | None = None) -> list[dict]:
    with _connect() as conn:
        if category:
            rows = conn.execute("""
                SELECT object_key, original_name, category, content_type, size_bytes, uploaded_at
                FROM stored_objects WHERE category = %s ORDER BY uploaded_at DESC
            """, (category,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT object_key, original_name, category, content_type, size_bytes, uploaded_at
                FROM stored_objects ORDER BY uploaded_at DESC
            """).fetchall()
    names = ["object_key", "original_name", "category", "content_type", "size_bytes", "uploaded_at"]
    return [dict(zip(names, row)) for row in rows]


def list_buckets() -> list[str]:
    """Return names only; useful for diagnosing a missing bucket setting."""
    return [item["Name"] for item in _s3_client().list_buckets().get("Buckets", [])]


def copy_local_file(path: str | Path, object_key: str, *, category: str,
                    content_type: str = "application/octet-stream") -> None:
    path = Path(path)
    put_file(path, object_key, category=category, original_name=path.name, content_type=content_type)
