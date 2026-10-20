import os
import unittest
import uuid

import psycopg

from app.backend.server import app, init_db


class TaskApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        app.config.update(TESTING=True)

    def setUp(self):
        self.client = app.test_client()
        self.marker = f"integration-check-{uuid.uuid4()}"

    def tearDown(self):
        with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
            connection.execute("DELETE FROM tasks WHERE title = %s", (self.marker,))

    def test_health_checks_real_database(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"database": "ok", "status": "ok"})

    def test_task_round_trip_persists_in_postgres(self):
        created = self.client.post("/api/tasks", json={"title": self.marker})
        self.assertEqual(created.status_code, 201)

        listed = self.client.get("/api/tasks")
        self.assertIn(
            {"id": created.get_json()["id"], "title": self.marker,
             "created_at": created.get_json()["created_at"]},
            listed.get_json(),
        )

    def test_blank_task_is_rejected(self):
        response = self.client.post("/api/tasks", json={"title": "  "})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
