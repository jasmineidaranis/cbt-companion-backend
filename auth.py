"""
Authentication Module
Handles user registration, login, and JWT token management
"""

import os
import jwt
import hashlib
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify
from database import get_db


# JWT Configuration
JWT_SECRET = os.environ.get("JWT_SECRET", "your-secret-key-change-in-production")
JWT_EXPIRY_HOURS = 24 * 7  # 7 days

# Admin Configuration
# Comma-separated list of admin emails
ADMIN_EMAILS = [
    email.strip().lower()
    for email in os.environ.get("ADMIN_EMAILS", "").split(",")
    if email.strip()
]


def hash_password(password: str) -> str:
    """Hash password using SHA-256."""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against hash."""
    return hash_password(password) == password_hash


def generate_token(user_id: str, email: str) -> str:
    """Generate JWT token for user."""
    payload = {
        "user_id": user_id,
        "email": email,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decode_token(token: str) -> dict:
    """Decode and verify JWT token."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def token_required(f):
    """Decorator to require valid JWT token."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # Get token from header
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
        
        if not token:
            return jsonify({"error": "Token is missing"}), 401
        
        # Decode token
        payload = decode_token(token)
        if not payload:
            return jsonify({"error": "Token is invalid or expired"}), 401
        
        # Get user from database
        db = get_db()
        user = db.get_user_by_id(payload["user_id"])
        if not user:
            return jsonify({"error": "User not found"}), 401
        
        # Add user to request context
        request.current_user = user
        
        return f(*args, **kwargs)
    
    return decorated


def register_user(email: str, password: str, name: str, context: str = "person") -> dict:
    """
    Register a new user.
    
    Returns:
        dict with user info and token, or error
    """
    # Validate input
    if not email or not password or not name:
        return {"error": "Email, password, and name are required"}
    
    if len(password) < 6:
        return {"error": "Password must be at least 6 characters"}
    
    if "@" not in email:
        return {"error": "Invalid email format"}
    
    # Hash password and create user
    db = get_db()
    password_hash = hash_password(password)
    
    try:
        user = db.create_user(email, password_hash, name, context)
        token = generate_token(user["id"], user["email"])
        
        return {
            "success": True,
            "user": {
                "id": user["id"],
                "email": user["email"],
                "name": user["name"],
                "context": user["context"]
            },
            "token": token
        }
    
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        print(f"Registration error: {e}")
        return {"error": "Registration failed"}


def login_user(email: str, password: str) -> dict:
    """
    Login a user.

    Returns:
        dict with user info and token, or error
    """
    if not email or not password:
        return {"error": "Email and password are required"}

    db = get_db()
    user = db.get_user_by_email(email)

    if not user:
        return {"error": "Invalid email or password"}

    if not verify_password(password, user["password_hash"]):
        return {"error": "Invalid email or password"}

    token = generate_token(user["id"], user["email"])

    return {
        "success": True,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
            "context": user["context"]
        },
        "token": token
    }


def is_admin(email: str) -> bool:
    """Check if an email is in the admin list."""
    return email.lower() in ADMIN_EMAILS


def admin_required(f):
    """Decorator to require valid JWT token AND admin privileges."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None

        # Get token from header
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]

        if not token:
            return jsonify({"error": "Token is missing"}), 401

        # Decode token
        payload = decode_token(token)
        if not payload:
            return jsonify({"error": "Token is invalid or expired"}), 401

        # Check for hardcoded admin user
        if payload.get("user_id") == "admin" and payload.get("email") == "admin123":
            request.current_user = {
                "id": "admin",
                "email": "admin123",
                "name": "Admin",
                "context": "admin"
            }
            return f(*args, **kwargs)

        # Get user from database
        db = get_db()
        user = db.get_user_by_id(payload["user_id"])
        if not user:
            return jsonify({"error": "User not found"}), 401

        # Check if user is admin
        if not is_admin(user["email"]):
            return jsonify({"error": "Admin access required"}), 403

        # Add user to request context
        request.current_user = user

        return f(*args, **kwargs)

    return decorated
