"""
=============================================================
  AI Super Assistant — Telegram Bot + OpenRouter (FREE)
  Supports: PDF, Images, Word (.docx), Text, and more
  Image Generation: OpenAI DALL-E 3
  Model: qwen/qwen3-235b-a22b:free (100% free, always on)
=============================================================

REQUIREMENTS:
    pip install python-telegram-bot requests pymupdf python-docx pillow pytesseract openai

FOR IMAGE OCR — install Tesseract:
    Windows : https://github.com/UB-Mannheim/tesseract/wiki
    Linux   : sudo apt install tesseract-ocr tesseract-ocr-nld tesseract-ocr-fra
    Mac     : brew install tesseract

HOW TO RUN LOCALLY:
    1. Fill in TELEGRAM_TOKEN, OPENROUTER_KEY, and OPENAI_KEY below
    2. Run: python plc_bot.py

HOW TO USE ON TELEGRAM:
    - Send any file (PDF, image, Word, .txt) -> bot reads it
    - Ask questions about it in plain text
    - /image <description> -> generates an image with DALL-E 3
    /reset  -> clears all files and conversation
    /files  -> shows loaded files
    /help   -> shows all commands
=============================================================
"""

import os
import io
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
    print("WARNING: openai not installed. Run: pip install openai")


# ─────────────────────────────────────────────
#  CONFIGURATION — fill in your keys here
# ─────────────────────────────────────────────

# From @BotFather on Telegram
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_TELEGRAM_TOKEN_HERE")

# From openrouter.ai (free account, no credit card needed)
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "YOUR_OPENROUTER_KEY_HERE")

# From platform.openai.com — used only for image generation (DALL-E 3)
OPENAI_KEY = os.environ.get("OPENAI_KEY", "YOUR_OPENAI_KEY_HERE")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL          = "qwen/qwen3-235b-a22b:free"   # Free & very powerful

MAX_FILE_CHARS   = 12000   # Max characters extracted per file
MAX_CONTEXT_DOCS = 5       # Max files kept in memory per user
MAX_HISTORY_MSGS = 10      # Max conversation turns kept per user

SYSTEM_PROMPT = """Industrial Electrician AI Assistant (Telegram Bot Script Optimized)
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
#  USER SESSIONS
# ─────────────────────────────────────────────

user_sessions: dict = {}

def get_session(user_id: int) -> dict:
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            "history":   [],
            "documents": [],
        }
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
#  OPENROUTER API CALL (text)
# ─────────────────────────────────────────────

def ask_ai(session: dict, user_message: str) -> str:
    doc_context = build_document_context(session)

    system_content = SYSTEM_PROMPT
    if doc_context:
        system_content += f"\n\n{doc_context}"

    messages = [{"role": "system", "content": system_content}]
    messages += session["history"]
    messages.append({"role": "user", "content": user_message})

    # Try these free models in order if one is busy
    models_to_try = [
        "qwen/qwen3-235b-a22b:free",
        "qwen/qwen3.6-plus:free",
        "meta-llama/llama-3.3-70b-instruct:free",
    ]

    for model in models_to_try:
        try:
            response = requests.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {OPENROUTER_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "stream": False,
                },
                timeout=120
            )
            if response.status_code == 429:
                continue  # this model is busy, try next one
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]

        except requests.exceptions.Timeout:
            continue
        except Exception:
            continue

    return "All models are busy right now. Wait a few seconds and try again!"


# ─────────────────────────────────────────────
#  OPENAI IMAGE GENERATION (DALL-E 3)
# ─────────────────────────────────────────────

def generate_image(prompt: str) -> tuple:
    """
    Generate an image using OpenAI DALL-E 3.
    Returns (image_url, revised_prompt) on success, or (None, error_message) on failure.
    """
    if not OPENAI_AVAILABLE:
        return None, "openai package not installed. Run: pip install openai"

    if OPENAI_KEY == "YOUR_OPENAI_KEY_HERE":
        return None, "OpenAI API key not configured. Set OPENAI_KEY in your environment or in the script."

    try:
        client = openai.OpenAI(api_key=OPENAI_KEY)
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            n=1,
        )
        image_url      = response.data[0].url
        revised_prompt = response.data[0].revised_prompt or prompt
        return image_url, revised_prompt

    except openai.AuthenticationError:
        return None, "Invalid OpenAI API key. Check your OPENAI_KEY."
    except openai.RateLimitError:
        return None, "OpenAI rate limit reached. Wait a moment and try again."
    except openai.BadRequestError as e:
        return None, f"Request rejected by OpenAI (content policy): {e}"
    except Exception as e:
        return None, f"Image generation failed: {e}"


# ─────────────────────────────────────────────
#  TELEGRAM COMMANDS
# ─────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name
    await update.message.reply_text(
        f"Hey {name}! I am your AI assistant.\n\n"
        "Send me any file (PDF, Word, image, text...) and ask questions about it!\n\n"
        "Commands:\n"
        "/image <description> - generate an image with DALL-E 3\n"
        "/files - see loaded files\n"
        "/reset - clear everything\n"
        "/help  - show this message",
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "How to use me:\n\n"
        "1. Send a file (PDF, image, Word, .txt...)\n"
        "2. I will confirm I have read it\n"
        "3. Ask any question about it!\n\n"
        "Commands:\n"
        "/image <description> - generate an image with DALL-E 3\n"
        "/files - list loaded files\n"
        "/reset - clear files and conversation\n"
        "/help  - show this help\n\n"
        f"Text model: {MODEL}\n"
        "Image model: DALL-E 3 (OpenAI)",
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

async def cmd_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /image <prompt> — generate an image with DALL-E 3."""
    user_input = " ".join(context.args).strip() if context.args else ""

    if not user_input:
        await update.message.reply_text(
            "Please provide a description after /image\n"
            "Example: /image a detailed wiring diagram of a 3-phase motor starter"
        )
        return

    await update.message.reply_text(f"Generating image for: {user_input}\nThis may take up to 20 seconds...")

    image_url, info = generate_image(user_input)

    if image_url is None:
        await update.message.reply_text(f"Image generation failed: {info}")
        return

    # Download the image and send it as a Telegram photo
    try:
        img_response = requests.get(image_url, timeout=60)
        img_response.raise_for_status()
        img_bytes = io.BytesIO(img_response.content)
        img_bytes.name = "generated.png"

        caption = f"Generated image\nPrompt: {info[:900]}" if info != user_input else f"Prompt: {user_input[:900]}"

        await update.message.reply_photo(
            photo=img_bytes,
            caption=caption,
        )
    except Exception as e:
        # Fallback: send the URL if download fails
        await update.message.reply_text(
            f"Image generated! View it here:\n{image_url}\n\n"
            f"(Direct send failed: {e})"
        )


# ─────────────────────────────────────────────
#  FILE HANDLER
# ─────────────────────────────────────────────

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


# ─────────────────────────────────────────────
#  TEXT MESSAGE HANDLER
# ─────────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id   = update.effective_user.id
    session   = get_session(user_id)
    user_text = update.message.text.strip()

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

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
    print("=" * 50)
    print("  AI Assistant Bot starting...")
    print(f"  Text model : {MODEL}")
    print(f"  Image model: DALL-E 3 (OpenAI)")
    print(f"  Text API   : OpenRouter (free)")
    print("=" * 50)

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("files",  cmd_files))
    app.add_handler(CommandHandler("reset",  cmd_reset))
    app.add_handler(CommandHandler("image",  cmd_image))

    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.PHOTO,        handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Bot is running! Open Telegram and start chatting.")
    print("Press Ctrl+C to stop.\n")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
