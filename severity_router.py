"""
Severity-Based Treatment Router
Routes patients to appropriate treatment branch based on BDI score and session history
Based on Beck et al., 1979 - behavioral activation precedes cognitive work for severe depression
"""

def route_by_severity(bdi_score: int, session_number: int, bdi_history: list) -> str:
    """
    Determine which treatment branch to use.

    Args:
        bdi_score: Current BDI-II score (0-63)
        session_number: Session count for this patient
        bdi_history: List of previous BDI scores

    Returns:
        str: Target state ("BEHAVIORAL_ACTIVATION", "RELAPSE_PREVENTION", or "VALIDATE")
    """

    # Default to moderate if score is missing
    if bdi_score is None:
        bdi_score = 15

    # SEVERE DEPRESSION (BDI >= 29): Behavioral Activation first
    # Too depressed for cognitive work - need activity scheduling
    if bdi_score >= 29:
        return "BEHAVIOURAL_ACTIVATION"

    # RELAPSE PREVENTION: 3+ consecutive sessions with BDI < 14
    # Patient has recovered - focus on maintaining gains
    if session_number >= 8 and len(bdi_history) >= 3:
        recent_scores = bdi_history[-3:]
        # Check if all recent scores are below clinical threshold
        if all(score < 14 for score in recent_scores):
            return "RELAPSE_PREVENTION"

    # DEFAULT: Standard Cognitive Restructuring
    # Use the existing 20-state protocol (VALIDATE → COMPLETE)
    return "VALIDATE"


def should_continue_ba(bdi_score: int, sessions_in_ba: int) -> bool:
    """
    Determine if patient should continue behavioral activation or move to cognitive work.

    Args:
        bdi_score: Current BDI score
        sessions_in_ba: Number of BA sessions completed

    Returns:
        bool: True if should continue BA, False if ready for cognitive work
    """
    # Continue BA if still severe after < 4 sessions
    if sessions_in_ba < 4 and bdi_score >= 29:
        return True

    # Continue BA if improving but not yet moderate (after 4+ sessions)
    if sessions_in_ba >= 4 and bdi_score >= 20:
        return True

    # Ready for cognitive work if BDI < 20
    return False


def get_treatment_phase(bdi_score: int, session_number: int, bdi_history: list) -> str:
    """
    Get descriptive treatment phase name.

    Returns:
        str: "assessment", "behavioral_activation", "cognitive_restructuring",
             "schema_work", "relapse_prevention"
    """
    if session_number == 1:
        return "assessment"

    route = route_by_severity(bdi_score, session_number, bdi_history)

    if route == "BEHAVIOURAL_ACTIVATION":
        return "behavioral_activation"
    elif route == "RELAPSE_PREVENTION":
        return "relapse_prevention"
    else:
        # VALIDATE route = cognitive restructuring
        if session_number >= 4:
            return "schema_work"  # Session 4+ can include schema exploration
        else:
            return "cognitive_restructuring"


# Test if run directly
if __name__ == "__main__":
    print("Testing severity router:\n")

    # Test case 1: Severe depression, first session
    result = route_by_severity(bdi_score=35, session_number=1, bdi_history=[])
    print(f"Severe depression (BDI=35): {result}")
    assert result == "BEHAVIOURAL_ACTIVATION"

    # Test case 2: Moderate depression, session 3
    result = route_by_severity(bdi_score=22, session_number=3, bdi_history=[35, 28])
    print(f"Moderate depression (BDI=22): {result}")
    assert result == "VALIDATE"

    # Test case 3: Recovered, session 10
    result = route_by_severity(
        bdi_score=10,
        session_number=10,
        bdi_history=[35, 28, 22, 18, 15, 12, 11, 10, 9]
    )
    print(f"Recovered (BDI=10, session 10): {result}")
    assert result == "RELAPSE_PREVENTION"

    # Test case 4: Mild depression, session 5
    result = route_by_severity(bdi_score=16, session_number=5, bdi_history=[22, 19, 18, 17])
    print(f"Mild depression (BDI=16): {result}")
    assert result == "VALIDATE"

    print("\n✅ All tests passed!")
