import os
import json
import base64

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from firebase_admin import credentials, initialize_app, firestore

# ======================================================
# App setup
# ======================================================
app = FastAPI(title="Airdrop Backend", version="1.0.0")

# CORS (required for Firebase frontend + browser)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ======================================================
# Firebase Admin Init
# ======================================================
FIREBASE_ADMIN_KEY_B64 = os.getenv("FIREBASE_ADMIN_KEY_B64")

if not FIREBASE_ADMIN_KEY_B64:
    raise RuntimeError("Missing FIREBASE_ADMIN_KEY_B64")

try:
    firebase_key_json = base64.b64decode(
        FIREBASE_ADMIN_KEY_B64
    ).decode("utf-8")
    cred_dict = json.loads(firebase_key_json)
except Exception as e:
    raise RuntimeError(f"Invalid FIREBASE_ADMIN_KEY_B64: {e}")

cred = credentials.Certificate(cred_dict)
initialize_app(cred)

db = firestore.client()

print("✅ Firebase Admin initialized")
print("Project ID:", cred_dict.get("project_id"))

# ======================================================
# Models
# ======================================================
class ClaimRequest(BaseModel):
    wallet: str

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

@app.post("/claim")
def claim_airdrop(data: ClaimRequest):
    """
    TEMPORARY stub endpoint.
    This lets you test POST /claim from /docs.
    """

    if not data.wallet:
        raise HTTPException(status_code=400, detail="Wallet missing")

    # Example Firestore write (safe test)
    doc_ref = db.collection("claims").document(data.wallet)
    doc_ref.set({
        "wallet": data.wallet,
        "claimed": True
    })

    return {
        "status": "success",
        "wallet": data.wallet
    }
