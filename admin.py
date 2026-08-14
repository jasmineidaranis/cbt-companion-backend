"""
Admin Panel Module
Handles admin routes, authentication, and dashboard functionality
"""

from flask import Blueprint, render_template, jsonify, request, redirect, url_for
from auth import admin_required, login_user, is_admin, generate_token
from database import get_db

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


# ==================== PAGE ROUTES ====================

@admin_bp.route('/')
def admin_index():
    """Redirect /admin to /admin/login."""
    return redirect(url_for('admin.admin_login_page'))


@admin_bp.route('/login')
def admin_login_page():
    """Render admin login page."""
    return render_template('admin_login.html')


@admin_bp.route('/dashboard')
def admin_dashboard_page():
    """Render admin dashboard page."""
    return render_template('admin_dashboard.html')


@admin_bp.route('/patients')
def admin_patients_page():
    """Render patient list page."""
    return render_template('admin_patients.html')


@admin_bp.route('/patients/<user_id>')
def admin_patient_detail_page(user_id):
    """Render patient detail page."""
    return render_template('admin_patient_detail.html', user_id=user_id)


# ==================== API ROUTES ====================

# Hardcoded admin credentials
ADMIN_USERNAME = "admin123"
ADMIN_PASSWORD = "1234"


@admin_bp.route('/api/login', methods=['POST'])
def admin_login():
    """Admin login endpoint."""
    data = request.json
    email = data.get('email', '')
    password = data.get('password', '')

    # Check hardcoded admin credentials first
    if email == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        token = generate_token("admin", ADMIN_USERNAME)
        return jsonify({
            'success': True,
            'user': {
                'id': 'admin',
                'email': ADMIN_USERNAME,
                'name': 'Admin',
                'context': 'admin'
            },
            'token': token
        })

    # Fallback to existing login logic
    result = login_user(email, password)

    if 'error' in result:
        return jsonify(result), 401

    # Check if user is admin
    if not is_admin(email):
        return jsonify({'error': 'Admin access required'}), 403

    return jsonify(result)


@admin_bp.route('/api/stats')
@admin_required
def get_dashboard_stats():
    """Get dashboard statistics."""
    db = get_db()
    stats = db.get_dashboard_stats()
    return jsonify(stats)


@admin_bp.route('/api/alerts')
@admin_required
def get_alerts():
    """Get crisis alerts."""
    reviewed = request.args.get('reviewed')

    if reviewed is not None:
        reviewed = reviewed.lower() == 'true'

    db = get_db()
    alerts = db.get_all_crisis_flags(reviewed=reviewed)
    return jsonify({'alerts': alerts})


@admin_bp.route('/api/alerts/<flag_id>/review', methods=['POST'])
@admin_required
def review_alert(flag_id):
    """Mark an alert as reviewed."""
    db = get_db()
    db.mark_crisis_reviewed(flag_id)
    return jsonify({'success': True})


@admin_bp.route('/api/patients')
@admin_required
def get_patients():
    """Get all patients."""
    db = get_db()
    patients = db.get_all_users()
    return jsonify({'patients': patients})


@admin_bp.route('/api/patients/<user_id>')
@admin_required
def get_patient_detail(user_id):
    """Get full patient data."""
    db = get_db()
    patient = db.get_user_full_details(user_id)

    if not patient:
        return jsonify({'error': 'Patient not found'}), 404

    # Add distortion pattern for radar chart
    patient['distortion_pattern'] = db.get_user_distortion_pattern(user_id)

    # Add mood history
    patient['mood_history'] = db.get_user_mood_history(user_id)

    # Add wearable summary
    patient['wearable_summary'] = db.get_user_wearable_summary(user_id)

    # Add depression risk statistics (ML-based)
    patient['depression_stats'] = db.get_user_depression_stats(user_id)

    # Add recent depression episodes
    patient['recent_episodes'] = db.get_all_depression_episodes(user_id, limit=10)

    return jsonify(patient)


@admin_bp.route('/api/charts/sessions')
@admin_required
def get_session_chart_data():
    """Get session trend data for chart."""
    days = request.args.get('days', 30, type=int)
    db = get_db()
    data = db.get_daily_session_counts(days)
    return jsonify({'data': data})


@admin_bp.route('/api/charts/distortions')
@admin_required
def get_distortion_chart_data():
    """Get distortion distribution for chart."""
    db = get_db()
    data = db.get_distortion_distribution()
    return jsonify(data)


@admin_bp.route('/api/charts/vitals/<user_id>')
@admin_required
def get_vitals_chart_data(user_id):
    """Get vitals time-series for charts."""
    hours = request.args.get('hours', 24, type=int)
    db = get_db()
    data = db.get_wearable_timeseries(user_id, hours)
    return jsonify({'data': data})


@admin_bp.route('/api/export/all-readings', methods=['GET'])
@admin_required
def export_all_readings():
    """Get every wearable reading from every participant, joined with their
    name/email, for the global Export Readings CSV button on the Patients page."""
    db = get_db()
    readings = db.get_all_wearable_readings()
    return jsonify({'readings': readings})


@admin_bp.route('/api/resolve-episode/<user_id>', methods=['POST'])
@admin_required
def resolve_episode(user_id):
    """Manually clear a patient's active HIGH_STRESS episode, instead of
    waiting for 5 consecutive NORMAL readings to close it automatically.
    Useful for testing/calibration when the episode was opened by a false
    positive before a threshold fix."""
    db = get_db()
    active_episode = db.get_active_depression_episode(user_id)
    if not active_episode:
        return jsonify({'message': 'No active episode to resolve'}), 200
    db.end_depression_episode(active_episode['id'])
    return jsonify({'message': 'Episode resolved', 'episode_id': active_episode['id']})


@admin_bp.route('/api/charts/mood/<user_id>')
@admin_required
def get_mood_chart_data(user_id):
    """Get mood history for charts."""
    limit = request.args.get('limit', 20, type=int)
    db = get_db()
    data = db.get_user_mood_history(user_id, limit)
    return jsonify({'data': data})


@admin_bp.route('/api/charts/ml-predictions/<user_id>')
@admin_required
def get_ml_prediction_chart_data(user_id):
    """Get ML prediction history for charts."""
    limit = request.args.get('limit', 100, type=int)
    db = get_db()
    data = db.get_ml_prediction_history(user_id, limit)
    return jsonify({'data': data})


@admin_bp.route('/api/charts/window-predictions/<user_id>')
@admin_required
def get_window_prediction_chart_data(user_id):
    """Get ML window prediction history for charting."""
    limit = request.args.get('limit', 200, type=int)
    db = get_db()
    data = db.get_window_predictions(user_id, limit)
    return jsonify({'data': data})


@admin_bp.route('/api/depression-episodes/<user_id>')
@admin_required
def get_user_depression_episodes(user_id):
    """Get all depression episodes for a user."""
    limit = request.args.get('limit', 50, type=int)
    db = get_db()
    episodes = db.get_all_depression_episodes(user_id, limit)
    return jsonify({'episodes': episodes, 'count': len(episodes)})



@admin_bp.route('/api/users/<user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    """Delete a user and all their data."""
    db = get_db()
    success = db.delete_user(user_id)
    if success:
        return jsonify({'success': True, 'message': 'User deleted successfully'})
    return jsonify({'error': 'Failed to delete user'}), 500