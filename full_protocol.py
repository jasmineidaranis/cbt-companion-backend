"""
Full Beck Protocol State Controller
WRAPS the existing 20-state cognitive restructuring flow.
Does NOT replace it - adds pre-session and post-session states around it.

Total states: 32
- Pre-session (6): BDI, BRIDGE, HOMEWORK_REVIEW, AGENDA, PSYCHOEDUCATION, ROUTING
- Cognitive (20): VALIDATE → COMPLETE (existing, UNTOUCHED)
- Post-session (6): SCHEMA_CHECK, DRDT, SUMMARY, FEEDBACK, SESSION_DONE
- Behavioral (3): BA_MONITORING, BA_SCHEDULING, BA_GRADED_TASK
- Relapse (1): RELAPSE_PREVENTION
"""

import json
from bdi_scorer import get_severity
from severity_router import route_by_severity

# State categories
PRE_SESSION_STATES = [
    "BDI_ASSESSMENT",
    "BRIDGE",
    "HOMEWORK_REVIEW",
    "AGENDA_SETTING",
    "PSYCHOEDUCATION",
    "SEVERITY_ROUTING"  # Logic state, no LLM
]

# The existing 20 states from prompts.py - DO NOT MODIFY
EXISTING_COGNITIVE_STATES = [
    "VALIDATE", "RATE_BELIEF", "CAPTURE_EMOTION", "RATE_EMOTION",
    "Q1_EVIDENCE_FOR", "Q1_EVIDENCE_AGAINST", "Q2_ALTERNATIVE",
    "Q3_WORST", "Q3_BEST", "Q3_REALISTIC", "Q4_EFFECT", "Q5_FRIEND", "Q6_ACTION",
    "SUMMARIZING",
    "DELIVER_REFRAME", "RATE_NEW_THOUGHT", "RERATE_ORIGINAL",
    "RERATE_EMOTION", "ACTION_PLAN", "COMPLETE"
]

POST_SESSION_STATES = [
    "SCHEMA_CHECK",
    "DRDT_OUTPUT",
    "SESSION_SUMMARY",
    "SESSION_FEEDBACK",
    "SESSION_DONE"
]

BEHAVIOURAL_STATES = [
    "BA_MONITORING",
    "BA_SCHEDULING",
    "BA_GRADED_TASK"
]

RELAPSE_STATES = [
    "RELAPSE_PREVENTION"
]

# All states managed by the new protocol (not the existing state machine)
NEW_PROTOCOL_STATES = (PRE_SESSION_STATES + POST_SESSION_STATES +
                       BEHAVIOURAL_STATES + RELAPSE_STATES)


def is_new_protocol_state(state: str) -> bool:
    """
    Check if a state is handled by the new protocol.

    Args:
        state: State name

    Returns:
        True if new protocol handles it, False if existing state machine handles it
    """
    return state in NEW_PROTOCOL_STATES


def is_cognitive_state(state: str) -> bool:
    """Check if state is part of the existing 20-state cognitive flow."""
    return state in EXISTING_COGNITIVE_STATES


def get_next_state_full_protocol(current_state: str, session_data: dict, patient_profile: dict) -> str:
    """
    Get next state in the full 32-state protocol.

    Args:
        current_state: Current state
        session_data: Current session dict (includes beck_session data)
        patient_profile: Patient profile dict

    Returns:
        Next state name, or None if end of protocol
    """

    # Extract needed data
    total_sessions = patient_profile.get('total_beck_sessions', 0)
    bdi_score = session_data.get('bdi_score')
    bdi_history_raw = patient_profile.get('bdi_scores', [])

    # Parse BDI history
    if isinstance(bdi_history_raw, str):
        try:
            bdi_history_raw = json.loads(bdi_history_raw)
        except:
            bdi_history_raw = []

    bdi_history = [
        s.get('score') if isinstance(s, dict) else s
        for s in bdi_history_raw
    ]

    homework = patient_profile.get('homework_pending')
    has_homework = homework and homework != 'null'

    # State transitions
    transitions = {
        # Pre-session flow
        "BDI_ASSESSMENT": "BRIDGE" if total_sessions > 0 else "AGENDA_SETTING",
        "BRIDGE": "HOMEWORK_REVIEW" if has_homework else "AGENDA_SETTING",
        "HOMEWORK_REVIEW": "AGENDA_SETTING",
        "AGENDA_SETTING": "PSYCHOEDUCATION" if total_sessions == 0 else "SEVERITY_ROUTING",
        "PSYCHOEDUCATION": "SEVERITY_ROUTING",

        # Routing state - handled by special logic
        "SEVERITY_ROUTING": _do_severity_routing(bdi_score, total_sessions, bdi_history),

        # Behavioral activation flow
        "BA_MONITORING": "BA_SCHEDULING",
        "BA_SCHEDULING": "BA_GRADED_TASK",
        "BA_GRADED_TASK": "DRDT_OUTPUT",  # Skip to closing (no cognitive work in BA)

        # Relapse prevention
        "RELAPSE_PREVENTION": "SESSION_SUMMARY",

        # Post-session flow (after existing COMPLETE state)
        "SCHEMA_CHECK": "DRDT_OUTPUT",
        "DRDT_OUTPUT": "SESSION_SUMMARY",
        "SESSION_SUMMARY": "SESSION_FEEDBACK",
        "SESSION_FEEDBACK": "SESSION_DONE",
        "SESSION_DONE": None  # End of protocol
    }

    return transitions.get(current_state)


def _do_severity_routing(bdi_score: int, total_sessions: int, bdi_history: list) -> str:
    """
    Execute severity routing logic.

    Returns:
        Next state based on severity
    """
    if bdi_score is None:
        # Fallback if BDI not completed
        return "VALIDATE"

    route_result = route_by_severity(bdi_score, total_sessions, bdi_history)

    if route_result == "BEHAVIOURAL_ACTIVATION":
        return "BA_MONITORING"
    elif route_result == "RELAPSE_PREVENTION":
        return "RELAPSE_PREVENTION"
    else:
        # "VALIDATE" - hand off to existing 20-state cognitive flow
        return "VALIDATE"


def get_post_complete_state(total_sessions: int, bdi_score: int = None) -> str:
    """
    Called when the existing COMPLETE state is reached.
    Returns the first post-session state.

    Args:
        total_sessions: Number of sessions completed
        bdi_score: Optional BDI score

    Returns:
        Next state after COMPLETE
    """
    # Session 4+: Eligible for schema work
    if total_sessions >= 4:
        return "SCHEMA_CHECK"

    # Sessions 1-3: Skip schema work
    return "DRDT_OUTPUT"


def get_initial_state(total_sessions: int) -> str:
    """
    Get the initial state for a new session.

    Args:
        total_sessions: Number of previous sessions

    Returns:
        Initial state
    """
    return "BDI_ASSESSMENT"


def needs_bdi_assessment(session_data: dict) -> bool:
    """Check if BDI assessment is needed."""
    # BDI should be done at start of every session
    return not session_data.get('bdi_score')


def is_session_complete(current_state: str) -> bool:
    """Check if session is complete."""
    return current_state == "SESSION_DONE" or current_state is None


def should_trigger_downward_arrow(user_id: str, current_distortion_group: str) -> bool:
    """
    Check if this distortion has appeared 3+ times across sessions → trigger DA.
    Skip if we've already identified a core belief for this distortion group.
    """
    from patient_tracker import get_patient_profile

    profile = get_patient_profile(user_id)
    recurring = profile.get('recurring_distortions', {})
    if isinstance(recurring, str):
        try:
            recurring = json.loads(recurring)
        except:
            recurring = {}

    count = recurring.get(current_distortion_group, 0)

    # Already have core beliefs? Check if we've explored this group
    core_beliefs = profile.get('core_beliefs', [])
    if isinstance(core_beliefs, str):
        try:
            core_beliefs = json.loads(core_beliefs)
        except:
            core_beliefs = []

    # If we already have 2+ core beliefs, no need for more DA
    if len(core_beliefs) >= 2:
        return False

    return count >= 3


# Convenience functions for app.py

def get_protocol_branch(current_state: str) -> str:
    """
    Get which branch of the protocol we're in.

    Returns:
        "pre_session", "cognitive", "behavioral", "relapse", or "post_session"
    """
    if current_state in PRE_SESSION_STATES:
        return "pre_session"
    elif current_state in EXISTING_COGNITIVE_STATES:
        return "cognitive"
    elif current_state in BEHAVIOURAL_STATES:
        return "behavioral"
    elif current_state in RELAPSE_STATES:
        return "relapse"
    elif current_state in POST_SESSION_STATES:
        return "post_session"
    else:
        return "unknown"


def format_state_for_display(state: str) -> str:
    """Format state name for user-friendly display."""
    labels = {
        "BDI_ASSESSMENT": "Initial Assessment",
        "BRIDGE": "Session Bridge",
        "HOMEWORK_REVIEW": "Homework Review",
        "AGENDA_SETTING": "Setting Agenda",
        "PSYCHOEDUCATION": "Learning the CBT Model",
        "SEVERITY_ROUTING": "Determining Approach",
        "BA_MONITORING": "Activity Monitoring",
        "BA_SCHEDULING": "Activity Scheduling",
        "BA_GRADED_TASK": "Building Activity Plan",
        "RELAPSE_PREVENTION": "Relapse Prevention",
        "VALIDATE": "Validation",
        "SCHEMA_CHECK": "Deep Belief Exploration",
        "DRDT_OUTPUT": "Creating Thought Record",
        "SESSION_SUMMARY": "Session Summary",
        "SESSION_FEEDBACK": "Feedback",
        "SESSION_DONE": "Session Complete"
    }
    return labels.get(state, state.replace("_", " ").title())


# Test if run directly
if __name__ == "__main__":
    print("Testing full protocol controller:\n")

    # Mock data
    mock_session = {"bdi_score": 32}
    mock_patient = {
        "total_beck_sessions": 1,
        "bdi_scores": [],
        "homework_pending": None
    }

    # Test routing for severe depression
    print("Test 1: Severe depression, first session")
    state = "BDI_ASSESSMENT"
    path = [state]

    for _ in range(10):
        next_state = get_next_state_full_protocol(state, mock_session, mock_patient)
        if next_state:
            path.append(next_state)
            state = next_state
        else:
            break

        # Stop at routing to avoid infinite loop
        if state == "BA_MONITORING":
            break

    print(f"Path: {' → '.join(path)}")
    assert "BA_MONITORING" in path, "Should route to behavioral activation"

    # Test routing for mild depression
    print("\nTest 2: Mild depression, session 3")
    mock_session_2 = {"bdi_score": 16}
    mock_patient_2 = {
        "total_beck_sessions": 3,
        "bdi_scores": [28, 22, 18],
        "homework_pending": '{"task": "test"}'
    }

    state = "BDI_ASSESSMENT"
    path = [state]

    for _ in range(10):
        next_state = get_next_state_full_protocol(state, mock_session_2, mock_patient_2)
        if next_state:
            path.append(next_state)
            state = next_state
        else:
            break

        if state == "VALIDATE":
            break

    print(f"Path: {' → '.join(path)}")
    assert "VALIDATE" in path, "Should route to cognitive restructuring"
    assert "HOMEWORK_REVIEW" in path, "Should review homework"

    print("\n✅ All tests passed!")
