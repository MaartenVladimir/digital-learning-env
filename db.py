import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'dle.db')


def _conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS students (
                id         TEXT PRIMARY KEY,
                group_name TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS attempts (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id   TEXT NOT NULL,
                item_id      TEXT NOT NULL,
                step_input   TEXT NOT NULL,
                is_correct   INTEGER NOT NULL,
                error_id     TEXT,
                module_id    TEXT NOT NULL,
                is_crisis    INTEGER NOT NULL DEFAULT 0,
                crisis_phase TEXT,
                timestamp    TEXT NOT NULL
            );
        """)


def register_student(student_id, group):
    with _conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO students(id, group_name, created_at) VALUES (?,?,?)",
            (student_id, group, datetime.utcnow().isoformat()),
        )


def log_attempt(student_id, item_id, step_input, is_correct,
                error_id, module_id, is_crisis, crisis_phase=None):
    with _conn() as conn:
        conn.execute(
            """INSERT INTO attempts
               (student_id, item_id, step_input, is_correct,
                error_id, module_id, is_crisis, crisis_phase, timestamp)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (student_id, item_id, step_input, int(is_correct),
             error_id, module_id, int(is_crisis), crisis_phase,
             datetime.utcnow().isoformat()),
        )
