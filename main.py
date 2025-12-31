import os
import json
import base58
import struct

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware

from firebase_admin import credentials, auth, firestore, initialize_app

from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.transaction import Transaction
from solders.instruction import Instruction, AccountMeta
from solana.rpc.api import Client


# ======================================================
# App setup
# ======================================================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ======================================================
# Firebase Admin Init
# ======================================================
FIREBASE_ADMIN_KEY_B64 = os.environ.get("FIREBASE_ADMIN_KEY_B64")
if not FIREBASE_ADMIN_KEY_B64:
    raise RuntimeError("Missing FIREBASE_ADMIN_KEY_B64")

firebase_key_json = base58.b64decode(FIREBASE_ADMIN_KEY_B64).decode("utf-8")
cred_dict = json.loads(firebase_key_json)

cred = credentials.Certificate(cred_dict)
initialize_app(cred)

db = firestore.client()


# ======================================================
# Solana Config
# ======================================================
SOLANA_RPC = os.environ.get("SOLANA_RPC")
TOKEN_MINT = os.environ.get("TOKEN_MINT")
AIRDROP_PRIVATE_KEY_B58 = os.environ.get("AIRDROP_PRIVATE_KEY_B58")

if not SOLANA_RPC or not TOKEN_MINT or not AIRDROP_PRIVATE_KEY_B58:
    raise RuntimeError("Missing Solana environment variables")

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
# Health
# ======================================================
@app.get("/health")
def health():
    return {"status": "ok"}


# ======================================================
# Claim + Airdrop (ONE TIME)
# ======================================================
@app.post("/claim")
def claim_airdrop(authorization: str = Header(None)):
    # -------------------------------
    # 1. Verify Firebase token
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
    # 2. Firestore: one claim per UID
    # -------------------------------
    doc_ref = db.collection("airdrops").document(uid)
    doc = doc_ref.get()

    if doc.exists:
        return {
            "status": "already_claimed",
            "email": email,
            "tx": doc.to_dict().get("tx")
        }

    # -------------------------------
    # 3. Perform Solana airdrop
    # -------------------------------
    try:
        receiver_pubkey = Pubkey.from_string(decoded["wallet"])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid wallet")

    sender_ata = find_ata(AIRDROP_PUBKEY, MINT_ADDRESS)
    receiver_ata = find_ata(receiver_pubkey, MINT_ADDRESS)

    if client.get_account_info(sender_ata).value is None:
        raise HTTPException(status_code=500, detail="Airdrop wallet ATA missing")

    mint_info = client.get_token_supply(MINT_ADDRESS).value
    decimals = mint_info.decimals
    raw_amount = 1 * (10 ** decimals)

    bal = int(client.get_token_account_balance(sender_ata).value.amount)
    if bal < raw_amount:
        raise HTTPException(status_code=400, detail="Airdrop exhausted")

    instructions = []

    if client.get_account_info(receiver_ata).value is None:
        instructions.append(
            Instruction(
                program_id=ASSOCIATED_TOKEN_PROGRAM_ID,
                accounts=[
                    AccountMeta(AIRDROP_PUBKEY, True, True),
                    AccountMeta(receiver_ata, False, True),
                    AccountMeta(receiver_pubkey, False, False),
                    AccountMeta(MINT_ADDRESS, False, False),
                    AccountMeta(Pubkey.from_string("11111111111111111111111111111111"), False, False),
                    AccountMeta(TOKEN_2022_PROGRAM_ID, False, False),
                    AccountMeta(Pubkey.from_string("SysvarRent111111111111111111111111111111111"), False, False),
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

    recent = client.get_latest_blockhash().value.blockhash

    tx = Transaction.new_signed_with_payer(
        instructions=instructions,
        payer=AIRDROP_PUBKEY,
        signing_keypairs=[airdrop_keypair],
        recent_blockhash=recent
    )

    sig = client.send_raw_transaction(bytes(tx)).value

    # -------------------------------
    # 4. Save claim in Firestore
    # -------------------------------
    doc_ref.set({
        "email": email,
        "wallet": decoded["wallet"],
        "tx": sig,
        "claimed": True,
        "createdAt": firestore.SERVER_TIMESTAMP
    })

    return {
        "status": "success",
        "email": email,
        "wallet": decoded["wallet"],
        "tx": sig,
        "explorer": f"https://explorer.solana.com/tx/{sig}"
    }