"""
Groq API Client - 3 Agent System for Beck CBT Protocol
"""

import json
from groq import Groq


class GroqClient:
    """
    3-Agent system for Beck's Cognitive Restructuring Protocol.
    - Agent 1: Warm Questioner (validation + 6 questions)
    - Agent 2: Clinical Summarizer (internal analysis)
    - Agent 3: Treatment Agent (reframe + measurement + action)
    """

    MODEL = "llama-3.3-70b-versatile"

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("GROQ_API_KEY is required")
        # Set timeout to prevent hanging requests (60 seconds max per request)
        self.client = Groq(api_key=api_key, timeout=60.0)
        print(f"✅ Groq client initialized with model: {self.MODEL} (timeout: 60s)")

    # ==================== AGENT 1: WARM QUESTIONER ====================

    def agent1_warm_questioner(
        self,
        current_state: str,
        user_message: str,
        beck_data: dict,
        user_name: str,
        conversation_history: list = None,
        supervisor_note: str = None
    ) -> str:
        """
        Agent 1: Asks Beck's questions one at a time in a warm, supportive way.

        Args:
            current_state: Current Beck protocol state (e.g., "Q1_EVIDENCE_FOR")
            user_message: User's latest response
            beck_data: All collected data so far
            user_name: User's name for personalization
            conversation_history: Recent messages for context

        Returns:
            Response string to send to user
        """
        from prompts import BECK_STATES

        state_info = BECK_STATES.get(current_state, {})
        instruction = state_info.get("instruction", "")
        example = state_info.get("example", "")

        # Build context of what we know so far
        context_parts = []
        if beck_data.get("original_thought"):
            context_parts.append(f"Their thought: \"{beck_data['original_thought']}\"")
        if beck_data.get("initial_belief_rating"):
            context_parts.append(f"Belief rating: {beck_data['initial_belief_rating']}%")
        if beck_data.get("emotion"):
            context_parts.append(f"Emotion: {beck_data['emotion']}")
        if beck_data.get("initial_emotion_intensity"):
            context_parts.append(f"Emotion intensity: {beck_data['initial_emotion_intensity']}%")

        context_text = "\n".join(context_parts) if context_parts else "Just starting the conversation."

        history_text = self._format_history(conversation_history) if conversation_history else ""

        system_prompt = f"""You are a warm, caring CBT companion named Aria talking to {user_name}.
You are NOT a clinical therapist - you're like a supportive friend who knows CBT techniques.

CURRENT STATE: {current_state}
YOUR TASK: {instruction}
EXAMPLE RESPONSE: "{example}"

WHAT WE KNOW SO FAR:
{context_text}

CRITICAL RULES:
1. Be WARM and GENTLE - like a caring friend, not a clinician
2. Keep responses SHORT (1-3 sentences max) - be concise and warm
3. Ask only ONE thing at a time
4. Use {user_name}'s name occasionally (not every message)
5. Use 1-2 emojis to feel warm (💙 🌟 ✨)
6. VALIDATE before asking - acknowledge what they shared
7. Don't lecture or be preachy - keep it light
8. If they give a number (like "80"), acknowledge it warmly before moving on
9. Don't explain what you're doing - just do it naturally

OUTPUT FORMAT — STRICTLY FOLLOW:
- Output ONLY Aria's next message. Nothing else.
- Do NOT write "(Note: ...)" annotations or stage directions
- Do NOT write from {user_name}'s perspective or prompt them to respond
- Do NOT roleplay as {user_name} or write their lines
- Do NOT prefix your response with "Aria:"

IMPORTANT:
- If they share something painful, validate it first
- Match their emotional tone
- Be conversational, not scripted{f'''

SUPERVISOR FEEDBACK (improve on this):
{supervisor_note}''' if supervisor_note else ""}"""

        user_prompt = f"""RECENT CONVERSATION:
{history_text}

{user_name}'s latest message: "{user_message}"

Respond as Aria, the warm CBT companion. Remember: short, warm, one question at a time."""

        try:
            response = self.client.chat.completions.create(
                model=self.MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=150
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"Agent 1 error: {e}")
            return f"I hear you, {user_name}. 💙 Tell me more about that."

    # ==================== AGENT 2: CLINICAL SUMMARIZER ====================

    def agent2_clinical_summarizer(self, beck_data: dict) -> dict:
        """
        Agent 2: Analyzes all responses and prepares summary for Agent 3.
        This is INTERNAL - user never sees this output.

        Args:
            beck_data: All collected data from Agent 1

        Returns:
            dict with analysis for Agent 3
        """
        system_prompt = """You are a clinical analyzer for a CBT system.
Analyze the patient's responses and extract key patterns for the treatment agent.

Your task:
1. Identify CONTRADICTIONS (where their evidence contradicts their belief)
2. Extract their OWN WISDOM (what they'd tell a friend)
3. Note the COST of their belief (how it hurts them)
4. Pull their REALISTIC prediction (usually more balanced than their fear)
5. Suggest elements for a reframe using THEIR OWN WORDS

Respond ONLY in JSON format."""

        user_prompt = f"""Analyze these responses:

ORIGINAL THOUGHT: {beck_data.get('original_thought', 'Not captured')}
INITIAL BELIEF: {beck_data.get('initial_belief_rating', '?')}%
EMOTION: {beck_data.get('emotion', '?')} at {beck_data.get('initial_emotion_intensity', '?')}%

EVIDENCE FOR THE THOUGHT: {beck_data.get('q1_evidence_for', 'Not answered')}
EVIDENCE AGAINST: {beck_data.get('q1_evidence_against', 'Not answered')}
ALTERNATIVE EXPLANATION: {beck_data.get('q2_alternative', 'Not answered')}
WORST CASE: {beck_data.get('q3_worst', 'Not answered')}
BEST CASE: {beck_data.get('q3_best', 'Not answered')}
REALISTIC CASE: {beck_data.get('q3_realistic', 'Not answered')}
EFFECT OF BELIEVING: {beck_data.get('q4_effect', 'Not answered')}
WHAT THEY'D TELL A FRIEND: {beck_data.get('q5_friend', 'Not answered')}
WHAT THEY THINK THEY SHOULD DO: {beck_data.get('q6_action', 'Not answered')}

Return JSON with:
{{
  "contradictions": ["list of contradictions between thought and evidence"],
  "patient_wisdom": "what they said they'd tell a friend",
  "cost_of_belief": "how believing this thought hurts them",
  "realistic_prediction": "their realistic outcome prediction",
  "reframe_elements": ["key phrases from their answers to use in reframe"],
  "suggested_balanced_thought": "a balanced thought using their own words"
}}"""

        try:
            response = self.client.chat.completions.create(
                model=self.MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_tokens=500,
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            print(f"Agent 2 error: {e}")
            return {
                "contradictions": [],
                "patient_wisdom": beck_data.get('q5_friend', ''),
                "cost_of_belief": beck_data.get('q4_effect', ''),
                "realistic_prediction": beck_data.get('q3_realistic', ''),
                "reframe_elements": [],
                "suggested_balanced_thought": "Things are hard right now, but one moment doesn't define everything."
            }

    # ==================== AGENT 3: TREATMENT AGENT ====================

    def agent3_treatment_agent(
        self,
        current_state: str,
        user_message: str,
        beck_data: dict,
        clinical_summary: dict,
        user_name: str,
        conversation_history: list = None,
        supervisor_note: str = None
    ) -> str:
        """
        Agent 3: Delivers the reframe, measures change, creates action plan.

        Args:
            current_state: Current state (DELIVER_REFRAME, RATE_NEW_THOUGHT, etc.)
            user_message: User's latest response
            beck_data: All collected data
            clinical_summary: Analysis from Agent 2
            user_name: User's name
            conversation_history: Recent messages

        Returns:
            Response string to send to user
        """
        from prompts import BECK_STATES

        state_info = BECK_STATES.get(current_state, {})
        instruction = state_info.get("instruction", "")

        # Build improvement stats if available
        improvement_text = ""
        if beck_data.get('initial_belief_rating') and beck_data.get('final_belief_rating'):
            belief_change = beck_data['initial_belief_rating'] - beck_data['final_belief_rating']
            improvement_text += f"Belief dropped from {beck_data['initial_belief_rating']}% to {beck_data['final_belief_rating']}% ({belief_change}% improvement). "
        if beck_data.get('initial_emotion_intensity') and beck_data.get('final_emotion_intensity'):
            emotion_change = beck_data['initial_emotion_intensity'] - beck_data['final_emotion_intensity']
            improvement_text += f"Emotion dropped from {beck_data['initial_emotion_intensity']}% to {beck_data['final_emotion_intensity']}% ({emotion_change}% improvement)."

        history_text = self._format_history(conversation_history) if conversation_history else ""

        system_prompt = f"""You are Aria, a warm CBT companion helping {user_name} complete cognitive restructuring.

CURRENT STATE: {current_state}
YOUR TASK: {instruction}

ORIGINAL THOUGHT: "{beck_data.get('original_thought', '')}"
INITIAL BELIEF: {beck_data.get('initial_belief_rating', '?')}%
EMOTION: {beck_data.get('emotion', '?')} at {beck_data.get('initial_emotion_intensity', '?')}%

CLINICAL ANALYSIS:
- Contradictions found: {clinical_summary.get('contradictions', [])}
- Their own wisdom: "{clinical_summary.get('patient_wisdom', '')}"
- Cost of belief: "{clinical_summary.get('cost_of_belief', '')}"
- Realistic prediction: "{clinical_summary.get('realistic_prediction', '')}"
- Suggested reframe: "{clinical_summary.get('suggested_balanced_thought', '')}"

{f"IMPROVEMENT SO FAR: {improvement_text}" if improvement_text else ""}

CRITICAL RULES:
1. Use THEIR OWN WORDS when possible - this makes the reframe feel like theirs
2. Be warm and celebratory about any progress
3. Keep responses SHORT but meaningful (2-4 sentences max)
4. If delivering reframe, list what THEY discovered first
5. For re-ratings, acknowledge the number warmly
6. 10%+ improvement = SUCCESS - celebrate it!
7. Use 1-2 emojis (💙 🌟 ✨)
8. Don't be clinical or lecture-y

OUTPUT FORMAT — STRICTLY FOLLOW:
- Output ONLY Aria's next message. Nothing else.
- Do NOT write "(Note: ...)" annotations or stage directions
- Do NOT write from {user_name}'s perspective or prompt them to respond
- Do NOT roleplay as {user_name} or write their lines
- Do NOT prefix your response with "Aria:"{f'''

SUPERVISOR FEEDBACK (improve on this):
{supervisor_note}''' if supervisor_note else ""}"""

        user_prompt = f"""RECENT CONVERSATION:
{history_text}

{user_name}'s latest message: "{user_message}"

Respond as Aria for the {current_state} state."""

        try:
            response = self.client.chat.completions.create(
                model=self.MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=400
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"Agent 3 error: {e}")
            return f"You've done really good work here, {user_name}. 💙"

    # ==================== COGNITIVE DISTORTION CLASSIFIER ====================

    def classify_distortion(self, text: str) -> dict:
        """
        Classify text into cognitive distortion groups using LLM.

        Groups:
        - G0: No Distortion
        - G1: Binary & Global Evaluation (All-or-nothing, Labeling)
        - G2: Overgeneralized Beliefs (Overgeneralization, Mind Reading, Fortune-telling)
        - G3: Attentional Bias (Mental Filter, Magnification)
        - G4: Self-Referential Reasoning (Emotional Reasoning, Personalization, Should statements)

        Args:
            text: User's thought to classify

        Returns:
            dict with group, confidence, group_name, description, and distortions
        """
        system_prompt = """You are a cognitive distortion classifier for CBT (Cognitive Behavioral Therapy).

Analyze the user's thought and classify it into ONE of these groups:

G0: No Distortion - Healthy, balanced thinking
G1: Binary & Global Evaluation - All-or-nothing thinking, Labeling
G2: Overgeneralized Beliefs - Overgeneralization, Mind Reading, Fortune-telling
G3: Attentional & Salience Bias - Mental Filter, Magnification/Minimization
G4: Self-Referential & Emotion-Driven - Emotional Reasoning, Personalization, Should statements

Examples:
- "I failed my exam. I'll never succeed at anything." → G1 (all-or-nothing)
- "My friend didn't text back. She must hate me." → G2 (mind reading)
- "Everything in my life is terrible." → G3 (mental filter)
- "I feel anxious so something bad must be happening." → G4 (emotional reasoning)
- "I had a nice day today and enjoyed my lunch." → G0 (no distortion)

Respond ONLY in JSON format:
{
  "group": "G0/G1/G2/G3/G4",
  "confidence": 0.85,
  "reasoning": "Brief explanation of why this classification"
}"""

        user_prompt = f'Classify this thought: "{text}"'

        try:
            response = self.client.chat.completions.create(
                model=self.MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_tokens=200,
                response_format={"type": "json_object"}
            )

            result = json.loads(response.choices[0].message.content)
            group = result.get("group", "G0")

            # Group information
            label_info = {
                "G0": {
                    "name": "No Distortion Detected",
                    "description": "Healthy, balanced thinking",
                    "distortions": []
                },
                "G1": {
                    "name": "Binary & Global Evaluation",
                    "description": "All-or-nothing thinking patterns",
                    "distortions": ["All-or-nothing thinking", "Labeling"]
                },
                "G2": {
                    "name": "Overgeneralized Beliefs",
                    "description": "Making broad conclusions from limited evidence",
                    "distortions": ["Overgeneralization", "Mind Reading", "Fortune-telling"]
                },
                "G3": {
                    "name": "Attentional & Salience Bias",
                    "description": "Focusing on negatives, ignoring positives",
                    "distortions": ["Mental Filter", "Magnification"]
                },
                "G4": {
                    "name": "Self-Referential & Emotion-Driven",
                    "description": "Letting emotions drive conclusions",
                    "distortions": ["Emotional Reasoning", "Personalization", "Should statements"]
                }
            }

            group_info = label_info.get(group, label_info["G0"])

            return {
                "group": group,
                "confidence": round(result.get("confidence", 0.8), 4),
                "group_name": group_info["name"],
                "description": group_info["description"],
                "distortions": group_info["distortions"],
                "reasoning": result.get("reasoning", "")
            }

        except Exception as e:
            print(f"Classification error: {e}")
            # Default to G0 (no distortion) on error
            return {
                "group": "G0",
                "confidence": 0.5,
                "group_name": "No Distortion Detected",
                "description": "Healthy, balanced thinking",
                "distortions": [],
                "reasoning": "Classification failed, defaulting to G0"
            }

    # ==================== SUPPORTIVE RESPONSE (G0 - No Distortion) ====================

    def generate_supportive_response(
        self,
        user_message: str,
        conversation_history: list,
        user_name: str
    ) -> str:
        """For G0 cases - just listen supportively, no intervention."""

        history_text = self._format_history(conversation_history)

        system_prompt = f"""You are Aria, a warm companion talking to {user_name}.
They're sharing something with you, and right now they don't seem caught in negative thinking.

YOUR TASK:
1. Listen and validate warmly
2. Gently ask if there's anything else on their mind
3. Keep it friendly and brief

RULES:
- Use {user_name}'s name occasionally
- Keep responses SHORT (1-2 sentences max)
- Use 1-2 emojis (💙 🌟 ✨)
- Don't lecture - just be a supportive friend"""

        user_prompt = f"""CONVERSATION:
{history_text}

{user_name}'s latest message: "{user_message}"

Respond warmly as their supportive companion."""

        try:
            response = self.client.chat.completions.create(
                model=self.MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=200
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"Supportive response error: {e}")
            return f"I hear you, {user_name}. Thanks for sharing that with me. 💙"

    # ==================== HELPER METHODS ====================

    def _format_history(self, history: list) -> str:
        """Format conversation history for prompts."""
        if not history:
            return "(This is the start of the conversation)"

        formatted = []
        for msg in history[-6:]:  # Last 6 messages
            role = "User" if msg.get("role") == "user" else "Aria"
            formatted.append(f"{role}: {msg.get('content', '')}")

        return "\n".join(formatted)
