import os
import json
import base64

from fastapi import FastAPI
from firebase_admin import credentials, initialize_app, firestore

# ======================================================
# App setup
# ======================================================
app = FastAPI()

# ======================================================
# Firebase Admin Init (minimal)
# ======================================================
FIREBASE_ADMIN_KEY_B64 = os.getenv("FIREBASE_ADMIN_KEY_B64")

if not FIREBASE_ADMIN_KEY_B64:
    raise RuntimeError("Missing FIREBASE_ADMIN_KEY_B64")

try:
    firebase_key_json = base64.b64decode(FIREBASE_ADMIN_KEY_B64).decode("utf-8")
    cred_dict = json.loads(firebase_key_json)
except Exception as e:
    raise RuntimeError(f"Invalid FIREBASE_ADMIN_KEY_B64: {e}")

cred = credentials.Certificate(cred_dict)
initialize_app(cred)

db = firestore.client()

print("✅ Firebase Admin initialized successfully")

# ======================================================
# Routes
# ======================================================
@app.get("/health")
def health():
    return {
        "status": "ok",
        "firebase": "connected"
    }

@app.get("/env-check")
def env_check():
    return {
        "firebase_key_present": True,
        "project_id": cred_dict.get("project_id")
    }


print("KEY LENGTH:", len(FIREBASE_ADMIN_KEY_B64))
print("KEY HEAD:", FIREBASE_ADMIN_KEY_B64[:30])
print("KEY TAIL:", FIREBASE_ADMIN_KEY_B64[-30:])
