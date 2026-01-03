import os
import base58
import struct

from fastapi import FastAPI, HTTPException
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.transaction import Transaction
from solders.instruction import Instruction, AccountMeta
from solana.rpc.api import Client

# ======================================================
# App
# ======================================================
app = FastAPI(title="Airdrop Test Backend")

# ======================================================
# Env vars
# ======================================================
SOLANA_RPC = os.getenv("SOLANA_RPC")
TOKEN_MINT = os.getenv("TOKEN_MINT")
AIRDROP_SECRET_B58 = os.getenv("AIRDROP_SECRET_B58")

if not SOLANA_RPC or not TOKEN_MINT or not AIRDROP_SECRET_B58:
    raise RuntimeError("Missing required environment variables")

# ======================================================
# Solana setup
# ======================================================
client = Client(SOLANA_RPC)

MINT_ADDRESS = Pubkey.from_string(TOKEN_MINT)

TOKEN_2022_PROGRAM_ID = Pubkey.from_string(
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
)

ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string(
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
)

airdrop_keypair = Keypair.from_bytes(
    base58.b58decode(AIRDROP_SECRET_B58)
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
# Routes
# ======================================================
@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/airdrop-test")
def airdrop_test(receiver_wallet: str):
    try:
        receiver_pubkey = Pubkey.from_string(receiver_wallet)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid receiver wallet")

    sender_ata = find_ata(AIRDROP_PUBKEY, MINT_ADDRESS)
    receiver_ata = find_ata(receiver_pubkey, MINT_ADDRESS)

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
                    AccountMeta(Pubkey.from_string("11111111111111111111111111111111"), False, False),
                    AccountMeta(TOKEN_2022_PROGRAM_ID, False, False),
                    AccountMeta(Pubkey.from_string("SysvarRent111111111111111111111111111111111"), False, False),
                ],
                data=b""
            )
        )

    # TransferChecked
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

    return {
        "status": "success",
        "receiver": receiver_wallet,
        "tx": sig,
        "explorer": f"https://explorer.solana.com/tx/{sig}"
    }
