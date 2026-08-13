"""
Crisis Detector Module
Detects messages that indicate potential self-harm or crisis
Flags them for admin review and triggers immediate support response
"""

import re
from typing import Optional, Tuple


# Crisis trigger words and phrases
CRISIS_TRIGGERS = [
    # Suicide-related
    "suicide",
    "suicidal",
    "kill myself",
    "kill me",
    "end my life",
    "end it all",
    "want to die",
    "wanna die",
    "better off dead",
    "don't want to live",
    "dont want to live",
    "no reason to live",
    "nothing to live for",
    "take my own life",
    
    # Self-harm related
    "self harm",
    "self-harm",
    "hurt myself",
    "cutting myself",
    "cut myself",
    "harm myself",
    
    # Hopelessness indicators
    "everyone would be better without me",
    "no one would miss me",
    "no one cares if i die",
    "world would be better without me",
    
    # Planning indicators
    "plan to end",
    "planning to kill",
    "going to kill myself",
    "gonna kill myself",
    "how to kill myself",
    "ways to die",
    "methods to die"
]

# Compile patterns for efficient matching
CRISIS_PATTERNS = [re.compile(r'\b' + re.escape(trigger) + r'\b', re.IGNORECASE) 
                   for trigger in CRISIS_TRIGGERS]


def check_for_crisis(message: str) -> Tuple[bool, Optional[str]]:
    """
    Check if a message contains crisis indicators.
    
    Args:
        message: The user's message to check
        
    Returns:
        Tuple of (is_crisis, trigger_word)
        - is_crisis: True if crisis detected
        - trigger_word: The word/phrase that triggered the flag
    """
    message_lower = message.lower()
    
    for pattern, trigger in zip(CRISIS_PATTERNS, CRISIS_TRIGGERS):
        if pattern.search(message_lower):
            return True, trigger
    
    return False, None


def get_crisis_response(user_name: str) -> str:
    """
    Get an immediate supportive response for crisis situations.
    This response is shown BEFORE the regular chat continues.
    """
    return f"""💙 {user_name}, I'm really glad you shared that with me. What you're feeling is serious, and I want you to know that you matter.

Right now, please reach out to someone who can help:

🆘 **National Suicide Prevention Lifeline**: 988 (call or text)
📱 **Crisis Text Line**: Text HOME to 741741
🌍 **International Association for Suicide Prevention**: https://www.iasp.info/resources/Crisis_Centres/

These are trained professionals who are available 24/7 and want to help.

I'm here to support you too, but please also connect with one of these resources. You don't have to face this alone. 💙"""


def get_crisis_resources() -> list:
    """Get list of crisis resources."""
    return [
        {
            "name": "National Suicide Prevention Lifeline",
            "contact": "988",
            "type": "call_or_text",
            "description": "Free, confidential 24/7 support"
        },
        {
            "name": "Crisis Text Line",
            "contact": "Text HOME to 741741",
            "type": "text",
            "description": "Free 24/7 text support"
        },
        {
            "name": "SAMHSA National Helpline",
            "contact": "1-800-662-4357",
            "type": "call",
            "description": "Treatment referral and information 24/7"
        },
        {
            "name": "International Association for Suicide Prevention",
            "contact": "https://www.iasp.info/resources/Crisis_Centres/",
            "type": "website",
            "description": "Find crisis centers worldwide"
        }
    ]


# Test if run directly
if __name__ == "__main__":
    test_messages = [
        "I'm feeling sad today",
        "I want to kill myself",
        "I've been thinking about suicide",
        "I had a bad day at work",
        "I feel like hurting myself",
        "Nobody cares about me",
        "I want to die",
        "I'm going to end it all",
        "Just feeling stressed"
    ]
    
    print("Testing crisis detector:\n")
    for msg in test_messages:
        is_crisis, trigger = check_for_crisis(msg)
        status = f"🚨 CRISIS (trigger: {trigger})" if is_crisis else "✅ OK"
        print(f"{status}: {msg}")
