from typing import Optional, List, Dict, Any
from psycopg2 import sql
from .database import get_connection

TABLE_NAME = "email_status"
ALLOWED_STATUSES = {"blacklist", "whitelist", "none"}


def _validate_status(status: Optional[str]):
    if status is None:
        raise ValueError("status is required and must be one of: blacklist, whitelist, none")
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Allowed: {', '.join(sorted(ALLOWED_STATUSES))}")


def purge_invalid_statuses() -> int:
    """Delete rows whose status is not one of the allowed values. Returns count deleted."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "DELETE FROM {table} WHERE status NOT IN (%s, %s, %s);"
                ).format(table=sql.Identifier(TABLE_NAME)),
                tuple(sorted(ALLOWED_STATUSES)),
            )
            deleted = cur.rowcount
            conn.commit()
            return deleted


def create_email_record(email: str, status: str) -> Dict[str, Any]:
    _validate_status(status)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    """
                    INSERT INTO {table} (email, status)
                    VALUES (%s, %s)
                    RETURNING id, created_at, email, status;
                    """
                ).format(table=sql.Identifier(TABLE_NAME)),
                (email, status),
            )
            row = cur.fetchone()
            return dict(row)


def get_email_record(record_id: int) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "SELECT id, created_at, email, status FROM {table} WHERE id = %s;"
                ).format(table=sql.Identifier(TABLE_NAME)),
                (record_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def list_email_records(limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    """
                    SELECT id, created_at, email, status
                    FROM {table}
                    ORDER BY id DESC
                    LIMIT %s OFFSET %s;
                    """
                ).format(table=sql.Identifier(TABLE_NAME)),
                (limit, offset),
            )
            rows = cur.fetchall()
            return [dict(r) for r in rows]


def update_email_record(record_id: int, *, email: Optional[str] = None, status: Optional[str] = None) -> Optional[Dict[str, Any]]:
    fields = []
    values = []
    if email is not None:
        fields.append(sql.SQL("email = %s"))
        values.append(email)
    if status is not None:
        _validate_status(status)
        fields.append(sql.SQL("status = %s"))
        values.append(status)

    if not fields:
        return get_email_record(record_id)

    with get_connection() as conn:
        with conn.cursor() as cur:
            values.append(record_id)
            cur.execute(
                sql.SQL("UPDATE {table} SET ")
                .format(table=sql.Identifier(TABLE_NAME))
                + sql.SQL(", ").join(fields)
                + sql.SQL(" WHERE id = %s RETURNING id, created_at, email, status;"),
                values,
            )
            row = cur.fetchone()
            return dict(row) if row else None


def delete_email_record(record_id: int) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("DELETE FROM {table} WHERE id = %s;").format(table=sql.Identifier(TABLE_NAME)),
                (record_id,),
            )
            deleted = cur.rowcount
            conn.commit()
            return deleted > 0
