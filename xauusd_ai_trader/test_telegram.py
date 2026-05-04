"""
Telegram diagnostic script — run this directly to confirm credentials and connectivity.

Usage (from inside the xauusd_ai_trader/ directory):
    python test_telegram.py

What it checks
--------------
1. Whether a .env file exists next to this script
2. The raw values of TELEGRAM_TOKEN and TELEGRAM_CHAT_ID after dotenv loads them
3. Whether the token format looks valid
4. Network reachability of api.telegram.org (plain TCP + HTTPS)
5. getMe() — confirms the token is accepted by Telegram
6. sendMessage() — sends a live test message to TELEGRAM_CHAT_ID
"""

import asyncio
import os
import socket
import sys
import time
from pathlib import Path

# ── 1. Locate and load .env ───────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent
env_path = HERE / ".env"

print("=" * 60)
print("TELEGRAM DIAGNOSTIC")
print("=" * 60)

print(f"\n[1] .env file path : {env_path}")
if env_path.exists():
    print("    Status         : FOUND")
    # Print the raw file lines that mention Telegram (token & chat id only)
    raw_lines = env_path.read_text().splitlines()
    telegram_lines = [l for l in raw_lines if "TELEGRAM" in l.upper()]
    if telegram_lines:
        print("    Telegram lines in .env:")
        for line in telegram_lines:
            print(f"      {line}")
    else:
        print("    WARNING: No TELEGRAM_* lines found in .env")
else:
    print("    Status         : MISSING — create it from .env.template")
    print("    Continuing with environment variables only...\n")

# Load dotenv (safe to call even if file is missing)
try:
    from dotenv import load_dotenv
    loaded = load_dotenv(env_path, override=True)
    print(f"\n    dotenv load_dotenv() returned: {loaded}")
except ImportError:
    print("    WARNING: python-dotenv not installed — reading OS env only")

# ── 2. Read and display credentials ──────────────────────────────────────────
TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

print("\n[2] Loaded values")
if TOKEN:
    # Show first 10 and last 5 chars; mask the middle for security
    visible = TOKEN[:10] + "..." + TOKEN[-5:] if len(TOKEN) > 15 else TOKEN
    print(f"    TELEGRAM_TOKEN    : {visible}  (length={len(TOKEN)})")
else:
    print("    TELEGRAM_TOKEN    : *** EMPTY — not set in .env or environment ***")

if CHAT_ID:
    print(f"    TELEGRAM_CHAT_ID  : {CHAT_ID}")
else:
    print("    TELEGRAM_CHAT_ID  : *** EMPTY — not set in .env or environment ***")

# ── 3. Token format check ─────────────────────────────────────────────────────
print("\n[3] Token format check")
if TOKEN:
    parts = TOKEN.split(":")
    if len(parts) == 2 and parts[0].isdigit() and len(parts[1]) > 20:
        print(f"    Format looks valid  (bot_id={parts[0]}, secret_len={len(parts[1])})")
    else:
        print("    WARNING: Token format looks wrong.")
        print("    Expected format:  123456789:ABCDefghIJKlmNoPQRstuVWXyz")
        print(f"    Got:              {TOKEN[:40]}...")
else:
    print("    Skipped — token is empty")

if not TOKEN or not CHAT_ID:
    print("\nCannot proceed without both TELEGRAM_TOKEN and TELEGRAM_CHAT_ID.")
    print("Add them to xauusd_ai_trader/.env and re-run this script.")
    sys.exit(1)

# ── 4. Network reachability ───────────────────────────────────────────────────
print("\n[4] Network reachability — api.telegram.org:443")
try:
    start = time.monotonic()
    with socket.create_connection(("api.telegram.org", 443), timeout=10) as s:
        latency = (time.monotonic() - start) * 1000
    print(f"    TCP connect OK  ({latency:.0f} ms)")
except OSError as exc:
    print(f"    FAILED: {exc}")
    print("    This VPS may be blocking Telegram — check firewall / DNS.")
    sys.exit(1)

# ── 5. getMe ──────────────────────────────────────────────────────────────────
print("\n[5] Calling getMe() to validate token")
try:
    from telegram import Bot
    from telegram.request import HTTPXRequest
    from telegram.error import InvalidToken, Unauthorized

    request = HTTPXRequest(connect_timeout=20, read_timeout=30, write_timeout=30)
    bot = Bot(token=TOKEN, request=request)

    async def get_me():
        return await bot.get_me()

    me = asyncio.run(get_me())
    print(f"    Token valid!  Bot name: @{me.username}  (id={me.id})")
except (InvalidToken, Unauthorized) as exc:
    print(f"    INVALID TOKEN: {exc}")
    print("    Get a new token from @BotFather on Telegram.")
    sys.exit(1)
except Exception as exc:
    print(f"    getMe() failed: {type(exc).__name__}: {exc}")
    sys.exit(1)

# ── 6. sendMessage ────────────────────────────────────────────────────────────
print(f"\n[6] Sending test message to chat_id={CHAT_ID}")
try:
    async def send_test():
        return await bot.send_message(
            chat_id=CHAT_ID,
            text="✅ <b>XAUUSD AI Trader</b> — Telegram connectivity test passed.",
            parse_mode="HTML",
        )

    msg = asyncio.run(send_test())
    print(f"    Message sent!  message_id={msg.message_id}")
    print(f"    Chat type: {msg.chat.type}  Chat title/name: {getattr(msg.chat, 'title', None) or getattr(msg.chat, 'username', None) or msg.chat.id}")
except Exception as exc:
    print(f"    sendMessage() FAILED: {type(exc).__name__}: {exc}")
    print()
    hint = str(exc).lower()
    if "chat not found" in hint:
        print("    Hint: The bot has never received a message from this chat.")
        print("    → Open Telegram, find your bot, and send it /start first.")
        print("    → For a channel, make sure the bot is added as an Administrator.")
    elif "bot was blocked" in hint:
        print("    Hint: You blocked the bot. Unblock it in Telegram.")
    elif "not enough rights" in hint:
        print("    Hint: The bot lacks permission to post in this chat/channel.")
    sys.exit(1)

print("\n" + "=" * 60)
print("ALL CHECKS PASSED — Telegram is configured correctly.")
print("=" * 60)
