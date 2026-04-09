"""
=============================================================
  AI Super Assistant — Telegram Bot
  Primary  : Groq (fast, free, stable)
  Fallback : OpenRouter (11 free models)
  Files    : PDF, Images, Word (.docx), Text
  Images   : Google Gemini 2.0 Flash (free)
  Access   : Password-protected persistent whitelist
  100% free — no paid APIs needed
=============================================================

REQUIREMENTS:
    pip install python-telegram-bot requests pymupdf python-docx pillow pytesseract

FOR IMAGE OCR — install Tesseract:
    Windows : https://github.com/UB-Mannheim/tesseract/wiki
    Linux   : sudo apt install tesseract-ocr tesseract-ocr-nld tesseract-ocr-fra
    Mac     : brew install tesseract

HOW TO GET YOUR FREE API KEYS:
    Groq        : https://console.groq.com       (free, no credit card)
    OpenRouter  : https://openrouter.ai          (free tier available)
    Gemini      : https://aistudio.google.com    (free)

HOW TO RUN LOCALLY:
    1. Set environment variables:
         TELEGRAM_TOKEN, GROQ_KEY, OPENROUTER_KEY, GEMINI_KEY, BOT_PASSWORD
       OR fill in the fallback strings below directly.
    2. Add your own Telegram user ID to ADMIN_IDS so you never need the password.
       (Find your ID by messaging @userinfobot on Telegram)
    3. Run: python plc_bot.py

ACCESS SYSTEM:
    - New users must send /unlock <password> to gain access
    - Approved users are saved to whitelist.json and persist across restarts
    - Admins listed in ADMIN_IDS are always allowed without a password

TELEGRAM COMMANDS:
    /unlock <password> — unlock the bot with the secret password
    /image <description> — generate an image with Gemini
    /files  — show loaded files
    /status — check which AI models are online
    /reset  — clear files and conversation
    /help   — show all commands
=============================================================
"""

import os
import io
import json
import time
import logging
import requests

from telegram import Update
from telegram.ext import (
    ApplicationBuilder, MessageHandler,
    CommandHandler, filters, ContextTypes
)

try:
    import fitz
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
    print("WARNING: PyMuPDF not installed. Run: pip install pymupdf")

try:
    from docx import Document as DocxDocument
    DOCX_SUPPORT = True
except ImportError:
    DOCX_SUPPORT = False
    print("WARNING: python-docx not installed. Run: pip install python-docx")

try:
    from PIL import Image
    import pytesseract
    IMAGE_SUPPORT = True
except ImportError:
    IMAGE_SUPPORT = False
    print("WARNING: Pillow/pytesseract not installed. Run: pip install pillow pytesseract")


# ─────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_TELEGRAM_TOKEN_HERE")
GROQ_KEY       = os.environ.get("GROQ_KEY",       "YOUR_GROQ_KEY_HERE")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "YOUR_OPENROUTER_KEY_HERE")
GEMINI_KEY     = os.environ.get("GEMINI_KEY",     "YOUR_GEMINI_KEY_HERE")

# ── Access control ────────────────────────────────────────────────────────────
# The password users must send via /unlock to gain access.
BOT_PASSWORD = os.environ.get("BOT_PASSWORD", "YOUR_SECRET_PASSWORD_HERE")

# Your own Telegram user ID(s) — always allowed, no password needed.
# Find your ID by messaging @userinfobot on Telegram.
ADMIN_IDS: set[int] = {
    123456789,   # ← replace with your real Telegram user ID
}

# File where approved user IDs are saved so they survive bot restarts.
WHITELIST_FILE = "whitelist.json"

# ── Groq (primary — fast LPU inference, free tier) ──────────────────────────
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

GROQ_MODELS = [
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "llama-3.3-70b-versatile",
    "llama3-70b-8192",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
]

# ── OpenRouter (fallback — 11 free models) ───────────────────────────────────
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

OPENROUTER_MODELS = [
    "meta-llama/llama-4-maverick:free",
    "deepseek/deepseek-chat-v3-0324:free",
    "nvidia/llama-3.1-nemotron-ultra-253b-v1:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
    "meta-llama/llama-4-scout:free",
    "qwen/qwen3-235b-a22b:free",
    "google/gemma-3-27b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "microsoft/phi-4:free",
    "google/gemma-3-12b-it:free",
    "mistralai/mistral-7b-instruct:free",
]

MAX_FILE_CHARS   = 12000
MAX_CONTEXT_DOCS = 5
MAX_HISTORY_MSGS = 10

SYSTEM_PROMPT = """Industrial Electrician AI Assistant (Telegram Bot)
ROLE
You are a specialized industrial electrician AI assistant built for a Telegram bot.
Your job is to:
* Provide accurate electrical knowledge
* Help troubleshoot real-world problems
* Explain PLC programming, wiring diagrams, and electrical schematics
* Answer questions about files and documents the user shares

Stay focused. Be precise. Be structured."""


# ─────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  WHITELIST — load / save / check
# ─────────────────────────────────────────────

def _load_whitelist() -> set[int]:
    """Load approved user IDs from disk. Returns empty set if file doesn't exist."""
    try:
        with open(WHITELIST_FILE, "r") as f:
            data = json.load(f)
            return set(int(uid) for uid in data)
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return set()

def _save_whitelist(whitelist: set[int]) -> None:
    """Persist approved user IDs to disk."""
    try:
        with open(WHITELIST_FILE, "w") as f:
            json.dump(list(whitelist), f)
    except Exception as e:
        logger.error(f"Failed to save whitelist: {e}")

# In-memory whitelist — loaded once at startup, updated on unlock
approved_users: set[int] = _load_whitelist()

def is_allowed(user_id: int) -> bool:
    """Return True if user is an admin or has been approved via password."""
    return user_id in ADMIN_IDS or user_id in approved_users

def approve_user(user_id: int) -> None:
    """Add user to the approved set and persist to disk."""
    approved_users.add(user_id)
    _save_whitelist(approved_users)
    logger.info(f"User {user_id} approved and saved to whitelist")


# ─────────────────────────────────────────────
#  USER SESSIONS
# ─────────────────────────────────────────────

user_sessions: dict = {}

def get_session(user_id: int) -> dict:
    if user_id not in user_sessions:
        user_sessions[user_id] = {"history": [], "documents": []}
    return user_sessions[user_id]

def build_document_context(session: dict) -> str:
    if not session["documents"]:
        return ""
    parts = ["=== FILES THE USER SHARED ===\n"]
    for i, doc in enumerate(session["documents"], 1):
        parts.append(f"--- File {i}: {doc['name']} ---\n{doc['content']}\n")
    parts.append("=== END OF FILES ===")
    return "\n".join(parts)


# ─────────────────────────────────────────────
#  FILE EXTRACTION
# ─────────────────────────────────────────────

def extract_pdf(file_bytes: bytes) -> str:
    if not PDF_SUPPORT:
        return "[PDF support not available — install pymupdf]"
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        pages = []
        for num, page in enumerate(doc, 1):
            text = page.get_text().strip()
            if text:
                pages.append(f"[Page {num}]\n{text}")
        doc.close()
        result = "\n\n".join(pages)
        return result if result.strip() else "[PDF is image-only — no text found]"
    except Exception as e:
        return f"[Error reading PDF: {e}]"

def extract_docx(file_bytes: bytes) -> str:
    if not DOCX_SUPPORT:
        return "[Word support not available — install python-docx]"
    try:
        doc = DocxDocument(io.BytesIO(file_bytes))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs)
    except Exception as e:
        return f"[Error reading Word file: {e}]"

def extract_image(file_bytes: bytes) -> str:
    if not IMAGE_SUPPORT:
        return "[Image OCR not available — install pillow and pytesseract]"
    try:
        image = Image.open(io.BytesIO(file_bytes))
        text = pytesseract.image_to_string(image, lang="nld+fra+eng")
        if text.strip():
            return f"[Text extracted from image via OCR]\n{text.strip()}"
        return "[Image received — no readable text found. You can still ask me questions about it.]"
    except Exception as e:
        return f"[Error reading image: {e}]"

def extract_text(file_bytes: bytes) -> str:
    try:
        return file_bytes.decode("utf-8", errors="replace")
    except Exception as e:
        return f"[Error reading file: {e}]"

def extract_file(file_bytes: bytes, filename: str) -> str:
    ext = os.path.splitext(filename.lower())[1]
    if ext == ".pdf":
        content = extract_pdf(file_bytes)
    elif ext in (".docx", ".doc"):
        content = extract_docx(file_bytes)
    elif ext in (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp"):
        content = extract_image(file_bytes)
    else:
        content = extract_text(file_bytes)
    if len(content) > MAX_FILE_CHARS:
        content = content[:MAX_FILE_CHARS] + f"\n\n[... truncated at {MAX_FILE_CHARS} characters ...]"
    return content


# ─────────────────────────────────────────────
#  RESPONSE VALIDATION
# ─────────────────────────────────────────────

def _is_valid_response(data: dict) -> tuple:
    if data.get("error"):
        logger.warning(f"API error in response body: {data['error']}")
        return False, ""
    choices = data.get("choices", [])
    if not choices:
        return False, ""
    text = choices[0].get("message", {}).get("content", "").strip()
    if not text:
        return False, ""
    text_lower = text.lower()
    error_prefixes = ("error:", "i'm sorry, i cannot", "model is currently unavailable")
    if any(text_lower.startswith(p) for p in error_prefixes):
        logger.warning(f"Model returned error-like content: {text[:80]}")
        return False, ""
    return True, text


# ─────────────────────────────────────────────
#  GROQ PROVIDER
# ─────────────────────────────────────────────

def _try_groq(messages: list) -> str | None:
    if GROQ_KEY == "YOUR_GROQ_KEY_HERE":
        logger.info("Groq key not set — skipping Groq")
        return None
    headers = {
        "Authorization": f"Bearer {GROQ_KEY}",
        "Content-Type": "application/json",
    }
    for model in GROQ_MODELS:
        try:
            logger.info(f"[Groq] Trying: {model}")
            resp = requests.post(
                GROQ_URL,
                headers=headers,
                json={"model": model, "messages": messages, "stream": False},
                timeout=30,
            )
            if resp.status_code == 429:
                time.sleep(1)
                continue
            if resp.status_code >= 400:
                continue
            valid, text = _is_valid_response(resp.json())
            if valid:
                logger.info(f"[Groq] Success with: {model}")
                return text
        except requests.exceptions.Timeout:
            logger.warning(f"[Groq] {model} → timeout")
        except Exception as e:
            logger.warning(f"[Groq] {model} → {e}")
    logger.warning("[Groq] All models failed")
    return None


# ─────────────────────────────────────────────
#  OPENROUTER PROVIDER (fallback)
# ─────────────────────────────────────────────

def _try_openrouter(messages: list) -> str | None:
    if OPENROUTER_KEY == "YOUR_OPENROUTER_KEY_HERE":
        logger.info("OpenRouter key not set — skipping")
        return None
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
    }
    for attempt in range(2):
        if attempt == 1:
            logger.info("[OpenRouter] Pass 1 failed — waiting 8s before retry...")
            time.sleep(8)
        for model in OPENROUTER_MODELS:
            try:
                logger.info(f"[OpenRouter] Trying: {model}")
                resp = requests.post(
                    OPENROUTER_URL,
                    headers=headers,
                    json={"model": model, "messages": messages, "stream": False},
                    timeout=60,
                )
                if resp.status_code == 429:
                    time.sleep(1)
                    continue
                if resp.status_code in (503,) or resp.status_code >= 400:
                    continue
                valid, text = _is_valid_response(resp.json())
                if valid:
                    logger.info(f"[OpenRouter] Success with: {model}")
                    return text
            except requests.exceptions.Timeout:
                logger.warning(f"[OpenRouter] {model} → timeout")
            except Exception as e:
                logger.warning(f"[OpenRouter] {model} → {e}")
    logger.warning("[OpenRouter] All models failed")
    return None


# ─────────────────────────────────────────────
#  ASK AI — Groq first, OpenRouter fallback
# ─────────────────────────────────────────────

def ask_ai(session: dict, user_message: str) -> str:
    doc_context = build_document_context(session)
    system_content = SYSTEM_PROMPT
    if doc_context:
        system_content += f"\n\n{doc_context}"
    messages = [{"role": "system", "content": system_content}]
    messages += session["history"]
    messages.append({"role": "user", "content": user_message})

    result = _try_groq(messages)
    if result:
        return result

    logger.info("Groq unavailable — falling back to OpenRouter...")
    result = _try_openrouter(messages)
    if result:
        return result

    return (
        "⚠️ All AI providers are currently busy or unavailable.\n"
        "This usually resolves within a minute — please try again shortly!\n\n"
        "Tip: Use /status to check which models are online."
    )


# ─────────────────────────────────────────────
#  IMAGE GENERATION — Gemini 2.0 Flash (FREE)
# ─────────────────────────────────────────────

def generate_image(prompt: str) -> tuple:
    if GEMINI_KEY == "YOUR_GEMINI_KEY_HERE":
        return None, "Gemini key not set. Get a free key at aistudio.google.com and set GEMINI_KEY."
    try:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.0-flash-exp:generateContent?key={GEMINI_KEY}"
        )
        payload = {
            "contents": [{"parts": [{"text": f"Generate an image of: {prompt}"}]}],
            "generationConfig": {"responseModalities": ["image", "text"]},
        }
        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        for part in data.get("candidates", [{}])[0].get("content", {}).get("parts", []):
            if part.get("inlineData"):
                import base64
                img_bytes = base64.b64decode(part["inlineData"]["data"])
                return img_bytes, prompt
        return None, "No image returned by Gemini. Try a different prompt."
    except requests.exceptions.Timeout:
        return None, "Gemini timed out. Try again."
    except Exception as e:
        return None, f"Image generation failed: {e}"


# ─────────────────────────────────────────────
#  /status — probe models from both providers
# ─────────────────────────────────────────────

def check_model_status() -> list:
    probe = [{"role": "user", "content": "Reply with one word: OK"}]
    results = []

    if GROQ_KEY != "YOUR_GROQ_KEY_HERE":
        groq_headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
        for model in GROQ_MODELS[:3]:
            label = f"[Groq] {model.split('/')[-1]}"
            try:
                t0 = time.time()
                resp = requests.post(
                    GROQ_URL, headers=groq_headers,
                    json={"model": model, "messages": probe, "stream": False, "max_tokens": 5},
                    timeout=10,
                )
                latency = int((time.time() - t0) * 1000)
                if resp.status_code == 200:
                    valid, _ = _is_valid_response(resp.json())
                    results.append((label, "✅" if valid else "⚠️", latency))
                elif resp.status_code == 429:
                    results.append((label, "🔴 rate-limited", 0))
                else:
                    results.append((label, f"🔴 HTTP {resp.status_code}", 0))
            except requests.exceptions.Timeout:
                results.append((label, "🔴 timeout", 0))
            except Exception:
                results.append((label, "🔴 error", 0))
    else:
        results.append(("[Groq]", "⚙️ key not set", 0))

    if OPENROUTER_KEY != "YOUR_OPENROUTER_KEY_HERE":
        or_headers = {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"}
        for model in OPENROUTER_MODELS[:3]:
            label = f"[OR] {model.split('/')[-1].replace(':free', '')}"
            try:
                t0 = time.time()
                resp = requests.post(
                    OPENROUTER_URL, headers=or_headers,
                    json={"model": model, "messages": probe, "stream": False, "max_tokens": 5},
                    timeout=15,
                )
                latency = int((time.time() - t0) * 1000)
                if resp.status_code == 200:
                    valid, _ = _is_valid_response(resp.json())
                    results.append((label, "✅" if valid else "⚠️", latency))
                elif resp.status_code == 429:
                    results.append((label, "🔴 rate-limited", 0))
                elif resp.status_code == 503:
                    results.append((label, "🔴 overloaded", 0))
                else:
                    results.append((label, f"🔴 HTTP {resp.status_code}", 0))
            except requests.exceptions.Timeout:
                results.append((label, "🔴 timeout", 0))
            except Exception:
                results.append((label, "🔴 error", 0))
    else:
        results.append(("[OpenRouter]", "⚙️ key not set", 0))

    return results


# ─────────────────────────────────────────────
#  TELEGRAM COMMANDS
# ─────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    name    = update.effective_user.first_name

    if is_allowed(user_id):
        await update.message.reply_text(
            f"Hey {name}! I am your AI assistant. ✅\n\n"
            "Send me any file (PDF, Word, image, text...) and ask questions about it!\n\n"
            "Commands:\n"
            "/image <description> — generate an image\n"
            "/files  — see loaded files\n"
            "/status — check which AI models are online\n"
            "/reset  — clear everything\n"
            "/help   — show this message",
        )
    else:
        await update.message.reply_text(
            f"Hey {name}! This bot is password-protected. 🔒\n\n"
            "Send /unlock <password> to get access.\n"
            "Example: /unlock mysecretword"
        )

async def cmd_unlock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /unlock <password> — approve user if password matches."""
    user_id = update.effective_user.id
    name    = update.effective_user.first_name

    # Already approved
    if is_allowed(user_id):
        await update.message.reply_text("You already have access! ✅")
        return

    # Check password
    provided = " ".join(context.args).strip() if context.args else ""
    if not provided:
        await update.message.reply_text(
            "Please provide the password after /unlock\n"
            "Example: /unlock mysecretword"
        )
        return

    if provided == BOT_PASSWORD:
        approve_user(user_id)
        logger.info(f"User {name} ({user_id}) unlocked the bot")
        await update.message.reply_text(
            f"✅ Access granted, {name}! Welcome!\n\n"
            "Send me any file (PDF, Word, image, text...) and ask questions about it!\n"
            "Use /help to see all commands."
        )
    else:
        logger.warning(f"Failed unlock attempt by {name} ({user_id}) — wrong password")
        await update.message.reply_text("❌ Wrong password. Please try again.")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        await update.message.reply_text(
            "🔒 This bot is password-protected.\n"
            "Send /unlock <password> to get access."
        )
        return
    groq_list = "\n".join(f"  {i+1}. {m.split('/')[-1]}" for i, m in enumerate(GROQ_MODELS))
    await update.message.reply_text(
        "How to use me:\n\n"
        "1. Send a file (PDF, image, Word, .txt...)\n"
        "2. I will confirm I have read it\n"
        "3. Ask any question about it!\n\n"
        "Commands:\n"
        "/image <description> — generate an image with Gemini\n"
        "/files  — list loaded files\n"
        "/status — check AI model availability\n"
        "/reset  — clear files and conversation\n"
        "/help   — show this help\n\n"
        f"Primary   : Groq ⚡ ({len(GROQ_MODELS)} models)\n"
        f"{groq_list}\n\n"
        f"Fallback  : OpenRouter 🔄 ({len(OPENROUTER_MODELS)} free models)\n\n"
        "Images    : Gemini 2.0 Flash (free via Google AI Studio)",
    )

async def cmd_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        await update.message.reply_text("🔒 Send /unlock <password> to get access.")
        return
    session = get_session(user_id)
    docs = session["documents"]
    if not docs:
        await update.message.reply_text("No files loaded yet. Send me a file!")
        return
    lines = [f"Loaded files ({len(docs)}):"]
    for i, doc in enumerate(docs, 1):
        lines.append(f"{i}. {doc['name']} ({len(doc['content']):,} chars)")
    await update.message.reply_text("\n".join(lines))

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        await update.message.reply_text("🔒 Send /unlock <password> to get access.")
        return
    user_sessions[user_id] = {"history": [], "documents": []}
    await update.message.reply_text("Reset done! All files and conversation cleared.")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        await update.message.reply_text("🔒 Send /unlock <password> to get access.")
        return
    await update.message.reply_text("Checking models across both providers... ⏳ (~15 seconds)")
    results = check_model_status()
    lines = ["🤖 AI Provider Status:\n"]
    for label, status, latency in results:
        if latency > 0:
            lines.append(f"{status} {label} ({latency}ms)")
        else:
            lines.append(f"{status} {label}")
    lines.append(f"\nGroq: {len(GROQ_MODELS)} models | OpenRouter: {len(OPENROUTER_MODELS)} models")
    await update.message.reply_text("\n".join(lines))

async def cmd_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        await update.message.reply_text("🔒 Send /unlock <password> to get access.")
        return
    user_input = " ".join(context.args).strip() if context.args else ""
    if not user_input:
        await update.message.reply_text(
            "Please provide a description after /image\n"
            "Example: /image a detailed wiring diagram of a 3-phase motor starter"
        )
        return
    await update.message.reply_text(f"Generating image for: {user_input}\nThis may take up to 20 seconds...")
    img_bytes, info = generate_image(user_input)
    if img_bytes is None:
        await update.message.reply_text(f"Image generation failed: {info}")
        return
    try:
        buf = io.BytesIO(img_bytes)
        buf.name = "generated.png"
        await update.message.reply_photo(photo=buf, caption=f"Prompt: {user_input[:900]}")
    except Exception as e:
        await update.message.reply_text(f"Failed to send image: {e}")


# ─────────────────────────────────────────────
#  FILE HANDLER
# ─────────────────────────────────────────────

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        await update.message.reply_text("🔒 Send /unlock <password> to get access.")
        return

    session  = get_session(user_id)
    message  = update.message
    tg_file  = None
    filename = "unknown"

    if message.document:
        tg_file  = await message.document.get_file()
        filename = message.document.file_name or "document"
    elif message.photo:
        tg_file  = await message.photo[-1].get_file()
        filename = f"photo_{tg_file.file_id[:8]}.jpg"

    if tg_file is None:
        await message.reply_text("I could not read that. Try PDF, image, Word, or text.")
        return

    await message.reply_text(f"Reading {filename}...")

    try:
        file_bytes = bytes(await tg_file.download_as_bytearray())
    except Exception as e:
        await message.reply_text(f"Failed to download file: {e}")
        return

    content = extract_file(file_bytes, filename)
    session["documents"].append({"name": filename, "content": content})

    if len(session["documents"]) > MAX_CONTEXT_DOCS:
        removed = session["documents"].pop(0)
        await message.reply_text(f"Removed oldest file '{removed['name']}' to free space.")

    preview = content[:300].replace("\n", " ")
    await update.message.reply_text(
        f"{filename} loaded! ({len(content):,} characters extracted)\n\n"
        f"Preview: {preview}...\n\n"
        "Now ask me anything about it!"
    )


# ─────────────────────────────────────────────
#  TEXT MESSAGE HANDLER
# ─────────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id   = update.effective_user.id
    user_text = update.message.text.strip()

    if not is_allowed(user_id):
        await update.message.reply_text(
            "🔒 This bot is password-protected.\n"
            "Send /unlock <password> to get access."
        )
        return

    session = get_session(user_id)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    session["history"].append({"role": "user", "content": user_text})
    if len(session["history"]) > MAX_HISTORY_MSGS * 2:
        session["history"] = session["history"][-(MAX_HISTORY_MSGS * 2):]

    reply = ask_ai(session, user_text)
    session["history"].append({"role": "assistant", "content": reply})

    if len(reply) <= 4096:
        await update.message.reply_text(reply)
    else:
        for i in range(0, len(reply), 4096):
            await update.message.reply_text(reply[i:i + 4096])


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  AI Assistant Bot starting...")
    print(f"  Primary  : Groq ⚡ ({len(GROQ_MODELS)} models)")
    print(f"  Fallback : OpenRouter 🔄 ({len(OPENROUTER_MODELS)} free models)")
    print(f"  Images   : Gemini 2.0 Flash (FREE)")
    print(f"  Access   : Password-protected whitelist 🔒")
    print(f"  Approved : {len(approved_users)} user(s) loaded from {WHITELIST_FILE}")
    print(f"  Admins   : {len(ADMIN_IDS)} admin(s) configured")
    print("=" * 55)

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("unlock", cmd_unlock))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("files",  cmd_files))
    app.add_handler(CommandHandler("reset",  cmd_reset))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("image",  cmd_image))

    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.PHOTO,        handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Bot is running! Open Telegram and start chatting.")
    print("Press Ctrl+C to stop.\n")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
