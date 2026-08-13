---
title: CBT Companion API
emoji: 💙
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
---

# CBT Companion — Backend API

Flask backend for the Tikvah CBT Companion app. Powered by Groq LLaMA 3.3 70B, Turso (libSQL) database, and a 3-agent Beck's Cognitive Restructuring protocol.

> **Live deployment:** [HuggingFace Space](https://huggingface.co/spaces/santa47/cbt-companion-api)

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.10+ | Runtime |
| pip | latest | Package manager |
| [Groq account](https://console.groq.com) | — | LLM inference (free tier available) |
| [Turso account](https://turso.tech) | — | Cloud database (free tier available) |
| [Turso CLI](https://docs.turso.tech/cli/introduction) | latest | Database setup |
| Firebase project | — | Push notifications (optional) |

---

## Running Locally — Step by Step

### Step 1 — Clone the repo

```bash
git clone https://github.com/stanlee47/cbt-companion-backend.git
cd cbt-companion-backend
```

---

### Step 2 — Create and activate a virtual environment

```bash
python -m venv venv
```

```bash
# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

---

### Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

> This installs Flask, Groq SDK, Turso client, PyTorch (for ML inference), and Firebase Admin SDK. May take a few minutes.

---

### Step 4 — Set up Turso database

If you don't have a Turso database yet:

```bash
# Install Turso CLI
curl -sSfL https://get.tur.so/install.sh | bash   # macOS/Linux
# Windows: see https://docs.turso.tech/cli/introduction

# Login
turso auth login

# Create a database
turso db create cbt-companion

# Get your credentials
turso db show cbt-companion        # copy the URL
turso db tokens create cbt-companion   # copy the token
```

> You'll use these in the `.env` file below.

---

### Step 5 — Get a Groq API key

1. Go to [console.groq.com](https://console.groq.com)
2. Sign up / log in
3. Navigate to **API Keys** → **Create API Key**
4. Copy the key

---

### Step 6 — Create the `.env` file

Create a file named `.env` in the project root:

```env
GROQ_API_KEY=your_groq_api_key_here
TURSO_DATABASE_URL=libsql://your-db-name.turso.io
TURSO_AUTH_TOKEN=your_turso_auth_token_here
JWT_SECRET=any_long_random_string_here
```

> **Never commit this file.** It is already excluded by `.gitignore`.

#### Optional — Firebase push notifications

If you want stress alert push notifications:

1. Go to [Firebase Console](https://console.firebase.google.com) → your project → **Project Settings → Service Accounts**
2. Click **Generate new private key** → save as `firebase-service-account.json` in the project root
3. Add to `.env`:
   ```env
   FIREBASE_SERVICE_ACCOUNT=firebase-service-account.json
   ```

---

### Step 7 — Run the server

```bash
python app.py
```

You should see:

```
✅ Database connected to Turso
 * Running on http://127.0.0.1:5000
```

> **Database tables are created automatically** on first run — no migration script needed.

---

### Step 8 — Verify it's working

```bash
curl http://localhost:5000/health
```

Expected response:

```json
{ "status": "ok" }
```

You can now point the Flutter app to `http://10.0.2.2:5000` (Android emulator) or `http://localhost:5000` (iOS simulator).

---

## Run with Docker (Alternative)

```bash
docker build -t cbt-companion-api .
docker run -p 5000:7860 --env-file .env cbt-companion-api
```

The server will be available at `http://localhost:5000`.

---

## API Endpoints

All endpoints except `/api/register`, `/api/login`, `/api/resources`, and `/health` require:

```
Authorization: Bearer <jwt_token>
```

### Auth
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/register` | Register a new user |
| POST | `/api/login` | Login, returns JWT token |
| GET | `/api/me` | Get current user info |

### Sessions
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/session/new` | Start a new CBT session |
| GET | `/api/session/status` | Get session state & protocol stage |
| GET | `/api/sessions` | Get user's past sessions |
| GET | `/api/session/quality` | Get CTS-R quality score for a session |

### Chat
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/chat` | Send a message, receive AI response |

### Exercises & Homework
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/exercise` | Get CBT exercise for current session |
| POST | `/api/exercise/complete` | Mark exercise as completed |
| GET | `/api/homework` | Get adaptive homework assignment |
| POST | `/api/homework/complete` | Mark homework as completed |

### Insights
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/stats` | Get user statistics |
| GET | `/api/beliefs/trajectory` | Get belief change over sessions |
| GET | `/api/ccd` | Get Cognitive Conceptualization Diagram |

### Wearable
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/wearable/data` | Post sensor data (GSR, PPG, motion) |
| POST | `/api/wearable/batch` | Post batch sensor readings |
| GET | `/api/wearable/status` | Get latest stress detection result |

### Admin
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/admin` | Admin dashboard (crisis alerts, analytics) |

### Misc
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/resources` | Get crisis resources (public, no auth) |
| GET | `/health` | Health check |

---

## Project Structure

```
backend/
├── app.py                  # Main Flask app & all routes
├── auth.py                 # JWT authentication helpers
├── database.py             # All Turso DB operations (auto-creates tables)
├── groq_client.py          # 3-agent Beck protocol (Groq LLaMA 3.3 70B)
├── beck_agents.py          # Individual agent logic
├── prompts.py              # Beck protocol state machine (20 states)
├── context_builder.py      # CCD generation & session context
├── belief_tracker.py       # Belief trajectory tracking
├── exercises.py            # Adaptive homework by distortion type
├── ml_inference.py         # TCN-AE stress detection model
├── wearable.py             # Wearable sensor API routes
├── crisis_detector.py      # Crisis keyword detection
├── severity_router.py      # Session severity routing
├── patient_tracker.py      # Patient profile management
├── admin.py                # Admin panel routes
├── fcm_push.py             # Firebase push notifications
├── bdi_scorer.py           # Beck Depression Inventory scoring
├── full_protocol.py        # Full protocol orchestration
├── models/                 # ML model checkpoints (.pth.zip)
├── templates/              # Admin panel HTML templates
├── static/                 # Admin panel static assets
├── requirements.txt
├── Dockerfile
└── gunicorn.conf.py        # Gunicorn config (used in production/Docker)
```

---

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `GROQ_API_KEY` | Yes | Groq API key for LLaMA 3.3 70B |
| `TURSO_DATABASE_URL` | Yes | Turso libSQL database URL (`libsql://...`) |
| `TURSO_AUTH_TOKEN` | Yes | Turso auth token |
| `JWT_SECRET` | Yes | Secret string for signing JWT tokens |
| `FIREBASE_SERVICE_ACCOUNT` | No | Path to Firebase service account JSON file |

---

## Deploying to HuggingFace Spaces

```bash
git remote add hf https://huggingface.co/spaces/santa47/cbt-companion-api
git push hf main
```

Set all environment variables above in the Space's **Settings → Variables and secrets** tab — do **not** push your `.env` file.
