"""
High School Management System API

A super simple FastAPI application that allows students to view and sign up
for extracurricular activities at Mergington High School.
"""

from contextlib import contextmanager
import sqlite3
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from seed_data import SEED_ACTIVITIES

app = FastAPI(title="Mergington High School API",
              description="API for viewing and signing up for extracurricular activities")

# Mount the static files directory
current_dir = Path(__file__).parent
app.mount("/static", StaticFiles(directory=os.path.join(Path(__file__).parent,
          "static")), name="static")

DB_PATH = current_dir / "activities.db"


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
    finally:
        conn.close()


def initialize_database():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                name TEXT,
                grade TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL,
                schedule TEXT NOT NULL,
                max_participants INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS enrollments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                activity_id INTEGER NOT NULL,
                FOREIGN KEY (user_email) REFERENCES users(email) ON DELETE CASCADE,
                FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE,
                UNIQUE(user_email, activity_id)
            )
            """
        )
        conn.commit()


def seed_database_if_empty():
    with get_connection() as conn:
        activity_count = conn.execute("SELECT COUNT(*) AS count FROM activities").fetchone()["count"]
        if activity_count > 0:
            return

        for activity in SEED_ACTIVITIES:
            conn.execute(
                """
                INSERT INTO activities (name, description, schedule, max_participants)
                VALUES (?, ?, ?, ?)
                """,
                (
                    activity["name"],
                    activity["description"],
                    activity["schedule"],
                    activity["max_participants"],
                ),
            )

            activity_id = conn.execute(
                "SELECT id FROM activities WHERE name = ?",
                (activity["name"],),
            ).fetchone()["id"]

            for email in activity["participants"]:
                conn.execute(
                    "INSERT OR IGNORE INTO users (email) VALUES (?)",
                    (email,),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO enrollments (user_email, activity_id)
                    VALUES (?, ?)
                    """,
                    (email, activity_id),
                )

        conn.commit()


@app.on_event("startup")
def startup():
    initialize_database()
    seed_database_if_empty()


@app.get("/")
def root():
    return RedirectResponse(url="/static/index.html")


@app.get("/activities")
def get_activities():
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                a.name AS activity_name,
                a.description,
                a.schedule,
                a.max_participants,
                e.user_email
            FROM activities a
            LEFT JOIN enrollments e ON e.activity_id = a.id
            ORDER BY a.name, e.user_email
            """
        ).fetchall()

    activities = {}
    for row in rows:
        name = row["activity_name"]
        if name not in activities:
            activities[name] = {
                "description": row["description"],
                "schedule": row["schedule"],
                "max_participants": row["max_participants"],
                "participants": [],
            }

        if row["user_email"]:
            activities[name]["participants"].append(row["user_email"])

    return activities


@app.post("/activities/{activity_name}/signup")
def signup_for_activity(activity_name: str, email: str):
    """Sign up a student for an activity"""
    with get_connection() as conn:
        activity = conn.execute(
            "SELECT id, max_participants FROM activities WHERE name = ?",
            (activity_name,),
        ).fetchone()

        if activity is None:
            raise HTTPException(status_code=404, detail="Activity not found")

        existing_enrollment = conn.execute(
            """
            SELECT 1
            FROM enrollments
            WHERE user_email = ? AND activity_id = ?
            """,
            (email, activity["id"]),
        ).fetchone()
        if existing_enrollment:
            raise HTTPException(status_code=400, detail="Student is already signed up")

        enrollment_count = conn.execute(
            "SELECT COUNT(*) AS count FROM enrollments WHERE activity_id = ?",
            (activity["id"],),
        ).fetchone()["count"]
        if enrollment_count >= activity["max_participants"]:
            raise HTTPException(status_code=400, detail="Activity is full")

        conn.execute(
            "INSERT OR IGNORE INTO users (email) VALUES (?)",
            (email,),
        )
        try:
            conn.execute(
                "INSERT INTO enrollments (user_email, activity_id) VALUES (?, ?)",
                (email, activity["id"]),
            )
        except sqlite3.IntegrityError as exc:
            # This catches race conditions and enforces DB-level duplicate safety.
            if "UNIQUE constraint failed" in str(exc):
                raise HTTPException(status_code=400, detail="Student is already signed up") from exc
            raise
        conn.commit()

    return {"message": f"Signed up {email} for {activity_name}"}


@app.delete("/activities/{activity_name}/unregister")
def unregister_from_activity(activity_name: str, email: str):
    """Unregister a student from an activity"""
    with get_connection() as conn:
        activity = conn.execute(
            "SELECT id FROM activities WHERE name = ?",
            (activity_name,),
        ).fetchone()

        if activity is None:
            raise HTTPException(status_code=404, detail="Activity not found")

        result = conn.execute(
            "DELETE FROM enrollments WHERE user_email = ? AND activity_id = ?",
            (email, activity["id"]),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=400, detail="Student is not signed up for this activity")

        conn.commit()

    return {"message": f"Unregistered {email} from {activity_name}"}
