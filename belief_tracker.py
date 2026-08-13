"""
Cross-Session Belief Modification Tracking
Links recurring thoughts across sessions, tracks belief rating trajectories,
and flags treatment-resistant thoughts.

Research contribution: Automated longitudinal belief tracking with
modification index and treatment resistance detection.
"""

import json
import uuid
from database import get_db
from patient_tracker import get_patient_profile


def _init_thought_clusters_table():
    """Create thought_clusters table if it doesn't exist."""
    db = get_db()
    try:
        db.conn.execute("""
            CREATE TABLE IF NOT EXISTS thought_clusters (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                representative_thought TEXT,
                distortion_group TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        db.conn.commit()
    except Exception as e:
        print(f"thought_clusters table: {str(e)[:60]}")


# Initialize on import
_init_thought_clusters_table()


def _keyword_overlap(thought_a: str, thought_b: str) -> float:
    """Simple keyword overlap score between two thoughts."""
    if not thought_a or not thought_b:
        return 0.0
    stop_words = {'i', 'me', 'my', 'the', 'a', 'an', 'is', 'am', 'are', 'was',
                  'were', 'be', 'been', 'do', 'does', 'did', 'have', 'has', 'had',
                  'will', 'would', 'could', 'should', 'to', 'of', 'in', 'for',
                  'on', 'at', 'by', 'it', 'that', 'this', 'with', 'not', 'but',
                  'and', 'or', 'so', 'if', 'just', 'like', 'feel', 'think', 'know'}

    words_a = set(w.lower().strip('.,!?') for w in thought_a.split()) - stop_words
    words_b = set(w.lower().strip('.,!?') for w in thought_b.split()) - stop_words

    if not words_a or not words_b:
        return 0.0

    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union) if union else 0.0


def find_similar_thoughts(current_thought: str, user_id: str, current_group: str = None):
    """
    Find past thoughts with same distortion group + keyword overlap.

    Returns: list of {cluster_id, thought, initial_rating, final_rating, date}
    """
    db = get_db()

    # Get all past beck_sessions for user
    sessions = db.conn.execute("""
        SELECT bs.*, s.locked_group, s.created_at as session_date
        FROM beck_sessions bs
        JOIN sessions s ON bs.session_id = s.id
        WHERE s.user_id = ? AND s.completed = 1
        ORDER BY s.created_at DESC
    """, (user_id,)).fetchall()

    if not sessions:
        return []

    columns = [row[1] for row in db.conn.execute("PRAGMA table_info(beck_sessions)").fetchall()]
    # Add the joined columns
    extra_cols = ['locked_group', 'session_date']

    matches = []
    for row in sessions:
        session_dict = dict(zip(columns, row[:len(columns)]))
        # Get extra columns from the join
        if len(row) > len(columns):
            session_dict['locked_group'] = row[len(columns)]
            session_dict['session_date'] = row[len(columns) + 1]

        past_thought = session_dict.get('original_thought', '')
        past_group = session_dict.get('locked_group', '')

        # Filter by same distortion group if provided
        if current_group and past_group != current_group:
            continue

        # Check keyword overlap
        overlap = _keyword_overlap(current_thought, past_thought)
        if overlap > 0.25:
            matches.append({
                "session_id": session_dict.get('session_id'),
                "thought": past_thought,
                "initial_rating": session_dict.get('initial_belief_rating'),
                "final_rating": session_dict.get('final_belief_rating'),
                "date": session_dict.get('session_date'),
                "overlap": round(overlap, 2),
                "cluster_id": session_dict.get('thought_cluster_id')
            })

    return matches


def link_thought_to_cluster(session_id: str, user_id: str, thought: str, distortion_group: str):
    """
    Link a thought to an existing cluster or create a new one.
    Returns the cluster_id.
    """
    db = get_db()

    # Find similar past thoughts
    matches = find_similar_thoughts(thought, user_id, distortion_group)

    # Check if any match has a cluster
    for match in matches:
        if match.get('cluster_id'):
            # Link to existing cluster
            db.conn.execute(
                "UPDATE beck_sessions SET thought_cluster_id = ? WHERE session_id = ?",
                (match['cluster_id'], session_id)
            )
            db.conn.commit()
            return match['cluster_id']

    # Create new cluster
    cluster_id = f"tc_{uuid.uuid4().hex[:8]}"
    db.conn.execute(
        "INSERT INTO thought_clusters (id, user_id, representative_thought, distortion_group) VALUES (?, ?, ?, ?)",
        (cluster_id, user_id, thought, distortion_group)
    )

    # Link current session
    db.conn.execute(
        "UPDATE beck_sessions SET thought_cluster_id = ? WHERE session_id = ?",
        (cluster_id, session_id)
    )

    # Also link any matching past sessions that didn't have a cluster
    for match in matches:
        if not match.get('cluster_id') and match.get('session_id'):
            db.conn.execute(
                "UPDATE beck_sessions SET thought_cluster_id = ? WHERE session_id = ?",
                (cluster_id, match['session_id'])
            )

    db.conn.commit()
    return cluster_id


def get_belief_trajectory(user_id: str) -> list:
    """
    Get all thought clusters with their rating trajectories.

    Returns list of cluster dicts with trajectory data and treatment resistance flags.
    """
    db = get_db()

    # Get all clusters for user
    clusters = db.conn.execute(
        "SELECT * FROM thought_clusters WHERE user_id = ? ORDER BY created_at",
        (user_id,)
    ).fetchall()

    if not clusters:
        return []

    cluster_cols = [row[1] for row in db.conn.execute("PRAGMA table_info(thought_clusters)").fetchall()]

    results = []
    for cluster_row in clusters:
        cluster = dict(zip(cluster_cols, cluster_row))
        cluster_id = cluster['id']

        # Get all sessions in this cluster
        sessions = db.conn.execute("""
            SELECT bs.initial_belief_rating, bs.final_belief_rating, s.created_at
            FROM beck_sessions bs
            JOIN sessions s ON bs.session_id = s.id
            WHERE bs.thought_cluster_id = ?
            ORDER BY s.created_at
        """, (cluster_id,)).fetchall()

        trajectory = []
        for s in sessions:
            initial = int(float(s[0])) if s[0] is not None else None
            final = int(float(s[1])) if s[1] is not None else None
            date = s[2]
            if initial is not None or final is not None:
                trajectory.append({
                    "session_date": date,
                    "initial_rating": initial,
                    "final_rating": final
                })

        # Calculate treatment resistance
        is_resistant = check_treatment_resistant(trajectory)

        # Calculate modification index (rate of belief decay)
        mod_index = 0.0
        if len(trajectory) >= 2:
            finals = [t['final_rating'] for t in trajectory if t.get('final_rating') is not None]
            if len(finals) >= 2:
                total_change = finals[0] - finals[-1]
                mod_index = round(total_change / (len(finals) - 1) / 100, 2) if finals[0] > 0 else 0.0

        results.append({
            "cluster_id": cluster_id,
            "representative_thought": cluster.get('representative_thought'),
            "distortion_group": cluster.get('distortion_group'),
            "trajectory": trajectory,
            "is_treatment_resistant": is_resistant,
            "modification_index": mod_index,
            "session_count": len(trajectory)
        })

    return results


def check_treatment_resistant(trajectory: list) -> bool:
    """
    Flag if belief hasn't improved in 3+ sessions.
    If avg final_rating across last 3 sessions hasn't dropped by >10% → resistant.
    """
    if len(trajectory) < 3:
        return False

    last_3 = trajectory[-3:]
    finals = [t['final_rating'] for t in last_3 if t.get('final_rating') is not None]

    if len(finals) < 3:
        return False

    # Check if there's been meaningful improvement
    avg_recent = sum(finals) / len(finals)
    first_final = trajectory[0].get('final_rating')

    if first_final is None or first_final == 0:
        return False

    improvement_pct = (first_final - avg_recent) / first_final * 100
    return improvement_pct < 10  # Less than 10% improvement = resistant
