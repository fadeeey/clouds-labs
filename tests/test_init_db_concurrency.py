import os
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
from psycopg import sql

from app.backend import server


class InitDbConcurrencyTests(unittest.TestCase):
    def test_two_backends_can_initialize_a_fresh_schema_at_once(self):
        database_url = os.environ["DATABASE_URL"]
        schema = f"init_race_{uuid.uuid4().hex}"
        original_connect = server.connect

        with psycopg.connect(database_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))
            )

        def connect_to_fixture():
            return psycopg.connect(
                database_url,
                connect_timeout=5,
                options=f"-c search_path={schema}",
            )

        barrier = threading.Barrier(2)
        server.connect = connect_to_fixture

        def initialize():
            barrier.wait(timeout=5)
            server.init_db()

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(initialize) for _ in range(2)]
                for future in futures:
                    future.result(timeout=15)

            with connect_to_fixture() as connection:
                table = connection.execute("SELECT to_regclass('tasks')").fetchone()[0]
            self.assertEqual(table, "tasks")
        finally:
            server.connect = original_connect
            with psycopg.connect(database_url, autocommit=True) as connection:
                connection.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                )


if __name__ == "__main__":
    unittest.main()
