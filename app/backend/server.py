import os
import time
from pathlib import Path

import psycopg
from flask import Flask, jsonify, request, send_from_directory


FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required; see .env.example")

app = Flask(__name__, static_folder=None)
BACKEND_ID = os.environ.get("BACKEND_ID", "backend-1")


@app.after_request
def identify_backend(response):
    response.headers["X-Backend-ID"] = BACKEND_ID
    return response


def connect():
    return psycopg.connect(DATABASE_URL, connect_timeout=5)


def init_db():
    for attempt in range(30):
        try:
            with connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tasks (
                        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                        title TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 200),
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
            return
        except psycopg.OperationalError:
            if attempt == 29:
                raise
            print(f"PostgreSQL isn't ready yet; retrying ({attempt + 1}/30).", flush=True)
            time.sleep(1)


@app.get("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.get("/assets/<path:filename>")
def frontend_asset(filename):
    return send_from_directory(FRONTEND_DIR, filename)


@app.get("/api/tasks")
def list_tasks():
    with connect() as connection:
        rows = connection.execute(
            "SELECT id, title, created_at FROM tasks ORDER BY id DESC"
        ).fetchall()
    return jsonify(
        [
            {"id": row[0], "title": row[1], "created_at": row[2].isoformat()}
            for row in rows
        ]
    )


@app.post("/api/tasks")
def create_task():
    data = request.get_json(silent=True)
    title = data.get("title", "") if isinstance(data, dict) else ""
    if not isinstance(title, str):
        return jsonify(error="Название должно быть текстом."), 400
    title = title.strip()
    if not title or len(title) > 200:
        return jsonify(error="Введите название длиной от 1 до 200 символов."), 400

    with connect() as connection:
        row = connection.execute(
            "INSERT INTO tasks (title) VALUES (%s) RETURNING id, title, created_at",
            (title,),
        ).fetchone()
    return (
        jsonify(id=row[0], title=row[1], created_at=row[2].isoformat()),
        201,
    )


@app.get("/health")
def health():
    with connect() as connection:
        connection.execute("SELECT 1")
    return jsonify(status="ok", database="ok")


@app.get("/live")
def live():
    return jsonify(status="alive")


if __name__ == "__main__":
    init_db()
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=False,
    )
