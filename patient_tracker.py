"""
Patient Tracking for Multi-Session Beck Protocol
Extends the existing database with patient-level tracking
Does NOT modify existing tables - only ADDs new columns via ALTER TABLE
"""

import json
from database import get_db


def init_patient_tracking():
    """
    Initialize patient tracking by adding new columns to beck_sessions table.
    Safe to run multiple times - uses ALTER TABLE ADD COLUMN IF NOT EXISTS pattern.

    CRITICAL: This does NOT modify existing columns, only adds new ones.
    """
    db = get_db()

    # New columns to add to beck_sessions for full protocol support
    new_columns = [
        # Patient identification
        ("user_id_extended", "TEXT"),  # Redundant with session->user_id but denormalized for convenience

        # Session context
        ("session_number", "INTEGER DEFAULT 1"),
        ("previous_session_id", "TEXT"),

        # BDI-II assessment
        ("bdi_responses", "TEXT DEFAULT '{}'"),  # JSON: {0: 2, 1: 1, ...}
        ("bdi_score", "INTEGER"),
        ("bdi_severity", "TEXT"),  # "minimal", "mild", "moderate", "severe"

        # Session structure
        ("agenda_items", "TEXT"),  # What patient wanted to focus on
        ("homework_reviewed", "INTEGER DEFAULT 0"),  # Boolean: was homework reviewed?
        ("homework_completion_notes", "TEXT"),
        ("session_summary_text", "TEXT"),  # Agent-generated summary
        ("patient_feedback", "TEXT"),  # Patient's feedback on session

        # Advanced protocol features
        ("drdt_output", "TEXT"),  # Daily Record of Dysfunctional Thoughts formatted output
        ("schema_identified", "TEXT"),  # Core belief identified via downward arrow
        ("ba_stage", "TEXT"),  # For behavioral activation: "monitoring", "scheduling", "graded_task"
        ("ba_activities", "TEXT"),  # JSON: scheduled activities

        # Protocol state tracking
        ("full_protocol_state", "TEXT DEFAULT 'BDI_ASSESSMENT'"),  # Current state in 32-state protocol
        ("protocol_branch", "TEXT DEFAULT 'cognitive'"),  # "cognitive", "behavioral", "relapse"

        # Improvement tracking
        ("pre_session_mood", "INTEGER"),  # 0-10 mood before session
        ("post_session_mood", "INTEGER"),  # 0-10 mood after session

        # Timestamps for phases
        ("bdi_completed_at", "TEXT"),
        ("cognitive_work_started_at", "TEXT"),
        ("session_closed_at", "TEXT"),

        # Quality gate (CTS-R scores)
        ("quality_scores", "TEXT"),  # JSON: list of per-response CTS-R scores

        # Downward arrow data
        ("da_level_1", "TEXT"),
        ("da_level_2", "TEXT"),
        ("da_core_belief", "TEXT"),
        ("da_triggered", "INTEGER DEFAULT 0"),

        # Thought cluster linkage
        ("thought_cluster_id", "TEXT")
    ]

    for col_name, col_type in new_columns:
        try:
            db.conn.execute(
                f"ALTER TABLE beck_sessions ADD COLUMN {col_name} {col_type}"
            )
            print(f"✅ Added column: {col_name}")
        except Exception as e:
            # Column already exists or other error - safe to ignore
            if "duplicate column name" not in str(e).lower():
                print(f"ℹ️  Column {col_name}: {str(e)[:50]}...")

    # Create new patient_profiles table for cross-session data
    try:
        db.conn.execute("""
            CREATE TABLE IF NOT EXISTS patient_profiles (
                user_id TEXT PRIMARY KEY,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                -- Session tracking
                total_beck_sessions INTEGER DEFAULT 0,
                last_session_date TEXT,

                -- BDI trajectory
                bdi_scores TEXT DEFAULT '[]',  -- JSON: [{"date": "...", "score": 32}, ...]

                -- Longitudinal tracking
                core_beliefs TEXT DEFAULT '[]',  -- JSON: ["I am incompetent", ...]
                intermediate_beliefs TEXT DEFAULT '[]',  -- JSON: ["I must be perfect", ...]
                compensatory_strategies TEXT DEFAULT '[]',  -- JSON: ["Overworking", ...]
                recurring_distortions TEXT DEFAULT '{}',  -- JSON: {"G1": 5, "G2": 3, ...}

                -- Treatment phase
                current_treatment_phase TEXT DEFAULT 'assessment',

                -- Homework tracking
                homework_pending TEXT,  -- JSON: current homework assignment
                homework_history TEXT DEFAULT '[]',  -- JSON: past homework with completion

                -- Relapse prevention
                relapse_prevention_plan TEXT,  -- JSON: warning signs, coping strategies, contacts

                -- CCD cache
                ccd_data TEXT,  -- JSON: cached Cognitive Conceptualization Diagram

                -- Flags
                needs_ba_assessment INTEGER DEFAULT 0,  -- Flag for BA eligibility check
                in_relapse_prevention INTEGER DEFAULT 0,  -- Currently in RP phase

                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        print("✅ Created patient_profiles table")
    except Exception as e:
        print(f"ℹ️  patient_profiles table: {str(e)[:50]}...")

    # Add ccd_data column to existing deployments
    try:
        db.conn.execute("ALTER TABLE patient_profiles ADD COLUMN ccd_data TEXT")
        print("✅ Added column: ccd_data to patient_profiles")
    except Exception:
        pass  # Column already exists

    db.conn.commit()
    print("✅ Patient tracking initialization complete")


def get_patient_profile(user_id: str) -> dict:
    """Get or create patient profile."""
    db = get_db()

    cursor = db.conn.execute(
        "SELECT * FROM patient_profiles WHERE user_id = ?",
        (user_id,)
    )
    result = cursor.fetchone()

    if result:
        # Use the cursor's own description (more reliable than a LIMIT 0 query in libsql)
        description = cursor.description or []
        columns = [desc[0] for desc in description]
        if not columns:
            # Fallback: query PRAGMA for column names
            pragma = db.conn.execute("PRAGMA table_info(patient_profiles)").fetchall()
            columns = [row[1] for row in pragma] if pragma else []
        profile = dict(zip(columns, result))

        # Parse JSON fields
        for json_field in ['bdi_scores', 'core_beliefs', 'intermediate_beliefs',
                          'compensatory_strategies', 'recurring_distortions', 'homework_history']:
            if profile.get(json_field):
                try:
                    profile[json_field] = json.loads(profile[json_field])
                except:
                    profile[json_field] = [] if json_field != 'recurring_distortions' else {}

        return profile

    # Create new profile
    db.conn.execute(
        "INSERT INTO patient_profiles (user_id) VALUES (?)",
        (user_id,)
    )
    db.conn.commit()

    return get_patient_profile(user_id)


def update_patient_profile(user_id: str, **updates):
    """Update patient profile fields."""
    db = get_db()

    # Convert dicts/lists to JSON strings
    for key, value in updates.items():
        if isinstance(value, (dict, list)):
            updates[key] = json.dumps(value)

    if not updates:
        return

    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    values = tuple(list(updates.values()) + [user_id])

    db.conn.execute(
        f"UPDATE patient_profiles SET {set_clause} WHERE user_id = ?",
        values
    )
    db.conn.commit()


def add_bdi_score(user_id: str, score: int, severity: str, session_id: str = None):
    """Add a BDI score to patient's history."""
    profile = get_patient_profile(user_id)
    bdi_scores = profile.get('bdi_scores', [])

    bdi_scores.append({
        "date": json.loads(profile.get('last_session_date', 'null')) if profile.get('last_session_date') else None,
        "score": score,
        "severity": severity,
        "session_id": session_id
    })

    update_patient_profile(user_id, bdi_scores=bdi_scores)


def get_previous_session(user_id: str, current_session_id: str) -> dict:
    """Get the most recent completed Beck session for this user."""
    db = get_db()

    cursor = db.conn.execute(
        """SELECT * FROM beck_sessions
           WHERE session_id IN (
               SELECT id FROM sessions
               WHERE user_id = ? AND id != ? AND completed = 1
           )
           ORDER BY started_at DESC
           LIMIT 1""",
        (user_id, current_session_id)
    )
    result = cursor.fetchone()

    if result:
        description = cursor.description or []
        columns = [desc[0] for desc in description]
        if not columns:
            pragma = db.conn.execute("PRAGMA table_info(beck_sessions)").fetchall()
            columns = [row[1] for row in pragma] if pragma else []
        return dict(zip(columns, result))

    return None


def increment_session_count(user_id: str):
    """Increment total session count for patient."""
    db = get_db()
    db.conn.execute(
        """UPDATE patient_profiles
           SET total_beck_session = total_beck_sessions + 1,
               last_session_date = CURRENT_TIMESTAMP
           WHERE user_id = ?""",
        (user_id,)
    )
    db.conn.commit()


# Test if run directly
if __name__ == "__main__":
    print("Testing patient tracker:\n")
    print("⚠️  This module requires database connection")
    print("Run init_patient_tracking() from app.py startup")
