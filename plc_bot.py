"""
=============================================================
  AI Super Assistant — Telegram Bot + OpenRouter (FREE)
  Supports: PDF, Images, Word (.docx), Text, and more
  Image Generation: Google Gemini 2.0 Flash (FREE)
  100% free — no paid APIs needed
=============================================================

REQUIREMENTS:
    pip install python-telegram-bot requests pymupdf python-docx pillow pytesseract openai

FOR IMAGE OCR — install Tesseract:
    Windows : https://github.com/UB-Mannheim/tesseract/wiki
    Linux   : sudo apt install tesseract-ocr tesseract-ocr-nld tesseract-ocr-fra
    Mac     : brew install tesseract

HOW TO RUN LOCALLY:
    1. Fill in TELEGRAM_TOKEN, OPENROUTER_KEY, and GEMINI_KEY below
    2. Run: python plc_bot.py

HOW TO USE ON TELEGRAM:
    - Send any file (PDF, image, Word, .txt) -> bot reads it
    - Ask questions about it in plain text
    - /image <description> -> generates an image with Gemini
    /reset  -> clears all files and conversation
    /files  -> shows loaded files
    /status -> shows which AI models are currently online
    /help   -> shows all commands
=============================================================
"""

import os
import io
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

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


# ---------------------------------------------
#  CONFIGURATION
# ---------------------------------------------

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_TELEGRAM_TOKEN_HERE")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "YOUR_OPENROUTER_KEY_HERE")
GEMINI_KEY     = os.environ.get("GEMINI_KEY",     "YOUR_GEMINI_KEY_HERE")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Ordered list of free models — tried in sequence until one responds successfully.
# Most reliable models are placed first; lighter fallbacks at the end.
FREE_MODELS = [
    # Tier 1 — best quality free models (April 2026)
    "meta-llama/llama-4-maverick:free",               # Meta Llama 4 — best overall free model
    "deepseek/deepseek-chat-v3-0324:free",            # DeepSeek V3 — excellent reasoning
    "nvidia/llama-3.1-nemotron-ultra-253b-v1:free",   # NVIDIA 253B — very powerful
    "mistralai/mistral-small-3.1-24b-instruct:free",  # Mistral Small 3.1 — fast & reliable
    # Tier 2 — solid fallbacks
    "meta-llama/llama-4-scout:free",                  # Meta Llama 4 Scout — lighter version
    "qwen/qwen3-235b-a22b:free",                      # Qwen3 235B — strong multilingual
    "google/gemma-3-27b-it:free",                     # Google Gemma 3 27B
    "meta-llama/llama-3.3-70b-instruct:free",         # Llama 3.3 70B — proven reliable
    # Tier 3 — lightweight always-on safety nets
    "microsoft/phi-4:free",                           # Microsoft Phi-4 — small but capable
    "google/gemma-3-12b-it:free",                     # Google Gemma 3 12B — very light
    "mistralai/mistral-7b-instruct:free",             # Mistral 7B — near-always available
]

MAX_FILE_CHARS   = 12000
MAX_CONTEXT_DOCS = 5
MAX_HISTORY_MSGS = 10

SYSTEM_PROMPT = """Industrial Electrician AI Assistant (Telegram Bot Script Optimized)
ROLE
You are a specialized industrial electrician AI assistant built for a Telegram bot.
Your job is to:
* Provide accurate electrical knowledge
* Help troubleshoot real-world problems
* Explain PLC programming, wiring diagrams, and electrical schematics
* Answer questions about files and documents the user shares

Stay focused. Be precise. Be structured."""


# ---------------------------------------------
#  LOGGING
# ---------------------------------------------

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ---------------------------------------------
#  USER SESSIONS
# ---------------------------------------------

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


# ---------------------------------------------
#  FILE EXTRACTION
# ---------------------------------------------

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


# ---------------------------------------------
#  MODEL AVAILABILITY CHECK
# ---------------------------------------------

def _is_model_response_valid(data: dict) -> tuple:
    """
    Returns (is_valid: bool, text: str).
    Checks for OpenRouter error bodies and empty/error content.
    """
    # OpenRouter signals failure in the top-level 'error' key
    if data.get("error"):
        err = data["error"]
        logger.warning(f"OpenRouter error in response body: {err}")
        return False, ""

    choices = data.get("choices", [])
    if not choices:
        return False, ""

    text = choices[0].get("message", {}).get("content", "").strip()

    # Some models return a 200 with an error string as content
    if not text:
        return False, ""

    text_lower = text.lower()
    error_prefixes = ("error:", "i'm sorry, i cannot", "model is currently unavailable")
    if any(text_lower.startswith(p) for p in error_prefixes):
        logger.warning(f"Model returned error-like content: {text[:80]}")
        return False, ""

    return True, text


# ---------------------------------------------
#  ASK AI — robust fallback across all free models
# ---------------------------------------------

def ask_ai(session: dict, user_message: str) -> str:
    doc_context = build_document_context(session)
    system_content = SYSTEM_PROMPT
    if doc_context:
        system_content += f"\n\n{doc_context}"

    messages = [{"role": "system", "content": system_content}]
    messages += session["history"]
    messages.append({"role": "user", "content": user_message})

    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
    }

    # Two full passes through all models before giving up.
    # Pass 2 waits 8 seconds first to let overloaded models recover.
    for attempt in range(2):
        if attempt == 1:
            logger.info("All models failed on pass 1 — waiting 8s before retry pass...")
            time.sleep(8)

        for model in FREE_MODELS:
            try:
                logger.info(f"Trying model: {model}")
                resp = requests.post(
                    OPENROUTER_URL,
                    headers=headers,
                    json={"model": model, "messages": messages, "stream": False},
                    timeout=60,
                )

                # Rate-limited — short wait, try next model
                if resp.status_code == 429:
                    logger.warning(f"{model} → 429 rate limited, skipping")
                    time.sleep(1)
                    continue

                # Model overloaded / unavailable
                if resp.status_code == 503:
                    logger.warning(f"{model} → 503 unavailable, skipping")
                    continue

                # Any other 4xx/5xx — skip
                if resp.status_code >= 400:
                    logger.warning(f"{model} → HTTP {resp.status_code}, skipping")
                    continue

                data = resp.json()
                valid, text = _is_model_response_valid(data)
                if valid:
                    logger.info(f"Success with model: {model}")
                    return text

            except requests.exceptions.Timeout:
                logger.warning(f"{model} → timeout, skipping")
                continue
            except Exception as e:
                logger.warning(f"{model} → exception: {e}, skipping")
                continue

    return (
        "⚠️ All AI models are currently busy or unavailable.\n"
        "This usually resolves itself within a minute — please try again shortly!\n\n"
        "Tip: Use /status to see which models are online."
    )


# ---------------------------------------------
#  IMAGE GENERATION — Gemini 2.0 Flash (FREE)
# ---------------------------------------------

def generate_image(prompt: str) -> tuple:
    """
    Generate an image using Google Gemini 2.0 Flash — completely free.
    Get your free API key at: https://aistudio.google.com
    Returns (image_bytes, prompt) on success, or (None, error_message) on failure.
    """
    if GEMINI_KEY == "YOUR_GEMINI_KEY_HERE":
        return None, "Gemini API key not configured. Get a free key at aistudio.google.com and set GEMINI_KEY."
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={GEMINI_KEY}"
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
        return None, "Gemini image generation timed out. Try again."
    except Exception as e:
        return None, f"Image generation failed: {e}"


# ---------------------------------------------
#  MODEL STATUS CHECK (for /status command)
# ---------------------------------------------

def check_model_status() -> list:
    """
    Quickly probes each free model with a tiny prompt.
    Returns a list of (model_short_name, status_emoji, latency_ms).
    Runs in sequence — may take ~10-20s for many models.
    """
    probe_messages = [{"role": "user", "content": "Reply with one word: OK"}]
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
    }
    results = []
    # Only check top 6 to keep /status fast
    models_to_check = FREE_MODELS[:6]
    for model in models_to_check:
        short = model.split("/")[-1].replace(":free", "")
        try:
            t0 = time.time()
            resp = requests.post(
                OPENROUTER_URL,
                headers=headers,
                json={"model": model, "messages": probe_messages, "stream": False, "max_tokens": 5},
                timeout=15,
            )
            latency = int((time.time() - t0) * 1000)
            if resp.status_code == 200:
                data = resp.json()
                valid, _ = _is_model_response_valid(data)
                if valid:
                    results.append((short, "✅", latency))
                else:
                    results.append((short, "⚠️", latency))
            elif resp.status_code == 429:
                results.append((short, "🔴 rate-limited", 0))
            elif resp.status_code == 503:
                results.append((short, "🔴 overloaded", 0))
            else:
                results.append((short, f"🔴 HTTP {resp.status_code}", 0))
        except requests.exceptions.Timeout:
            results.append((short, "🔴 timeout", 0))
        except Exception as e:
            results.append((short, f"🔴 error", 0))
    return results


# ---------------------------------------------
#  TELEGRAM COMMANDS
# ---------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name
    await update.message.reply_text(
        f"Hey {name}! I am your AI assistant.\n\n"
        "Send me any file (PDF, Word, image, text...) and ask questions about it!\n\n"
        "Commands:\n"
        "/image <description> — generate an image\n"
        "/files  — see loaded files\n"
        "/status — check which AI models are online\n"
        "/reset  — clear everything\n"
        "/help   — show this message",
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    model_list = "\n".join(f"  {i+1}. {m.split('/')[-1].replace(':free','')}" for i, m in enumerate(FREE_MODELS))
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
        f"Free models tried in order ({len(FREE_MODELS)} total):\n{model_list}\n\n"
        "Image model: Gemini 2.0 Flash (free via Google AI Studio)",
    )

async def cmd_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session(update.effective_user.id)
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
    user_sessions[user_id] = {"history": [], "documents": []}
    await update.message.reply_text("Reset done! All files and conversation cleared.")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check which free models are currently responding."""
    await update.message.reply_text(
        f"Checking top {min(6, len(FREE_MODELS))} models... this takes ~15 seconds ⏳"
    )
    results = check_model_status()
    lines = ["🤖 Model Status:\n"]
    for name, status, latency in results:
        if latency > 0:
            lines.append(f"{status} {name} ({latency}ms)")
        else:
            lines.append(f"{status} {name}")
    lines.append(f"\n{len(FREE_MODELS)} total models in fallback chain.")
    await update.message.reply_text("\n".join(lines))

async def cmd_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


# ---------------------------------------------
#  FILE HANDLER
# ---------------------------------------------

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id  = update.effective_user.id
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
    await message.reply_text(
        f"{filename} loaded! ({len(content):,} characters extracted)\n\n"
        f"Preview: {preview}...\n\n"
        "Now ask me anything about it!"
    )


# ---------------------------------------------
#  TEXT MESSAGE HANDLER
# ---------------------------------------------

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id   = update.effective_user.id
    session   = get_session(user_id)
    user_text = update.message.text.strip()

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


# ---------------------------------------------
#  MAIN
# ---------------------------------------------

def main():
    print("=" * 50)
    print("  AI Assistant Bot starting...")
    print(f"  Free models in chain : {len(FREE_MODELS)}")
    print(f"  Image model          : Gemini 2.0 Flash (FREE)")
    print("=" * 50)

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",  cmd_start))
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
