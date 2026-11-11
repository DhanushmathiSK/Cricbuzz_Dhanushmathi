"""Centralised database access: the only module that opens connections.

SQLite is the default and needs no setup. To use another database, set
DATABASE_URL in .streamlit/secrets.toml (or as an environment variable):

    postgresql://user:password@host:5432/dbname    (pip install psycopg2-binary)
    mysql://user:password@host:3306/dbname         (pip install pymysql)

Only SQLite has been tested. The PostgreSQL/MySQL branches follow the
"database-agnostic" requirement and may need small adjustments.
"""
import re
import sqlite3
from contextlib import contextmanager
from urllib.parse import unquote, urlparse

import pandas as pd

from utils.config import get_setting

DEFAULT_URL = "sqlite:///cricket.db"

# ---------------------------------------------------------------------
# Schema definition (column name, type, default). "{PK}" = auto-number key.
# ---------------------------------------------------------------------
PK_TYPES = {
    "sqlite": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "postgres": "SERIAL PRIMARY KEY",
    "mysql": "INTEGER PRIMARY KEY AUTO_INCREMENT",
}

SCHEMA = {
    "players": {
        "columns": [
            ("player_id", "{PK}", None),
            ("api_player_id", "VARCHAR(32)", None),
            ("name", "VARCHAR(120) NOT NULL", None),
            ("country", "VARCHAR(80) NOT NULL", "'Unknown'"),
            ("role", "VARCHAR(20)", "'Batsman'"),
            ("batting_style", "VARCHAR(60)", "'Unknown'"),
            ("bowling_style", "VARCHAR(60)", "'Unknown'"),
            ("format", "VARCHAR(10)", "'ODI'"),
            ("matches_played", "INTEGER", "0"),
            ("runs", "INTEGER", "0"),
            ("wickets", "INTEGER", "0"),
            ("batting_avg", "FLOAT", "0"),
            ("bowling_avg", "FLOAT", "0"),
            ("economy_rate", "FLOAT", "0"),
            ("strike_rate", "FLOAT", "0"),
            ("centuries", "INTEGER", "0"),
            ("highest_score", "INTEGER", "0"),
            ("balls_bowled", "INTEGER", "0"),
            ("catches", "INTEGER", "0"),
            ("stumpings", "INTEGER", "0"),
            ("run_outs", "INTEGER", "0"),
            ("last_synced", "VARCHAR(20)", None),
        ],
        "constraints": [
            "UNIQUE (api_player_id, format)",
            "CHECK (role IN ('Batsman', 'Bowler', 'All-Rounder', 'Wicket-Keeper'))",
            "CHECK (format IN ('Test', 'ODI', 'T20I'))",
            "CHECK (length(trim(name)) > 0)",
        ],
        "indexes": [("ix_players_country", "country"), ("ix_players_format", "format"),
                    ("ix_players_name", "name")],
    },
    "series": {
        "columns": [
            ("series_id", "INTEGER PRIMARY KEY", None),
            ("name", "VARCHAR(200)", None),
            ("host_country", "VARCHAR(100)", None),
            ("match_type", "VARCHAR(30)", None),
            ("start_date", "VARCHAR(10)", None),
            ("end_date", "VARCHAR(10)", None),
            ("total_matches", "INTEGER", None),
        ],
        "constraints": [],
        "indexes": [("ix_series_start", "start_date")],
    },
    "venues": {
        "columns": [
            ("venue_id", "INTEGER PRIMARY KEY", None),
            ("name", "VARCHAR(200)", None),
            ("city", "VARCHAR(100)", None),
            ("country", "VARCHAR(100)", None),
            ("capacity", "INTEGER", None),
        ],
        "constraints": [],
        "indexes": [("ix_venues_capacity", "capacity")],
    },
    "matches": {
        "columns": [
            ("match_id", "{PK}", None),
            ("series_id", "INTEGER", None),
            ("series_name", "VARCHAR(200)", None),
            ("match_desc", "VARCHAR(120)", None),
            ("match_format", "VARCHAR(20)", None),
            ("start_date", "VARCHAR(10)", None),
            ("state", "VARCHAR(40)", None),
            ("status", "VARCHAR(300)", None),
            ("team1", "VARCHAR(100)", None),
            ("team2", "VARCHAR(100)", None),
            ("team1_score", "VARCHAR(100)", None),
            ("team2_score", "VARCHAR(100)", None),
            ("venue_id", "INTEGER", None),
            ("venue", "VARCHAR(200)", None),
            ("city", "VARCHAR(100)", None),
            ("country", "VARCHAR(100)", None),
            ("winner", "VARCHAR(100)", None),
            ("victory_type", "VARCHAR(20)", None),
            ("victory_margin", "INTEGER", None),
            ("toss_winner", "VARCHAR(100)", None),
            ("toss_decision", "VARCHAR(20)", None),
            ("details_synced", "INTEGER", "0"),
        ],
        "constraints": [],
        "indexes": [("ix_matches_date", "start_date"), ("ix_matches_winner", "winner"),
                    ("ix_matches_series", "series_id")],
    },
    "batting_performance": {
        "columns": [
            ("id", "{PK}", None),
            ("match_id", "INTEGER", None),
            ("innings", "INTEGER", None),
            ("team", "VARCHAR(100)", None),
            ("player_id", "VARCHAR(32)", None),
            ("player_name", "VARCHAR(120)", None),
            ("batting_position", "INTEGER", None),
            ("runs", "INTEGER", "0"),
            ("balls", "INTEGER", "0"),
            ("fours", "INTEGER", "0"),
            ("sixes", "INTEGER", "0"),
            ("strike_rate", "FLOAT", "0"),
            ("out_desc", "VARCHAR(200)", None),
        ],
        "constraints": [],
        "indexes": [("ix_bat_match", "match_id"), ("ix_bat_player", "player_name")],
    },
    "bowling_performance": {
        "columns": [
            ("id", "{PK}", None),
            ("match_id", "INTEGER", None),
            ("innings", "INTEGER", None),
            ("team", "VARCHAR(100)", None),
            ("player_id", "VARCHAR(32)", None),
            ("player_name", "VARCHAR(120)", None),
            ("overs", "FLOAT", "0"),
            ("maidens", "INTEGER", "0"),
            ("runs_conceded", "INTEGER", "0"),
            ("wickets", "INTEGER", "0"),
            ("economy", "FLOAT", "0"),
        ],
        "constraints": [],
        "indexes": [("ix_bowl_match", "match_id"), ("ix_bowl_player", "player_name")],
    },
    "partnerships": {
        "columns": [
            ("id", "{PK}", None),
            ("match_id", "INTEGER", None),
            ("innings", "INTEGER", None),
            ("batting_team", "VARCHAR(100)", None),
            ("player1", "VARCHAR(120)", None),
            ("player2", "VARCHAR(120)", None),
            ("runs", "INTEGER", "0"),
            ("balls", "INTEGER", "0"),
        ],
        "constraints": [],
        "indexes": [("ix_part_match", "match_id")],
    },
}

_NAMED_PARAM = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")


# ---------------------------------------------------------------------
# Connection handling
# ---------------------------------------------------------------------
def get_url():
    """Return the configured database URL (SQLite file by default)."""
    return get_setting("DATABASE_URL", DEFAULT_URL)


def get_dialect():
    """Return 'sqlite', 'postgres' or 'mysql' based on DATABASE_URL."""
    scheme = urlparse(get_url()).scheme.split("+")[0].lower()
    return {"postgresql": "postgres", "postgres": "postgres", "mysql": "mysql"}.get(scheme, "sqlite")


@contextmanager
def connect():
    """Open a connection, commit on success, roll back on error, always close."""
    url, dialect = get_url(), get_dialect()
    if dialect == "sqlite":
        path = url.split("sqlite:///", 1)[-1] or "cricket.db"
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA foreign_keys = ON")
    elif dialect == "postgres":
        import psycopg2  # imported lazily: only needed for PostgreSQL

        p = urlparse(url)
        conn = psycopg2.connect(host=p.hostname, port=p.port or 5432,
                                user=unquote(p.username or ""),
                                password=unquote(p.password or ""),
                                dbname=p.path.lstrip("/"))
    else:
        import pymysql  # imported lazily: only needed for MySQL

        p = urlparse(url)
        conn = pymysql.connect(host=p.hostname, port=p.port or 3306,
                               user=unquote(p.username or ""),
                               password=unquote(p.password or ""),
                               database=p.path.lstrip("/"))
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _py(value):
    """Convert numpy/pandas values to plain Python so every driver accepts them."""
    if value is None:
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(value, float) and value != value:  # NaN -> NULL
        return None
    return value


def _prepare(sql, params):
    """Turn ':name' placeholders into the driver's style and clean the values."""
    params = {k: _py(v) for k, v in (params or {}).items()}
    if get_dialect() == "sqlite":
        return sql, params
    return _NAMED_PARAM.sub(r"%(\1)s", sql), (params or None)


# ---------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------
def run_query(sql, params=None):
    """Run a SELECT with :named parameters and return a pandas DataFrame."""
    with connect() as conn:
        cur = conn.cursor()
        statement, values = _prepare(sql, params)
        cur.execute(statement, values) if values else cur.execute(statement)
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = [tuple(r) for r in cur.fetchall()] if cur.description else []
        cur.close()
    return pd.DataFrame(rows, columns=columns)


def execute(sql, params=None):
    """Run INSERT/UPDATE/DELETE; returns the number of affected rows."""
    with connect() as conn:
        cur = conn.cursor()
        statement, values = _prepare(sql, params)
        cur.execute(statement, values) if values else cur.execute(statement)
        count = cur.rowcount
        cur.close()
    return count


def insert_many(table, rows):
    """Insert a list of dicts that all share the same keys."""
    if not rows:
        return 0
    columns = list(rows[0])
    sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(':' + c for c in columns)})"
    with connect() as conn:
        cur = conn.cursor()
        for row in rows:
            statement, values = _prepare(sql, row)
            cur.execute(statement, values)
        cur.close()
    return len(rows)


def upsert_many(table, rows, keys):
    """Update the row matching `keys` if it exists, otherwise insert it.

    Only the columns present in each dict are written, so partial updates
    never overwrite other columns with NULL.
    """
    if not rows:
        return 0
    where = " AND ".join(f"{k} = :{k}" for k in keys)
    with connect() as conn:
        cur = conn.cursor()
        for row in rows:
            statement, values = _prepare(f"SELECT 1 FROM {table} WHERE {where}", row)
            cur.execute(statement, values)
            exists = cur.fetchone() is not None
            sets = ", ".join(f"{c} = :{c}" for c in row if c not in keys)
            if exists and sets:
                statement, values = _prepare(f"UPDATE {table} SET {sets} WHERE {where}", row)
                cur.execute(statement, values)
            elif not exists:
                cols = list(row)
                sql = (f"INSERT INTO {table} ({', '.join(cols)}) "
                       f"VALUES ({', '.join(':' + c for c in cols)})")
                statement, values = _prepare(sql, row)
                cur.execute(statement, values)
        cur.close()
    return len(rows)


# ---------------------------------------------------------------------
# Schema creation / migration
# ---------------------------------------------------------------------
def _column_sql(name, col_type, default):
    col_type = col_type.replace("{PK}", PK_TYPES[get_dialect()])
    return f"{name} {col_type}" + (f" DEFAULT {default}" if default is not None else "")


def create_table_sql(table):
    """Return the CREATE TABLE statement for `table` in the active dialect."""
    spec = SCHEMA[table]
    parts = [_column_sql(*c) for c in spec["columns"]] + spec["constraints"]
    return f"CREATE TABLE IF NOT EXISTS {table} (\n    " + ",\n    ".join(parts) + "\n)"


def index_sql(index_name, table, column):
    """Return the CREATE INDEX statement for the active dialect."""
    if_not_exists = "" if get_dialect() == "mysql" else "IF NOT EXISTS "
    return f"CREATE INDEX {if_not_exists}{index_name} ON {table} ({column})"


def _existing_columns(cur, table):
    if get_dialect() == "sqlite":
        cur.execute(f"PRAGMA table_info({table})")
        return {row[1] for row in cur.fetchall()}
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                (table,))
    return {row[0].lower() for row in cur.fetchall()}


def init_db():
    """Create missing tables/indexes and add any new columns to older tables.

    Existing data is kept: older databases are upgraded with ALTER TABLE.
    """
    with connect() as conn:
        cur = conn.cursor()
        for table, spec in SCHEMA.items():
            cur.execute(create_table_sql(table))
            existing = _existing_columns(cur, table)
            for name, col_type, default in spec["columns"]:
                if name not in existing and "{PK}" not in col_type:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN " + _column_sql(name, col_type, default))
            for index_name, column in spec["indexes"]:
                try:
                    cur.execute(index_sql(index_name, table, column))
                except Exception:  # MySQL has no IF NOT EXISTS for indexes
                    pass
        cur.close()


def table_counts():
    """Return {table_name: row_count} for every table."""
    counts = {}
    with connect() as conn:
        cur = conn.cursor()
        for table in SCHEMA:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            counts[table] = cur.fetchone()[0]
        cur.close()
    return counts


# ---------------------------------------------------------------------
# Exports (database schema + sample data deliverable)
# ---------------------------------------------------------------------
def export_schema_sql():
    """Return the full schema (tables + indexes) as SQL text."""
    parts = ["-- Cricbuzz LiveStats database schema", f"-- Dialect: {get_dialect()}", ""]
    for table, spec in SCHEMA.items():
        parts.append(create_table_sql(table) + ";")
        for index_name, column in spec["indexes"]:
            parts.append(index_sql(index_name, table, column) + ";")
        parts.append("")
    return "\n".join(parts)


def _literal(value):
    value = _py(value)
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def export_dump():
    """Return schema + INSERT statements for all current data (sample data export)."""
    parts = [export_schema_sql()]
    for table in SCHEMA:
        df = run_query(f"SELECT * FROM {table}")
        for _, row in df.iterrows():
            values = ", ".join(_literal(v) for v in row)
            parts.append(f"INSERT INTO {table} ({', '.join(df.columns)}) VALUES ({values});")
    return "\n".join(parts)
