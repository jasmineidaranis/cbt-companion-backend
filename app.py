"""
CBT Companion - Backend API
Multi-user version with authentication and database
Hosted on HuggingFace Spaces
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
load_dotenv()
from groq_client import GroqClient
from database import get_db
from auth import register_user, login_user, token_required
from crisis_detector import check_for_crisis, get_crisis_response, get_crisis_resources
from prompts import NATURAL_ENDINGS
from exercises import get_exercise_for_group, get_homework_for_distortion
from wearable import wearable_bp, FCM_ENABLED as _fcm_enabled
from admin import admin_bp
import os
import re
import json
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# === NEW IMPORTS FOR FULL BECK PROTOCOL ===
from patient_tracker import (init_patient_tracking, get_patient_profile,
                             update_patient_profile, add_bdi_score, get_previous_session,
                             increment_session_count)
from full_protocol import (is_new_protocol_state, get_next_state_full_protocol,
                           get_post_complete_state, get_initial_state, is_session_complete,
                           should_trigger_downward_arrow)
from beck_agents import (bdi_assessment_agent, bridge_agent, homework_review_agent,
                         agenda_setting_agent, psychoeducation_agent, behavioural_activation_agent,
                         schema_agent, drdt_agent, summary_agent, feedback_agent,
                         relapse_prevention_agent, supervisor_agent)
from context_builder import build_patient_context, build_minimal_context
from bdi_scorer import score_bdi, get_next_item_index, is_bdi_complete
from severity_router import route_by_severity
# === END NEW IMPORTS ===

app = Flask(__name__,
            template_folder='templates',
            static_folder='static')
CORS(app)

# Request timeout protection
from functools import wraps
import signal
from contextlib import contextmanager

class TimeoutError(Exception):
    pass

@contextmanager
def timeout_context(seconds):
    """Context manager for request timeout (Unix only)."""
    def timeout_handler(signum, frame):
        raise TimeoutError(f"Request exceeded {seconds} second timeout")

    # Only use signal timeout on Unix systems (not Windows)
    if hasattr(signal, 'SIGALRM'):
        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(seconds)
        try:
            yield
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
    else:
        # On Windows, just yield without timeout
        yield

# Register blueprints
app.register_blueprint(wearable_bp)
app.register_blueprint(admin_bp)

# Initialize components
groq_client = GroqClient(api_key=os.environ.get("GROQ_API_KEY"))

# Initialize patient tracking (adds columns to beck_sessions table)
init_patient_tracking()

# Initialize ML model for depression detection (LAZY LOADING to save memory)
# Only load when actually needed, not at startup
ML_MODEL_LOADED = False

def lazy_load_ml_model():
    """Lazy load ML model only when needed to save memory."""
    global ML_MODEL_LOADED
    if not ML_MODEL_LOADED:
        try:
            from ml_inference import initialize_model
            ml_ready = initialize_model()
            if ml_ready:
                print("✅ ML Model initialized successfully")
                ML_MODEL_LOADED = True
                return True
            else:
                print("⚠️  ML Model initialization failed - predictions disabled")
                return False
        except Exception as e:
            print(f"⚠️  Could not load ML model: {str(e)}")
            print("   Wearable predictions will be disabled")
            return False
    return True

print("ℹ️  ML Model will be lazy-loaded when needed (memory optimization)")


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "online",
        "app": "CBT Companion",
        "version": "2.1.1",
        "features": ["multi-user", "auth", "crisis-detection", "wearable-integration"]
    })


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint for monitoring."""
    import psutil
    import gc

    try:
        # Get memory info
        process = psutil.Process()
        memory_info = process.memory_info()

        return jsonify({
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "memory_mb": round(memory_info.rss / 1024 / 1024, 2),
            "memory_percent": round(process.memory_percent(), 2),
            "cpu_percent": round(process.cpu_percent(interval=0.1), 2),
            "ml_model_loaded": ML_MODEL_LOADED,
            "fcm_enabled": _fcm_enabled
        })
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }), 500


# ==================== AUTH ROUTES ====================

@app.route("/api/register", methods=["POST"])
def register():
    """Register a new user."""
    data = request.json
    
    result = register_user(
        email=data.get("email", ""),
        password=data.get("password", ""),
        name=data.get("name", ""),
        context=data.get("context", "person")
    )
    
    if "error" in result:
        return jsonify(result), 400
    
    return jsonify(result)


@app.route("/api/login", methods=["POST"])
def login():
    """Login user."""
    data = request.json
    
    result = login_user(
        email=data.get("email", ""),
        password=data.get("password", "")
    )
    
    if "error" in result:
        return jsonify(result), 401
    
    return jsonify(result)


@app.route("/api/me", methods=["GET"])
@token_required
def get_me():
    """Get current user info."""
    user = request.current_user
    return jsonify({
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "context": user["context"]
    })


@app.route("/api/user/fcm-token", methods=["POST"])
@token_required
def save_fcm_token():
    """Store FCM device token for push notifications."""
    user = request.current_user
    data = request.json or {}
    token = data.get('token', '').strip()
    if not token:
        return jsonify({"error": "token is required"}), 400
    db = get_db()
    db.save_fcm_token(user["id"], token)
    return jsonify({"success": True})


@app.route("/api/user/fcm-debug", methods=["GET"])
@token_required
def fcm_debug():
    """
    Debug endpoint: shows FCM status for current user and optionally sends a test push.
    Query param: ?send_test=1 to send a test notification.
    """
    user = request.current_user
    db = get_db()
    return _fcm_debug_for_user(user["id"], db)


@app.route("/api/wearable/device/fcm-debug", methods=["GET"])
def device_fcm_debug():
    """
    Same as /api/user/fcm-debug but authenticated via X-Device-Key header.
    Allows testing FCM without knowing the account email/password.
    Query param: ?send_test=1 to send a test notification.
    """
    api_key = request.headers.get("X-Device-Key")
    if not api_key:
        return jsonify({"error": "X-Device-Key header required"}), 401
    db = get_db()
    user = db.get_user_by_device_key(api_key)
    if not user:
        return jsonify({"error": "Invalid or revoked device key"}), 401
    return _fcm_debug_for_user(user["id"], db)


def _fcm_debug_for_user(user_id, db):
    fcm_token = db.get_fcm_token(user_id)
    result = {
        "fcm_backend_enabled": _fcm_enabled,
        "user_has_token": bool(fcm_token),
        "token_preview": f"...{fcm_token[-12:]}" if fcm_token else None,
    }
    if request.args.get("send_test") == "1":
        if not _fcm_enabled:
            result["test_push"] = "SKIPPED — firebase-admin not installed on server"
        elif not fcm_token:
            result["test_push"] = "SKIPPED — no FCM token stored for this user (login on phone first)"
        else:
            from fcm_push import send_stress_alert
            ok = send_stress_alert(
                fcm_token=fcm_token,
                alert_id="test-debug",
                condition="MILD_STRESS",
                dri_score=0.75,
                recorded_at=datetime.utcnow().isoformat(),
            )
            result["test_push"] = "SENT ✅" if ok else "FAILED ❌ (check server logs)"
    return jsonify(result)


# ==================== SESSION ROUTES ====================

@app.route("/api/session/new", methods=["POST"])
@token_required
def new_session():
    """Start a new chat session."""
    user = request.current_user
    db = get_db()

    session_id = db.create_session(user["id"])

    # Set initial mood if provided
    data = request.json or {}
    if "mood" in data:
        db.update_session(session_id, mood_start=data["mood"])

    # For returning users, set up BRIDGE state so prev-session follow-up fires
    # on their first message (bridge agent checks context and skips if nothing to bridge).
    # Use direct session count — user_stats.total_sessions is never incremented in normal flow.
    prior_count = db.conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE user_id = ? AND id != ?",
        (user["id"], session_id)
    ).fetchone()[0]
    is_returning = prior_count > 0

    if is_returning:
        db.create_beck_session(session_id)
        db.update_beck_state(session_id, "BRIDGE", full_protocol_state="BRIDGE")

    welcome_message = f"Hey {user['name']}! What's on your mind today?"

    return jsonify({
        "session_id": session_id,
        "message": welcome_message,
        "user_name": user["name"]
    })


@app.route("/api/session/status", methods=["GET"])
@token_required
def session_status():
    """Get current session status."""
    session_id = request.args.get("session_id")
    
    if not session_id:
        return jsonify({"error": "session_id is required"}), 400
    
    db = get_db()
    session = db.get_session(session_id)
    
    if not session:
        return jsonify({"error": "Session not found"}), 404
    
    # Verify session belongs to user
    if session["user_id"] != request.current_user["id"]:
        return jsonify({"error": "Unauthorized"}), 403
    
    return jsonify({
        "session_id": session["id"],
        "state": session["state"],
        "locked_group": session["locked_group"],
        "current_stage": session["current_stage"],
        "completed": session["completed"]
    })


@app.route("/api/sessions", methods=["GET"])
@token_required
def get_sessions():
    """Get user's past sessions."""
    user = request.current_user
    db = get_db()
    
    sessions = db.get_user_sessions(user["id"])
    
    return jsonify({"sessions": sessions})


# ==================== CHAT ROUTE ====================

@app.route("/api/chat", methods=["POST"])
@token_required
def chat():
    """
    Main chat endpoint using Beck's 3-Agent Protocol.
    """
    try:
        user = request.current_user
        db = get_db()

        data = request.json
        user_message = data.get("message", "").strip()
        session_id = data.get("session_id")
        conversation_history = data.get("conversation_history", [])

        print(f"[CHAT POST] user={user.get('name','?')} ({user.get('email','?')}) | "
              f"session={session_id[:8] if session_id else 'None'} | "
              f"msg={user_message[:60]!r}")

        if not user_message or not session_id:
            return jsonify({"error": "Message and session_id required"}), 400

        # Get session
        session = db.get_session(session_id)
        if not session or session["user_id"] != user["id"]:
            return jsonify({"error": "Session not found"}), 404

        # ========== FULL PROTOCOL INTERCEPT ==========
        # Check if session is using the full 32-state protocol
        beck_data_check = db.get_beck_session(session_id)
        if beck_data_check and beck_data_check.get('full_protocol_state'):
            full_state = beck_data_check['full_protocol_state']
            beck_state = beck_data_check.get('beck_state')
            # Only route to full protocol when beck_state matches full_protocol_state,
            # meaning the session was intentionally set up for it (not just the SQL default).
            if is_new_protocol_state(full_state) and beck_state == full_state:
                return handle_full_beck_protocol(
                    full_state, user_message, session_id,
                    user["id"], user["name"], conversation_history, db
                )
        # ========== END FULL PROTOCOL INTERCEPT ==========

        # ========== CRISIS DETECTION ==========
        is_crisis, trigger_word = check_for_crisis(user_message)
        if is_crisis:
            db.flag_crisis(user["id"], user["name"], user["email"],
                          session_id, user_message, trigger_word)
            crisis_response = get_crisis_response(user["name"])
            return jsonify({
                "response": crisis_response,
                "is_crisis": True,
                "crisis_resources": get_crisis_resources()
            })

        # ========== NATURAL EXIT CHECK ==========
        if is_natural_exit(user_message):
            return jsonify(handle_natural_exit(session, user, db, session_id))

        # ========== GET OR CREATE BECK SESSION ==========
        beck_data = db.get_beck_session(session_id)

        if not beck_data:
            # First message - check if distorted using LLM
            classification = groq_client.classify_distortion(user_message)

            if classification["group"] == "G0":
                # No distortion - supportive listening
                response_text = groq_client.generate_supportive_response(
                    user_message=user_message,
                    conversation_history=conversation_history[-6:],
                    user_name=user["name"]
                )
                return jsonify({
                    "response": response_text,
                    "beck_state": None,
                    "is_beck_protocol": False
                })
            else:
                # Distortion detected - START BECK PROTOCOL
                db.create_beck_session(session_id)
                db.update_session(session_id, locked_group=classification["group"])
                db.update_beck_state(session_id, "VALIDATE",
                                    original_thought=user_message)

                # Update recurring distortion count in patient profile
                try:
                    profile = get_patient_profile(user["id"])
                    distortions = profile.get('recurring_distortions', {})
                    if isinstance(distortions, str):
                        distortions = json.loads(distortions)
                    distortions[classification["group"]] = distortions.get(classification["group"], 0) + 1
                    update_patient_profile(user["id"], recurring_distortions=distortions)
                except Exception as rd_err:
                    logging.warning(f"Recurring distortion update error: {rd_err}")

                # Link thought to cluster for cross-session tracking
                try:
                    from belief_tracker import link_thought_to_cluster
                    link_thought_to_cluster(session_id, user["id"],
                                           user_message, classification["group"])
                except Exception as bt_err:
                    logging.warning(f"Belief tracker error: {bt_err}")

                beck_data = db.get_beck_session(session_id)

        # ========== BECK PROTOCOL STATE MACHINE ==========
        from prompts import BECK_STATES, AGENT1_STATES, AGENT3_STATES, get_next_state, get_field_to_save

        current_state = beck_data["beck_state"]

        # Determine which agent handles this state
        if current_state in AGENT1_STATES:
            # Agent 1: Warm Questioner
            response_text = groq_client.agent1_warm_questioner(
                current_state=current_state,
                user_message=user_message,
                beck_data=beck_data,
                user_name=user["name"],
                conversation_history=conversation_history[-6:]
            )

            # Quality Gate: check Agent 1 response
            review = run_quality_gate(response_text, current_state, session_id, db)
            if not review.get("approved", True) and review.get("corrective_prompt"):
                # Regenerate once with corrective prompt (in system prompt, not user message)
                response_text = groq_client.agent1_warm_questioner(
                    current_state=current_state,
                    user_message=user_message,
                    beck_data=beck_data,
                    user_name=user["name"],
                    conversation_history=conversation_history[-6:],
                    supervisor_note=review["corrective_prompt"]
                )
                run_quality_gate(response_text, current_state, session_id, db)

            # Save user's response to appropriate field
            field_to_save = get_field_to_save(current_state)
            next_state = get_next_state(current_state)

            # Downward Arrow trigger: intercept Q6_ACTION → SUMMARIZING
            if current_state == "Q6_ACTION" and next_state == "SUMMARIZING":
                locked_group = session.get("locked_group")
                if locked_group and should_trigger_downward_arrow(user["id"], locked_group):
                    next_state = "DA_LEVEL_1"
                    db.update_beck_state(session_id, next_state,
                                        da_triggered=1,
                                        **({field_to_save: user_message} if field_to_save else {}))
                    # Skip normal save below
                    field_to_save = None

            # Save DA core belief to patient profile when DA_LEVEL_3 completes
            if current_state == "DA_LEVEL_3" and field_to_save == "da_core_belief":
                try:
                    profile = get_patient_profile(user["id"])
                    core_beliefs = profile.get('core_beliefs', [])
                    if isinstance(core_beliefs, str):
                        core_beliefs = json.loads(core_beliefs)
                    if user_message not in core_beliefs:
                        core_beliefs.append(user_message)
                        update_patient_profile(user["id"], core_beliefs=core_beliefs)
                except Exception as da_err:
                    logging.warning(f"DA core belief save error: {da_err}")

            # Extract rating if this is a rating state
            if field_to_save and ('rating' in field_to_save or 'intensity' in field_to_save):
                rating = extract_rating(user_message)
                if rating is not None:
                    db.update_beck_state(session_id, next_state, **{field_to_save: rating})
                else:
                    db.update_beck_state(session_id, next_state)
            elif field_to_save:
                db.update_beck_state(session_id, next_state, **{field_to_save: user_message})
            else:
                db.update_beck_state(session_id, next_state)

        elif current_state == "SUMMARIZING":
            # Agent 2: Clinical Summarizer (internal)
            clinical_summary = groq_client.agent2_clinical_summarizer(beck_data)

            # Move to Agent 3
            db.update_beck_state(session_id, "DELIVER_REFRAME")

            # Get updated beck_data and call Agent 3
            beck_data = db.get_beck_session(session_id)
            response_text = groq_client.agent3_treatment_agent(
                current_state="DELIVER_REFRAME",
                user_message=user_message,
                beck_data=beck_data,
                clinical_summary=clinical_summary,
                user_name=user["name"],
                conversation_history=conversation_history[-6:]
            )

        elif current_state in AGENT3_STATES:
            # Agent 3: Treatment Agent
            # Need clinical summary - regenerate if needed
            clinical_summary = groq_client.agent2_clinical_summarizer(beck_data)

            response_text = groq_client.agent3_treatment_agent(
                current_state=current_state,
                user_message=user_message,
                beck_data=beck_data,
                clinical_summary=clinical_summary,
                user_name=user["name"],
                conversation_history=conversation_history[-6:]
            )

            # Quality Gate: check Agent 3 response
            review = run_quality_gate(response_text, current_state, session_id, db)
            if not review.get("approved", True) and review.get("corrective_prompt"):
                response_text = groq_client.agent3_treatment_agent(
                    current_state=current_state,
                    user_message=user_message,
                    beck_data=beck_data,
                    clinical_summary=clinical_summary,
                    user_name=user["name"],
                    conversation_history=conversation_history[-6:],
                    supervisor_note=review["corrective_prompt"]
                )
                run_quality_gate(response_text, current_state, session_id, db)

            # Save response and advance state
            field_to_save = get_field_to_save(current_state)
            next_state = get_next_state(current_state)

            if field_to_save and ('rating' in field_to_save or 'belief' in field_to_save or 'intensity' in field_to_save):
                rating = extract_rating(user_message)
                if rating is not None:
                    db.update_beck_state(session_id, next_state, **{field_to_save: rating})
                else:
                    db.update_beck_state(session_id, next_state)
            elif field_to_save:
                db.update_beck_state(session_id, next_state, **{field_to_save: user_message})
            else:
                if next_state:
                    db.update_beck_state(session_id, next_state)
                else:
                    # Existing cognitive flow complete
                    db.complete_beck_session(session_id)
                    db.update_session(session_id, completed=1)

                    # === HOOK: Assign distortion-specific homework ===
                    locked_group = session.get("locked_group")
                    if locked_group and locked_group != "G0":
                        hw = get_homework_for_distortion(locked_group)
                        if hw:
                            update_patient_profile(user["id"], homework_pending=hw)

                    # === HOOK: Transition to post-session states ===
                    patient_profile = get_patient_profile(user["id"])
                    total_sessions = patient_profile.get('total_beck_sessions', 0)
                    bdi_score_val = beck_data.get('bdi_score')

                    post_state = get_post_complete_state(total_sessions, bdi_score_val)
                    db.update_beck_state(session_id, post_state, full_protocol_state=post_state)

        else:
            # Fallback
            response_text = groq_client.generate_supportive_response(
                user_message, conversation_history[-6:], user["name"]
            )

        # Get updated state for response
        beck_data = db.get_beck_session(session_id)

        return jsonify({
            "response": response_text,
            "beck_state": beck_data["beck_state"] if beck_data else None,
            "is_beck_protocol": beck_data is not None,
            "protocol_complete": beck_data["beck_state"] == "COMPLETE" if beck_data else False,
            "belief_improvement": calculate_improvement(beck_data) if beck_data else None
        })

    except TimeoutError as e:
        print(f"Timeout in /api/chat: {str(e)}")
        return jsonify({
            "error": "Request took too long. Please try again.",
            "timeout": True
        }), 504
    except Exception as e:
        print(f"Error in /api/chat: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "error": "Something went wrong. Please try again.",
            "details": str(e) if os.getenv("DEBUG") else None
        }), 500


# ==================== EXERCISE ROUTES ====================

@app.route("/api/exercise", methods=["GET"])
@token_required
def get_exercise():
    """Get a CBT exercise for the current session."""
    session_id = request.args.get("session_id")
    
    if not session_id:
        return jsonify({"error": "session_id is required"}), 400
    
    db = get_db()
    session = db.get_session(session_id)
    
    if not session:
        return jsonify({"error": "Session not found"}), 404
    
    group = session["locked_group"]
    if not group or group == "G0":
        return jsonify({
            "exercise": None,
            "message": "No specific exercise needed for this session."
        })
    
    exercise = get_exercise_for_group(group)
    
    return jsonify({
        "exercise": exercise,
        "group": group
    })


@app.route("/api/exercise/complete", methods=["POST"])
@token_required
def complete_exercise():
    """Mark an exercise as completed."""
    user = request.current_user
    db = get_db()
    
    data = request.json
    session_id = data.get("session_id")
    exercise_id = data.get("exercise_id")
    exercise_name = data.get("exercise_name", "")
    
    if not exercise_id:
        return jsonify({"error": "exercise_id is required"}), 400
    
    session = db.get_session(session_id) if session_id else None
    group_type = session["locked_group"] if session else None
    
    db.log_exercise_completed(
        user_id=user["id"],
        session_id=session_id,
        exercise_id=exercise_id,
        exercise_name=exercise_name,
        group_type=group_type
    )
    
    return jsonify({
        "success": True,
        "message": f"Great job completing the exercise, {user['name']}! 🎉"
    })


# ==================== STATS ROUTES ====================

@app.route("/api/stats", methods=["GET"])
@token_required
def get_stats():
    """Get user's statistics."""
    user = request.current_user
    db = get_db()
    
    stats = db.get_user_stats(user["id"])
    
    # Get most common distortion
    distortion_counts = stats["distortion_counts"]
    most_common = None
    if distortion_counts:
        most_common = max(distortion_counts, key=distortion_counts.get)
    
    return jsonify({
        "total_sessions": stats["total_sessions"],
        "total_exercises": stats["total_exercises"],
        "current_streak": stats["current_streak"],
        "distortion_counts": distortion_counts,
        "most_common_distortion": most_common
    })


# ==================== RESOURCES ROUTE ====================

@app.route("/api/resources", methods=["GET"])
def get_resources():
    """Get crisis resources (public endpoint)."""
    return jsonify({
        "resources": get_crisis_resources(),
        "message": "You're not alone. Help is always available. 💙"
    })


# ==================== HELPER FUNCTIONS ====================

def is_natural_exit(message: str) -> bool:
    """Check if message indicates user wants to end conversation."""
    exit_phrases = [
        "thanks", "thank you", "bye", "goodbye", "see you",
        "i feel better", "that helps", "i'm good", "im good",
        "gotta go", "have to go", "talk later", "gtg"
    ]
    message_lower = message.lower().strip()
    return any(phrase in message_lower for phrase in exit_phrases)


def handle_natural_exit(session: dict, user: dict, db, session_id: str) -> dict:
    """Handle natural conversation exit."""
    import random

    endings = NATURAL_ENDINGS
    response = random.choice(endings).replace("{name}", user["name"])

    # Check if Beck protocol was completed
    beck_data = db.get_beck_session(session_id)
    if beck_data and beck_data.get("beck_state") == "COMPLETE":
        # Get improvement stats
        improvement = calculate_improvement(beck_data)
        if improvement:
            improvement_msg = "You made real progress today! "
            if improvement.get('belief_change', 0) >= 10:
                improvement_msg += f"Your belief shifted by {improvement['belief_change']}%. "
            if improvement.get('emotion_change', 0) >= 10:
                improvement_msg += f"Your emotion intensity dropped by {improvement['emotion_change']}%. "
            response = improvement_msg + "\n\n" + response

    # Update session
    db.update_session(session_id, completed=1)

    return {
        "response": response,
        "session_state": "COMPLETED",
        "natural_exit": True,
        "session_complete": True
    }


def extract_rating(message: str) -> int:
    """Extract a 0-100 rating from user message."""
    import re
    # Look for numbers
    numbers = re.findall(r'\d+', message)
    for num in numbers:
        n = int(num)
        if 0 <= n <= 100:
            return n
    return None


def calculate_improvement(beck_data: dict) -> dict:
    """Calculate belief and emotion improvement."""
    if not beck_data:
        return None

    result = {}
    if beck_data.get('initial_belief_rating') and beck_data.get('final_belief_rating'):
        result['belief_change'] = beck_data['initial_belief_rating'] - beck_data['final_belief_rating']
    if beck_data.get('initial_emotion_intensity') and beck_data.get('final_emotion_intensity'):
        result['emotion_change'] = beck_data['initial_emotion_intensity'] - beck_data['final_emotion_intensity']

    return result if result else None


def run_quality_gate(response_text: str, current_state: str, session_id: str, db):
    """Run supervisor quality gate on a therapist response. Regenerate once if failed."""
    try:
        review = supervisor_agent(groq_client, response_text, current_state)

        # Log quality scores to beck_sessions
        beck_data = db.get_beck_session(session_id)
        existing_scores = []
        if beck_data and beck_data.get('quality_scores'):
            try:
                existing_scores = json.loads(beck_data['quality_scores'])
            except:
                existing_scores = []
        existing_scores.append({
            "state": current_state,
            "scores": review.get("quality_scores", {}),
            "approved": review.get("approved", True)
        })
        db.update_beck_state(session_id, current_state,
                            quality_scores=json.dumps(existing_scores))

        return review
    except Exception as e:
        logging.warning(f"Quality gate error: {e}")
        return {"approved": True, "quality_scores": {}, "corrective_prompt": ""}


# ==================== FULL BECK PROTOCOL HANDLER ====================

def handle_full_beck_protocol(current_state: str, user_message: str, session_id: str,
                              user_id: str, user_name: str, conversation_history: list, db) -> dict:
    """
    Handle states from the full 32-state Beck protocol.

    This function handles:
    - Pre-session states (BDI, bridge, homework review, agenda, psychoeducation)
    - Behavioral activation states (for severe depression)
    - Post-session states (schema work, DRDT, summary, feedback)
    - Relapse prevention

    The existing 20-state cognitive flow (VALIDATE → COMPLETE) is NOT handled here.
    """

    # Get patient profile and session data
    patient_profile = get_patient_profile(user_id)
    beck_session = db.get_beck_session(session_id)
    previous_session = get_previous_session(user_id, session_id)

    # Build therapeutic context
    if patient_profile.get('total_beck_sessions', 0) > 0 and previous_session:
        context = build_patient_context(patient_profile, previous_session)
    else:
        context = build_minimal_context(
            patient_profile.get('total_beck_sessions', 0) + 1,
            beck_session.get('bdi_score') if beck_session else None,
            beck_session.get('bdi_severity') if beck_session else None
        )

    response_text = ""
    next_state = current_state
    metadata = {}

    # === ROUTING STATE (Logic only, no LLM) ===
    if current_state == "SEVERITY_ROUTING":
        bdi_score = beck_session.get('bdi_score') or 15
        bdi_history_raw = patient_profile.get('bdi_scores', [])

        if isinstance(bdi_history_raw, str):
            bdi_history_raw = json.loads(bdi_history_raw)

        bdi_history = [s.get('score') if isinstance(s, dict) else s for s in bdi_history_raw]

        route_result = route_by_severity(
            bdi_score,
            patient_profile.get('total_beck_sessions', 0) + 1,
            bdi_history
        )

        if route_result == "BEHAVIOURAL_ACTIVATION":
            next_state = "BA_MONITORING"
        elif route_result == "RELAPSE_PREVENTION":
            next_state = "RELAPSE_PREVENTION"
        else:
            # VALIDATE - hand off to existing cognitive flow
            next_state = "VALIDATE"

            # The patient's agenda thought (from AGENDA_SETTING) is the thought to work on.
            # user_message here is their last BDI answer, not the agenda thought.
            agenda_thought = (beck_session.get('agenda_items') if beck_session else None) or user_message

            # Classify distortion + wire all research feature hooks
            classified_group = "G1"  # fallback
            try:
                classification = groq_client.classify_distortion(agenda_thought)
                classified_group = classification.get("group", "G1")
                if classified_group != "G0":
                    # Set locked_group so homework assignment and other hooks work
                    db.update_session(session_id, locked_group=classified_group)

                    # Update recurring distortions in patient profile
                    distortions = patient_profile.get('recurring_distortions', {})
                    if isinstance(distortions, str):
                        distortions = json.loads(distortions)
                    distortions[classified_group] = distortions.get(classified_group, 0) + 1
                    update_patient_profile(user_id, recurring_distortions=distortions)

                    # Link thought to cluster for cross-session belief tracking
                    from belief_tracker import link_thought_to_cluster
                    link_thought_to_cluster(session_id, user_id, agenda_thought, classified_group)
            except Exception as cls_err:
                logging.warning(f"Full protocol distortion classification error: {cls_err}")

            db.update_beck_state(session_id, "VALIDATE", original_thought=agenda_thought,
                               full_protocol_state="VALIDATE")
            # Let existing handler take over
            return jsonify({
                "response": "",
                "full_protocol_state": "VALIDATE",
                "beck_state": "VALIDATE",
                "auto_advance": True
            })

        # Update state and continue
        db.update_beck_state(session_id, next_state, full_protocol_state=next_state)

        # Recursively handle next state
        return handle_full_beck_protocol(
            next_state, user_message, session_id, user_id, user_name,
            conversation_history, db
        )

    # === BDI ASSESSMENT ===
    elif current_state == "BDI_ASSESSMENT":
        # Get current BDI progress
        bdi_responses_raw = beck_session.get('bdi_responses', '{}') if beck_session else '{}'
        if isinstance(bdi_responses_raw, str):
            bdi_responses = json.loads(bdi_responses_raw) if bdi_responses_raw != '{}' else {}
        else:
            bdi_responses = bdi_responses_raw or {}

        # Call BDI assessment agent
        response_text = bdi_assessment_agent(
            groq_client, conversation_history, bdi_responses, user_name, context
        )

        # Check for completion signal
        if "[BDI_COMPLETE:" in response_text:
            # Extract score from signal
            match = re.search(r'\[BDI_COMPLETE:(\d+)\]', response_text)
            if match:
                total_score = int(match.group(1))
                from bdi_scorer import get_severity
                severity = get_severity(total_score)

                # Save BDI results
                db.update_beck_state(session_id, "SEVERITY_ROUTING",
                                   bdi_score=total_score,
                                   bdi_severity=severity,
                                   bdi_responses=json.dumps(bdi_responses),
                                   bdi_completed_at=datetime.utcnow().isoformat(),
                                   full_protocol_state="SEVERITY_ROUTING")

                # Add to patient history
                add_bdi_score(user_id, total_score, severity, session_id)

                next_state = "SEVERITY_ROUTING"

                # Clean the signal from response
                response_text = re.sub(r'\[BDI_COMPLETE:\d+\]', '', response_text).strip()

        # Check for crisis signal
        elif "[CRISIS_FLAG]" in response_text:
            # Item 9 indicated suicidal thoughts - flag for admin monitoring
            db.flag_crisis(
                user_id=user_id,
                user_name=user_name,
                user_email=request.current_user.get("email", ""),
                session_id=session_id,
                message_content="BDI Item 9 (Suicidal Thoughts) scored >= 2",
                trigger_word="BDI_SUICIDAL_IDEATION"
            )
            crisis_response = get_crisis_response(user_name)

            return jsonify({
                "response": crisis_response,
                "is_crisis": True,
                "crisis_resources": get_crisis_resources(),
                "full_protocol_state": "CRISIS"
            })

        # Parse BDI response from user message
        else:
            # Extract score from user message (0-3)
            score_match = re.search(r'\b([0-3])\b', user_message)
            if score_match:
                score = int(score_match.group(1))
                next_item = get_next_item_index(bdi_responses)

                if next_item is not None:
                    bdi_responses[next_item] = score
                    db.update_beck_state(session_id, current_state,
                                       bdi_responses=json.dumps(bdi_responses),
                                       full_protocol_state=current_state)

    # === PRE-SESSION AGENTS ===
    elif current_state == "BRIDGE":
        response_text = bridge_agent(groq_client, user_message, conversation_history, user_name, context)
        if "[BRIDGE_COMPLETE]" in response_text:
            next_state = get_next_state_full_protocol(current_state, beck_session, patient_profile)
            db.update_beck_state(session_id, next_state, full_protocol_state=next_state)
            response_text = re.sub(r'\[BRIDGE_COMPLETE\]', '', response_text).strip()
            # Silent completion — re-process user message in next state
            if not response_text:
                return handle_full_beck_protocol(
                    next_state, user_message, session_id, user_id, user_name,
                    conversation_history, db
                )

    elif current_state == "HOMEWORK_REVIEW":
        response_text = homework_review_agent(groq_client, user_message, conversation_history, user_name, context)
        if "[HOMEWORK_REVIEW_COMPLETE]" in response_text:
            next_state = get_next_state_full_protocol(current_state, beck_session, patient_profile)
            db.update_beck_state(session_id, next_state, full_protocol_state=next_state,
                               homework_reviewed=1, homework_completion_notes=user_message)
            response_text = re.sub(r'\[HOMEWORK_REVIEW_COMPLETE\]', '', response_text).strip()
            # Silent completion — re-process user message in next state
            if not response_text:
                return handle_full_beck_protocol(
                    next_state, user_message, session_id, user_id, user_name,
                    conversation_history, db
                )

    elif current_state == "AGENDA_SETTING":
        response_text = agenda_setting_agent(groq_client, user_message, conversation_history, user_name, context)
        if "[AGENDA_SET:" in response_text:
            # Extract agenda
            match = re.search(r'\[AGENDA_SET:\s*([^\]]+)\]', response_text)
            agenda = match.group(1) if match else "Session focus"

            next_state = get_next_state_full_protocol(current_state, beck_session, patient_profile)
            db.update_beck_state(session_id, next_state, full_protocol_state=next_state,
                               agenda_items=agenda)
            response_text = re.sub(r'\[AGENDA_SET:[^\]]+\]', '', response_text).strip()

    elif current_state == "PSYCHOEDUCATION":
        response_text = psychoeducation_agent(groq_client, user_message, conversation_history, user_name, context)
        if "[PSYCHOEDUCATION_COMPLETE]" in response_text:
            next_state = get_next_state_full_protocol(current_state, beck_session, patient_profile)
            db.update_beck_state(session_id, next_state, full_protocol_state=next_state)
            response_text = re.sub(r'\[PSYCHOEDUCATION_COMPLETE\]', '', response_text).strip()

    # === BEHAVIORAL ACTIVATION ===
    elif current_state in ["BA_MONITORING", "BA_SCHEDULING", "BA_GRADED_TASK"]:
        ba_stage_map = {
            "BA_MONITORING": "monitoring",
            "BA_SCHEDULING": "scheduling",
            "BA_GRADED_TASK": "graded_task"
        }
        ba_stage = ba_stage_map[current_state]

        response_text = behavioural_activation_agent(
            groq_client, user_message, conversation_history, ba_stage, user_name, context
        )

        completion_signals = {
            "BA_MONITORING": "[BA_MONITORING_COMPLETE]",
            "BA_SCHEDULING": "[BA_SCHEDULING_COMPLETE]",
            "BA_GRADED_TASK": "[BA_GRADED_COMPLETE]"
        }

        if completion_signals[current_state] in response_text:
            next_state = get_next_state_full_protocol(current_state, beck_session, patient_profile)
            db.update_beck_state(session_id, next_state, full_protocol_state=next_state,
                               ba_stage=ba_stage, ba_activities=user_message)
            response_text = re.sub(r'\[BA_\w+_COMPLETE\]', '', response_text).strip()

    # === POST-SESSION AGENTS ===
    elif current_state == "SCHEMA_CHECK":
        response_text = schema_agent(groq_client, user_message, conversation_history, beck_session, user_name, context)

        if "[SCHEMA_IDENTIFIED:" in response_text:
            match = re.search(r'\[SCHEMA_IDENTIFIED:\s*([^\]]+)\]', response_text)
            schema = match.group(1) if match else "Core belief identified"

            # Add to patient profile
            core_beliefs = patient_profile.get('core_beliefs', [])
            if isinstance(core_beliefs, str):
                core_beliefs = json.loads(core_beliefs)
            if schema not in core_beliefs:
                core_beliefs.append(schema)
                update_patient_profile(user_id, core_beliefs=core_beliefs)

            next_state = "DRDT_OUTPUT"
            db.update_beck_state(session_id, next_state, full_protocol_state=next_state,
                               schema_identified=schema)
            response_text = re.sub(r'\[SCHEMA_IDENTIFIED:[^\]]+\]', '', response_text).strip()

        elif "[SCHEMA_SKIP]" in response_text:
            next_state = "DRDT_OUTPUT"
            db.update_beck_state(session_id, next_state, full_protocol_state=next_state)
            response_text = re.sub(r'\[SCHEMA_SKIP\]', '', response_text).strip()

    elif current_state == "DRDT_OUTPUT":
        response_text = drdt_agent(groq_client, beck_session, user_name)
        next_state = "SESSION_SUMMARY"
        db.update_beck_state(session_id, next_state, full_protocol_state=next_state,
                           drdt_output=response_text)
        response_text = re.sub(r'\[DRDT_COMPLETE\]', '', response_text).strip()

    elif current_state == "SESSION_SUMMARY":
        response_text = summary_agent(groq_client, user_message, conversation_history, user_name, context)
        if "[SUMMARY_COMPLETE]" in response_text:
            next_state = "SESSION_FEEDBACK"
            db.update_beck_state(session_id, next_state, full_protocol_state=next_state,
                               session_summary_text=user_message)
            response_text = re.sub(r'\[SUMMARY_COMPLETE\]', '', response_text).strip()

    elif current_state == "SESSION_FEEDBACK":
        response_text = feedback_agent(groq_client, user_message, conversation_history, user_name, context)
        if "[FEEDBACK_COMPLETE]" in response_text:
            next_state = "SESSION_DONE"
            db.update_beck_state(session_id, next_state, full_protocol_state=next_state,
                               patient_feedback=user_message, session_closed_at=datetime.utcnow().isoformat())

            # Increment session count and mark session complete
            increment_session_count(user_id)
            db.update_session(session_id, completed=1)

            response_text = re.sub(r'\[FEEDBACK_COMPLETE\]', '', response_text).strip()

    # === RELAPSE PREVENTION ===
    elif current_state == "RELAPSE_PREVENTION":
        response_text = relapse_prevention_agent(groq_client, user_message, conversation_history, user_name, context)
        if "[RELAPSE_PLAN_COMPLETE]" in response_text:
            # Save relapse plan
            update_patient_profile(user_id, relapse_prevention_plan=user_message, in_relapse_prevention=1)

            next_state = "SESSION_SUMMARY"
            db.update_beck_state(session_id, next_state, full_protocol_state=next_state)
            response_text = re.sub(r'\[RELAPSE_PLAN_COMPLETE\]', '', response_text).strip()

    # === SESSION DONE ===
    elif current_state == "SESSION_DONE":
        response_text = f"Session complete! Take care, {user_name}. 💙"
        metadata["session_complete"] = True

    # Save messages to database
    try:
        db.add_message(session_id, user_id, "user", user_message)
        db.add_message(session_id, user_id, "assistant", response_text)
    except Exception as db_error:
        print(f"Database error saving messages: {str(db_error)}")
        # Continue anyway - don't fail the whole request

    return jsonify({
        "response": response_text,
        "full_protocol_state": next_state,
        "beck_state": beck_session.get('beck_state') if beck_session else None,
        "is_full_protocol": True,
        **metadata
    })


# ==================== NEW API ROUTES FOR FULL PROTOCOL ====================

@app.route("/api/patient/profile", methods=["GET"])
@token_required
def get_patient_profile_route():
    """Get patient profile with BDI trajectory and treatment phase."""
    user = request.current_user
    profile = get_patient_profile(user["id"])

    return jsonify({
        "profile": profile,
        "success": True
    })


@app.route("/api/patient/bdi-history", methods=["GET"])
@token_required
def get_bdi_history():
    """Get BDI score history for patient."""
    user = request.current_user
    profile = get_patient_profile(user["id"])

    bdi_scores = profile.get('bdi_scores', [])
    if isinstance(bdi_scores, str):
        bdi_scores = json.loads(bdi_scores)

    return jsonify({
        "bdi_history": bdi_scores,
        "current_phase": profile.get('current_treatment_phase'),
        "success": True
    })


@app.route("/api/session/start-full-protocol", methods=["POST"])
@token_required
def start_full_protocol_session():
    """
    Start a new session using the full 32-state Beck protocol.
    This is the entry point for new sessions that should use the extended protocol.
    """
    user = request.current_user
    db = get_db()

    # Create session
    session_id = db.create_session(user["id"])

    # Create Beck session with full protocol
    db.create_beck_session(session_id)

    # Get patient profile to determine session number
    patient_profile = get_patient_profile(user["id"])
    session_number = patient_profile.get('total_beck_sessions', 0)

    # Set initial state
    initial_state = get_initial_state(session_number)
    db.update_beck_state(session_id, initial_state, full_protocol_state=initial_state,
                       user_id_extended=user["id"])

    return jsonify({
        "session_id": session_id,
        "message": f"Hey {user['name']}! 👋 Let's start by checking in on how you've been feeling lately.",
        "full_protocol_state": initial_state,
        "is_full_protocol": True,
        "success": True
    })


@app.route("/api/session/quality", methods=["GET"])
@token_required
def get_session_quality():
    """Get CTS-R quality scores for a session."""
    session_id = request.args.get("session_id")
    if not session_id:
        return jsonify({"error": "session_id is required"}), 400

    db = get_db()
    session = db.get_session(session_id)
    if not session or session["user_id"] != request.current_user["id"]:
        return jsonify({"error": "Session not found"}), 404

    beck_data = db.get_beck_session(session_id)
    quality_scores = []
    if beck_data and beck_data.get('quality_scores'):
        try:
            quality_scores = json.loads(beck_data['quality_scores'])
        except:
            pass

    return jsonify({"session_id": session_id, "quality_scores": quality_scores})


# ==================== HOMEWORK ROUTES ====================

@app.route("/api/homework", methods=["GET"])
@token_required
def get_homework():
    """Get current pending homework for user."""
    user = request.current_user
    profile = get_patient_profile(user["id"])

    pending = profile.get('homework_pending')
    if pending and isinstance(pending, str):
        try:
            pending = json.loads(pending)
        except:
            pending = None

    history = profile.get('homework_history', [])
    if isinstance(history, str):
        try:
            history = json.loads(history)
        except:
            history = []

    return jsonify({
        "pending": pending,
        "history": history,
        "success": True
    })


@app.route("/api/homework/complete", methods=["POST"])
@token_required
def complete_homework():
    """Mark homework as completed with rating and notes."""
    user = request.current_user
    data = request.json or {}

    homework_id = data.get("homework_id")
    rating = data.get("rating", 3)  # 1-5 helpfulness
    notes = data.get("notes", "")

    if not homework_id:
        return jsonify({"error": "homework_id is required"}), 400

    profile = get_patient_profile(user["id"])

    # Get current pending homework
    pending = profile.get('homework_pending')
    if pending and isinstance(pending, str):
        try:
            pending = json.loads(pending)
        except:
            pending = None

    if not pending or pending.get('id') != homework_id:
        return jsonify({"error": "No matching pending homework"}), 400

    # Move to history
    history = profile.get('homework_history', [])
    if isinstance(history, str):
        try:
            history = json.loads(history)
        except:
            history = []

    pending['completed'] = True
    pending['completed_at'] = datetime.utcnow().isoformat()
    pending['helpful_rating'] = rating
    pending['notes'] = notes
    history.append(pending)

    update_patient_profile(user["id"], homework_pending=None, homework_history=history)

    return jsonify({"success": True, "message": "Homework completed! Great work!"})


# ==================== BELIEF TRACKING ROUTES ====================

@app.route("/api/beliefs/trajectory", methods=["GET"])
@token_required
def get_belief_trajectory():
    """Get all thought clusters with their belief rating trajectories."""
    user = request.current_user
    try:
        from belief_tracker import get_belief_trajectory
        trajectory = get_belief_trajectory(user["id"])
        return jsonify({"clusters": trajectory, "success": True})
    except Exception as e:
        import traceback
        print(f"[TRAJECTORY ERROR] {e}\n{traceback.format_exc()}")
        return jsonify({"clusters": [], "success": False, "error": str(e)}), 200


# ==================== CCD ROUTES ====================

@app.route("/api/ccd", methods=["GET"])
@token_required
def get_ccd():
    """Generate or return cached Cognitive Conceptualization Diagram."""
    user = request.current_user
    profile = get_patient_profile(user["id"])

    # Check if enough sessions
    total_sessions = profile.get('total_beck_sessions', 0)
    if total_sessions < 3:
        return jsonify({
            "ccd": None,
            "message": f"Need at least 3 completed sessions (currently {total_sessions})",
            "sessions_needed": 3 - total_sessions
        })

    from context_builder import generate_ccd
    ccd = generate_ccd(user["id"], groq_client)

    return jsonify({"ccd": ccd, "success": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860, debug=True)
