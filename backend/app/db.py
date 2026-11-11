"""Engine/session factory and DB-level guards (immutability + append-only triggers).

The same business code runs on SQLite (dev/tests) and PostgreSQL (prod); only the trigger DDL
is dialect-specific.
"""
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import settings
from .models import Base, Meta

SCHEMA_VERSION = "2"   # 2: auto_pending status; inference/recommendation/review_reason columns

# (trigger name, table, timing/event, guard condition or None, message)
_GUARDS = [
    ("questions_original_immutable", "questions", "UPDATE OF original_json",
     "NEW.original_json <> OLD.original_json", "questions.original_json is immutable"),
    ("questions_no_delete", "questions", "DELETE", None, "questions cannot be deleted"),
    ("audit_no_update", "audit_events", "UPDATE", None, "audit_events is append-only"),
    ("audit_no_delete", "audit_events", "DELETE", None, "audit_events is append-only"),
    ("revisions_no_update", "question_revisions", "UPDATE", None, "question_revisions is append-only"),
    ("revisions_no_delete", "question_revisions", "DELETE", None, "question_revisions is append-only"),
]


def make_engine(url: str | None = None) -> Engine:
    url = url or settings.database_url
    if url.startswith("sqlite"):
        kw = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kw["poolclass"] = StaticPool
        eng = create_engine(url, **kw)

        @event.listens_for(eng, "connect")
        def _fk_on(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
        return eng
    return create_engine(url, pool_pre_ping=True)


def _install_guards(conn) -> None:
    if conn.dialect.name == "sqlite":
        for name, table, ev, cond, msg in _GUARDS:
            when = f" WHEN {cond}" if cond else ""
            conn.execute(text(
                f"CREATE TRIGGER IF NOT EXISTS {name} BEFORE {ev} ON {table}{when} "
                f"BEGIN SELECT RAISE(ABORT, '{msg}'); END;"))
    elif conn.dialect.name == "postgresql":
        conn.execute(text(
            "CREATE OR REPLACE FUNCTION acadza_forbid() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION '%', TG_ARGV[0]; END; $$ LANGUAGE plpgsql;"))
        for name, table, ev, cond, msg in _GUARDS:
            when = f" WHEN ({cond.replace('<>', 'IS DISTINCT FROM')})" if cond else ""
            conn.execute(text(f"DROP TRIGGER IF EXISTS {name} ON {table}"))
            conn.execute(text(
                f"CREATE TRIGGER {name} BEFORE {ev} ON {table} FOR EACH ROW{when} "
                f"EXECUTE FUNCTION acadza_forbid('{msg}')"))
    else:
        raise RuntimeError(f"unsupported database dialect {conn.dialect.name!r}")


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        _install_guards(conn)
    with Session(engine) as s:
        row = s.get(Meta, "schema_version")
        if row is None:
            s.add(Meta(key="schema_version", value=SCHEMA_VERSION))
            s.commit()
        elif row.value != SCHEMA_VERSION:
            raise RuntimeError(
                f"DB schema_version {row.value} != app {SCHEMA_VERSION}; delete the DB and re-import "
                "(migration policy: DATABASE_SCHEMA.md section 5)")


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def table_counts(s: Session) -> dict[str, int]:
    from sqlalchemy import func
    from .models import Case, Question, Report
    return {m.__tablename__: s.scalar(select(func.count()).select_from(m)) for m in (Question, Report, Case)}
