"""Database-backed stores (MySQL/Azure, or any SQLAlchemy URL).

Activated when DATABASE_URL (or MYSQL_URL) is set; otherwise the app uses
the file-based stores in settings.py. Two tables:

    loaner_settings  one row — the RateBook as JSON, with updated_at
    loaner_sheets    every generated sheet (html + meta), newest = current

Azure MySQL requires TLS; it is enabled by default for mysql URLs
(set DB_SSL=off to disable, e.g. for a local MySQL without TLS).
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone

from sqlalchemy import (Column, DateTime, Integer, MetaData, Table, Text,
                        create_engine, delete, insert, select, update)
from sqlalchemy.dialects.mysql import MEDIUMTEXT

from .models import RateBook
from .settings import BUNDLED_DEFAULTS, ratebook_from_dict, ratebook_to_dict

KEEP_SHEETS = 90  # newest N generated sheets retained as history

metadata = MetaData()

# Sheets run ~300 KB; MySQL TEXT caps at 64 KB, so use MEDIUMTEXT there.
_LONG_TEXT = Text().with_variant(MEDIUMTEXT(), "mysql")

settings_table = Table(
    "loaner_settings", metadata,
    Column("id", Integer, primary_key=True),
    Column("data", _LONG_TEXT, nullable=False),
    Column("updated_at", DateTime, nullable=False),
)

sheets_table = Table(
    "loaner_sheets", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("html", _LONG_TEXT, nullable=False),
    Column("meta", Text, nullable=False),
    Column("created_at", DateTime, nullable=False),
)


def database_url() -> str | None:
    return os.environ.get("DATABASE_URL") or os.environ.get("MYSQL_URL")


def make_engine(url: str):
    if url.startswith("mysql://"):
        url = "mysql+pymysql://" + url[len("mysql://"):]
    connect_args = {}
    ssl_on = os.environ.get("DB_SSL", "on").lower() not in ("off", "0", "false")
    if url.startswith("mysql+pymysql://") and ssl_on:
        connect_args["ssl"] = {}  # enables TLS with default context (Azure requires it)
    engine = create_engine(url, pool_pre_ping=True, pool_recycle=280,
                           connect_args=connect_args)
    metadata.create_all(engine)
    return engine


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # store naive UTC


class DbSettingsStore:
    """Same interface as settings.SettingsStore, backed by loaner_settings."""

    def __init__(self, engine):
        self.engine = engine

    @property
    def path(self) -> str:  # shown on the admin page
        return f"database ({self.engine.url.render_as_string(hide_password=True)})"

    def exists(self) -> bool:
        with self.engine.connect() as conn:
            return conn.execute(
                select(settings_table.c.id).where(settings_table.c.id == 1)
            ).first() is not None

    def load_dict(self) -> dict:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(settings_table.c.data).where(settings_table.c.id == 1)
            ).first()
        if row is None:
            return json.loads(BUNDLED_DEFAULTS.read_text(encoding="utf-8"))
        return json.loads(row.data)

    def load(self) -> RateBook:
        return ratebook_from_dict(self.load_dict())

    def save(self, rb: RateBook) -> None:
        payload = json.dumps(ratebook_to_dict(rb))
        with self.engine.begin() as conn:
            result = conn.execute(
                update(settings_table)
                .where(settings_table.c.id == 1)
                .values(data=payload, updated_at=_now())
            )
            if result.rowcount == 0:
                conn.execute(insert(settings_table).values(
                    id=1, data=payload, updated_at=_now()))

    def last_updated(self) -> date | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(settings_table.c.updated_at).where(settings_table.c.id == 1)
            ).first()
        if row is None:
            return None
        value = row.updated_at
        if isinstance(value, str):  # sqlite returns strings
            value = datetime.fromisoformat(value)
        return value.date()


class DbReportStore:
    """Same interface as settings.ReportStore, backed by loaner_sheets."""

    def __init__(self, engine):
        self.engine = engine

    def exists(self) -> bool:
        with self.engine.connect() as conn:
            return conn.execute(select(sheets_table.c.id).limit(1)).first() is not None

    def save(self, html: str, meta: dict) -> None:
        with self.engine.begin() as conn:
            conn.execute(insert(sheets_table).values(
                html=html, meta=json.dumps(meta), created_at=_now()))
            ids = conn.execute(
                select(sheets_table.c.id).order_by(sheets_table.c.id.desc())
                .offset(KEEP_SHEETS).limit(1)
            ).first()
            if ids is not None:
                conn.execute(delete(sheets_table).where(sheets_table.c.id <= ids.id))

    def load(self) -> tuple[str, dict] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(sheets_table.c.html, sheets_table.c.meta)
                .order_by(sheets_table.c.id.desc()).limit(1)
            ).first()
        if row is None:
            return None
        return row.html, json.loads(row.meta)
