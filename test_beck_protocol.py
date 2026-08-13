"""
Quick test script for Beck Protocol implementation
Run this to verify the 3-agent system works
"""

import os
from groq_client import GroqClient

# Test the components
def test_classifier():
    """Test LLM-based cognitive distortion classification"""
    print("=" * 60)
    print("TEST 1: LLM CLASSIFIER (Cognitive Distortion Detection)")
    print("=" * 60)

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("❌ GROQ_API_KEY not set - skipping classifier test")
        return

    client = GroqClient(api_key)

    test_cases = [
        ("I had a nice day today", "G0"),
        ("I'm such a failure, I always mess up", "G1 or G2"),
        ("Nobody likes me, everyone thinks I'm weird", "G2 or G3"),
    ]

    for text, expected in test_cases:
        result = client.classify_distortion(text)
        print(f"\nText: {text[:50]}...")
        print(f"  Predicted: {result['group']} ({result['confidence']:.2%})")
        print(f"  Reasoning: {result.get('reasoning', 'N/A')}")
        print(f"  Expected: {expected}")

    print("\n✅ LLM Classifier test complete\n")


def test_agent1():
    """Test Agent 1 - Warm Questioner"""
    print("=" * 60)
    print("TEST 2: AGENT 1 - Warm Questioner")
    print("=" * 60)

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("❌ GROQ_API_KEY not set - skipping LLM tests")
        return

    client = GroqClient(api_key)

    # Simulate VALIDATE state
    beck_data = {
        "original_thought": "I'm a complete failure",
        "beck_state": "VALIDATE"
    }

    response = client.agent1_warm_questioner(
        current_state="VALIDATE",
        user_message="I'm a complete failure",
        beck_data=beck_data,
        user_name="TestUser",
        conversation_history=[]
    )

    print(f"\nAgent 1 response (VALIDATE state):")
    print(f"  {response}")

    # Test Q1_EVIDENCE_FOR
    beck_data["beck_state"] = "Q1_EVIDENCE_FOR"
    beck_data["initial_belief_rating"] = 85
    beck_data["emotion"] = "sadness"
    beck_data["initial_emotion_intensity"] = 75

    response = client.agent1_warm_questioner(
        current_state="Q1_EVIDENCE_FOR",
        user_message="85",
        beck_data=beck_data,
        user_name="TestUser",
        conversation_history=[
            {"role": "user", "content": "I'm a complete failure"},
            {"role": "assistant", "content": "That sounds really heavy..."}
        ]
    )

    print(f"\nAgent 1 response (Q1_EVIDENCE_FOR state):")
    print(f"  {response}")

    print("\n✅ Agent 1 test complete\n")


def test_agent2():
    """Test Agent 2 - Clinical Summarizer"""
    print("=" * 60)
    print("TEST 3: AGENT 2 - Clinical Summarizer")
    print("=" * 60)

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("❌ GROQ_API_KEY not set - skipping LLM tests")
        return

    client = GroqClient(api_key)

    # Simulate collected Beck data
    beck_data = {
        "original_thought": "I always fail at everything",
        "initial_belief_rating": 85,
        "emotion": "sadness",
        "initial_emotion_intensity": 70,
        "q1_evidence_for": "I failed my exam yesterday",
        "q1_evidence_against": "Well, I did get a good grade on my report last week",
        "q2_alternative": "Maybe I was just tired and didn't prepare enough",
        "q3_worst": "I'll fail out of school",
        "q3_best": "I'll do better next time",
        "q3_realistic": "I'll probably pass the class even if I don't ace everything",
        "q4_effect": "It makes me feel awful and want to give up",
        "q5_friend": "I'd tell them one test doesn't define them",
        "q6_action": "Maybe study more next time"
    }

    summary = client.agent2_clinical_summarizer(beck_data)

    print("\nAgent 2 Clinical Summary:")
    print(f"  Contradictions: {summary.get('contradictions', [])}")
    print(f"  Patient Wisdom: {summary.get('patient_wisdom', 'N/A')}")
    print(f"  Cost of Belief: {summary.get('cost_of_belief', 'N/A')}")
    print(f"  Realistic Prediction: {summary.get('realistic_prediction', 'N/A')}")
    print(f"  Suggested Reframe: {summary.get('suggested_balanced_thought', 'N/A')}")

    print("\n✅ Agent 2 test complete\n")


def test_agent3():
    """Test Agent 3 - Treatment Agent"""
    print("=" * 60)
    print("TEST 4: AGENT 3 - Treatment Agent")
    print("=" * 60)

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("❌ GROQ_API_KEY not set - skipping LLM tests")
        return

    client = GroqClient(api_key)

    beck_data = {
        "original_thought": "I always fail at everything",
        "initial_belief_rating": 85,
        "emotion": "sadness",
        "initial_emotion_intensity": 70,
    }

    clinical_summary = {
        "contradictions": ["Said 'always fails' but got good grade last week"],
        "patient_wisdom": "One test doesn't define them",
        "cost_of_belief": "Makes them feel awful and want to give up",
        "realistic_prediction": "Will probably pass the class",
        "suggested_balanced_thought": "I failed this test, but I've succeeded before and can improve"
    }

    response = client.agent3_treatment_agent(
        current_state="DELIVER_REFRAME",
        user_message="I'm ready to hear it",
        beck_data=beck_data,
        clinical_summary=clinical_summary,
        user_name="TestUser",
        conversation_history=[]
    )

    print(f"\nAgent 3 response (DELIVER_REFRAME):")
    print(f"  {response}")

    print("\n✅ Agent 3 test complete\n")


def test_state_flow():
    """Test state machine flow"""
    print("=" * 60)
    print("TEST 5: STATE MACHINE FLOW")
    print("=" * 60)

    from prompts import BECK_STATES, get_next_state, get_field_to_save

    states_to_test = [
        "VALIDATE",
        "RATE_BELIEF",
        "CAPTURE_EMOTION",
        "Q1_EVIDENCE_FOR",
        "SUMMARIZING",
        "DELIVER_REFRAME",
        "COMPLETE"
    ]

    for state in states_to_test:
        next_state = get_next_state(state)
        field = get_field_to_save(state)
        print(f"\n{state}")
        print(f"  → Next: {next_state}")
        print(f"  → Saves to: {field}")

    print("\n✅ State flow test complete\n")


def test_rating_extraction():
    """Test rating extraction from messages"""
    print("=" * 60)
    print("TEST 6: RATING EXTRACTION")
    print("=" * 60)

    import re

    def extract_rating(message: str) -> int:
        numbers = re.findall(r'\d+', message)
        for num in numbers:
            n = int(num)
            if 0 <= n <= 100:
                return n
        return None

    test_cases = [
        ("85", 85),
        ("I'd say about 70", 70),
        ("100%", 100),
        ("Maybe like... 50?", 50),
        ("Not sure, somewhere around 0", 0),
        ("I don't know", None),
    ]

    for text, expected in test_cases:
        result = extract_rating(text)
        status = "✅" if result == expected else "❌"
        print(f"{status} '{text}' → {result} (expected {expected})")

    print("\n✅ Rating extraction test complete\n")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("BECK PROTOCOL IMPLEMENTATION - TEST SUITE")
    print("=" * 60 + "\n")

    # Run tests
    test_classifier()
    test_agent1()
    test_agent2()
    test_agent3()
    test_state_flow()
    test_rating_extraction()

    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETE")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Start the Flask server: python app.py")
    print("2. Test via API with a real session")
    print("3. Monitor database for beck_sessions table")
    print("\n")
