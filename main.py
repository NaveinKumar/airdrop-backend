import os
import json
import base64
import base58
import struct

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from firebase_admin import credentials, initialize_app, firestore, auth

from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.transaction import Transaction
from solders.instruction import Instruction, AccountMeta
from solana.rpc.api import Client

# ======================================================
# App setup
# ======================================================
app = FastAPI(title="Airdrop Backend", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ======================================================
# Environment variables
# ======================================================
FIREBASE_ADMIN_KEY_B64 = os.getenv("FIREBASE_ADMIN_KEY_B64")
SOLANA_RPC = os.getenv("SOLANA_RPC")
TOKEN_MINT = os.getenv("TOKEN_MINT")
AIRDROP_PRIVATE_KEY_B58 = os.getenv("AIRDROP_PRIVATE_KEY_B58")

if not all([
    FIREBASE_ADMIN_KEY_B64,
    SOLANA_RPC,
    TOKEN_MINT,
    AIRDROP_PRIVATE_KEY_B58
]):
    raise RuntimeError("Missing required environment variables")

# ======================================================
# Firebase Admin Init
# ======================================================
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

# ======================================================
# Solana setup
# ======================================================
client = Client(SOLANA_RPC)

TOKEN_2022_PROGRAM_ID = Pubkey.from_string(
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
)

ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string(
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
)

MINT_ADDRESS = Pubkey.from_string(TOKEN_MINT)

airdrop_keypair = Keypair.from_bytes(
    base58.b58decode(AIRDROP_PRIVATE_KEY_B58)
)
AIRDROP_PUBKEY = airdrop_keypair.pubkey()

# ======================================================
# Helpers
# ======================================================
def find_ata(owner: Pubkey, mint: Pubkey) -> Pubkey:
    return Pubkey.find_program_address(
        [bytes(owner), bytes(TOKEN_2022_PROGRAM_ID), bytes(mint)],
        ASSOCIATED_TOKEN_PROGRAM_ID
    )[0]

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
    return {"status": "ok"}

@app.post("/claim")
def claim_airdrop(
    data: ClaimRequest,
    authorization: str = Header(None)
):
    # -------------------------------
    # 1. Verify Firebase ID token
    # -------------------------------
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing auth token")

    id_token = authorization.replace("Bearer ", "")

    try:
        decoded = auth.verify_id_token(id_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Firebase token")

    uid = decoded["uid"]
    email = decoded.get("email", "")

    # -------------------------------
    # 2. Enforce one-claim-per-user
    # -------------------------------
    doc_ref = db.collection("airdrops").document(uid)
    doc = doc_ref.get()

    if doc.exists:
        return {
            "status": "already_claimed",
            "tx": doc.to_dict().get("tx")
        }

    # -------------------------------
    # 3. Validate wallet
    # -------------------------------
    try:
        receiver_pubkey = Pubkey.from_string(data.wallet)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid wallet address")

    sender_ata = find_ata(AIRDROP_PUBKEY, MINT_ADDRESS)
    receiver_ata = find_ata(receiver_pubkey, MINT_ADDRESS)

    # -------------------------------
    # 4. Prepare token transfer
    # -------------------------------
    mint_info = client.get_token_supply(MINT_ADDRESS).value
    decimals = mint_info.decimals
    raw_amount = 1 * (10 ** decimals)

    instructions = []

    # Create ATA if missing
    if client.get_account_info(receiver_ata).value is None:
        instructions.append(
            Instruction(
                program_id=ASSOCIATED_TOKEN_PROGRAM_ID,
                accounts=[
                    AccountMeta(AIRDROP_PUBKEY, True, True),
                    AccountMeta(receiver_ata, False, True),
                    AccountMeta(receiver_pubkey, False, False),
                    AccountMeta(MINT_ADDRESS, False, False),
                    AccountMeta(
                        Pubkey.from_string("11111111111111111111111111111111"),
                        False, False
                    ),
                    AccountMeta(TOKEN_2022_PROGRAM_ID, False, False),
                    AccountMeta(
                        Pubkey.from_string(
                            "SysvarRent111111111111111111111111111111111"
                        ),
                        False, False
                    ),
                ],
                data=b""
            )
        )

    instructions.append(
        Instruction(
            program_id=TOKEN_2022_PROGRAM_ID,
            accounts=[
                AccountMeta(sender_ata, False, True),
                AccountMeta(MINT_ADDRESS, False, False),
                AccountMeta(receiver_ata, False, True),
                AccountMeta(AIRDROP_PUBKEY, True, False),
            ],
            data=struct.pack("<BQB", 12, raw_amount, decimals)
        )
    )

    # -------------------------------
    # 5. Send transaction
    # -------------------------------
    recent = client.get_latest_blockhash().value.blockhash

    tx = Transaction.new_signed_with_payer(
        instructions=instructions,
        payer=AIRDROP_PUBKEY,
        signing_keypairs=[airdrop_keypair],
        recent_blockhash=recent
    )

    sig = client.send_raw_transaction(bytes(tx)).value

    # -------------------------------
    # 6. Save claim
    # -------------------------------
    doc_ref.set({
        "uid": uid,
        "email": email,
        "wallet": data.wallet,
        "tx": sig,
        "claimed": True,
        "createdAt": firestore.SERVER_TIMESTAMP
    })

    return {
        "status": "success",
        "wallet": data.wallet,
        "tx": sig,
        "explorer": f"https://explorer.solana.com/tx/{sig}"
    }
