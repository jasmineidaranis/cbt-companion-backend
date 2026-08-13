"""
FCM Diagnostic Test
====================
Uses device API key to check FCM status and send a test push notification.
No email/password needed.

Usage:
    python test_fcm.py
"""

import csv
import sys
import io
import time
import requests

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE_URL      = "https://santa47-cbt-companion-api.hf.space"
DEVICE_API_KEY = "0c4358009dbe75db461b760222a6e15b"

DATA_DIR   = "data"
SEVERE_CSV = "sampled_data_DepressionLevel_Severe.csv"

DEVICE_HEADERS = {
    "Content-Type": "application/json",
    "X-Device-Key": DEVICE_API_KEY,
}


def check_health():
    return requests.get(f"{BASE_URL}/health", timeout=10).json()


def check_fcm_status(send_test=False):
    url = f"{BASE_URL}/api/wearable/device/fcm-debug"
    if send_test:
        url += "?send_test=1"
    return requests.get(url, headers=DEVICE_HEADERS, timeout=15).json()


def load_severe_data():
    readings = []
    with open(f"{DATA_DIR}/{SEVERE_CSV}", "r") as f:
        for row in csv.DictReader(f):
            readings.append({
                "ppg":   float(row["PPG"]),
                "gsr":   float(row["GSR"]),
                "acc_x": float(row["ACC_X"]),
                "acc_y": float(row["ACC_Y"]),
                "acc_z": float(row["ACC_Z"]),
            })
    return readings


def send_sensor(reading):
    return requests.post(
        f"{BASE_URL}/api/wearable/device/data",
        headers=DEVICE_HEADERS,
        json=reading,
        timeout=20,
    ).json()


def main():
    print("\n" + "="*60)
    print("  CBT COMPANION — FCM DIAGNOSTIC TEST")
    print(f"  Device key: {DEVICE_API_KEY[:8]}...")
    print("="*60)

    # 1. Health
    print("\n[1] Health check...")
    health = check_health()
    print(f"  Status:          {health.get('status')}")
    print(f"  ML model loaded: {health.get('ml_model_loaded')}")
    print(f"  FCM enabled:     {health.get('fcm_enabled')}")
    if not health.get("fcm_enabled"):
        print("\n  ❌ firebase-admin NOT loaded on server.")
        print("     Check HuggingFace Space logs + FIREBASE_SERVICE_ACCOUNT secret.")
        return

    # 2. FCM token check (no test push yet)
    print("\n[2] Checking if device owner has FCM token in DB...")
    status = check_fcm_status(send_test=False)
    print(f"  FCM backend enabled: {status.get('fcm_backend_enabled')}")
    print(f"  User has token:      {status.get('user_has_token')}")
    print(f"  Token preview:       {status.get('token_preview', 'N/A')}")

    if not status.get("user_has_token"):
        print("\n  ❌ No FCM token stored for this user!")
        print("     → Open the app on your phone and LOG IN.")
        print("       The token uploads automatically on login.")
        print("     → Then run this script again.")
        return

    # 3. Test push
    print("\n[3] Sending test FCM push notification...")
    push_result = check_fcm_status(send_test=True)
    test_push = push_result.get("test_push", "unknown")
    print(f"  Result: {test_push}")

    if "SENT" in str(test_push):
        print("\n  ✅ Test push SENT — check your phone NOW.")
        print("     (It may take a few seconds to arrive)")
        if not health.get("ml_model_loaded"):
            print("\n  ⚠️  ML model is NOT loaded — real alerts won't fire.")
            print("     But the test push above confirms FCM itself is working.")
            print("     The ML model file needs to be present on the server.")
        else:
            # 4. Real stress data
            print("\n[4] Sending SEVERE stress sensor data to trigger ML → FCM alert...")
            try:
                readings = load_severe_data()
            except FileNotFoundError:
                print(f"  ⚠️  {SEVERE_CSV} not found in {DATA_DIR}/ — skipping")
                print("     Run test_dry_run.py separately to trigger ML alerts.")
                return

            alert_seen = False
            for i, reading in enumerate(readings):
                result = send_sensor(reading)
                ml = result.get("ml_prediction")
                if ml and isinstance(ml, dict):
                    if ml.get("status") == "waiting":
                        cnt = ml.get("readings_count", "?")
                        print(f"  [{i+1:2d}/{len(readings)}] waiting ({cnt}/25 readings)")
                    else:
                        pred = ml.get("prediction", "?")
                        conf = ml.get("confidence", 0)
                        risk = ml.get("risk_level", -1)
                        lbl = {"NORMAL": "[NORMAL]",
                               "MILD_STRESS": "[MILD_STRESS]",
                               "HIGH_STRESS": "[HIGH_STRESS] !!!"}.get(pred, pred)
                        print(f"  [{i+1:2d}/{len(readings)}] {lbl}  conf={conf:.0%}  risk={risk}")
                        if risk >= 1:
                            alert_seen = True
                            print(f"           ↑ FCM push should fire to ...{status.get('token_preview')}")
                time.sleep(0.3)

            if not alert_seen:
                print("\n  ⚠️  No stress detected in this data batch (model may need more readings).")

    elif "FAILED" in str(test_push):
        print("\n  ❌ FCM send FAILED — check HuggingFace Space logs for the error message.")
        print("     Common causes:")
        print("      • FIREBASE_SERVICE_ACCOUNT secret is malformed")
        print("      • FCM token is expired (log out and log back in on phone)")
        print("      • Wrong Firebase project")

    print("\n" + "="*60)
    print("  DONE")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
