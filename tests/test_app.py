import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

import app as app_module  # noqa: E402
from seed_data import SEED_ACTIVITIES  # noqa: E402


class ActivitiesPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._original_db_path = app_module.DB_PATH

    @classmethod
    def tearDownClass(cls):
        app_module.DB_PATH = cls._original_db_path

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        app_module.DB_PATH = Path(self.temp_dir.name) / "activities.db"
        app_module.initialize_database()
        app_module.seed_database_if_empty()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_seeded_activities_match_expected_shape(self):
        activities = app_module.get_activities()

        self.assertEqual(len(activities), len(SEED_ACTIVITIES))
        self.assertIn("Chess Club", activities)
        self.assertEqual(
            set(activities["Chess Club"].keys()),
            {"description", "schedule", "max_participants", "participants"},
        )

    def test_signup_persists_and_duplicate_signup_is_rejected(self):
        email = "unit-test-signup@mergington.edu"

        result = app_module.signup_for_activity("Chess Club", email)
        self.assertIn("Signed up", result["message"])

        updated = app_module.get_activities()
        self.assertIn(email, updated["Chess Club"]["participants"])

        with self.assertRaises(HTTPException) as context:
            app_module.signup_for_activity("Chess Club", email)

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail, "Student is already signed up")

    def test_enrollments_table_enforces_unique_user_activity_pair(self):
        email = "db-constraint-test@mergington.edu"

        with app_module.get_connection() as conn:
            activity_id = conn.execute(
                "SELECT id FROM activities WHERE name = ?",
                ("Chess Club",),
            ).fetchone()["id"]

            conn.execute(
                "INSERT OR IGNORE INTO users (email) VALUES (?)",
                (email,),
            )
            conn.execute(
                "INSERT INTO enrollments (user_email, activity_id) VALUES (?, ?)",
                (email, activity_id),
            )

            with self.assertRaises(sqlite3.IntegrityError) as context:
                conn.execute(
                    "INSERT INTO enrollments (user_email, activity_id) VALUES (?, ?)",
                    (email, activity_id),
                )

        self.assertIn(
            "UNIQUE constraint failed: enrollments.user_email, enrollments.activity_id",
            str(context.exception),
        )

    def test_unregister_removes_enrollment_and_second_unregister_fails(self):
        email = "unit-test-unregister@mergington.edu"
        app_module.signup_for_activity("Math Club", email)

        result = app_module.unregister_from_activity("Math Club", email)
        self.assertIn("Unregistered", result["message"])

        updated = app_module.get_activities()
        self.assertNotIn(email, updated["Math Club"]["participants"])

        with self.assertRaises(HTTPException) as context:
            app_module.unregister_from_activity("Math Club", email)

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(
            context.exception.detail,
            "Student is not signed up for this activity",
        )

    def test_nonexistent_activity_raises_not_found(self):
        with self.assertRaises(HTTPException) as signup_context:
            app_module.signup_for_activity("Nonexistent Club", "someone@mergington.edu")

        self.assertEqual(signup_context.exception.status_code, 404)
        self.assertEqual(signup_context.exception.detail, "Activity not found")

        with self.assertRaises(HTTPException) as unregister_context:
            app_module.unregister_from_activity("Nonexistent Club", "someone@mergington.edu")

        self.assertEqual(unregister_context.exception.status_code, 404)
        self.assertEqual(unregister_context.exception.detail, "Activity not found")


if __name__ == "__main__":
    unittest.main()