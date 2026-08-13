"""
Firebase Cloud Messaging — Push Notification Sender
Sends stress alerts to users' devices when ML detects elevated risk.
"""

import os
import json

_firebase_app = None


def _get_app():
    """Lazily initialize Firebase Admin SDK."""
    global _firebase_app
    if _firebase_app is not None:
        return _firebase_app

    service_account_json = os.environ.get('FIREBASE_SERVICE_ACCOUNT')
    if not service_account_json:
        raise ValueError("FIREBASE_SERVICE_ACCOUNT environment variable not set")

    import firebase_admin
    from firebase_admin import credentials

    cred_dict = json.loads(service_account_json)
    cred = credentials.Certificate(cred_dict)
    _firebase_app = firebase_admin.initialize_app(cred)
    print("✅ Firebase Admin SDK initialized")
    return _firebase_app


def send_stress_alert(fcm_token: str, alert_id: str, condition: str,
                      dri_score: float, ppg=None, gsr=None,
                      recorded_at: str = None) -> bool:
    """
    Send a stress alert push notification to a specific device.
    Returns True if sent successfully, False otherwise.
    """
    if not fcm_token:
        return False

    try:
        _get_app()
        from firebase_admin import messaging

        # Data-only message (no 'notification' field) so Android delivers it
        # to the background handler, which shows a full-screen alarm notification.
        message = messaging.Message(
            data={
                'alert_id': str(alert_id),
                'condition': condition,
                'dri_score': str(round(dri_score, 4)),
                'ppg': str(ppg) if ppg is not None else '',
                'gsr': str(gsr) if gsr is not None else '',
                'recorded_at': recorded_at or '',
                'type': 'stress_alert',
            },
            android=messaging.AndroidConfig(
                priority='high',   # FCM transport priority — bypasses Doze mode
            ),
            token=fcm_token,
        )

        response = messaging.send(message)
        print(f"✅ FCM alert sent ({condition}) to ...{fcm_token[-10:]}: {response}")
        return True

    except Exception as e:
        print(f"❌ FCM send error: {str(e)}")
        return False
