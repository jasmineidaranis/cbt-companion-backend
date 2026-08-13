# Gunicorn Configuration for Hugging Face Spaces

import multiprocessing
import os

# Worker Configuration
workers = int(os.getenv("GUNICORN_WORKERS", 2))  # Use 2 workers for HF
worker_class = "sync"
worker_connections = 1000

# Timeout Configuration - CRITICAL for preventing worker kills
timeout = 180  # 3 minutes - gives Groq API calls time to complete
graceful_timeout = 30
keepalive = 5

# Memory Management
max_requests = 100  # Restart workers after 100 requests to prevent memory leaks
max_requests_jitter = 20  # Add randomness to prevent all workers restarting at once

# Binding
bind = "0.0.0.0:7860"

# Logging
accesslog = "-"  # Log to stdout
errorlog = "-"   # Log to stderr
loglevel = "info"

# Process Naming
proc_name = "cbt_companion"

# Server Mechanics
daemon = False
pidfile = None
user = None
group = None
tmp_upload_dir = None

# Preload app for faster worker spawning (but uses more memory)
# Set to False if having memory issues
preload_app = False  # Keep False for HF to reduce memory

print(f"""
===== Gunicorn Configuration =====
Workers: {workers}
Timeout: {timeout}s
Max Requests: {max_requests}
Preload App: {preload_app}
==================================
""")
