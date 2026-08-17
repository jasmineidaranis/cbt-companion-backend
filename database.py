"""
Database Module - Turso (libSQL) Connection
Handles all database operations for the CBT Companion app
"""

import os
import libsql as libsql
from datetime import datetime, date, timezone, timedelta
import uuid
import json

# IST = UTC+5:30
_IST = timezone(timedelta(hours=5, minutes=30))

def ist_now() -> str:
    """Return current IST time as ISO string for storing in DB."""
    return datetime.now(_IST).strftime("%Y-%m-%d %H:%M:%S")


class Database:
    """
    Database handler for Turso (libSQL).
    
    Required environment variables:
    - TURSO_DATABASE_URL: Your Turso database URL
    - TURSO_AUTH_TOKEN: Your Turso auth token
    """
    
    def __init__(self):
        url = os.environ.get("TURSO_DATABASE_URL")
        token = os.environ.get("TURSO_AUTH_TOKEN")
        
        if not url or not token:
            raise ValueError("TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are required")
        
        self.conn = libsql.connect(database=url, auth_token=token)
        self._init_tables()
        print("✅ Database connected to Turso")
    
    def _init_tables(self):
        """Create tables if they don't exist."""
        
        # Users table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                name TEXT NOT NULL,
                context TEXT DEFAULT 'person',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                fcm_token TEXT
            )
        """)
        # Add fcm_token column to existing deployments that lack it
        try:
            self.conn.execute("ALTER TABLE users ADD COLUMN fcm_token TEXT")
            self.conn.commit()
        except Exception:
            pass  # Column already exists
        # Add last_fcm_sent column for cooldown tracking
        try:
            self.conn.execute("ALTER TABLE users ADD COLUMN last_fcm_sent TEXT")
            self.conn.commit()
        except Exception:
            pass  # Column already exists
        
        # Sessions table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                ended_at TEXT,
                mood_start INTEGER,
                mood_end INTEGER,
                locked_group TEXT,
                stages_reached INTEGER DEFAULT 1,
                completed INTEGER DEFAULT 0,
                messages_in_current_stage INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        
        # Messages table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES sessions(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        
        # Exercises completed
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS exercises_completed (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                session_id TEXT,
                exercise_id TEXT NOT NULL,
                exercise_name TEXT,
                group_type TEXT,
                completed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        
        # Crisis flags
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS crisis_flags (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                user_name TEXT NOT NULL,
                user_email TEXT NOT NULL,
                session_id TEXT NOT NULL,
                message_content TEXT NOT NULL,
                trigger_word TEXT NOT NULL,
                flagged_at TEXT DEFAULT CURRENT_TIMESTAMP,
                reviewed INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)
        
        # User stats
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id TEXT PRIMARY KEY,
                total_sessions INTEGER DEFAULT 0,
                total_exercises INTEGER DEFAULT 0,
                current_streak INTEGER DEFAULT 0,
                last_session_date TEXT,
                distortion_counts TEXT DEFAULT '{}',
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Wearable sensor data
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS wearable_data (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                ppg REAL NOT NULL,
                gsr REAL NOT NULL,
                acc_x REAL NOT NULL,
                acc_y REAL NOT NULL,
                acc_z REAL NOT NULL,
                device_timestamp TEXT,
                recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS session_markers (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                label TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Migrate: add columns that may be missing from older table versions
        for col, col_type, default in [
            ("dri_score", "REAL", None),
            ("condition", "TEXT", None),
            ("acknowledged", "INTEGER", "0"),
            ("ml_prediction", "TEXT", None),
            ("ml_confidence", "REAL", None),
            ("risk_level", "INTEGER", None),
        ]:
            try:
                default_clause = f" DEFAULT {default}" if default is not None else ""
                self.conn.execute(
                    f"ALTER TABLE wearable_data ADD COLUMN {col} {col_type}{default_clause}"
                )
            except Exception:
                pass  # Column already exists

        # Create index for faster queries on wearable data
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_wearable_user_time
            ON wearable_data(user_id, recorded_at DESC)
        """)

        # Device API keys for wearables
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS device_keys (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                api_key TEXT UNIQUE NOT NULL,
                device_name TEXT DEFAULT 'ESP32 Wearable',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_used_at TEXT,
                is_active INTEGER DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Index for fast API key lookups
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_device_api_key
            ON device_keys(api_key)
        """)

        # Beck sessions table for cognitive restructuring protocol
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS beck_sessions (
                session_id TEXT PRIMARY KEY,

                -- Current state in the protocol
                beck_state TEXT DEFAULT 'VALIDATE',

                -- Phase 1: Capture
                original_thought TEXT,
                initial_belief_rating INTEGER,
                emotion TEXT,
                initial_emotion_intensity INTEGER,

                -- Phase 2: Discovery (6 Questions)
                q1_evidence_for TEXT,
                q1_evidence_against TEXT,
                q2_alternative TEXT,
                q3_worst TEXT,
                q3_best TEXT,
                q3_realistic TEXT,
                q4_effect TEXT,
                q5_friend TEXT,
                q6_action TEXT,

                -- Phase 3: Reframe
                adaptive_thought TEXT,
                new_thought_belief INTEGER,

                -- Phase 4: Measure
                final_belief_rating INTEGER,
                final_emotion_intensity INTEGER,

                -- Phase 5: Action
                action_plan TEXT,

                -- Metadata
                started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                belief_improvement INTEGER,
                emotion_improvement INTEGER,

                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)

        # ML window predictions — one row per inference call (every 25 readings)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS ml_window_predictions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                prediction TEXT NOT NULL,
                risk_level INTEGER NOT NULL,
                confidence REAL NOT NULL,
                readings_used INTEGER DEFAULT 25,
                predicted_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ml_window_user_time
            ON ml_window_predictions(user_id, predicted_at DESC)
        """)

        # Depression episodes table (ML-detected high stress periods)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS depression_episodes (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                peak_risk_level INTEGER,
                total_readings INTEGER DEFAULT 0,
                avg_confidence REAL,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Index for fast episode lookups
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_depression_episodes_user
            ON depression_episodes(user_id, is_active DESC)
        """)

        self.conn.commit()
    
    # ==================== USER OPERATIONS ====================
    
    def create_user(self, email: str, password_hash: str, name: str, context: str = "person") -> dict:
        """Create a new user."""
        user_id = str(uuid.uuid4())
        
        try:
            self.conn.execute(
                "INSERT INTO users (id, email, password_hash, name, context) VALUES (?, ?, ?, ?, ?)",
                (user_id, email.lower(), password_hash, name, context)
            )
            
            # Initialize user stats
            self.conn.execute(
                "INSERT INTO user_stats (user_id) VALUES (?)",
                (user_id,)
            )
            
            self.conn.commit()
            
            return {"id": user_id, "email": email, "name": name, "context": context}
        
        except Exception as e:
            if "UNIQUE constraint" in str(e):
                raise ValueError("Email already exists")
            raise e
    
    def get_user_by_email(self, email: str) -> dict:
        """Get user by email."""
        result = self.conn.execute(
            "SELECT id, email, password_hash, name, context FROM users WHERE email = ?",
            (email.lower(),)
        ).fetchone()
        
        if result:
            return {
                "id": result[0],
                "email": result[1],
                "password_hash": result[2],
                "name": result[3],
                "context": result[4]
            }
        return None
    
    def get_user_by_id(self, user_id: str) -> dict:
        """Get user by ID."""
        result = self.conn.execute(
            "SELECT id, email, name, context FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()
        
        if result:
            return {
                "id": result[0],
                "email": result[1],
                "name": result[2],
                "context": result[3]
            }
        return None
    
    def save_fcm_token(self, user_id: str, token: str):
        """Save or update FCM device token for a user."""
        self.conn.execute(
            "UPDATE users SET fcm_token = ? WHERE id = ?",
            (token, user_id)
        )
        self.conn.commit()

    def get_fcm_token(self, user_id: str) -> str:
        """Get the FCM token for a user, or None."""
        result = self.conn.execute(
            "SELECT fcm_token FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()
        return result[0] if result else None

    def fcm_cooldown_ok(self, user_id: str, cooldown_minutes: int = 30) -> bool:
        """Return True if enough time has passed since the last FCM push."""
        result = self.conn.execute(
            "SELECT last_fcm_sent FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not result or not result[0]:
            return True
        try:
            last = datetime.fromisoformat(result[0])
            return (datetime.now(_IST) - last).total_seconds() >= cooldown_minutes * 60
        except Exception:
            return True

    def update_fcm_sent_time(self, user_id: str):
        """Record the current UTC time as the last FCM send for cooldown tracking."""
        self.conn.execute(
            "UPDATE users SET last_fcm_sent = ? WHERE id = ?",
            (ist_now(), user_id)
        )
        self.conn.commit()

    # ==================== SESSION OPERATIONS ====================

    def create_session(self, user_id: str) -> str:
        """Create a new chat session."""
        session_id = str(uuid.uuid4())
        
        self.conn.execute(
            "INSERT INTO sessions (id, user_id) VALUES (?, ?)",
            (session_id, user_id)
        )
        self.conn.commit()
        
        return session_id
    
    def get_session(self, session_id: str) -> dict:
        """Get session by ID."""
        result = self.conn.execute(
            """SELECT id, user_id, started_at, ended_at, mood_start, mood_end, 
                      locked_group, stages_reached, completed, messages_in_current_stage
               FROM sessions WHERE id = ?""",
            (session_id,)
        ).fetchone()
        
        if result:
            return {
                "id": result[0],
                "user_id": result[1],
                "started_at": result[2],
                "ended_at": result[3],
                "mood_start": result[4],
                "mood_end": result[5],
                "locked_group": result[6],
                "current_stage": result[7],
                "completed": bool(result[8]),
                "messages_in_current_stage": result[9] or 0,
                "state": "COMPLETED" if result[8] else ("IN_PROGRESS" if result[6] else "WAITING_FOR_PROBLEM")
            }
        return None
    
    def update_session(self, session_id: str, **kwargs):
        """Update session fields."""
        allowed_fields = {
            "mood_start", "mood_end", "locked_group", "stages_reached", 
            "completed", "ended_at", "messages_in_current_stage"
        }
        
        updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
        
        if not updates:
            return
        
        # Map stages_reached to the column
        if "current_stage" in kwargs:
            updates["stages_reached"] = kwargs["current_stage"]
        
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        values = tuple(list(updates.values()) + [session_id])

        self.conn.execute(
            f"UPDATE sessions SET {set_clause} WHERE id = ?",
            values
        )
        self.conn.commit()
    
    def increment_stage_messages(self, session_id: str) -> int:
        """Increment message counter for current stage."""
        self.conn.execute(
            "UPDATE sessions SET messages_in_current_stage = messages_in_current_stage + 1 WHERE id = ?",
            (session_id,)
        )
        self.conn.commit()
        
        result = self.conn.execute(
            "SELECT messages_in_current_stage FROM sessions WHERE id = ?",
            (session_id,)
        ).fetchone()
        
        return result[0] if result else 0
    
    def reset_stage_messages(self, session_id: str):
        """Reset message counter (called when advancing stage)."""
        self.conn.execute(
            "UPDATE sessions SET messages_in_current_stage = 0 WHERE id = ?",
            (session_id,)
        )
        self.conn.commit()
    
    def get_user_sessions(self, user_id: str, limit: int = 20) -> list:
        """Get user's past sessions."""
        results = self.conn.execute(
            """SELECT id, started_at, ended_at, mood_start, mood_end, 
                      locked_group, stages_reached, completed
               FROM sessions WHERE user_id = ? 
               ORDER BY started_at DESC LIMIT ?""",
            (user_id, limit)
        ).fetchall()
        
        return [
            {
                "id": r[0],
                "started_at": r[1],
                "ended_at": r[2],
                "mood_start": r[3],
                "mood_end": r[4],
                "locked_group": r[5],
                "stages_reached": r[6],
                "completed": bool(r[7])
            }
            for r in results
        ]
    
    # ==================== MESSAGE OPERATIONS ====================
    
    def add_message(self, session_id: str, user_id: str, role: str, content: str):
        """Add a message to conversation history."""
        message_id = str(uuid.uuid4())
        
        self.conn.execute(
            "INSERT INTO messages (id, session_id, user_id, role, content) VALUES (?, ?, ?, ?, ?)",
            (message_id, session_id, user_id, role, content)
        )
        self.conn.commit()
    
    def get_session_messages(self, session_id: str, limit: int = None) -> list:
        """Get messages for a session."""
        query = """SELECT role, content, timestamp FROM messages 
                   WHERE session_id = ? ORDER BY timestamp ASC"""
        
        if limit:
            query += f" LIMIT {limit}"
        
        results = self.conn.execute(query, (session_id,)).fetchall()
        
        return [
            {"role": r[0], "content": r[1], "timestamp": r[2]}
            for r in results
        ]
    
    def get_recent_messages(self, session_id: str, n: int = 6) -> list:
        """Get last n messages for context window."""
        results = self.conn.execute(
            """SELECT role, content FROM messages 
               WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?""",
            (session_id, n)
        ).fetchall()
        
        # Reverse to get chronological order
        return [{"role": r[0], "content": r[1]} for r in reversed(results)]
    
    # ==================== EXERCISE OPERATIONS ====================
    
    def log_exercise_completed(self, user_id: str, session_id: str, exercise_id: str, 
                                exercise_name: str, group_type: str):
        """Log a completed exercise."""
        entry_id = str(uuid.uuid4())
        
        self.conn.execute(
            """INSERT INTO exercises_completed 
               (id, user_id, session_id, exercise_id, exercise_name, group_type) 
               VALUES (?, ?, ?, ?, ?, ?)""",
            (entry_id, user_id, session_id, exercise_id, exercise_name, group_type)
        )
        
        # Update user stats
        self.conn.execute(
            "UPDATE user_stats SET total_exercises = total_exercises + 1 WHERE user_id = ?",
            (user_id,)
        )
        
        self.conn.commit()
    
    # ==================== CRISIS FLAG OPERATIONS ====================
    
    def flag_crisis(self, user_id: str, user_name: str, user_email: str,
                    session_id: str, message_content: str, trigger_word: str):
        """Flag a crisis message."""
        flag_id = str(uuid.uuid4())
        
        self.conn.execute(
            """INSERT INTO crisis_flags 
               (id, user_id, user_name, user_email, session_id, message_content, trigger_word) 
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (flag_id, user_id, user_name, user_email, session_id, message_content, trigger_word)
        )
        self.conn.commit()
        
        print(f"🚨 CRISIS FLAGGED: User {user_name} ({user_email}) - Trigger: {trigger_word}")
    
    # ==================== STATS OPERATIONS ====================
    
    def get_user_stats(self, user_id: str) -> dict:
        """Get user statistics."""
        result = self.conn.execute(
            """SELECT total_sessions, total_exercises, current_streak, 
                      last_session_date, distortion_counts
               FROM user_stats WHERE user_id = ?""",
            (user_id,)
        ).fetchone()
        
        if result:
            return {
                "total_sessions": result[0],
                "total_exercises": result[1],
                "current_streak": result[2],
                "last_session_date": result[3],
                "distortion_counts": json.loads(result[4] or "{}")
            }
        
        return {
            "total_sessions": 0,
            "total_exercises": 0,
            "current_streak": 0,
            "last_session_date": None,
            "distortion_counts": {}
        }
    
    def update_user_stats_on_session_end(self, user_id: str, locked_group: str):
        """Update user stats when a session ends."""
        today = date.today().isoformat()
        
        # Get current stats
        stats = self.get_user_stats(user_id)
        
        # Update distortion counts
        distortion_counts = stats["distortion_counts"]
        if locked_group and locked_group != "G0":
            distortion_counts[locked_group] = distortion_counts.get(locked_group, 0) + 1
        
        # Calculate streak
        last_date = stats["last_session_date"]
        if last_date == today:
            new_streak = stats["current_streak"]
        elif last_date == (date.today().replace(day=date.today().day - 1)).isoformat():
            new_streak = stats["current_streak"] + 1
        else:
            new_streak = 1
        
        # Update stats
        self.conn.execute(
            """UPDATE user_stats SET 
               total_sessions = total_sessions + 1,
               current_streak = ?,
               last_session_date = ?,
               distortion_counts = ?
               WHERE user_id = ?""",
            (new_streak, today, json.dumps(distortion_counts), user_id)
        )
        self.conn.commit()

    # ==================== WEARABLE DATA OPERATIONS ====================

    def save_wearable_data(self, user_id: str, ppg: float, gsr: float,
                           acc_x: float, acc_y: float, acc_z: float,
                           device_timestamp: str = None) -> str:
        """Save wearable sensor data."""
        record_id = str(uuid.uuid4())

        self.conn.execute(
            """INSERT INTO wearable_data
               (id, user_id, ppg, gsr, acc_x, acc_y, acc_z, device_timestamp, recorded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (record_id, user_id, ppg, gsr, acc_x, acc_y, acc_z, device_timestamp, ist_now())
        )
        self.conn.commit()

        return record_id

    def get_latest_wearable_data(self, user_id: str) -> dict:
        """Get the most recent wearable data for a user."""
        result = self.conn.execute(
            """SELECT id, ppg, gsr, acc_x, acc_y, acc_z, device_timestamp, recorded_at
               FROM wearable_data WHERE user_id = ?
               ORDER BY recorded_at DESC LIMIT 1""",
            (user_id,)
        ).fetchone()

        if result:
            return {
                "id": result[0],
                "ppg": result[1],
                "gsr": result[2],
                "acc_x": result[3],
                "acc_y": result[4],
                "acc_z": result[5],
                "device_timestamp": result[6],
                "recorded_at": result[7]
            }
        return None

    def get_wearable_history(self, user_id: str, limit: int = 100,
                             offset: int = 0, start_date: str = None,
                             end_date: str = None) -> list:
        """Get wearable data history for a user."""
        query = """SELECT id, ppg, gsr, acc_x, acc_y, acc_z, device_timestamp, recorded_at
                   FROM wearable_data WHERE user_id = ?"""
        params = [user_id]

        if start_date:
            query += " AND recorded_at >= ?"
            params.append(start_date)

        if end_date:
            query += " AND recorded_at <= ?"
            params.append(end_date)

        query += " ORDER BY recorded_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        results = self.conn.execute(query, tuple(params)).fetchall()

        return [
            {
                "id": r[0],
                "ppg": r[1],
                "gsr": r[2],
                "acc_x": r[3],
                "acc_y": r[4],
                "acc_z": r[5],
                "device_timestamp": r[6],
                "recorded_at": r[7]
            }
            for r in results
        ]

    def get_wearable_stats(self, user_id: str, period: str = "day") -> dict:
        """Get aggregated statistics for wearable data."""
        # Calculate date filter based on period
        if period == "day":
            date_filter = "datetime('now', '-1 day')"
        elif period == "week":
            date_filter = "datetime('now', '-7 days')"
        else:  # month
            date_filter = "datetime('now', '-30 days')"

        result = self.conn.execute(
            f"""SELECT
                COUNT(*) as count,
                AVG(ppg) as avg_ppg,
                MIN(ppg) as min_ppg,
                MAX(ppg) as max_ppg,
                AVG(gsr) as avg_gsr,
                MIN(gsr) as min_gsr,
                MAX(gsr) as max_gsr,
                AVG(acc_x) as avg_acc_x,
                AVG(acc_y) as avg_acc_y,
                AVG(acc_z) as avg_acc_z
               FROM wearable_data
               WHERE user_id = ? AND recorded_at >= {date_filter}""",
            (user_id,)
        ).fetchone()

        if result and result[0] > 0:
            return {
                "reading_count": result[0],
                "ppg": {
                    "avg": round(result[1], 2) if result[1] else None,
                    "min": round(result[2], 2) if result[2] else None,
                    "max": round(result[3], 2) if result[3] else None
                },
                "gsr": {
                    "avg": round(result[4], 4) if result[4] else None,
                    "min": round(result[5], 4) if result[5] else None,
                    "max": round(result[6], 4) if result[6] else None
                },
                "accelerometer": {
                    "avg_x": round(result[7], 4) if result[7] else None,
                    "avg_y": round(result[8], 4) if result[8] else None,
                    "avg_z": round(result[9], 4) if result[9] else None
                }
            }

        return {
            "reading_count": 0,
            "ppg": {"avg": None, "min": None, "max": None},
            "gsr": {"avg": None, "min": None, "max": None},
            "accelerometer": {"avg_x": None, "avg_y": None, "avg_z": None}
        }

    # ==================== DEVICE KEY OPERATIONS ====================

    def create_device_key(self, user_id: str, device_name: str = "ESP32 Wearable") -> dict:
        """Create a new device API key for a user."""
        import secrets

        key_id = str(uuid.uuid4())
        # Generate a secure 32-character API key
        api_key = secrets.token_hex(16)

        self.conn.execute(
            """INSERT INTO device_keys (id, user_id, api_key, device_name)
               VALUES (?, ?, ?, ?)""",
            (key_id, user_id, api_key, device_name)
        )
        self.conn.commit()

        return {
            "id": key_id,
            "api_key": api_key,
            "device_name": device_name,
            "created_at": ist_now()
        }

    def get_user_by_device_key(self, api_key: str) -> dict:
        """Get user associated with a device API key."""
        result = self.conn.execute(
            """SELECT u.id, u.email, u.name, u.context, dk.id as device_id
               FROM device_keys dk
               JOIN users u ON dk.user_id = u.id
               WHERE dk.api_key = ? AND dk.is_active = 1""",
            (api_key,)
        ).fetchone()

        if result:
            # Update last_used_at
            self.conn.execute(
                "UPDATE device_keys SET last_used_at = ? WHERE api_key = ?",
                (ist_now(), api_key)
            )
            self.conn.commit()

            return {
                "id": result[0],
                "email": result[1],
                "name": result[2],
                "context": result[3],
                "device_id": result[4]
            }
        return None

    def get_user_device_keys(self, user_id: str) -> list:
        """Get all device keys for a user."""
        results = self.conn.execute(
            """SELECT id, api_key, device_name, created_at, last_used_at, is_active
               FROM device_keys
               WHERE user_id = ?
               ORDER BY created_at DESC""",
            (user_id,)
        ).fetchall()

        return [
            {
                "id": r[0],
                "api_key": r[1][:8] + "..." + r[1][-4:],  # Masked for security
                "device_name": r[2],
                "created_at": r[3],
                "last_used_at": r[4],
                "is_active": bool(r[5])
            }
            for r in results
        ]

    def revoke_device_key(self, key_id: str, user_id: str) -> bool:
        """Revoke a device API key."""
        # Pre-check existence — libsql rowcount is unreliable for UPDATE
        exists = self.conn.execute(
            "SELECT id FROM device_keys WHERE id = ? AND user_id = ?",
            (key_id, user_id)
        ).fetchone()
        if not exists:
            return False
        self.conn.execute(
            "UPDATE device_keys SET is_active = 0 WHERE id = ? AND user_id = ?",
            (key_id, user_id)
        )
        self.conn.commit()
        return True

    def delete_device_key(self, key_id: str, user_id: str) -> bool:
        """Permanently delete a device API key."""
        result = self.conn.execute(
            "DELETE FROM device_keys WHERE id = ? AND user_id = ?",
            (key_id, user_id)
        )
        self.conn.commit()
        return result.rowcount > 0

    # ==================== ADMIN OPERATIONS ====================

    def get_all_users(self) -> list:
        """Get all users with basic info for admin panel."""
        results = self.conn.execute(
            """SELECT u.id, u.email, u.name, u.context, u.created_at,
                      s.total_sessions, s.total_exercises, s.current_streak, s.last_session_date
               FROM users u
               LEFT JOIN user_stats s ON u.id = s.user_id
               ORDER BY u.created_at DESC"""
        ).fetchall()

        users = []
        for r in results:
            # Count crisis flags for this user
            flag_count = self.conn.execute(
                "SELECT COUNT(*) FROM crisis_flags WHERE user_id = ? AND reviewed = 0",
                (r[0],)
            ).fetchone()[0]

            # Check for active ML-detected risk episode
            active_ep = self.conn.execute(
                "SELECT COUNT(*) FROM depression_episodes WHERE user_id = ? AND is_active = 1",
                (r[0],)
            ).fetchone()[0]

            users.append({
                "id": r[0],
                "email": r[1],
                "name": r[2],
                "context": r[3],
                "created_at": r[4],
                "total_sessions": r[5] or 0,
                "total_exercises": r[6] or 0,
                "current_streak": r[7] or 0,
                "last_session_date": r[8],
                "unreviewed_alerts": flag_count,
                "has_active_episode": active_ep > 0,
            })

        return users

    def get_user_full_details(self, user_id: str) -> dict:
        """Get complete user data for admin patient detail view."""
        user = self.get_user_by_id(user_id)
        if not user:
            return None

        # Get user stats
        stats = self.get_user_stats(user_id)

        # Get created_at
        created_at = self.conn.execute(
            "SELECT created_at FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()

        # Get sessions
        sessions = self.get_user_sessions(user_id, limit=50)

        # Get crisis history
        crisis_flags = self.conn.execute(
            """SELECT id, session_id, message_content, trigger_word, flagged_at, reviewed
               FROM crisis_flags WHERE user_id = ?
               ORDER BY flagged_at DESC""",
            (user_id,)
        ).fetchall()

        crisis_history = [
            {
                "id": r[0],
                "session_id": r[1],
                "message_content": r[2],
                "trigger_word": r[3],
                "flagged_at": r[4],
                "reviewed": bool(r[5])
            }
            for r in crisis_flags
        ]

        # Get latest wearable data
        latest_wearable = self.get_latest_wearable_data(user_id)

        return {
            **user,
            "created_at": created_at[0] if created_at else None,
            "stats": stats,
            "sessions": sessions,
            "crisis_history": crisis_history,
            "latest_wearable": latest_wearable
        }

    def get_all_crisis_flags(self, reviewed: bool = None) -> list:
        """Get all crisis flags, optionally filtered by reviewed status."""
        query = """SELECT cf.id, cf.user_id, cf.user_name, cf.user_email,
                          cf.session_id, cf.message_content, cf.trigger_word,
                          cf.flagged_at, cf.reviewed
                   FROM crisis_flags cf
                   ORDER BY cf.flagged_at DESC"""

        if reviewed is not None:
            query = """SELECT cf.id, cf.user_id, cf.user_name, cf.user_email,
                              cf.session_id, cf.message_content, cf.trigger_word,
                              cf.flagged_at, cf.reviewed
                       FROM crisis_flags cf
                       WHERE cf.reviewed = ?
                       ORDER BY cf.flagged_at DESC"""
            results = self.conn.execute(query, (1 if reviewed else 0,)).fetchall()
        else:
            results = self.conn.execute(query).fetchall()

        return [
            {
                "id": r[0],
                "user_id": r[1],
                "user_name": r[2],
                "user_email": r[3],
                "session_id": r[4],
                "message_content": r[5],
                "trigger_word": r[6],
                "flagged_at": r[7],
                "reviewed": bool(r[8])
            }
            for r in results
        ]

    def mark_crisis_reviewed(self, flag_id: str) -> bool:
        """Mark a crisis flag as reviewed."""
        self.conn.execute(
            "UPDATE crisis_flags SET reviewed = 1 WHERE id = ?",
            (flag_id,)
        )
        self.conn.commit()
        return True

    def get_dashboard_stats(self) -> dict:
        """Get overview statistics for admin dashboard."""
        # Total users
        total_users = self.conn.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        # Sessions today
        sessions_today = self.conn.execute(
            """SELECT COUNT(*) FROM sessions
               WHERE DATE(started_at) = DATE('now')"""
        ).fetchone()[0]

        # Unreviewed crisis flags
        unreviewed_alerts = self.conn.execute(
            "SELECT COUNT(*) FROM crisis_flags WHERE reviewed = 0"
        ).fetchone()[0]

        # Average mood improvement (mood_end - mood_start for completed sessions)
        mood_result = self.conn.execute(
            """SELECT AVG(mood_end - mood_start)
               FROM sessions
               WHERE mood_start IS NOT NULL
               AND mood_end IS NOT NULL
               AND completed = 1"""
        ).fetchone()
        avg_mood_change = round(mood_result[0], 2) if mood_result[0] else 0

        # Total sessions
        total_sessions = self.conn.execute(
            "SELECT COUNT(*) FROM sessions"
        ).fetchone()[0]

        # Completed sessions
        completed_sessions = self.conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE completed = 1"
        ).fetchone()[0]

        # Active ML-detected risk episodes
        active_episodes = self.conn.execute(
            "SELECT COUNT(*) FROM depression_episodes WHERE is_active = 1"
        ).fetchone()[0]

        # Wearable readings in last 24 hours
        wearable_today = self.conn.execute(
            """SELECT COUNT(*) FROM wearable_data
               WHERE recorded_at >= datetime('now', '-24 hours')"""
        ).fetchone()[0]

        return {
            "total_users": total_users,
            "sessions_today": sessions_today,
            "unreviewed_alerts": unreviewed_alerts,
            "avg_mood_change": avg_mood_change,
            "total_sessions": total_sessions,
            "completed_sessions": completed_sessions,
            "active_episodes": active_episodes,
            "wearable_readings_today": wearable_today,
        }

    def get_user_wearable_summary(self, user_id: str) -> dict:
        """Get vitals summary for a patient."""
        # Get stats for day, week, month
        day_stats = self.get_wearable_stats(user_id, "day")
        week_stats = self.get_wearable_stats(user_id, "week")
        month_stats = self.get_wearable_stats(user_id, "month")

        # Get latest reading
        latest = self.get_latest_wearable_data(user_id)

        return {
            "latest": latest,
            "day": day_stats,
            "week": week_stats,
            "month": month_stats
        }

    def get_wearable_timeseries(self, user_id: str, hours: int = 24) -> list:
        """Get time-series wearable data for charts."""
        results = self.conn.execute(
            """SELECT ppg, gsr, acc_x, acc_y, acc_z, recorded_at
               FROM wearable_data
               WHERE user_id = ?
               AND recorded_at >= datetime('now', ? || ' hours')
               ORDER BY recorded_at ASC""",
            (user_id, -hours)
        ).fetchall()

        return [
            {
                "ppg": r[0],
                "gsr": r[1],
                "acc_x": r[2],
                "acc_y": r[3],
                "acc_z": r[4],
                "recorded_at": r[5]
            }
            for r in results
        ]

    def create_session_marker(self, user_id: str, label: str) -> dict:
        """Create a timestamped marker to tag subsequent readings with a participant label.
        Used because the physical wearable always sends data under one fixed account
        (no firmware access to change this), so we label who was actually wearing it
        at the software level instead."""
        import uuid
        marker_id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO session_markers (id, user_id, label) VALUES (?, ?, ?)",
            (marker_id, user_id, label)
        )
        self.conn.commit()
        result = self.conn.execute(
            "SELECT id, label, created_at FROM session_markers WHERE id = ?",
            (marker_id,)
        ).fetchone()
        return {"id": result[0], "label": result[1], "created_at": result[2]}

    def get_session_markers(self, user_id: str) -> list:
        """Get all participant-session markers for a user, oldest first."""
        results = self.conn.execute(
            "SELECT id, label, created_at FROM session_markers WHERE user_id = ? ORDER BY created_at ASC",
            (user_id,)
        ).fetchall()
        return [{"id": r[0], "label": r[1], "created_at": r[2]} for r in results]

    def get_all_wearable_readings(self) -> list:
        """
        Get every wearable reading across ALL users, with a computed
        'participant' label for the global 'Export Sensor Readings CSV' button.

        Since the physical wearable always sends data under one fixed account
        (no firmware/BLE access to reassign it), the real participant identity
        comes from session_markers (set via 'Start New Participant') rather
        than the account name. For each reading, we use whichever marker was
        most recently created at or before that reading's timestamp, for that
        same user_id. If no marker exists yet for a user, we fall back to
        their account name so the column is never blank.
        """
        readings = self.conn.execute(
            """SELECT u.id, u.name, u.email, w.recorded_at, w.ppg, w.gsr, w.acc_x, w.acc_y, w.acc_z, w.device_timestamp
               FROM wearable_data w
               JOIN users u ON u.id = w.user_id
               ORDER BY u.email ASC, w.recorded_at ASC"""
        ).fetchall()

        markers = self.conn.execute(
            "SELECT user_id, label, created_at FROM session_markers ORDER BY user_id ASC, created_at ASC"
        ).fetchall()

        # Group markers by user_id for fast lookup
        markers_by_user = {}
        for user_id, label, created_at in markers:
            markers_by_user.setdefault(user_id, []).append((created_at, label))

        def participant_label(user_id, account_name, recorded_at):
            user_markers = markers_by_user.get(user_id)
            if not user_markers:
                return account_name  # no markers set yet for this account
            label = account_name
            for created_at, marker_label in user_markers:
                if created_at <= recorded_at:
                    label = marker_label
                else:
                    break
            return label

        return [
            {
                "participant": participant_label(r[0], r[1], r[3]),
                "account_email": r[2],
                "recorded_at": r[3],
                "device_timestamp": r[9],
                "ppg": r[4],
                "gsr": r[5],
                "acc_x": r[6],
                "acc_y": r[7],
                "acc_z": r[8],
            }
            for r in readings
        ]

    def get_daily_session_counts(self, days: int = 30) -> list:
        """Get daily session counts for trend chart."""
        results = self.conn.execute(
            """SELECT DATE(started_at) as day, COUNT(*) as count
               FROM sessions
               WHERE started_at >= datetime('now', ? || ' days')
               GROUP BY DATE(started_at)
               ORDER BY day ASC""",
            (-days,)
        ).fetchall()

        return [{"date": r[0], "count": r[1]} for r in results]

    def get_distortion_distribution(self) -> dict:
        """Get aggregate distortion group distribution."""
        results = self.conn.execute(
            """SELECT locked_group, COUNT(*) as count
               FROM sessions
               WHERE locked_group IS NOT NULL AND locked_group != 'G0'
               GROUP BY locked_group"""
        ).fetchall()

        distribution = {"G1": 0, "G2": 0, "G3": 0, "G4": 0}
        for r in results:
            if r[0] in distribution:
                distribution[r[0]] = r[1]

        return distribution

    def get_user_mood_history(self, user_id: str, limit: int = 20) -> list:
        """Get mood history for a user's sessions."""
        results = self.conn.execute(
            """SELECT started_at, mood_start, mood_end, locked_group, completed
               FROM sessions
               WHERE user_id = ?
               AND mood_start IS NOT NULL
               ORDER BY started_at DESC
               LIMIT ?""",
            (user_id, limit)
        ).fetchall()

        return [
            {
                "date": r[0],
                "mood_start": r[1],
                "mood_end": r[2],
                "locked_group": r[3],
                "completed": bool(r[4])
            }
            for r in reversed(results)  # Chronological order
        ]

    def get_user_distortion_pattern(self, user_id: str) -> dict:
        """Get distortion pattern for radar chart."""
        stats = self.get_user_stats(user_id)
        counts = stats.get("distortion_counts", {})

        return {
            "G1": counts.get("G1", 0),
            "G2": counts.get("G2", 0),
            "G3": counts.get("G3", 0),
            "G4": counts.get("G4", 0)
        }

    # ==================== BECK SESSION OPERATIONS ====================

    def create_beck_session(self, session_id: str) -> dict:
        """Initialize a Beck session when distortion is detected."""
        try:
            self.conn.execute(
                """INSERT INTO beck_sessions (session_id, beck_state)
                   VALUES (?, 'VALIDATE')""",
                (session_id,)
            )
            self.conn.commit()
            return {"session_id": session_id, "beck_state": "VALIDATE"}
        except Exception as e:
            print(f"Error creating Beck session: {e}")
            return None

    def get_beck_session(self, session_id: str) -> dict:
        """Get current Beck session state and all data."""
        result = self.conn.execute(
            """SELECT session_id, beck_state, original_thought, initial_belief_rating,
                      emotion, initial_emotion_intensity, q1_evidence_for, q1_evidence_against,
                      q2_alternative, q3_worst, q3_best, q3_realistic, q4_effect, q5_friend,
                      q6_action, adaptive_thought, new_thought_belief, final_belief_rating,
                      final_emotion_intensity, action_plan, started_at, completed_at,
                      belief_improvement, emotion_improvement, full_protocol_state,
                      quality_scores, agenda_items, bdi_score
               FROM beck_sessions WHERE session_id = ?""",
            (session_id,)
        ).fetchone()

        if result:
            return {
                "session_id": result[0],
                "beck_state": result[1],
                "original_thought": result[2],
                "initial_belief_rating": result[3],
                "emotion": result[4],
                "initial_emotion_intensity": result[5],
                "q1_evidence_for": result[6],
                "q1_evidence_against": result[7],
                "q2_alternative": result[8],
                "q3_worst": result[9],
                "q3_best": result[10],
                "q3_realistic": result[11],
                "q4_effect": result[12],
                "q5_friend": result[13],
                "q6_action": result[14],
                "adaptive_thought": result[15],
                "new_thought_belief": result[16],
                "final_belief_rating": result[17],
                "final_emotion_intensity": result[18],
                "action_plan": result[19],
                "started_at": result[20],
                "completed_at": result[21],
                "belief_improvement": result[22],
                "emotion_improvement": result[23],
                "full_protocol_state": result[24],
                "quality_scores": result[25],
                "agenda_items": result[26],
                "bdi_score": result[27],
            }
        return None

    def update_beck_state(self, session_id: str, new_state: str, **fields):
        """Update state and save any new field values."""
        # Start with state update
        updates = {"beck_state": new_state}
        updates.update(fields)

        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        values = tuple(list(updates.values()) + [session_id])

        self.conn.execute(
            f"UPDATE beck_sessions SET {set_clause} WHERE session_id = ?",
            values
        )
        self.conn.commit()

    def complete_beck_session(self, session_id: str):
        """Mark session complete, calculate improvements."""
        # Get current data
        beck_data = self.get_beck_session(session_id)
        if not beck_data:
            return

        # Calculate improvements
        belief_improvement = None
        emotion_improvement = None

        if beck_data.get('initial_belief_rating') and beck_data.get('final_belief_rating'):
            belief_improvement = beck_data['initial_belief_rating'] - beck_data['final_belief_rating']

        if beck_data.get('initial_emotion_intensity') and beck_data.get('final_emotion_intensity'):
            emotion_improvement = beck_data['initial_emotion_intensity'] - beck_data['final_emotion_intensity']

        # Update completion status
        self.conn.execute(
            """UPDATE beck_sessions SET
               completed_at = CURRENT_TIMESTAMP,
               belief_improvement = ?,
               emotion_improvement = ?
               WHERE session_id = ?""",
            (belief_improvement, emotion_improvement, session_id)
        )
        self.conn.commit()

    # ==================== ML INFERENCE & DEPRESSION TRACKING ====================

    def get_recent_readings_for_ml(self, user_id: str, limit: int = 50) -> list:
        """
        Get most recent sensor readings for ML inference.
        Returns data ordered from OLDEST to NEWEST (required for time-series analysis).
        """
        results = self.conn.execute(
            """SELECT ppg, gsr, acc_x, acc_y, acc_z, recorded_at
               FROM wearable_data
               WHERE user_id = ?
               ORDER BY recorded_at DESC
               LIMIT ?""",
            (user_id, limit)
        ).fetchall()

        # Reverse to get oldest-to-newest order
        readings = [
            {
                "ppg": r[0],
                "gsr": r[1],
                "acc_x": r[2],
                "acc_y": r[3],
                "acc_z": r[4],
                "timestamp": r[5]
            }
            for r in reversed(results)
        ]

        return readings

    def update_ml_prediction(self, record_id: str, prediction: str, confidence: float, risk_level: int):
        """Update a wearable data record with ML prediction results."""
        condition = prediction  # prediction is already "NORMAL", "MILD_STRESS", or "HIGH_STRESS"
        self.conn.execute(
            """UPDATE wearable_data
               SET ml_prediction = ?, ml_confidence = ?, risk_level = ?,
                   condition = ?, dri_score = ?
               WHERE id = ?""",
            (prediction, confidence, risk_level, condition, confidence, record_id)
        )
        self.conn.commit()

    def get_active_depression_episode(self, user_id: str) -> dict:
        """Get the currently active depression episode for a user, if any."""
        result = self.conn.execute(
            """SELECT id, user_id, start_time, peak_risk_level, total_readings, avg_confidence
               FROM depression_episodes
               WHERE user_id = ? AND is_active = 1
               ORDER BY start_time DESC LIMIT 1""",
            (user_id,)
        ).fetchone()

        if result:
            return {
                "id": result[0],
                "user_id": result[1],
                "start_time": result[2],
                "peak_risk_level": result[3],
                "total_readings": result[4],
                "avg_confidence": result[5]
            }
        return None

    def start_depression_episode(self, user_id: str, risk_level: int, confidence: float) -> str:
        """Start a new depression episode."""
        episode_id = str(uuid.uuid4())

        self.conn.execute(
            """INSERT INTO depression_episodes
               (id, user_id, start_time, peak_risk_level, total_readings, avg_confidence, is_active)
               VALUES (?, ?, CURRENT_TIMESTAMP, ?, 1, ?, 1)""",
            (episode_id, user_id, risk_level, confidence)
        )
        self.conn.commit()

        return episode_id

    def update_depression_episode(self, episode_id: str, risk_level: int, confidence: float):
        """Update an active depression episode with new reading."""
        # Get current stats
        result = self.conn.execute(
            """SELECT total_readings, avg_confidence, peak_risk_level
               FROM depression_episodes WHERE id = ?""",
            (episode_id,)
        ).fetchone()

        if result:
            total_readings = result[0]
            avg_confidence = result[1]
            peak_risk = result[2]

            # Update rolling average confidence
            new_total = total_readings + 1
            new_avg_confidence = ((avg_confidence * total_readings) + confidence) / new_total

            # Update peak risk level
            new_peak_risk = max(peak_risk, risk_level)

            self.conn.execute(
                """UPDATE depression_episodes
                   SET total_readings = ?,
                       avg_confidence = ?,
                       peak_risk_level = ?
                   WHERE id = ?""",
                (new_total, new_avg_confidence, new_peak_risk, episode_id)
            )
            self.conn.commit()

    def end_depression_episode(self, episode_id: str):
        """Mark a depression episode as ended."""
        self.conn.execute(
            """UPDATE depression_episodes
               SET end_time = CURRENT_TIMESTAMP,
                   is_active = 0
               WHERE id = ?""",
            (episode_id,)
        )
        self.conn.commit()

    def get_user_depression_stats(self, user_id: str) -> dict:
        """Get depression episode statistics for a user."""
        # Total episodes
        total_result = self.conn.execute(
            """SELECT COUNT(*) FROM depression_episodes WHERE user_id = ?""",
            (user_id,)
        ).fetchone()

        # Active episode
        active_result = self.conn.execute(
            """SELECT COUNT(*) FROM depression_episodes
               WHERE user_id = ? AND is_active = 1""",
            (user_id,)
        ).fetchone()

        # Last 7 days episodes
        recent_result = self.conn.execute(
            """SELECT COUNT(*) FROM depression_episodes
               WHERE user_id = ? AND start_time >= datetime('now', '-7 days')""",
            (user_id,)
        ).fetchone()

        # Peak risk level in last 7 days
        peak_result = self.conn.execute(
            """SELECT MAX(peak_risk_level) FROM depression_episodes
               WHERE user_id = ? AND start_time >= datetime('now', '-7 days')""",
            (user_id,)
        ).fetchone()

        # Latest ML prediction
        latest_pred = self.conn.execute(
            """SELECT ml_prediction, ml_confidence, risk_level, recorded_at
               FROM wearable_data
               WHERE user_id = ? AND ml_prediction IS NOT NULL
               ORDER BY recorded_at DESC LIMIT 1""",
            (user_id,)
        ).fetchone()

        return {
            "total_episodes": total_result[0] if total_result else 0,
            "has_active_episode": (active_result[0] > 0) if active_result else False,
            "episodes_last_7_days": recent_result[0] if recent_result else 0,
            "peak_risk_last_7_days": peak_result[0] if (peak_result and peak_result[0]) else 0,
            "latest_prediction": {
                "prediction": latest_pred[0],
                "confidence": latest_pred[1],
                "risk_level": latest_pred[2],
                "timestamp": latest_pred[3]
            } if latest_pred else None
        }

    def get_all_depression_episodes(self, user_id: str, limit: int = 50) -> list:
        """Get all depression episodes for a user."""
        results = self.conn.execute(
            """SELECT id, start_time, end_time, peak_risk_level, total_readings, avg_confidence, is_active
               FROM depression_episodes
               WHERE user_id = ?
               ORDER BY start_time DESC
               LIMIT ?""",
            (user_id, limit)
        ).fetchall()

        return [
            {
                "id": r[0],
                "start_time": r[1],
                "end_time": r[2],
                "peak_risk_level": r[3],
                "total_readings": r[4],
                "avg_confidence": r[5],
                "is_active": bool(r[6])
            }
            for r in results
        ]

    def get_ml_prediction_history(self, user_id: str, limit: int = 100) -> list:
        """Get history of ML predictions for a user."""
        results = self.conn.execute(
            """SELECT ml_prediction, ml_confidence, risk_level, recorded_at
               FROM wearable_data
               WHERE user_id = ? AND ml_prediction IS NOT NULL
               ORDER BY recorded_at DESC
               LIMIT ?""",
            (user_id, limit)
        ).fetchall()

        return [
            {
                "prediction": r[0],
                "confidence": r[1],
                "risk_level": r[2],
                "timestamp": r[3]
            }
            for r in results
        ]


    # ==================== ML WINDOW PREDICTION OPERATIONS ====================

    def save_window_prediction(self, user_id: str, prediction: str,
                               confidence: float, risk_level: int,
                               readings_used: int = 25) -> str:
        """Save one ML inference result (covers a window of readings)."""
        record_id = str(uuid.uuid4())
        self.conn.execute(
            """INSERT INTO ml_window_predictions
               (id, user_id, prediction, risk_level, confidence, readings_used)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (record_id, user_id, prediction, risk_level,
             round(confidence, 4), readings_used)
        )
        self.conn.commit()
        return record_id

    def get_window_predictions(self, user_id: str, limit: int = 200) -> list:
        """Get ML window prediction history for a user (newest first)."""
        results = self.conn.execute(
            """SELECT id, prediction, risk_level, confidence, readings_used, predicted_at
               FROM ml_window_predictions
               WHERE user_id = ?
               ORDER BY predicted_at DESC
               LIMIT ?""",
            (user_id, limit)
        ).fetchall()

        return [
            {
                "id": r[0],
                "prediction": r[1],
                "risk_level": r[2],
                "confidence": r[3],
                "readings_used": r[4],
                "predicted_at": r[5]
            }
            for r in reversed(results)  # chronological for charting
        ]

    def delete_user(self, user_id: str) -> bool:
        """Delete a user and all their associated data (cascading)."""
        try:
            # Delete child records first, then the user row
            child_tables = [
                "messages",
                "beck_sessions",
                "exercises_completed",
                "crisis_flags",
                "user_stats",
                "wearable_data",
                "device_keys",
                "depression_episodes",
                "window_predictions",
            ]
            for table in child_tables:
                try:
                    self.conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
                except Exception:
                    pass  # table may not exist or may use a different FK

            # messages / beck_sessions may be linked via session_id
            try:
                session_ids = self.conn.execute(
                    "SELECT id FROM sessions WHERE user_id = ?", (user_id,)
                ).fetchall()
                for (sid,) in session_ids:
                    self.conn.execute("DELETE FROM messages     WHERE session_id = ?", (sid,))
                    self.conn.execute("DELETE FROM beck_sessions WHERE session_id = ?", (sid,))
            except Exception:
                pass

            self.conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            self.conn.execute("DELETE FROM users    WHERE id = ?",      (user_id,))
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Error deleting user {user_id}: {e}")
            return False


# Singleton instance
_db_instance = None

def get_db() -> Database:
    """Get database singleton instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance