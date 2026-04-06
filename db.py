import sqlite3
import os
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(__file__), 'dle.db')


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Models ────────────────────────────────────────────────────────────────────

@dataclass
class Klas:
    id: str          # slug used at login, e.g. 'vwo5-2025'
    name: str        # display name
    created_at: str


@dataclass
class Module:
    id: str          # matches JSON filename, e.g. 'd1'
    title: str
    created_at: str


@dataclass
class Student:
    pk: int          # surrogate PK used in all FK relations
    id: str          # student number shown/entered by student
    class_id: str    # FK -> classes.id
    group_name: str  # 'control' | 'treatment'
    created_at: str


@dataclass
class ClassModule:
    class_id: str
    module_id: str
    is_visible: bool
    added_at: str


@dataclass
class ModuleProgress:
    student_pk: int
    module_id: str
    item_index: int
    status: str      # 'in_progress' | 'completed'
    started_at: str
    completed_at: Optional[str] = None


@dataclass
class ItemSession:
    id: int
    student_pk: int
    module_id: str
    item_id: str
    crisis_phase: Optional[str]
    attempt_count: int
    started_at: str
    completed_at: Optional[str] = None
    time_seconds: Optional[float] = None


@dataclass
class StepInput:
    id: int
    session_id: int
    step_input: str
    is_correct: bool
    error_id: Optional[str]
    timestamp: str


# ── Schema ────────────────────────────────────────────────────────────────────

def init_db():
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS classes (
                id         TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            -- Modules are registered here so classes can reference them.
            -- 'id' matches the JSON filename in /items/.
            CREATE TABLE IF NOT EXISTS modules (
                id         TEXT PRIMARY KEY,
                title      TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            -- Surrogate PK allows the same student number to exist in
            -- different classes without collision.
            CREATE TABLE IF NOT EXISTS students (
                pk         INTEGER PRIMARY KEY AUTOINCREMENT,
                id         TEXT NOT NULL,
                class_id   TEXT NOT NULL REFERENCES classes(id),
                group_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (id, class_id)
            );

            -- Which modules belong to a class, and whether students can see them.
            CREATE TABLE IF NOT EXISTS class_modules (
                class_id   TEXT NOT NULL REFERENCES classes(id),
                module_id  TEXT NOT NULL REFERENCES modules(id),
                is_visible INTEGER NOT NULL DEFAULT 0,
                added_at   TEXT NOT NULL,
                PRIMARY KEY (class_id, module_id)
            );

            -- Resume pointer: one row per student x module.
            CREATE TABLE IF NOT EXISTS module_progress (
                student_pk   INTEGER NOT NULL REFERENCES students(pk),
                module_id    TEXT NOT NULL,
                item_index   INTEGER NOT NULL DEFAULT 0,
                status       TEXT NOT NULL DEFAULT 'in_progress',
                started_at   TEXT NOT NULL,
                completed_at TEXT,
                PRIMARY KEY (student_pk, module_id)
            );

            -- One row per student x item attempt.
            -- crisis_phase is NULL for normal items, 'crisis' or 'post_crisis'
            -- for treatment-group crisis items.
            CREATE TABLE IF NOT EXISTS item_sessions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                student_pk    INTEGER NOT NULL REFERENCES students(pk),
                module_id     TEXT NOT NULL,
                item_id       TEXT NOT NULL,
                crisis_phase  TEXT,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                started_at    TEXT NOT NULL,
                completed_at  TEXT,
                time_seconds  REAL
            );

            -- Optional per-step input log; only written when the module's
            -- log_steps flag is true.
            CREATE TABLE IF NOT EXISTS step_inputs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  INTEGER NOT NULL REFERENCES item_sessions(id),
                step_input  TEXT NOT NULL,
                is_correct  INTEGER NOT NULL,
                error_id    TEXT,
                timestamp   TEXT NOT NULL
            );
        """)


# ── Classes ───────────────────────────────────────────────────────────────────

def get_klas(class_id: str) -> Optional[Klas]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT id, name, created_at FROM classes WHERE id=?", (class_id,)
        ).fetchone()
    return Klas(**row) if row else None


def create_klas(class_id: str, name: str) -> Klas:
    now = _now()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO classes(id, name, created_at) VALUES (?,?,?)",
            (class_id, name, now),
        )
    return Klas(id=class_id, name=name, created_at=now)


def get_all_classes() -> list[Klas]:
    with _conn() as conn:
        rows = conn.execute("SELECT id, name, created_at FROM classes").fetchall()
    return [Klas(**r) for r in rows]


# ── Modules ───────────────────────────────────────────────────────────────────

def get_module(module_id: str) -> Optional[Module]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT id, title, created_at FROM modules WHERE id=?", (module_id,)
        ).fetchone()
    return Module(**row) if row else None


def register_module(module_id: str, title: str) -> Module:
    now = _now()
    with _conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO modules(id, title, created_at) VALUES (?,?,?)",
            (module_id, title, now),
        )
    return Module(id=module_id, title=title, created_at=now)


def get_all_modules() -> list[Module]:
    with _conn() as conn:
        rows = conn.execute("SELECT id, title, created_at FROM modules").fetchall()
    return [Module(**r) for r in rows]


# ── Class ↔ Module assignments ────────────────────────────────────────────────

def add_module_to_class(class_id: str, module_id: str) -> ClassModule:
    """Register a module in a class (hidden by default)."""
    now = _now()
    with _conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO class_modules(class_id, module_id, is_visible, added_at)
               VALUES (?,?,0,?)""",
            (class_id, module_id, now),
        )
    return ClassModule(class_id=class_id, module_id=module_id,
                       is_visible=False, added_at=now)


def set_module_visibility(class_id: str, module_id: str, is_visible: bool) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE class_modules SET is_visible=? WHERE class_id=? AND module_id=?",
            (int(is_visible), class_id, module_id),
        )


def get_visible_modules(class_id: str) -> list[Module]:
    """Returns modules the students of this class can currently see."""
    with _conn() as conn:
        rows = conn.execute(
            """SELECT m.id, m.title, m.created_at
               FROM modules m
               JOIN class_modules cm ON cm.module_id = m.id
               WHERE cm.class_id=? AND cm.is_visible=1
               ORDER BY cm.added_at""",
            (class_id,)
        ).fetchall()
    return [Module(**r) for r in rows]


def get_class_modules(class_id: str) -> list[tuple[Module, ClassModule]]:
    """Returns all modules in a class with their visibility state (for admin)."""
    with _conn() as conn:
        rows = conn.execute(
            """SELECT m.id, m.title, m.created_at,
                      cm.class_id, cm.module_id, cm.is_visible, cm.added_at
               FROM modules m
               JOIN class_modules cm ON cm.module_id = m.id
               WHERE cm.class_id=?
               ORDER BY cm.added_at""",
            (class_id,)
        ).fetchall()
    return [
        (
            Module(id=r['id'], title=r['title'], created_at=r['created_at']),
            ClassModule(class_id=r['class_id'], module_id=r['module_id'],
                        is_visible=bool(r['is_visible']), added_at=r['added_at']),
        )
        for r in rows
    ]


# ── Students ──────────────────────────────────────────────────────────────────

def get_student(student_id: str, class_id: str) -> Optional[Student]:
    with _conn() as conn:
        row = conn.execute(
            """SELECT pk, id, class_id, group_name, created_at
               FROM students WHERE id=? AND class_id=?""",
            (student_id, class_id)
        ).fetchone()
    return Student(**row) if row else None


def create_student(student_id: str, class_id: str, group: str) -> Student:
    now = _now()
    with _conn() as conn:
        cursor = conn.execute(
            """INSERT INTO students(id, class_id, group_name, created_at)
               VALUES (?,?,?,?)""",
            (student_id, class_id, group, now),
        )
        pk = cursor.lastrowid
    return Student(pk=pk, id=student_id, class_id=class_id,
                   group_name=group, created_at=now)


def get_students_in_class(class_id: str) -> list[Student]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT pk, id, class_id, group_name, created_at
               FROM students WHERE class_id=? ORDER BY id""",
            (class_id,)
        ).fetchall()
    return [Student(**r) for r in rows]


# ── Module progress ───────────────────────────────────────────────────────────

def get_module_progress(student_pk: int, module_id: str) -> Optional[ModuleProgress]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM module_progress WHERE student_pk=? AND module_id=?",
            (student_pk, module_id)
        ).fetchone()
    return ModuleProgress(**row) if row else None


def get_all_module_progress(student_pk: int) -> list[ModuleProgress]:
    """Returns all progress rows for a student (used on the home page)."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM module_progress WHERE student_pk=?", (student_pk,)
        ).fetchall()
    return [ModuleProgress(**r) for r in rows]


def start_module(student_pk: int, module_id: str) -> ModuleProgress:
    """Return existing progress or create a fresh entry."""
    existing = get_module_progress(student_pk, module_id)
    if existing:
        return existing
    now = _now()
    with _conn() as conn:
        conn.execute(
            """INSERT INTO module_progress
               (student_pk, module_id, item_index, status, started_at)
               VALUES (?,?,0,'in_progress',?)""",
            (student_pk, module_id, now),
        )
    return ModuleProgress(student_pk=student_pk, module_id=module_id,
                          item_index=0, status='in_progress', started_at=now)


def advance_module(student_pk: int, module_id: str,
                   next_index: int, total_items: int) -> None:
    """Move the resume pointer; mark completed when all items are done."""
    if next_index >= total_items:
        with _conn() as conn:
            conn.execute(
                """UPDATE module_progress
                   SET item_index=?, status='completed', completed_at=?
                   WHERE student_pk=? AND module_id=?""",
                (next_index, _now(), student_pk, module_id),
            )
    else:
        with _conn() as conn:
            conn.execute(
                """UPDATE module_progress SET item_index=?
                   WHERE student_pk=? AND module_id=?""",
                (next_index, student_pk, module_id),
            )


# ── Item sessions ─────────────────────────────────────────────────────────────

def get_active_item_session(student_pk: int, module_id: str,
                             item_id: str,
                             crisis_phase: Optional[str]) -> Optional[ItemSession]:
    with _conn() as conn:
        row = conn.execute(
            """SELECT * FROM item_sessions
               WHERE student_pk=? AND module_id=? AND item_id=?
               AND crisis_phase IS ? AND completed_at IS NULL""",
            (student_pk, module_id, item_id, crisis_phase)
        ).fetchone()
    return ItemSession(**row) if row else None


def start_item_session(student_pk: int, module_id: str,
                        item_id: str,
                        crisis_phase: Optional[str]) -> ItemSession:
    """Return the open session for this item, creating one if needed."""
    existing = get_active_item_session(student_pk, module_id, item_id, crisis_phase)
    if existing:
        return existing
    now = _now()
    with _conn() as conn:
        cursor = conn.execute(
            """INSERT INTO item_sessions
               (student_pk, module_id, item_id, crisis_phase, attempt_count, started_at)
               VALUES (?,?,?,?,0,?)""",
            (student_pk, module_id, item_id, crisis_phase, now),
        )
        session_id = cursor.lastrowid
    return ItemSession(id=session_id, student_pk=student_pk, module_id=module_id,
                       item_id=item_id, crisis_phase=crisis_phase,
                       attempt_count=0, started_at=now)


def record_attempt(session_id: int, step_input: str, is_correct: bool,
                   error_id: Optional[str], log_steps: bool) -> None:
    """Increment attempt count; write a step_inputs row only if log_steps is True."""
    with _conn() as conn:
        conn.execute(
            "UPDATE item_sessions SET attempt_count = attempt_count + 1 WHERE id=?",
            (session_id,)
        )
        if log_steps:
            conn.execute(
                """INSERT INTO step_inputs
                   (session_id, step_input, is_correct, error_id, timestamp)
                   VALUES (?,?,?,?,?)""",
                (session_id, step_input, int(is_correct), error_id, _now()),
            )


def complete_item_session(session_id: int) -> None:
    """Stamp completed_at and compute elapsed seconds."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT started_at FROM item_sessions WHERE id=?", (session_id,)
        ).fetchone()
        now_str = _now()
        elapsed = (datetime.fromisoformat(now_str) -
                   datetime.fromisoformat(row['started_at'])).total_seconds()
        conn.execute(
            "UPDATE item_sessions SET completed_at=?, time_seconds=? WHERE id=?",
            (now_str, elapsed, session_id),
        )
