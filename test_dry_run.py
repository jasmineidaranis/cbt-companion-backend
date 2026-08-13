"""
Dry Run Test Script - Sends wearable sensor data to the deployed backend
and shows ML classification results in real-time.

Usage:
    python test_dry_run.py
"""

import csv
import json
import time
import sys
import io
import requests

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE_URL = "https://santa47-cbt-companion-api.hf.space"
DEVICE_API_KEY = "0c4358009dbe75db461b760222a6e15b"

DATA_DIR = "data"

HEADERS = {
    "Content-Type": "application/json",
    "X-Device-Key": DEVICE_API_KEY
}


def load_csv(filename):
    """Load sensor data from CSV file."""
    readings = []
    with open(f"{DATA_DIR}/{filename}", "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            readings.append({
                "ppg": float(row["PPG"]),
                "gsr": float(row["GSR"]),
                "acc_x": float(row["ACC_X"]),
                "acc_y": float(row["ACC_Y"]),
                "acc_z": float(row["ACC_Z"]),
                "timestamp": row["time"]
            })
    return readings


def send_reading(reading, retries=2):
    """Send a single sensor reading and return the response. Retries on connection errors."""
    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                f"{BASE_URL}/api/wearable/device/data",
                headers=HEADERS,
                json=reading,
                timeout=30
            )
            return resp.json()
        except requests.exceptions.ConnectionError as e:
            if attempt < retries:
                wait = 2 ** attempt  # 1s, 2s backoff
                print(f"    (connection error, retrying in {wait}s...)")
                time.sleep(wait)
            else:
                return {"_error": f"ConnectionError: {e}"}
        except requests.exceptions.Timeout:
            return {"_error": "Timeout after 30s"}
        except Exception as e:
            return {"_error": str(e)}


def send_batch(readings, label):
    """Send all readings one by one and show ML results."""
    print(f"\n{'='*60}")
    print(f"  SENDING {len(readings)} readings - Expected: {label}")
    print(f"{'='*60}")

    errors = 0
    for i, reading in enumerate(readings):
        result = send_reading(reading)

        if "_error" in result:
            errors += 1
            print(f"  [{i+1:2d}/{len(readings)}] ERROR: {result['_error']}")
            time.sleep(1)
            continue

        ml = result.get("ml_prediction")
        if ml and isinstance(ml, dict):
            if ml.get("status") == "waiting":
                count = ml.get('readings_count', '?')
                needed = ml.get('needed', 25)
                print(f"  [{i+1:2d}/{len(readings)}] Sent OK  ML: waiting ({count}/{needed} readings)")
            else:
                pred = ml.get("prediction", "?")
                conf = ml.get("confidence", 0)
                risk = ml.get("risk_level", -1)

                if pred == "NORMAL":
                    tag = "[NORMAL]"
                elif pred == "MILD_STRESS":
                    tag = "[MILD_STRESS]"
                else:
                    tag = "[HIGH_STRESS] !!!"

                print(f"  [{i+1:2d}/{len(readings)}] Sent OK  ML: {tag}  confidence={conf:.1%}  risk_level={risk}")
        else:
            status = "OK" if result.get("success") else "FAIL"
            extra = f"  ml={ml}" if ml else "  (no ML - model not loaded)"
            print(f"  [{i+1:2d}/{len(readings)}] Sent {status}{extra}")

        time.sleep(0.3)

    if errors:
        print(f"\n  WARNING: {errors}/{len(readings)} readings failed to send.")


def check_alerts():
    """Check server status after test."""
    print(f"\n{'='*60}")
    print(f"  RESULTS")
    print(f"{'='*60}")

    resp = requests.get(f"{BASE_URL}/health", timeout=10)
    health = resp.json()
    print(f"  Server status:    {health.get('status')}")
    print(f"  ML model loaded:  {health.get('ml_model_loaded')}")
    print()
    if not health.get('ml_model_loaded'):
        print("  WARNING: ML model is NOT loaded on server!")
        print("  The model file 'models/multiscale_tcn.pth' is missing.")
        print("  Data was saved but NO predictions were made.")
        print()
    print("  >> Check your phone app now!")
    print("  >> If HIGH_STRESS was detected, within 30s you should see:")
    print("     - A notification on your phone")
    print("     - A full-screen red alert with DRI score")


def main():
    print(f"\n{'#'*60}")
    print(f"  CBT COMPANION - DRY RUN TEST")
    print(f"  Backend: {BASE_URL}")
    print(f"  Device Key: {DEVICE_API_KEY[:8]}...")
    print(f"{'#'*60}")

    # Verify connection
    print("\n[1/5] Verifying backend connection...")
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=10)
        health = resp.json()
        print(f"  Status:          {health.get('status')}")
        print(f"  ML Model Loaded: {health.get('ml_model_loaded')}")
    except Exception as e:
        print(f"  ERROR: Cannot reach backend - {e}")
        return

    # Verify device key
    print("\n[2/5] Verifying device API key...")
    test_resp = requests.post(
        f"{BASE_URL}/api/wearable/device/data",
        headers=HEADERS,
        json={"ppg": 0, "gsr": 0, "acc_x": 0, "acc_y": 0, "acc_z": 0},
        timeout=10
    )
    if test_resp.status_code == 401:
        print(f"  ERROR: Invalid device API key!")
        return
    elif test_resp.status_code == 200:
        print(f"  Device key valid - OK")
    else:
        print(f"  Unexpected response: {test_resp.status_code} - {test_resp.text}")

    # Load datasets
    print("\n[3/5] Loading datasets...")
    normal_data = load_csv("sampled_data_DepressionLevel_Normal.csv")
    mild_data = load_csv("sampled_data_DepressionLevel_Mild.csv")
    moderate_data = load_csv("sampled_data_DepressionLevel_Moderate.csv")
    severe_data = load_csv("sampled_data_DepressionLevel_Severe.csv")
    print(f"  Normal:   {len(normal_data)} readings")
    print(f"  Mild:     {len(mild_data)} readings")
    print(f"  Moderate: {len(moderate_data)} readings")
    print(f"  Severe:   {len(severe_data)} readings")

    # Step 1: Send Normal data
    print("\n[4/5] Sending NORMAL data (should NOT trigger alert)...")
    send_batch(normal_data, "NORMAL")

    print("\n  Pausing 3 seconds before next batch...")
    time.sleep(3)

    # Step 2: Send Severe data
    print("\n[5/5] Sending SEVERE data (SHOULD trigger HIGH_STRESS alert)...")
    send_batch(severe_data, "HIGH_STRESS")

    # Check results
    check_alerts()

    print(f"\n{'#'*60}")
    print(f"  TEST COMPLETE")
    print(f"{'#'*60}\n")


if __name__ == "__main__":
    main()
