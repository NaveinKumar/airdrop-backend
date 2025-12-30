import os
import base64
import json

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware

import firebase_admin
from firebase_admin import credentials, auth, firestore

# =========================
# App
# =========================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # later restrict
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# Firebase Admin Init
# =========================
FIREBASE_KEY_B64 = os.environ.get("FIREBASE_ADMIN_KEY_B64")

if not FIREBASE_KEY_B64:
    raise RuntimeError("Missing FIREBASE_ADMIN_KEY_B64")

key_json = base64.b64decode(FIREBASE_KEY_B64).decode("utf-8")
cred_dict = json.loads(key_json)

cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)

db = firestore.client()

# =========================
# Routes
# =========================
@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/claim")
def claim_airdrop(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing auth token")

    id_token = authorization.replace("Bearer ", "")

    try:
        decoded = auth.verify_id_token(id_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Firebase token")

    uid = decoded["uid"]
    email = decoded.get("email")

    doc_ref = db.collection("airdrops").document(uid)
    doc = doc_ref.get()

    if doc.exists:
        return {
            "status": "already_claimed",
            "email": email
        }

    doc_ref.set({
        "email": email,
        "claimed": True,
        "createdAt": firestore.SERVER_TIMESTAMP
    })

    return {
        "status": "claimed",
        "email": email
    }
