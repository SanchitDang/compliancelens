import os
from typing import Any

import pg8000.dbapi


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    connection = pg8000.dbapi.connect(
        host=os.environ["DATABASE_HOST"],
        port=int(os.environ["DATABASE_PORT"]),
        user=os.environ["DATABASE_USER"],
        password=os.environ["DATABASE_PASSWORD"],
        database=os.environ["DATABASE_NAME"],
        timeout=10,
        ssl_context=False,
    )
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT 1, (SELECT extversion FROM pg_extension WHERE extname = 'vector')")
        row = cursor.fetchone()
        return {"sql_result": row[0], "vector_version": row[1]}
    finally:
        connection.close()
