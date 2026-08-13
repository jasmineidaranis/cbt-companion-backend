"""
Wearable Device Module
Handles sensor data from wearable devices (PPG, GSR, Accelerometer)
Includes ML-based depression risk prediction
"""

from flask import Blueprint, request, jsonify
from auth import token_required
from database import get_db
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

try:
    from fcm_push import send_stress_alert as fcm_send
    FCM_ENABLED = True
except Exception as _fcm_err:
    print(f"⚠️  FCM not available: {_fcm_err}")
    FCM_ENABLED = False

# Import ML inference (will be initialized at startup)
try:
    from ml_inference import predict_risk, MIN_READINGS as ML_MIN_READINGS
    ML_ENABLED = True
except Exception as e:
    print(f"⚠️  ML inference not available: {str(e)}")
    ML_ENABLED = False
    ML_MIN_READINGS = 17

wearable_bp = Blueprint('wearable', __name__)


def convert_one_reading(ppg, gsr, acc_x, acc_y, acc_z):
    """
    Convert ONE raw ESP32 reading to real physical units, to be called at
    SAVE time (not just later at inference time), so every row stored in
    the database is consistently in physical units. This is what makes the
    exported CSV / dashboard show real BPM / uS / m/s^2 instead of a mix of
    raw sensor counts and converted values.

    ESP32 sends:
      ppg   - BPM directly from MAX30102 checkForBeat() → already correct BPM,
              no conversion needed. 0 means "no finger detected".
      gsr   - 10-bit ADC (0-1023), 3.3V ref, 10kOhm R_ref → convert to uS
      acc_* - ADXL345 raw LSB (+/-2g default, 256 LSB/g)  → convert to m/s^2

    Returns (ppg_bpm, gsr_us, acc_x_ms2, acc_y_ms2, acc_z_ms2).
    """
    # GSR: 10-bit ADC -> skin conductance uS (microsiemens)
    v_adc = (gsr / 1023.0) * 3.3
    v_adc = max(v_adc, 0.001)   # avoid div-by-zero
    v_adc = min(v_adc, 3.299)
    gsr_us = v_adc / (10000.0 * (3.3 - v_adc)) * 1000

    # ADXL345: raw LSB -> m/s^2 (+/-2g range, 256 LSB/g)
    scale = 9.81 / 256.0
    ax_ms2 = acc_x * scale
    ay_ms2 = acc_y * scale
    az_ms2 = acc_z * scale

    ppg_bpm = ppg if ppg > 0 else 65.0  # no finger detected -> resting default

    return ppg_bpm, gsr_us, ax_ms2, ay_ms2, az_ms2


def validate_sensor_reading(ppg, gsr, acc_x, acc_y, acc_z):
    """
    Reject RAW sensor readings that are outside what the ESP32 can physically
    send. Called BEFORE convert_one_reading(), so these ranges are the raw,
    unconverted sensor ranges only (not the converted physical ranges).

    Reference ranges (medically standard, physical meaning):
      Heart rate (PPG):  60-100 BPM at rest (normal adult resting range).
                          Down to ~40 BPM is possible for very fit individuals.
                          Up to ~180-200 BPM is legitimate during exercise or
                          an acute stress task (e.g. TSST) — not an error.
                          Below 40 or above 200 BPM is not physiologically
                          plausible for any state and is rejected as sensor
                          error (bad contact, disconnected finger, noise).
                          PPG is sent as BPM directly — no unit conversion.
      GSR (skin conductance): raw 10-bit ADC, must be 0-1023 — negative or
                          >1023 is impossible for this sensor and rejected.
                          Once converted (see convert_one_reading), this
                          typically becomes ~0.05-0.25 uS at rest, up to a
                          few uS under strong stress.
      Accelerometer: raw ADXL345 LSB, +/-2g range = roughly -256..256 LSB.
                          A little headroom is allowed for movement spikes;
                          anything far beyond that is corrupted data.
    """
    if not (0 <= gsr <= 1023):
        return f"gsr out of valid raw ADC range (0-1023): {gsr}"

    if ppg != 0 and not (40 <= ppg <= 200):
        return f"ppg outside plausible human heart-rate range (40-200 BPM): {ppg}"

    for name, val in [("acc_x", acc_x), ("acc_y", acc_y), ("acc_z", acc_z)]:
        if not (-320 <= val <= 320):  # +/-256 raw range with headroom for spikes
            return f"{name} outside plausible raw accelerometer range: {val}"

    return None


# ==================== ML INFERENCE HELPER ====================

def convert_esp32_to_model_units(readings):
    """
    Convert raw ESP32 sensor values to physical units expected by the ML model.

    ESP32 sends:
      ppg   - BPM from MAX30102 checkForBeat()  → already correct, skip if 0
      gsr   - 10-bit ADC (0-1023), 3.3V ref, 10kΩ R_ref → convert to µS
      acc_* - ADXL345 raw LSB (±2g default, 256 LSB/g)   → convert to m/s²

    Model expects:
      ppg   - BPM (~65-110)
      gsr   - skin conductance µS (~0.05-0.25)
      acc_* - m/s²
    """
    converted = []
    for r in readings:
        ppg = float(r['ppg'])
        gsr = float(r['gsr'])
        ax  = float(r['acc_x'])
        ay  = float(r['acc_y'])
        az  = float(r['acc_z'])

        # GSR: 10-bit ADC → skin conductance mS (millisiemens)
        # Circuit: Vcc=3.3V, R_ref=10kΩ in series, ADC reads across skin
        # conductance_mS = V / (R_ref × (Vcc - V)) × 1000
        # Calibrated: ADC≈400 → 0.064 mS ≈ training mean (0.0576 mS)
        v_adc = (gsr / 1023.0) * 3.3
        v_adc = max(v_adc, 0.001)           # avoid div-by-zero
        v_adc = min(v_adc, 3.299)
        gsr_us = v_adc / (10000.0 * (3.3 - v_adc)) * 1000

        # ADXL345: raw LSB → m/s²
        # Default config: ±2g, 10-bit, 256 LSB/g
        scale = 9.81 / 256.0                # ≈ 0.03832 m/s² per LSB
        ax_ms2 = ax * scale
        ay_ms2 = ay * scale
        az_ms2 = az * scale

        converted.append({
            'ppg':   ppg if 45 <= ppg <= 180 else 65.0,   # reject implausible values, not just 0
            'gsr':   gsr_us,
            'acc_x': ax_ms2,
            'acc_y': ay_ms2,
            'acc_z': az_ms2,
        })
    return converted


def has_device_settling_artifact(raw_readings, motion_spike_threshold=15.0):
    """
    Detect if this window still contains the 'putting the device on' transition,
    rather than a clean, settled reading period. Two signs of this:
      1. Some readings show no finger/skin contact (raw ppg == 0) mixed together
         with readings that do show a real heart rate — meaning contact just
         started partway through this window.
      2. A sudden large jump in accelerometer magnitude between two consecutive
         readings — typical of the device being picked up / strapped on / adjusted.
    """
    ppgs = [r.get('ppg', 0) for r in raw_readings]
    has_no_contact = any(p == 0 for p in ppgs)
    has_real_reading = any(p > 0 for p in ppgs)
    if has_no_contact and has_real_reading:
        return True

    magnitudes = [
        (r.get('acc_x', 0) ** 2 + r.get('acc_y', 0) ** 2 + r.get('acc_z', 0) ** 2) ** 0.5
        for r in raw_readings
    ]
    for i in range(1, len(magnitudes)):
        if abs(magnitudes[i] - magnitudes[i - 1]) > motion_spike_threshold:
            return True

    return False


def run_ml_inference_and_alert(user_id: str, record_id: str, db):
    """
    Run ML inference on recent sensor data and trigger alerts if needed.
    This runs after each new sensor reading is saved.
    Returns the prediction result dict or None.
    """
    if not ML_ENABLED:
        return None

    try:
        # Get recent readings — need ML_MIN_READINGS for a full window
        recent_readings = db.get_recent_readings_for_ml(user_id, limit=50)
        n = len(recent_readings)

        print(f"[ML] user={user_id} | readings={n}/{ML_MIN_READINGS}", end="")

        if n < ML_MIN_READINGS:
            print(f"  → waiting ({ML_MIN_READINGS - n} more needed)")
            return None

        if has_device_settling_artifact(recent_readings):
            print("  → skipping inference: device still settling in (no-contact→contact "
                  "transition or large motion spike detected, likely device being worn/adjusted)")
            return None

        # Convert raw ESP32 units → physical units expected by model
        model_readings = convert_esp32_to_model_units(recent_readings)

        # Run ML prediction
        prediction_result = predict_risk(model_readings)

        if not prediction_result:
            print("  → predict_risk returned None")
            return None

        prediction = prediction_result["prediction"]
        confidence = prediction_result["confidence"]
        risk_level = prediction_result["risk_level"]

        RISK_EMOJI = {0: "✅ NORMAL", 1: "⚠️  MILD_STRESS", 2: "🚨 HIGH_STRESS"}
        print(f"  → {RISK_EMOJI[risk_level]} | confidence={confidence:.2%} | readings_used={n}")

        # Require minimum confidence before acting on the prediction.
        # Low-confidence predictions (model unsure) should not trigger alerts or episodes.
        MIN_CONFIDENCE = 0.55
        if risk_level >= 1 and confidence < MIN_CONFIDENCE:
            print(f"[ML] Skipping alert — confidence {confidence:.2%} < {MIN_CONFIDENCE:.0%} threshold")
            risk_level = 0  # treat as normal for alert/episode logic

        # Save prediction to its own table
        db.save_window_prediction(user_id, prediction, confidence, risk_level,
                                  readings_used=n)
        print(f"[ML] Window prediction saved to db")

        # Handle depression episodes based on risk level
        if risk_level >= 1:  # MILD_STRESS or HIGH_STRESS
            # Send FCM push notification to user's phone
            if FCM_ENABLED:
                try:
                    fcm_token = db.get_fcm_token(user_id)
                    if fcm_token and db.fcm_cooldown_ok(user_id, cooldown_minutes=3):
                        condition = 'HIGH_STRESS' if risk_level == 2 else 'MILD_STRESS'
                        sent = fcm_send(
                            fcm_token=fcm_token,
                            alert_id=record_id,
                            condition=condition,
                            dri_score=float(confidence),
                        )
                        if sent:
                            db.update_fcm_sent_time(user_id)
                            print(f"[FCM] Push sent → {condition}")
                    elif fcm_token:
                        print(f"[FCM] Skipped — still in cooldown")
                except Exception as fcm_err:
                    print(f"[FCM] Push failed (non-fatal): {fcm_err}")

            # Check if there's an active episode
            active_episode = db.get_active_depression_episode(user_id)

            if active_episode:
                db.update_depression_episode(active_episode["id"], risk_level, confidence)
                print(f"[EP]  Updated active episode {active_episode['id'][:8]}...")
            else:
                ep_id = db.start_depression_episode(user_id, risk_level, confidence)
                print(f"[EP]  New depression episode started → {ep_id[:8]}...")

            # Crisis flag for high stress
            if risk_level == 2:
                user = db.get_user_by_id(user_id)
                if user:
                    # crisis_flags.session_id has a FOREIGN KEY to sessions(id) and is
                    # required. This is a wearable-triggered event, not a chat session,
                    # so create a lightweight session record to satisfy that constraint
                    # instead of using a fake string that doesn't exist in `sessions`.
                    wearable_session_id = db.create_session(user_id)
                    db.flag_crisis(
                        user_id=user_id,
                        user_name=user.get("name", "Unknown"),
                        user_email=user.get("email", ""),
                        session_id=wearable_session_id,
                        message_content=f"ML detected HIGH STRESS: {prediction} ({confidence:.2%})",
                        trigger_word="HIGH_STRESS_ML"
                    )
                    print(f"[CRISIS] Flag raised for {user.get('name')} ({user.get('email')})")

        else:  # NORMAL
            active_episode = db.get_active_depression_episode(user_id)
            if active_episode:
                recent_predictions = db.get_ml_prediction_history(user_id, limit=5)
                if len(recent_predictions) >= 5:
                    all_normal = all(p["risk_level"] == 0 for p in recent_predictions)
                    if all_normal:
                        db.end_depression_episode(active_episode["id"])
                        print(f"[EP]  Episode ended — 5 consecutive NORMAL readings")

        return prediction_result

    except Exception as e:
        print(f"[ML] ❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


# ==================== SENSOR DATA ENDPOINTS ====================

@wearable_bp.route("/api/wearable/data", methods=["POST"])
@token_required
def receive_sensor_data():
    """
    Receive sensor data from wearable device.

    Expected JSON payload:
    {
        "ppg": 75.5,           # Photoplethysmography value (heart rate/pulse)
        "gsr": 2.3,            # Galvanic Skin Response (skin conductance)
        "acc_x": 0.12,         # Accelerometer X-axis
        "acc_y": -0.05,        # Accelerometer Y-axis
        "acc_z": 9.81,         # Accelerometer Z-axis
        "timestamp": "2024-01-31T12:00:00Z"  # Optional: device timestamp
    }
    """
    try:
        user = request.current_user
        db = get_db()

        data = request.json

        if not data:
            return jsonify({"error": "No data provided"}), 400

        # Extract sensor values
        ppg = data.get("ppg")
        gsr = data.get("gsr")
        acc_x = data.get("acc_x")
        acc_y = data.get("acc_y")
        acc_z = data.get("acc_z")
        device_timestamp = data.get("timestamp")

        # Validate required fields
        if ppg is None or gsr is None:
            return jsonify({"error": "ppg and gsr values are required"}), 400

        if acc_x is None or acc_y is None or acc_z is None:
            return jsonify({"error": "acc_x, acc_y, and acc_z values are required"}), 400

        ppg, gsr = float(ppg), float(gsr)
        acc_x, acc_y, acc_z = float(acc_x), float(acc_y), float(acc_z)

        validation_error = validate_sensor_reading(ppg, gsr, acc_x, acc_y, acc_z)
        if validation_error:
            return jsonify({"error": validation_error}), 400

        # Convert raw values to real physical units BEFORE saving, so the
        # database always stores consistent BPM / uS / m/s^2 values.
        ppg, gsr, acc_x, acc_y, acc_z = convert_one_reading(ppg, gsr, acc_x, acc_y, acc_z)

        # Save to database
        record_id = db.save_wearable_data(
            user_id=user["id"],
            ppg=ppg,
            gsr=gsr,
            acc_x=acc_x,
            acc_y=acc_y,
            acc_z=acc_z,
            device_timestamp=device_timestamp
        )

        print(f"[DATA POST] user={user.get('name','?')} ({user.get('email','?')}) | "
              f"ppg={ppg} | gsr={gsr} | acc=({acc_x},{acc_y},{acc_z}) | "
              f"record_id={record_id[:8]} | device_ts={device_timestamp}")

        # Run ML inference and check for depression risk
        ml_result = run_ml_inference_and_alert(user["id"], record_id, db)

        if ml_result:
            print(f"[ML RESULT] user={user.get('name','?')} | "
                  f"prediction={ml_result.get('prediction')} | "
                  f"risk_level={ml_result.get('risk_level')} | "
                  f"confidence={ml_result.get('confidence', 0):.2%}")
        else:
            print(f"[ML RESULT] user={user.get('name','?')} | not enough readings yet (need {ML_MIN_READINGS})")

        return jsonify({
            "success": True,
            "record_id": record_id,
            "message": "Sensor data saved successfully"
        })

    except ValueError as e:
        return jsonify({"error": f"Invalid data format: {str(e)}"}), 400
    except Exception as e:
        print(f"Error saving wearable data: {str(e)}")
        return jsonify({"error": "Failed to save sensor data"}), 500


@wearable_bp.route("/api/wearable/batch", methods=["POST"])
@token_required
def receive_batch_data():
    """
    Receive batch sensor data from wearable device.
    Useful for sending multiple readings at once (e.g., when device reconnects).

    Expected JSON payload:
    {
        "readings": [
            {"ppg": 75.5, "gsr": 2.3, "acc_x": 0.1, "acc_y": -0.05, "acc_z": 9.81, "timestamp": "..."},
            {"ppg": 76.0, "gsr": 2.4, "acc_x": 0.2, "acc_y": -0.04, "acc_z": 9.80, "timestamp": "..."},
            ...
        ]
    }
    """
    try:
        user = request.current_user
        db = get_db()

        data = request.json
        readings = data.get("readings", [])

        if not readings:
            return jsonify({"error": "No readings provided"}), 400

        if len(readings) > 1000:
            return jsonify({"error": "Maximum 1000 readings per batch"}), 400

        saved_count = 0
        errors = []

        for i, reading in enumerate(readings):
            try:
                ppg = reading.get("ppg")
                gsr = reading.get("gsr")
                acc_x = reading.get("acc_x")
                acc_y = reading.get("acc_y")
                acc_z = reading.get("acc_z")
                device_timestamp = reading.get("timestamp")

                if None in (ppg, gsr, acc_x, acc_y, acc_z):
                    errors.append(f"Reading {i}: missing required fields")
                    continue

                ppg, gsr = float(ppg), float(gsr)
                acc_x, acc_y, acc_z = float(acc_x), float(acc_y), float(acc_z)
                validation_error = validate_sensor_reading(ppg, gsr, acc_x, acc_y, acc_z)
                if validation_error:
                    errors.append(f"Reading {i}: {validation_error}")
                    continue

                # Convert raw values to real physical units BEFORE saving
                ppg, gsr, acc_x, acc_y, acc_z = convert_one_reading(ppg, gsr, acc_x, acc_y, acc_z)

                db.save_wearable_data(
                    user_id=user["id"],
                    ppg=ppg,
                    gsr=gsr,
                    acc_x=acc_x,
                    acc_y=acc_y,
                    acc_z=acc_z,
                    device_timestamp=device_timestamp
                )
                saved_count += 1

            except (ValueError, TypeError) as e:
                errors.append(f"Reading {i}: {str(e)}")

        # Run ML inference after batch save (uses latest 25+ readings)
        if saved_count > 0:
            try:
                last_record_id = db.conn.execute(
                    """SELECT id FROM wearable_data
                       WHERE user_id = ? ORDER BY recorded_at DESC LIMIT 1""",
                    (user["id"],)
                ).fetchone()
                if last_record_id:
                    ml_result = run_ml_inference_and_alert(user["id"], last_record_id[0], db)
                    if ml_result:
                        print(f"[ML RESULT BATCH] user={user.get('name','?')} | "
                              f"prediction={ml_result.get('prediction')} | "
                              f"risk_level={ml_result.get('risk_level')} | "
                              f"confidence={ml_result.get('confidence', 0):.2%}")
            except Exception as ml_err:
                print(f"ML inference after batch failed: {str(ml_err)}")

        print(f"[BATCH POST] user={user.get('name','?')} ({user.get('email','?')}) | "
              f"saved={saved_count}/{len(readings)} readings | errors={len(errors)}")

        return jsonify({
            "success": True,
            "saved_count": saved_count,
            "total_readings": len(readings),
            "errors": errors if errors else None
        })

    except Exception as e:
        print(f"Error saving batch wearable data: {str(e)}")
        return jsonify({"error": "Failed to save batch data"}), 500


@wearable_bp.route("/api/wearable/history", methods=["GET"])
@token_required
def get_sensor_history():
    """
    Get user's sensor data history.

    Query parameters:
    - limit: Number of records to return (default: 100, max: 1000)
    - offset: Number of records to skip (for pagination)
    - start_date: Filter records from this date (ISO format)
    - end_date: Filter records until this date (ISO format)
    """
    try:
        user = request.current_user
        db = get_db()

        limit = min(int(request.args.get("limit", 100)), 1000)
        offset = int(request.args.get("offset", 0))
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")

        records = db.get_wearable_history(
            user_id=user["id"],
            limit=limit,
            offset=offset,
            start_date=start_date,
            end_date=end_date
        )

        return jsonify({
            "records": records,
            "count": len(records),
            "limit": limit,
            "offset": offset
        })

    except Exception as e:
        print(f"Error fetching wearable history: {str(e)}")
        return jsonify({"error": "Failed to fetch sensor history"}), 500


@wearable_bp.route("/api/wearable/latest", methods=["GET"])
@token_required
def get_latest_reading():
    """Get the most recent sensor reading for the user."""
    try:
        user = request.current_user
        db = get_db()

        record = db.get_latest_wearable_data(user["id"])

        if not record:
            return jsonify({
                "record": None,
                "message": "No sensor data found"
            })

        return jsonify({
            "record": record
        })

    except Exception as e:
        print(f"Error fetching latest wearable data: {str(e)}")
        return jsonify({"error": "Failed to fetch latest reading"}), 500


@wearable_bp.route("/api/wearable/stats", methods=["GET"])
@token_required
def get_sensor_stats():
    """
    Get aggregated statistics for user's sensor data.

    Query parameters:
    - period: 'day', 'week', 'month' (default: 'day')
    """
    try:
        user = request.current_user
        db = get_db()

        period = request.args.get("period", "day")
        if period not in ("day", "week", "month"):
            return jsonify({"error": "Invalid period. Use 'day', 'week', or 'month'"}), 400

        stats = db.get_wearable_stats(user["id"], period)

        return jsonify({
            "period": period,
            "stats": stats
        })

    except Exception as e:
        print(f"Error fetching wearable stats: {str(e)}")
        return jsonify({"error": "Failed to fetch sensor statistics"}), 500


# ==================== DEVICE API KEY ENDPOINTS ====================

@wearable_bp.route("/api/wearable/device/register", methods=["POST"])
@token_required
def register_device():
    """
    Generate a new device API key for the authenticated user.
    This key can be used by ESP32 to send data without JWT.

    Optional JSON payload:
    {
        "device_name": "My ESP32 Wearable"  # Optional, defaults to "ESP32 Wearable"
    }

    Returns the API key - SAVE IT, it won't be shown again in full!
    """
    try:
        user = request.current_user
        db = get_db()

        data = request.json or {}
        device_name = data.get("device_name", "ESP32 Wearable")

        # Limit to 5 active devices per user
        existing_keys = db.get_user_device_keys(user["id"])
        active_keys = [k for k in existing_keys if k["is_active"]]
        if len(active_keys) >= 5:
            return jsonify({
                "error": "Maximum 5 active devices allowed. Please revoke an existing device first."
            }), 400

        result = db.create_device_key(user["id"], device_name)

        return jsonify({
            "success": True,
            "message": "Device registered successfully. Save the API key - it won't be shown again!",
            "device": {
                "id": result["id"],
                "api_key": result["api_key"],
                "device_name": result["device_name"],
                "created_at": result["created_at"]
            }
        })

    except Exception as e:
        print(f"Error registering device: {str(e)}")
        return jsonify({"error": "Failed to register device"}), 500


@wearable_bp.route("/api/wearable/device/keys", methods=["GET"])
@token_required
def list_device_keys():
    """Get all device keys for the authenticated user (API keys are masked)."""
    try:
        user = request.current_user
        db = get_db()

        keys = db.get_user_device_keys(user["id"])

        return jsonify({
            "devices": keys
        })

    except Exception as e:
        print(f"Error listing device keys: {str(e)}")
        return jsonify({"error": "Failed to list devices"}), 500


@wearable_bp.route("/api/wearable/device/<key_id>", methods=["DELETE"])
@token_required
def revoke_device(key_id):
    """Revoke a device API key."""
    try:
        user = request.current_user
        db = get_db()

        success = db.revoke_device_key(key_id, user["id"])

        if success:
            return jsonify({
                "success": True,
                "message": "Device revoked successfully"
            })
        else:
            return jsonify({"error": "Device not found or already revoked"}), 404

    except Exception as e:
        print(f"Error revoking device: {str(e)}")
        return jsonify({"error": "Failed to revoke device"}), 500


@wearable_bp.route("/api/wearable/device/data", methods=["POST"])
def receive_device_data():
    """
    Receive sensor data from ESP32 using device API key.
    NO JWT required - uses X-Device-Key header instead.

    Required Header:
        X-Device-Key: <your_device_api_key>

    Expected JSON payload:
    {
        "ppg": 75.5,
        "gsr": 2.3,
        "acc_x": 0.12,
        "acc_y": -0.05,
        "acc_z": 9.81,
        "timestamp": "2024-01-31T12:00:00Z"  # Optional
    }
    """
    try:
        # Get device API key from header
        api_key = request.headers.get("X-Device-Key")

        if not api_key:
            return jsonify({"error": "X-Device-Key header is required"}), 401

        db = get_db()

        # Validate API key and get user
        user = db.get_user_by_device_key(api_key)

        if not user:
            return jsonify({"error": "Invalid or revoked device key"}), 401

        data = request.json

        if not data:
            return jsonify({"error": "No data provided"}), 400

        # Extract sensor values
        ppg = data.get("ppg")
        gsr = data.get("gsr")
        acc_x = data.get("acc_x")
        acc_y = data.get("acc_y")
        acc_z = data.get("acc_z")
        device_timestamp = data.get("timestamp")
        # On-device DRI score computed by ESP32 after its 5-min personal baseline calibration
        device_dri_score = data.get("dri_score")
        device_condition = data.get("condition")

        # Validate required fields
        if ppg is None or gsr is None:
            return jsonify({"error": "ppg and gsr values are required"}), 400

        if acc_x is None or acc_y is None or acc_z is None:
            return jsonify({"error": "acc_x, acc_y, and acc_z values are required"}), 400

        # Save to database
        record_id = db.save_wearable_data(
            user_id=user["id"],
            ppg=float(ppg),
            gsr=float(gsr),
            acc_x=float(acc_x),
            acc_y=float(acc_y),
            acc_z=float(acc_z),
            device_timestamp=device_timestamp
        )

        dri_info = f" | device_dri={float(device_dri_score):.2f} ({device_condition})" if device_dri_score is not None else ""
        logger.info(
            "[DEVICE DATA] user=%s... | ppg=%.3f gsr=%.1f acc=(%.2f,%.2f,%.2f)%s | record=%s...",
            user['id'][:8], float(ppg), float(gsr),
            float(acc_x), float(acc_y), float(acc_z),
            dri_info, record_id[:8]
        )

        # Run ML inference (results logged to backend console, not returned)
        run_ml_inference_and_alert(user["id"], record_id, db)

        return jsonify({"success": True, "record_id": record_id})

    except ValueError as e:
        return jsonify({"error": f"Invalid data format: {str(e)}"}), 400
    except Exception as e:
        print(f"Error saving device data: {str(e)}")
        return jsonify({"error": "Failed to save sensor data"}), 500


# ==================== ALERT ENDPOINTS ====================

@wearable_bp.route("/api/wearable/alerts/latest", methods=["GET"])
@token_required
def get_latest_alert():
    """
    Get the latest unacknowledged HIGH_STRESS or MILD_STRESS alert.
    Used by the Flutter app for polling-based alert detection.
    """
    try:
        user = request.current_user
        db = get_db()

        # Find the latest unacknowledged stress reading
        result = db.conn.execute(
            """SELECT id, risk_level, ml_confidence, ml_prediction, ppg, gsr,
                      recorded_at, condition
               FROM wearable_data
               WHERE user_id = ?
                 AND risk_level >= 1
                 AND (acknowledged = 0 OR acknowledged IS NULL)
               ORDER BY recorded_at DESC
               LIMIT 1""",
            (user["id"],)
        ).fetchone()

        if not result:
            return jsonify({"has_alert": False, "alert": None})

        alert = {
            "id": result[0],
            "dri_score": result[2] if result[2] else 0.0,
            "condition": result[7] if result[7] else ("HIGH_STRESS" if result[1] == 2 else "MILD_STRESS"),
            "ppg": result[4],
            "gsr": result[5],
            "recorded_at": result[6],
        }

        return jsonify({"has_alert": True, "alert": alert})

    except Exception as e:
        print(f"Error fetching latest alert: {str(e)}")
        return jsonify({"error": "Failed to fetch alert"}), 500


@wearable_bp.route("/api/wearable/alerts", methods=["GET"])
@token_required
def get_all_alerts():
    """
    Get all unacknowledged stress alerts for the user.
    """
    try:
        user = request.current_user
        db = get_db()

        results = db.conn.execute(
            """SELECT id, risk_level, ml_confidence, ml_prediction, ppg, gsr,
                      recorded_at, condition
               FROM wearable_data
               WHERE user_id = ?
                 AND risk_level >= 1
                 AND (acknowledged = 0 OR acknowledged IS NULL)
               ORDER BY recorded_at DESC
               LIMIT 50""",
            (user["id"],)
        ).fetchall()

        alerts = []
        high_count = 0
        mild_count = 0
        for r in results:
            condition = r[7] if r[7] else ("HIGH_STRESS" if r[1] == 2 else "MILD_STRESS")
            alerts.append({
                "id": r[0],
                "dri_score": r[2] if r[2] else 0.0,
                "condition": condition,
                "ppg": r[4],
                "gsr": r[5],
                "recorded_at": r[6],
            })
            if r[1] == 2:
                high_count += 1
            elif r[1] == 1:
                mild_count += 1

        return jsonify({
            "alerts": alerts,
            "count": len(alerts),
            "high_stress_count": high_count,
            "mild_stress_count": mild_count,
            "has_critical": high_count > 0,
        })

    except Exception as e:
        print(f"Error fetching alerts: {str(e)}")
        return jsonify({"error": "Failed to fetch alerts"}), 500


@wearable_bp.route("/api/wearable/alerts/acknowledge", methods=["POST"])
@token_required
def acknowledge_alerts():
    """
    Acknowledge stress alerts. If alert_id is provided, acknowledge that specific alert.
    Otherwise, acknowledge all unacknowledged alerts for the user.
    """
    try:
        user = request.current_user
        db = get_db()

        data = request.json or {}
        alert_id = data.get("alert_id")

        if alert_id:
            db.conn.execute(
                """UPDATE wearable_data SET acknowledged = 1
                   WHERE id = ? AND user_id = ?""",
                (alert_id, user["id"])
            )
        else:
            db.conn.execute(
                """UPDATE wearable_data SET acknowledged = 1
                   WHERE user_id = ? AND risk_level >= 1
                     AND (acknowledged = 0 OR acknowledged IS NULL)""",
                (user["id"],)
            )

        db.conn.commit()

        return jsonify({"success": True, "message": "Alerts acknowledged"})

    except Exception as e:
        print(f"Error acknowledging alerts: {str(e)}")
        return jsonify({"error": "Failed to acknowledge alerts"}), 500


# ==================== ML STATUS ENDPOINTS ====================

@wearable_bp.route("/api/wearable/ml/status", methods=["GET"])
@token_required
def get_ml_status():
    """
    Get current ML-based depression risk status for the user.
    Returns latest prediction and depression episode information.
    """
    try:
        user = request.current_user
        db = get_db()

        # Get depression statistics
        stats = db.get_user_depression_stats(user["id"])

        # Get active episode details if any
        active_episode = db.get_active_depression_episode(user["id"]) if stats.get("has_active_episode") else None

        # Get recent prediction history from ml_window_predictions table
        recent_predictions = db.get_window_predictions(user["id"], limit=10)

        return jsonify({
            "ml_enabled": ML_ENABLED,
            "current_status": stats.get("latest_prediction"),
            "has_active_episode": stats.get("has_active_episode"),
            "active_episode": active_episode,
            "statistics": {
                "total_episodes": stats.get("total_episodes"),
                "episodes_last_7_days": stats.get("episodes_last_7_days"),
                "peak_risk_last_7_days": stats.get("peak_risk_last_7_days")
            },
            "recent_predictions": recent_predictions
        })

    except Exception as e:
        print(f"Error fetching ML status: {str(e)}")
        return jsonify({"error": "Failed to fetch ML status"}), 500


@wearable_bp.route("/api/wearable/ml/episodes", methods=["GET"])
@token_required
def get_depression_episodes():
    """Get all depression episodes for the user."""
    try:
        user = request.current_user
        db = get_db()

        limit = min(int(request.args.get("limit", 50)), 100)
        episodes = db.get_all_depression_episodes(user["id"], limit=limit)

        return jsonify({
            "episodes": episodes,
            "count": len(episodes)
        })

    except Exception as e:
        print(f"Error fetching depression episodes: {str(e)}")
        return jsonify({"error": "Failed to fetch episodes"}), 500


@wearable_bp.route("/api/wearable/device/batch", methods=["POST"])
def receive_device_batch():
    """
    Receive batch sensor data from ESP32 using device API key.
    Useful when device stores readings and sends in bulk.

    Required Header:
        X-Device-Key: <your_device_api_key>

    Expected JSON payload:
    {
        "readings": [
            {"ppg": 75.5, "gsr": 2.3, "acc_x": 0.1, "acc_y": -0.05, "acc_z": 9.81, "timestamp": "..."},
            ...
        ]
    }
    """
    try:
        # Get device API key from header
        api_key = request.headers.get("X-Device-Key")

        if not api_key:
            return jsonify({"error": "X-Device-Key header is required"}), 401

        db = get_db()

        # Validate API key and get user
        user = db.get_user_by_device_key(api_key)

        if not user:
            return jsonify({"error": "Invalid or revoked device key"}), 401

        data = request.json
        readings = data.get("readings", [])

        if not readings:
            return jsonify({"error": "No readings provided"}), 400

        if len(readings) > 1000:
            return jsonify({"error": "Maximum 1000 readings per batch"}), 400

        saved_count = 0
        errors = []

        for i, reading in enumerate(readings):
            try:
                ppg = reading.get("ppg")
                gsr = reading.get("gsr")
                acc_x = reading.get("acc_x")
                acc_y = reading.get("acc_y")
                acc_z = reading.get("acc_z")
                device_timestamp = reading.get("timestamp")

                if None in (ppg, gsr, acc_x, acc_y, acc_z):
                    errors.append(f"Reading {i}: missing required fields")
                    continue

                ppg, gsr = float(ppg), float(gsr)
                acc_x, acc_y, acc_z = float(acc_x), float(acc_y), float(acc_z)
                validation_error = validate_sensor_reading(ppg, gsr, acc_x, acc_y, acc_z)
                if validation_error:
                    errors.append(f"Reading {i}: {validation_error}")
                    continue

                # Convert raw values to real physical units BEFORE saving
                ppg, gsr, acc_x, acc_y, acc_z = convert_one_reading(ppg, gsr, acc_x, acc_y, acc_z)

                db.save_wearable_data(
                    user_id=user["id"],
                    ppg=ppg,
                    gsr=gsr,
                    acc_x=acc_x,
                    acc_y=acc_y,
                    acc_z=acc_z,
                    device_timestamp=device_timestamp
                )
                saved_count += 1

            except (ValueError, TypeError) as e:
                errors.append(f"Reading {i}: {str(e)}")

        # Run ML inference after batch save (uses latest 25+ readings)
        if saved_count > 0:
            try:
                last_record_id = db.conn.execute(
                    """SELECT id FROM wearable_data
                       WHERE user_id = ? ORDER BY recorded_at DESC LIMIT 1""",
                    (user["id"],)
                ).fetchone()
                if last_record_id:
                    run_ml_inference_and_alert(user["id"], last_record_id[0], db)
            except Exception as ml_err:
                print(f"ML inference after device batch failed: {str(ml_err)}")

        return jsonify({
            "success": True,
            "saved_count": saved_count,
            "total_readings": len(readings),
            "errors": errors if errors else None
        })

    except Exception as e:
        print(f"Error saving device batch data: {str(e)}")
        return jsonify({"error": "Failed to save batch data"}), 500