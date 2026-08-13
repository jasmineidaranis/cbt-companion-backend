"""
BDI-II (Beck Depression Inventory-II) Scoring Logic
Pure logic module - no LLM calls, no database access
Based on Beck et al., 1996
"""

# 21 items of BDI-II
BDI_ITEMS = [
    "Sadness",                      # 0
    "Pessimism",                    # 1
    "Past Failure",                 # 2
    "Loss of Pleasure",             # 3
    "Guilty Feelings",              # 4
    "Punishment Feelings",          # 5
    "Self-Dislike",                 # 6
    "Self-Criticalness",            # 7
    "Suicidal Thoughts",            # 8 - CRISIS ITEM
    "Crying",                       # 9
    "Agitation",                    # 10
    "Loss of Interest",             # 11
    "Indecisiveness",               # 12
    "Worthlessness",                # 13
    "Loss of Energy",               # 14
    "Changes in Sleep",             # 15
    "Irritability",                 # 16
    "Changes in Appetite",          # 17
    "Concentration Difficulty",     # 18
    "Tiredness",                    # 19
    "Loss of Interest in Sex"       # 20
]

CRISIS_ITEM_INDEX = 8  # Item 9 (0-indexed) = suicidal thoughts


def score_bdi(responses: dict) -> dict:
    """
    Score BDI-II responses.

    Args:
        responses: dict mapping item index (0-20) to score (0-3)

    Returns:
        dict with total, severity, is_crisis, completed_items
    """
    total = sum(responses.values())
    is_crisis = responses.get(CRISIS_ITEM_INDEX, 0) >= 2  # Score 2 or 3 on item 9

    # Beck et al. (1996) severity cutoffs
    if total <= 13:
        severity = "minimal"
    elif total <= 19:
        severity = "mild"
    elif total <= 28:
        severity = "moderate"
    else:
        severity = "severe"

    return {
        "total": total,
        "severity": severity,
        "is_crisis": is_crisis,
        "completed_items": len(responses)
    }


def get_severity(bdi_score: int) -> str:
    """Get severity level from BDI score."""
    if bdi_score <= 13:
        return "minimal"
    elif bdi_score <= 19:
        return "mild"
    elif bdi_score <= 28:
        return "moderate"
    else:
        return "severe"


def is_bdi_complete(responses: dict) -> bool:
    """Check if all 21 items have been answered."""
    return len(responses) == 21


def get_next_item_index(responses: dict) -> int:
    """Get the index of the next unanswered item."""
    for i in range(21):
        if i not in responses:
            return i
    return None  # All complete


def get_item_name(index: int) -> str:
    """Get the name of a BDI item by index."""
    if 0 <= index < len(BDI_ITEMS):
        return BDI_ITEMS[index]
    return None


# Test if run directly
if __name__ == "__main__":
    print("Testing BDI scorer:\n")

    # Test case: moderate depression
    test_responses = {i: 1 for i in range(21)}  # All items scored 1
    result = score_bdi(test_responses)

    print(f"Score: {result['total']}")
    print(f"Severity: {result['severity']}")
    print(f"Crisis: {result['is_crisis']}")
    print(f"Completed: {result['completed_items']}/21")

    # Test case: severe with crisis
    test_responses[CRISIS_ITEM_INDEX] = 3
    for i in range(10):
        test_responses[i] = 2

    result = score_bdi(test_responses)
    print(f"\nSevere case:")
    print(f"Score: {result['total']}")
    print(f"Severity: {result['severity']}")
    print(f"Crisis: {result['is_crisis']}")
