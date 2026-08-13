"""
Therapeutic Context Builder
Builds context strings to inject into agent system prompts for continuity.
Also generates Cognitive Conceptualization Diagrams (CCD) from session history.
"""

import json
from datetime import datetime


def build_patient_context(patient_profile: dict, previous_session: dict = None) -> str:
    """
    Build therapeutic context from patient history.

    Args:
        patient_profile: Patient profile dict from patient_tracker
        previous_session: Previous beck_session dict (optional)

    Returns:
        Formatted context string for agent prompts
    """
    ctx_parts = []

    ctx_parts.append("=== THERAPEUTIC CONTEXT ===")

    # Session history
    total_sessions = patient_profile.get('total_beck_sessions', 0)
    ctx_parts.append(f"Beck Protocol Sessions Completed: {total_sessions}")

    if total_sessions == 0:
        ctx_parts.append("This is the patient's FIRST Beck protocol session.")

    # Treatment phase
    phase = patient_profile.get('current_treatment_phase', 'assessment')
    phase_labels = {
        'assessment': 'Initial Assessment',
        'behavioral_activation': 'Behavioral Activation (Severe Depression)',
        'cognitive_restructuring': 'Cognitive Restructuring',
        'schema_work': 'Cognitive Restructuring + Schema Exploration',
        'relapse_prevention': 'Relapse Prevention & Maintenance'
    }
    ctx_parts.append(f"Current Phase: {phase_labels.get(phase, phase)}")

    # BDI trajectory
    bdi_scores = patient_profile.get('bdi_scores', [])
    if isinstance(bdi_scores, str):
        try:
            bdi_scores = json.loads(bdi_scores)
        except:
            bdi_scores = []

    if bdi_scores and len(bdi_scores) > 0:
        recent_scores = bdi_scores[-5:]  # Last 5 sessions
        score_str = " → ".join([str(s.get('score', s) if isinstance(s, dict) else s) for s in recent_scores])
        ctx_parts.append(f"BDI Trajectory (last {len(recent_scores)} sessions): {score_str}")

        if len(recent_scores) >= 2:
            # Calculate trend
            try:
                latest = recent_scores[-1].get('score') if isinstance(recent_scores[-1], dict) else recent_scores[-1]
                previous = recent_scores[-2].get('score') if isinstance(recent_scores[-2], dict) else recent_scores[-2]
                change = latest - previous
                if change < -3:
                    ctx_parts.append("  → Improving trend ✓")
                elif change > 3:
                    ctx_parts.append("  → Worsening trend - needs attention")
                else:
                    ctx_parts.append("  → Stable")
            except:
                pass

    # Core beliefs identified
    core_beliefs = patient_profile.get('core_beliefs', [])
    if isinstance(core_beliefs, str):
        try:
            core_beliefs = json.loads(core_beliefs)
        except:
            core_beliefs = []

    if core_beliefs:
        ctx_parts.append(f"Core Beliefs Identified: {', '.join(core_beliefs)}")

    # Intermediate beliefs
    intermediate_beliefs = patient_profile.get('intermediate_beliefs', [])
    if isinstance(intermediate_beliefs, str):
        try:
            intermediate_beliefs = json.loads(intermediate_beliefs)
        except:
            intermediate_beliefs = []

    if intermediate_beliefs:
        ctx_parts.append(f"Intermediate Beliefs: {', '.join(intermediate_beliefs[:3])}")

    # Recurring distortion patterns
    distortions = patient_profile.get('recurring_distortions', {})
    if isinstance(distortions, str):
        try:
            distortions = json.loads(distortions)
        except:
            distortions = {}

    if distortions:
        sorted_distortions = sorted(distortions.items(), key=lambda x: x[1], reverse=True)
        if sorted_distortions:
            top_distortion = sorted_distortions[0]
            distortion_labels = {
                'G1': 'All-or-nothing thinking',
                'G2': 'Overgeneralization',
                'G3': 'Mental filter',
                'G4': 'Emotional reasoning'
            }
            ctx_parts.append(f"Most Common Pattern: {distortion_labels.get(top_distortion[0], top_distortion[0])} ({top_distortion[1]}x)")

    # Homework status
    homework = patient_profile.get('homework_pending')
    if homework and homework != 'null':
        try:
            hw = json.loads(homework) if isinstance(homework, str) else homework
            ctx_parts.append(f"Pending Homework: {hw.get('description', 'assigned')}")
        except:
            pass

    # Previous session summary
    if previous_session:
        ctx_parts.append("\n--- PREVIOUS SESSION ---")

        # What they worked on
        if previous_session.get('original_thought'):
            ctx_parts.append(f"Worked on: \"{previous_session['original_thought'][:100]}...\"")

        # Reframe
        if previous_session.get('adaptive_thought'):
            ctx_parts.append(f"Reframe: \"{previous_session['adaptive_thought'][:100]}...\"")

        # Action plan
        if previous_session.get('action_plan'):
            ctx_parts.append(f"Action Plan: {previous_session['action_plan'][:100]}")

        # Improvement
        if previous_session.get('belief_improvement'):
            ctx_parts.append(f"Belief Improvement: {previous_session['belief_improvement']}%")

        # Session summary
        if previous_session.get('session_summary_text'):
            ctx_parts.append(f"Summary: {previous_session['session_summary_text'][:150]}...")

    ctx_parts.append("=== END CONTEXT ===\n")

    return "\n".join(ctx_parts)


def build_minimal_context(session_number: int, bdi_score: int = None, severity: str = None) -> str:
    """Build minimal context for early sessions."""
    ctx = "=== THERAPEUTIC CONTEXT ===\n"
    ctx += f"Session Number: {session_number}\n"

    if bdi_score is not None:
        ctx += f"BDI-II Score: {bdi_score} ({severity})\n"

    if session_number == 1:
        ctx += "This is the patient's FIRST Beck protocol session.\n"

    ctx += "=== END CONTEXT ===\n"
    return ctx


def generate_ccd(user_id: str, groq_client) -> dict:
    """
    Generate Cognitive Conceptualization Diagram from session history.
    Aggregates thoughts, distortions, core beliefs, emotions, and behaviors
    into Beck's CCD structure using one Groq call.

    Args:
        user_id: User ID
        groq_client: GroqClient instance for the summarization call

    Returns:
        CCD dict with core_beliefs, intermediate_beliefs, coping_strategies, patterns
    """
    from database import get_db
    from patient_tracker import get_patient_profile, update_patient_profile

    db = get_db()
    profile = get_patient_profile(user_id)

    # Check for cached CCD
    cached_ccd = profile.get('ccd_data')
    if cached_ccd and isinstance(cached_ccd, str):
        try:
            cached = json.loads(cached_ccd)
            # Use cache if generated within last session
            if cached.get('sessions_analyzed', 0) >= profile.get('total_beck_sessions', 0):
                return cached
        except:
            pass

    # Get all completed beck_sessions
    sessions = db.conn.execute("""
        SELECT bs.*, s.locked_group, s.created_at as session_date
        FROM beck_sessions bs
        JOIN sessions s ON bs.session_id = s.id
        WHERE s.user_id = ? AND s.completed = 1
        ORDER BY s.created_at
    """, (user_id,)).fetchall()

    if not sessions or len(sessions) < 3:
        return None

    columns = [row[1] for row in db.conn.execute("PRAGMA table_info(beck_sessions)").fetchall()]

    # Aggregate session data for the prompt
    session_summaries = []
    for row in sessions:
        sd = dict(zip(columns, row[:len(columns)]))
        if len(row) > len(columns):
            sd['locked_group'] = row[len(columns)]
            sd['session_date'] = row[len(columns) + 1]

        summary = {
            "date": sd.get('session_date', ''),
            "thought": sd.get('original_thought', ''),
            "emotion": sd.get('emotion', ''),
            "distortion": sd.get('locked_group', ''),
            "evidence_for": sd.get('q1_evidence_for', ''),
            "evidence_against": sd.get('q1_evidence_against', ''),
            "reframe": sd.get('adaptive_thought', ''),
            "action": sd.get('q6_action', ''),
            "action_plan": sd.get('action_plan', ''),
            "core_belief_da": sd.get('da_core_belief', ''),
            "initial_belief": sd.get('initial_belief_rating'),
            "final_belief": sd.get('final_belief_rating'),
        }
        session_summaries.append(summary)

    # Get existing core beliefs from profile
    core_beliefs = profile.get('core_beliefs', [])
    if isinstance(core_beliefs, str):
        try:
            core_beliefs = json.loads(core_beliefs)
        except:
            core_beliefs = []

    # One Groq call to generate CCD structure
    system_prompt = """You are a clinical psychologist generating a Cognitive Conceptualization Diagram (CCD) from session data.

Analyze the session history and output a JSON CCD with:
1. core_beliefs: Global, absolute beliefs about self (e.g., "I am incompetent")
2. intermediate_beliefs: Rules/assumptions derived from core beliefs (e.g., "If I make mistakes, people will reject me")
3. coping_strategies: How the patient deals with these beliefs (e.g., "Avoidance", "Overworking")
4. patterns: List of Situation → Automatic Thought → Emotion → Behavior patterns from sessions

Respond ONLY in JSON:
{
  "core_beliefs": ["..."],
  "intermediate_beliefs": ["If... then...", "I must..."],
  "coping_strategies": ["..."],
  "patterns": [
    {
      "situation": "...",
      "automatic_thought": "...",
      "emotion": "...",
      "behavior": "...",
      "distortion_group": "G1",
      "session_date": "..."
    }
  ]
}"""

    user_prompt = f"""Session history ({len(session_summaries)} sessions):
{json.dumps(session_summaries, indent=1)}

Previously identified core beliefs: {json.dumps(core_beliefs)}

Generate CCD."""

    try:
        response_text = groq_client.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            max_tokens=800,
            response_format={"type": "json_object"}
        ).choices[0].message.content

        ccd = json.loads(response_text)
    except Exception as e:
        print(f"CCD generation error: {e}")
        # Fallback: build CCD from raw data without LLM
        ccd = {
            "core_beliefs": core_beliefs,
            "intermediate_beliefs": [],
            "coping_strategies": [],
            "patterns": []
        }
        for sd in session_summaries:
            if sd.get('thought'):
                ccd["patterns"].append({
                    "situation": sd.get('evidence_for', ''),
                    "automatic_thought": sd['thought'],
                    "emotion": sd.get('emotion', ''),
                    "behavior": sd.get('action', ''),
                    "distortion_group": sd.get('distortion', ''),
                    "session_date": sd.get('date', '')
                })

    # Add metadata
    ccd["generated_at"] = datetime.utcnow().isoformat()
    ccd["sessions_analyzed"] = len(session_summaries)

    # Cache in patient_profiles
    try:
        update_patient_profile(user_id, ccd_data=json.dumps(ccd))
    except Exception:
        pass  # Non-critical

    return ccd


# Test if run directly
if __name__ == "__main__":
    print("Testing context builder:\n")

    # Mock patient profile
    mock_profile = {
        'total_beck_sessions': 5,
        'current_treatment_phase': 'cognitive_restructuring',
        'bdi_scores': [
            {'score': 35, 'severity': 'severe'},
            {'score': 28, 'severity': 'moderate'},
            {'score': 22, 'severity': 'moderate'},
            {'score': 18, 'severity': 'mild'},
            {'score': 15, 'severity': 'mild'}
        ],
        'core_beliefs': ['I am incompetent', 'I am unlovable'],
        'recurring_distortions': {'G1': 8, 'G2': 5, 'G4': 3}
    }

    mock_previous = {
        'original_thought': 'I am a complete failure at my job',
        'adaptive_thought': 'I struggle with some tasks but I am learning and improving',
        'action_plan': 'Ask for feedback from manager this week',
        'belief_improvement': 25
    }

    context = build_patient_context(mock_profile, mock_previous)
    print(context)
