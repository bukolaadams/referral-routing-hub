import os
from flask import Flask, jsonify
import psycopg2

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_db_connection():
    """Return a new psycopg2 connection using the DATABASE_URL env var."""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return psycopg2.connect(DATABASE_URL)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
