"""
Beck CBT Protocol - States and Prompts
Based on Beck Institute Thought Record Worksheet (J. Beck, 2020)
"""

# All possible states in the Beck protocol
BECK_STATES = {
    # Agent 1: Warm Questioner States
    "VALIDATE": {
        "agent": 1,
        "instruction": "Acknowledge their pain warmly. Don't ask questions yet. Just validate.",
        "example": "That sounds really heavy. Thank you for sharing that with me. 💙",
        "next_state": "RATE_BELIEF",
        "saves_field": None
    },
    "RATE_BELIEF": {
        "agent": 1,
        "instruction": "Ask how much they believe the thought, 0-100%. Be warm about it.",
        "example": "When that thought hits you — how much does it feel true? Like 0 being 'not at all' and 100 being 'completely certain'?",
        "next_state": "CAPTURE_EMOTION",
        "saves_field": "initial_belief_rating"
    },
    "CAPTURE_EMOTION": {
        "agent": 1,
        "instruction": "Ask what emotion comes up with this thought.",
        "example": "And when you think this thought, what emotion shows up? Sadness? Anxiety? Anger? Something else?",
        "next_state": "RATE_EMOTION",
        "saves_field": "emotion"
    },
    "RATE_EMOTION": {
        "agent": 1,
        "instruction": "Ask how intense the emotion is, 0-100%.",
        "example": "How intense is that feeling right now, 0 to 100?",
        "next_state": "Q1_EVIDENCE_FOR",
        "saves_field": "initial_emotion_intensity"
    },
    "Q1_EVIDENCE_FOR": {
        "agent": 1,
        "instruction": "Ask what happened that made them feel this way. Get the evidence FOR the thought.",
        "example": "I'd like to understand better. What happened that made this thought feel so true?",
        "next_state": "Q1_EVIDENCE_AGAINST",
        "saves_field": "q1_evidence_for"
    },
    "Q1_EVIDENCE_AGAINST": {
        "agent": 1,
        "instruction": "Gently ask if there's any evidence against the thought. Any exceptions.",
        "example": "That makes sense. Can I ask — has there been any time, even small, when things went differently? When you didn't fail, or it worked out okay?",
        "next_state": "Q2_ALTERNATIVE",
        "saves_field": "q1_evidence_against"
    },
    "Q2_ALTERNATIVE": {
        "agent": 1,
        "instruction": "Ask if there could be another explanation for what happened.",
        "example": "If your best friend was in this exact situation, what other explanation might you suggest to them?",
        "next_state": "Q3_WORST",
        "saves_field": "q2_alternative"
    },
    "Q3_WORST": {
        "agent": 1,
        "instruction": "Ask what the worst case scenario would be.",
        "example": "Let's imagine together for a moment. What's the worst that could happen here?",
        "next_state": "Q3_BEST",
        "saves_field": "q3_worst"
    },
    "Q3_BEST": {
        "agent": 1,
        "instruction": "Ask what the best case scenario would be.",
        "example": "And what's the best that could happen?",
        "next_state": "Q3_REALISTIC",
        "saves_field": "q3_best"
    },
    "Q3_REALISTIC": {
        "agent": 1,
        "instruction": "Ask what will realistically/probably happen.",
        "example": "And honestly — what do you think will probably happen? The realistic middle ground?",
        "next_state": "Q4_EFFECT",
        "saves_field": "q3_realistic"
    },
    "Q4_EFFECT": {
        "agent": 1,
        "instruction": "Ask how believing this thought affects them. Does it help or hurt?",
        "example": "When you carry this thought around with you, how does it affect you? Does believing it help you in any way, or does it mostly hurt?",
        "next_state": "Q5_FRIEND",
        "saves_field": "q4_effect"
    },
    "Q5_FRIEND": {
        "agent": 1,
        "instruction": "Ask what they would tell a friend who had this exact thought.",
        "example": "Last question in this part. If someone you really loved — a close friend, a sibling — came to you feeling exactly this way, with this exact thought... what would you say to them?",
        "next_state": "Q6_ACTION",
        "saves_field": "q5_friend"
    },
    "Q6_ACTION": {
        "agent": 1,
        "instruction": "Ask what would be good to do about the situation.",
        "example": "And what do you think would be good to do about this situation?",
        "next_state": "SUMMARIZING",
        "saves_field": "q6_action"
    },

    # Downward Arrow states (triggered when same distortion appears 3+ times)
    "DA_LEVEL_1": {
        "agent": 1,
        "instruction": "The same type of thinking keeps appearing across sessions. Gently begin the downward arrow: 'If that thought were true, what would that mean about you as a person?'",
        "example": "I notice a pattern here... if it were true that [thought], what would that say about you?",
        "next_state": "DA_LEVEL_2",
        "saves_field": "da_level_1"
    },
    "DA_LEVEL_2": {
        "agent": 1,
        "instruction": "Go deeper with the downward arrow. Ask: 'And if THAT were true, what would that mean?'",
        "example": "And if that were the case — what would that mean about you at a deeper level?",
        "next_state": "DA_LEVEL_3",
        "saves_field": "da_level_2"
    },
    "DA_LEVEL_3": {
        "agent": 1,
        "instruction": "Final level of the downward arrow. Ask: 'What does that say about you at your core?' Look for core beliefs: helplessness, unlovability, or worthlessness.",
        "example": "And at the very core — what does all of this say about who you are?",
        "next_state": "SUMMARIZING",
        "saves_field": "da_core_belief"
    },

    # Agent 2: Internal summarization (no user interaction)
    "SUMMARIZING": {
        "agent": 2,
        "instruction": "INTERNAL: Analyze all responses, extract contradictions, prepare for Agent 3.",
        "next_state": "DELIVER_REFRAME",
        "saves_field": None
    },

    # Agent 3: Treatment Agent States
    "DELIVER_REFRAME": {
        "agent": 3,
        "instruction": "Summarize what they discovered and present a balanced thought using THEIR words.",
        "example": "I really appreciate you walking through this with me. Here's what I noticed from YOUR words: [list their insights]. So maybe a thought that fits better might be: '[balanced thought]'. How does that land?",
        "next_state": "RATE_NEW_THOUGHT",
        "saves_field": "adaptive_thought"
    },
    "RATE_NEW_THOUGHT": {
        "agent": 3,
        "instruction": "Ask how much they believe the new balanced thought, 0-100%.",
        "example": "How much do you believe that new thought? 0 to 100?",
        "next_state": "RERATE_ORIGINAL",
        "saves_field": "new_thought_belief"
    },
    "RERATE_ORIGINAL": {
        "agent": 3,
        "instruction": "Ask how much they NOW believe the original thought. Should be lower.",
        "example": "Now thinking back to the original thought — '[original]' — how much do you believe that one now?",
        "next_state": "RERATE_EMOTION",
        "saves_field": "final_belief_rating"
    },
    "RERATE_EMOTION": {
        "agent": 3,
        "instruction": "Ask how intense the emotion is now. Should be lower.",
        "example": "And that [emotion] you mentioned — how intense is it now, 0 to 100?",
        "next_state": "ACTION_PLAN",
        "saves_field": "final_emotion_intensity"
    },
    "ACTION_PLAN": {
        "agent": 3,
        "instruction": "Help them create a small behavioral experiment or action plan.",
        "example": "You've made some real shifts today. Is there one small thing you could do this week to test this new perspective? Even something tiny counts.",
        "next_state": "COMPLETE",
        "saves_field": "action_plan"
    },
    "COMPLETE": {
        "agent": 3,
        "instruction": "Celebrate their progress. Summarize the improvement. End warmly.",
        "example": "You started at [X]% and you're at [Y]% now — that's real movement. 💙 You did good work today. Remember, you can always come back when you need to talk.",
        "next_state": None,
        "saves_field": None
    }
}

# States handled by each agent
AGENT1_STATES = [
    "VALIDATE", "RATE_BELIEF", "CAPTURE_EMOTION", "RATE_EMOTION",
    "Q1_EVIDENCE_FOR", "Q1_EVIDENCE_AGAINST", "Q2_ALTERNATIVE",
    "Q3_WORST", "Q3_BEST", "Q3_REALISTIC", "Q4_EFFECT", "Q5_FRIEND", "Q6_ACTION",
    "DA_LEVEL_1", "DA_LEVEL_2", "DA_LEVEL_3"
]

AGENT3_STATES = [
    "DELIVER_REFRAME", "RATE_NEW_THOUGHT", "RERATE_ORIGINAL",
    "RERATE_EMOTION", "ACTION_PLAN", "COMPLETE"
]

def get_state_info(state: str) -> dict:
    """Get info about a Beck state."""
    return BECK_STATES.get(state, {})

def get_next_state(current_state: str) -> str:
    """Get the next state in the protocol."""
    state_info = BECK_STATES.get(current_state, {})
    return state_info.get("next_state")

def get_field_to_save(state: str) -> str:
    """Get which database field this state saves to."""
    state_info = BECK_STATES.get(state, {})
    return state_info.get("saves_field")

# Natural conversation endings (kept for compatibility)
NATURAL_ENDINGS = [
    "Take care of yourself, {name}! I'm always here when you need to talk. 💙",
    "Glad I could help, {name}! Remember, you're doing better than you think. See you next time! 💙",
    "Bye for now, {name}! Be kind to yourself today. 💙",
    "Take it easy, {name}! You've got this. See you soon! 💙",
    "Catch you later, {name}! Remember, one step at a time. 💙"
]
