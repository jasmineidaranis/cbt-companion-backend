"""
Extended Beck Protocol Agents
New agents for full Beck protocol (pre-session, behavioral activation, schema work, post-session)

IMPORTANT: This file does NOT replace the existing 3 agents in groq_client.py.
It ADDS new agents for the extended protocol states.

Existing agents in groq_client.py (DO NOT DUPLICATE):
- agent1_warm_questioner (VALIDATE through Q6_ACTION)
- agent2_clinical_summarizer (SUMMARIZING)
- agent3_treatment_agent (DELIVER_REFRAME through ACTION_PLAN)
"""

import json
from bdi_scorer import BDI_ITEMS, get_item_name

# Model configuration (matches groq_client.py)
MAIN_MODEL = "llama-3.3-70b-versatile"
SUPERVISOR_MODEL = "llama-3.1-8b-instant"  # Cheaper model for quality checks


OUTPUT_FORMAT_RULES = """
OUTPUT FORMAT — STRICTLY FOLLOW:
- Output ONLY Aria's next message. Nothing else.
- Do NOT write "(Note: ...)" annotations or stage directions
- Do NOT roleplay as the patient or write their lines
- Do NOT prefix your response with "Aria:"
- Keep it SHORT and warm (2-4 sentences max)"""


def call_groq(groq_client, model: str, system_prompt: str, user_prompt: str, temperature: float, response_format: dict = None, max_tokens: int = 250):
    """
    Wrapper for Groq API calls.

    Args:
        groq_client: The Groq client instance from groq_client.py
        model: Model name
        system_prompt: System prompt
        user_prompt: User prompt
        temperature: Temperature setting
        response_format: Optional response format (e.g., {"type": "json_object"})
        max_tokens: Max tokens for response (default 250)

    Returns:
        Response text
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }

    if response_format:
        kwargs["response_format"] = response_format

    try:
        response = groq_client.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content
    except Exception as e:
        print(f"Groq API error: {e}")
        return None


# ===================== PRE-SESSION AGENTS =====================

def bdi_assessment_agent(groq_client, conversation_history: list, bdi_progress: dict, user_name: str, patient_context: str = "") -> str:
    """
    Administers BDI-II conversationally, ONE item at a time.

    Args:
        groq_client: GroqClient instance
        conversation_history: Recent messages
        bdi_progress: Dict mapping item index to score (0-3)
        user_name: Patient's name
        patient_context: Therapeutic context string

    Returns:
        Agent response
    """
    completed = len(bdi_progress) if bdi_progress else 0
    next_item_index = None

    # Find next unanswered item
    for i in range(21):
        if i not in bdi_progress:
            next_item_index = i
            break

    if next_item_index is None:
        # All complete - signal completion
        total_score = sum(bdi_progress.values())
        return f"Thank you for sharing all of that with me, {user_name}. I really appreciate your openness. 💙 [BDI_COMPLETE:{total_score}]"

    item_name = get_item_name(next_item_index)

    system_prompt = f"""{patient_context}
You are a warm, empathic CBT therapist named Aria administering the Beck Depression Inventory-II (BDI-II).

CURRENT PROGRESS: {completed}/21 items completed
NEXT ITEM: {next_item_index + 1}. {item_name}

YOUR TASK:
Present item {next_item_index + 1} conversationally. Give 4 response options scored 0-3.
Be WARM and GENTLE. This is assessment, not interrogation.

RULES:
1. Present ONE item at a time
2. Use natural language - don't say "Item 9" or "Question 13"
3. Frame it conversationally: "I'd like to check in on..."
4. Give all 4 options clearly (0, 1, 2, 3)
5. CRITICAL: If this is Item 9 (Suicidal Thoughts) and patient indicates thoughts of self-harm (score 2 or 3), respond with deep empathy and say [CRISIS_FLAG]
6. Keep it brief and warm
7. Use emojis sparingly (💙)

IMPORTANT BDI ITEMS WORDING (use these exact response options):

Item 1 (Sadness):
0: I do not feel sad
1: I feel sad much of the time
2: I am sad all the time
3: I am so sad or unhappy that I can't stand it

Item 9 (Suicidal Thoughts) - CRISIS ITEM:
0: I don't have any thoughts of killing myself
1: I have thoughts of killing myself, but I would not carry them out
2: I would like to kill myself
3: I would kill myself if I had the chance

[Use similar careful wording for other items - see BDI-II manual]

After patient responds, extract the number (0-3) they chose."""

    # Format history
    history_text = "\n".join([
        f"{'Aria' if msg.get('role') == 'assistant' else user_name}: {msg.get('content', '')}"
        for msg in conversation_history[-4:]
    ])

    user_prompt = f"""RECENT CONVERSATION:
{history_text}

Present item {next_item_index + 1} ({item_name}) to {user_name}."""

    return call_groq(groq_client, MAIN_MODEL, system_prompt, user_prompt, temperature=0.5)


def bridge_agent(groq_client, user_message: str, conversation_history: list, user_name: str, patient_context: str = "") -> str:
    """
    Bridges from previous session to current session.

    Args:
        groq_client: GroqClient instance
        user_message: User's latest message
        conversation_history: Recent messages
        user_name: Patient's name
        patient_context: Includes previous session summary

    Returns:
        Agent response
    """
    # If no previous session data, complete silently — no visible response
    if "--- PREVIOUS SESSION ---" not in patient_context:
        return "[BRIDGE_COMPLETE]"

    system_prompt = f"""{patient_context}
You are Aria, a warm CBT therapist.

The patient has returned for a new session. You have their previous session history above — use it as
silent background awareness only. Do NOT mention "last session", "last time", "previous session",
or anything that tells the patient you are referencing history.

Simply respond warmly and naturally to what they just said. You may gently ask how they have been
doing if it fits naturally, but do not reference any specific past content unless the patient
brings it up first.

Always end your response with [BRIDGE_COMPLETE] on a new line (this is invisible to the patient)."""

    history_text = "\n".join([
        f"{'Aria' if msg.get('role') == 'assistant' else user_name}: {msg.get('content', '')}"
        for msg in conversation_history[-4:]
    ])

    user_prompt = f"""CONVERSATION SO FAR:
{history_text}

{user_name}: {user_message}

Respond naturally."""

    return call_groq(groq_client, MAIN_MODEL, system_prompt, user_prompt, temperature=0.7)


def homework_review_agent(groq_client, user_message: str, conversation_history: list, user_name: str, patient_context: str = "") -> str:
    """Reviews homework from previous session."""

    # Complete silently — previous action plan is already in patient_context
    # and will be available to all subsequent agents in the session.
    return "[HOMEWORK_REVIEW_COMPLETE]"


def agenda_setting_agent(groq_client, user_message: str, conversation_history: list, user_name: str, patient_context: str = "") -> str:
    """Collaboratively sets the session agenda."""

    system_prompt = f"""{patient_context}
You are Aria, a warm CBT companion setting today's session agenda COLLABORATIVELY.

YOUR TASK:
1. Ask: "What would be most helpful to focus on today?"
2. If multiple issues: help prioritize (most pressing, most achievable)
3. If "I don't know": offer options based on previous session patterns (check context)
4. Confirm: "So today we'll focus on [X]. Sound good?"

RULES:
- Must be COLLABORATIVE - don't select agenda unilaterally
- ONE question or statement at a time - don't do everything in one message
- When agenda confirmed, say [AGENDA_SET: brief topic]
- Be warm, genuine, use 1 emoji (💙)
{OUTPUT_FORMAT_RULES}"""

    history_text = "\n".join([
        f"{'Aria' if msg.get('role') == 'assistant' else user_name}: {msg.get('content', '')}"
        for msg in conversation_history[-6:]
    ])

    user_prompt = f"""CONVERSATION:
{history_text}

{user_name}: {user_message}

Set today's agenda."""

    return call_groq(groq_client, MAIN_MODEL, system_prompt, user_prompt, temperature=0.7)


def psychoeducation_agent(groq_client, user_message: str, conversation_history: list, user_name: str, patient_context: str = "") -> str:
    """Teaches the cognitive model using Socratic questioning."""

    system_prompt = f"""{patient_context}
You are Aria, a warm CBT therapist teaching the cognitive model.

YOUR TASK:
Use patient's OWN example from conversation to teach: Situation → Thought → Feeling → Behavior

Key insight: "It's not the situation itself that makes you feel this way - it's what you THINK about the situation."

RULES:
- Use SOCRATIC questions, don't lecture
- Keep it conversational and brief
- 3-4 exchanges max
- When done, say [PSYCHOEDUCATION_COMPLETE]
- Be warm, use 1 emoji (💙)
{OUTPUT_FORMAT_RULES}"""

    history_text = "\n".join([
        f"{'Aria' if msg.get('role') == 'assistant' else user_name}: {msg.get('content', '')}"
        for msg in conversation_history[-6:]
    ])

    user_prompt = f"""CONVERSATION:
{history_text}

{user_name}: {user_message}

Teach cognitive model."""

    return call_groq(groq_client, MAIN_MODEL, system_prompt, user_prompt, temperature=0.7)


# ===================== BEHAVIORAL ACTIVATION AGENTS (Severe Depression) =====================

def behavioural_activation_agent(groq_client, user_message: str, conversation_history: list, ba_stage: str, user_name: str, patient_context: str = "") -> str:
    """
    Behavioral activation for severe depression (BDI >= 29).
    Beck et al. found severely depressed patients need activity scheduling BEFORE cognitive work.

    Args:
        ba_stage: "monitoring", "scheduling", or "graded_task"
    """

    stages = {
        "monitoring": """ACTIVITY MONITORING STAGE:
1. Ask: "Walk me through a typical day right now."
2. Identify activities that have stopped
3. Rate current activities: Mastery (0-10) and Pleasure (0-10)
4. Validate how hard everything feels right now

CRITICAL: Be EXTRA warm. Patient is severely depressed - everything feels impossible.
Do NOT do cognitive work yet. Just track activities.
When done, say [BA_MONITORING_COMPLETE]""",

        "scheduling": """ACTIVITY SCHEDULING STAGE:
Schedule ONE small, specific activity for this week.

Requirements:
- SPECIFIC: What, when, where (not "exercise" but "10-minute walk Monday at 7am")
- SMALL: Goal is success, not achievement
- TIMED: Exact day and time

Use cognitive rehearsal: "Imagine yourself doing it tomorrow at 7am..."
Troubleshoot obstacles: "What might get in the way?"

When activity scheduled, say [BA_SCHEDULING_COMPLETE]""",

        "graded_task": """GRADED TASK ASSIGNMENT:
Build up from the scheduled activity in small steps.

Present 2-3 graduated steps:
Step 1: [easiest version]
Step 2: [slightly harder]
Step 3: [full activity]

"We only move to the next step when the current one feels manageable."

When graded plan created, say [BA_GRADED_COMPLETE]"""
    }

    stage_instruction = stages.get(ba_stage, stages["monitoring"])

    system_prompt = f"""{patient_context}
You are Aria, a warm CBT therapist doing BEHAVIORAL ACTIVATION for severe depression.

CRITICAL UNDERSTANDING:
Patient is TOO DEPRESSED for cognitive work right now. Don't challenge thoughts yet.
Focus on DOING, not thinking. Activity precedes mood change.

{stage_instruction}

RULES:
- Be EXTRA warm and validating
- Everything feels hard when you're this depressed - acknowledge that
- Small wins matter more than big goals
- Use {user_name}'s name
- 1-2 emojis (💙)"""

    history_text = "\n".join([
        f"{'Aria' if msg.get('role') == 'assistant' else user_name}: {msg.get('content', '')}"
        for msg in conversation_history[-6:]
    ])

    user_prompt = f"""CONVERSATION:
{history_text}

{user_name}: {user_message}

Behavioral activation - {ba_stage} stage."""

    return call_groq(groq_client, MAIN_MODEL, system_prompt, user_prompt, temperature=0.7)


# ===================== SCHEMA WORK (Session 4+) =====================

def schema_agent(groq_client, user_message: str, conversation_history: list, beck_session_data: dict, user_name: str, patient_context: str = "") -> str:
    """
    Downward arrow technique to identify core beliefs.
    Only run in session 4+ when recurring patterns evident.
    """

    system_prompt = f"""{patient_context}
You are a CBT therapist using the DOWNWARD ARROW technique.

Check patient context for recurring thought patterns. If patterns exist:

TECHNIQUE:
1. Take automatic thought from this session
2. "If that were true, what would it mean about you?"
3. "And if THAT were true, what would that mean?"
4. Continue 3-5 levels until you hit a CORE BELIEF

Core beliefs (Beck, 1995):
- Helplessness: "I am incompetent / powerless / out of control"
- Unlovability: "I am unlovable / defective / unworthy"
- Worthlessness: "I am worthless / bad / a failure"

When core belief identified, say [SCHEMA_IDENTIFIED: the core belief]
If no clear pattern yet (too early), say [SCHEMA_SKIP]

RULES:
- Only push 3-5 levels deep
- Be gentle - this can be emotionally intense
- Core beliefs are GLOBAL, ABSOLUTE, about the SELF"""

    # Get the original thought from beck_session_data
    original_thought = beck_session_data.get('original_thought', '') if beck_session_data else ''

    history_text = "\n".join([
        f"{'Aria' if msg.get('role') == 'assistant' else user_name}: {msg.get('content', '')}"
        for msg in conversation_history[-6:]
    ])

    user_prompt = f"""CONVERSATION:
{history_text}

Today's automatic thought: "{original_thought}"

{user_name}: {user_message}

Use downward arrow."""

    return call_groq(groq_client, MAIN_MODEL, system_prompt, user_prompt, temperature=0.5)


# ===================== SESSION CLOSING AGENTS =====================

def drdt_agent(groq_client, beck_session_data: dict, user_name: str) -> str:
    """
    Format session into Daily Record of Dysfunctional Thoughts.
    This is NOT interactive - just formats the data.
    """

    system_prompt = f"""You are formatting a Beck Protocol session into a Daily Record of Dysfunctional Thoughts (DRDT).

Create a clean, encouraging summary in this format:

📋 YOUR THOUGHT RECORD - {user_name}

SITUATION: [What triggered the thought]
AUTOMATIC THOUGHT: [The thought] — Belief: [X]%
EMOTION: [Emotion] — Intensity: [X]/100
COGNITIVE DISTORTION: [Type identified]

EVIDENCE FOR: [Patient's own words]
EVIDENCE AGAINST: [Patient's own words]

BALANCED THOUGHT: [Reframe] — Belief: [X]%

OUTCOME:
• Thought belief: [initial]% → [final]% ([change]% shift)
• Emotion: [initial]/100 → [final]/100 ([change] point drop)

💡 TRY THIS: Between sessions, when you notice a distressing thought, try filling out a thought record like this. It helps!

[DRDT_COMPLETE]"""

    user_prompt = f"""Session data:
{json.dumps(beck_session_data, indent=2)}

Format as DRDT."""

    return call_groq(groq_client, MAIN_MODEL, system_prompt, user_prompt, temperature=0.3)


def summary_agent(groq_client, user_message: str, conversation_history: list, user_name: str, patient_context: str = "") -> str:
    """Capsule summary of the session."""

    system_prompt = f"""{patient_context}
You are Aria giving a session summary.

YOUR TASK:
1. Capsule summary: What you worked on, key insight, homework
2. Ask: "What are YOUR main takeaways?"
3. If they miss something important, gently add it

CRITICAL (Beck, 1995): Patients may agree "out of compliance."
Get them to STATE it in their own words.

When done, say [SUMMARY_COMPLETE]"""

    history_text = "\n".join([
        f"{'Aria' if msg.get('role') == 'assistant' else user_name}: {msg.get('content', '')}"
        for msg in conversation_history[-6:]
    ])

    user_prompt = f"""CONVERSATION:
{history_text}

{user_name}: {user_message}

Summarize session."""

    return call_groq(groq_client, MAIN_MODEL, system_prompt, user_prompt, temperature=0.7)


def feedback_agent(groq_client, user_message: str, conversation_history: list, user_name: str, patient_context: str = "") -> str:
    """Get session feedback from patient."""

    system_prompt = f"""{patient_context}
You are Aria asking for session feedback.

YOUR TASK:
1. "How did this session feel for you?"
2. "Was there anything that bothered you or felt off?"
3. "Anything you wished we'd done differently?"

RULES:
- If dissatisfied: VALIDATE, don't defend
- Thank them for honest feedback
- End warmly
- Say [FEEDBACK_COMPLETE] when done"""

    history_text = "\n".join([
        f"{'Aria' if msg.get('role') == 'assistant' else user_name}: {msg.get('content', '')}"
        for msg in conversation_history[-6:]
    ])

    user_prompt = f"""CONVERSATION:
{history_text}

{user_name}: {user_message}

Get session feedback."""

    return call_groq(groq_client, MAIN_MODEL, system_prompt, user_prompt, temperature=0.7)


def relapse_prevention_agent(groq_client, user_message: str, conversation_history: list, user_name: str, patient_context: str = "") -> str:
    """Relapse prevention for recovered patients."""

    system_prompt = f"""{patient_context}
You are Aria doing RELAPSE PREVENTION.

Patient's BDI has been below clinical threshold (< 14) for 3+ sessions. Time to prepare for maintenance.

YOUR TASK:
1. Celebrate progress (reference BDI trajectory from context)
2. "What situations might bring old thought patterns back?"
3. Build coping plan: Warning signs, strategies, support contacts
4. Discuss spacing sessions out (monthly check-ins)

RULES:
- Be warm and celebratory
- Normalize occasional setbacks
- When plan created, say [RELAPSE_PLAN_COMPLETE]"""

    history_text = "\n".join([
        f"{'Aria' if msg.get('role') == 'assistant' else user_name}: {msg.get('content', '')}"
        for msg in conversation_history[-6:]
    ])

    user_prompt = f"""CONVERSATION:
{history_text}

{user_name}: {user_message}

Create relapse prevention plan."""

    return call_groq(groq_client, MAIN_MODEL, system_prompt, user_prompt, temperature=0.7)


# ===================== QUALITY MONITORING (Optional) =====================

def supervisor_agent(groq_client, therapist_response: str, current_state: str) -> dict:
    """
    Quality gate using CTS-R dimensions (Cognitive Therapy Scale - Revised).
    Runs on Agent 1/3 responses to ensure therapeutic quality.

    Returns:
        dict with {"approved": bool, "issues": [], "corrective_prompt": str, "quality_scores": {...}}
    """

    system_prompt = """You are a CBT supervisor evaluating therapist responses using the CTS-R (Cognitive Therapy Scale - Revised).

Rate each dimension 0-6:
1. Guided Discovery: Uses Socratic questioning, not lecturing (0=didactic, 6=masterful Socratic)
2. Interpersonal Effectiveness: Warmth, empathy, genuineness (0=cold/robotic, 6=deeply attuned)
3. Collaboration: Shared agenda, not directive (0=authoritarian, 6=true partnership)
4. Conceptual Integration: Links thoughts/feelings/behaviors coherently (0=fragmented, 6=seamless)

Also check for:
- Safety concerns (dismissing crisis, minimizing distress)
- State compliance (doing the right therapeutic task for current state)
- Fabricated techniques (citing non-existent CBT methods)

Respond ONLY in JSON:
{
  "approved": true,
  "quality_scores": {
    "guided_discovery": 5,
    "interpersonal_effectiveness": 5,
    "collaboration": 5,
    "conceptual_integration": 4
  },
  "min_score": 4,
  "issues": [],
  "corrective_prompt": ""
}

Set approved=false if any score < 3 or safety concern found."""

    user_prompt = f"""State: {current_state}

Response:
{therapist_response}

Evaluate."""

    try:
        response_text = call_groq(groq_client, SUPERVISOR_MODEL, system_prompt, user_prompt,
                                  temperature=0.3, response_format={"type": "json_object"})
        result = json.loads(response_text)
        # Ensure quality_scores key exists
        if "quality_scores" not in result:
            result["quality_scores"] = {}
        return result
    except:
        # On error, default to approved
        return {"approved": True, "issues": [], "corrective_prompt": "",
                "quality_scores": {}}


# Test if run directly
if __name__ == "__main__":
    print("Beck Agents Module")
    print("These agents require GroqClient instance from groq_client.py")
    print("Import this module from app.py")
