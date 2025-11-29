# Email CRUD FastAPI

This project exposes a simple FastAPI service with CRUD endpoints to manage Email records (suitable for storing messages ingested from Gmail).

## Quickstart

1. Create and fill your `.env` (or export environment variables):

   Copy the example and adjust:
   
   ```
   cp .env.example .env
   ```

   Or set `DATABASE_URL` directly, e.g.:
   
   ```
   export DATABASE_URL="sqlite:///./mail.db"
   ```

2. Install dependencies (uses `uv` or pip):

   Using uv:
   
   ```
   uv pip install -e .
   ```

   Or with pip:
   
   ```
   pip install -e .
   ```

3. Run the API server:

   ```
   uvicorn app.main:app --reload
   ```

4. Visit docs:

   - Swagger UI: http://127.0.0.1:8000/docs
   - Health: http://127.0.0.1:8000/healthz

## Endpoints

- POST /emails — create
- GET /emails — list (skip, limit)
- GET /emails/{id} — retrieve
- PATCH /emails/{id} — partial update
- DELETE /emails/{id} — delete

## Notes

- By default will use SQLite at `./mail.db` if PostgreSQL vars are not set.
- For Postgres, prefer `psycopg2-binary` for local dev. In production, you may switch to `psycopg2`.

# Email Status CRUD (PostgreSQL)

This project includes a psycopg2-based CRUD for a table managing email status entries with strict status values.

## Table Schema

- Table: `email_status`
- Columns:
  - `id` bigint (identity/auto-increment primary key)
  - `created_at` timestamptz (defaults to `NOW()`)
  - `email` text (NOT NULL)
  - `status` text (NOT NULL; allowed values: `blacklist`, `whitelist`, `none`)

## Environment Configuration

Provide database connection settings via `.env`:

```
user=YOUR_DB_USER
password=YOUR_DB_PASSWORD
host=YOUR_DB_HOST
port=5432
dbname=YOUR_DB_NAME
```

An example is already present in `.env` using a Supabase Postgres instance.

## Dependencies

- psycopg2-binary
- python-dotenv

These are already declared in `pyproject.toml`. Install with:

```
uv pip install -e .
# or
pip install -e .
```

## CRUD Functions

Located in `app/crud.py`:
- `create_email_record(email: str, status: str) -> dict`
- `get_email_record(record_id: int) -> dict | None`
- `list_email_records(limit: int = 100, offset: int = 0) -> list[dict]`
- `update_email_record(record_id: int, email: str | None = None, status: str | None = None) -> dict | None`
- `delete_email_record(record_id: int) -> bool`
- `purge_invalid_statuses() -> int` (utility to remove rows with invalid status values)

Status enforcement:
- Allowed statuses: `blacklist`, `whitelist`, `none`.
- `create` and `update` validate the status and raise a `ValueError` if invalid.

## Create Table and Seed Mock Data

A small test runner `app/test_crud.py` will:
- Create the table if it does not exist.
- Purge any rows violating the status constraint.
- Seed valid mock data.
- Exercise all CRUD operations and print results.

Run it:

```
python app/test_crud.py
```

Expected output includes:
- Purged count, initial list, created rows, fetched row, updated row, deletion result, and final list.

## Optional: FastAPI (previous example)

The repository also contains a FastAPI example under `app/main.py` using SQLAlchemy for an `emails` model. This is independent from the `email_status` psycopg2 CRUD.
- To run the API:
  
  ```
  uvicorn app.main:app --reload
  ```
- Docs: http://127.0.0.1:8000/docs

If desired, we can expose `email_status` CRUD via FastAPI endpoints; open an issue or request and we’ll wire it up.
