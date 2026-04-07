SYSTEM_PROMPT = """You are an industrial electricity assistant for students.
You help people learn and understand industrial electrical systems in a simple, clear way.
You behave like a friendly teacher — not a robot.

YOUR TOPICS (ONLY respond to these):
- Industrial electricity
- Motors (3-phase, 400V, etc.)
- Wiring and control panels
- PLC basics and automation
- Electrical troubleshooting
- Control systems and circuits

If the user asks something outside these topics, reply ONLY:
"I am specialized in industrial electrical systems only. Please ask a related question."

---

STYLE RULES:
- Use simple words, like explaining to a 16-year-old student
- Short sentences
- Step-by-step when needed
- Always explain technical words if you use them
- No long paragraphs
- Optimized for phone reading (Telegram)

BAD: "Nominal voltage discrepancy may indicate impedance irregularities"
GOOD: "The voltage is wrong. This usually means there is a wiring problem or a broken part."

---

STANDARD RESPONSE FORMAT:
TITLE: [Short clear title]
EXPLANATION: [Simple explanation]
STEPS:
1. First step
2. Second step
SAFETY:
* Safety warning if needed

---

TROUBLESHOOTING FORMAT:
PROBLEM: [What the user described]
CAUSES:
* Possible cause 1
* Possible cause 2
STEPS:
1. Check this first
2. Then check this
SAFETY:
* Always turn off power before touching anything
* Use insulated tools
* Follow lockout/tagout procedure

---

DIAGRAM / SCHEMA MODE:
When the user asks for a wiring diagram, schema, or blueprint, reply EXACTLY like this:

SCHEMA:
[Draw a clean readable layout using text and labels]
Use: L1, L2, L3, N, PE, Motor, Contactor, Relay, Lamp, Button, PLC, etc.

Example format:
L1 ──┬── Fuse ── Contactor (K1) ── Motor Terminal U
L2 ──┼── Fuse ── Contactor (K1) ── Motor Terminal V
L3 ──┴── Fuse ── Contactor (K1) ── Motor Terminal W
         │
    Overload Relay (F2)
         │
    Control Circuit

Rules:
- Must be readable by a human
- Must be clear enough to recreate in a real app
- Use real electrical labels
- No random code or symbols

---

IMAGE / LOGO MODE:
When the user asks for an image or logo, reply EXACTLY like this:

IMAGE_PROMPT: [Clear visual description]

Example:
IMAGE_PROMPT: Minimalist industrial logo with a 3-phase motor symbol in the center, bold text saying '400V Systems', arrows showing current flow from left to right, dark blue background, white lines, professional style.

---

PDF MODE:
When the user asks for a PDF or document, reply EXACTLY like this:

PDF_CONTENT:
Title: [Document title]

Section 1: [Title]
[Simple explanation]
- Point 1
- Point 2

Section 2: [Title]
[Simple explanation]
- Point 1
- Point 2

Safety Notes:
- Always disconnect power before working
- Use proper PPE

---

SAFETY RULE (NEVER SKIP):
Always add safety warnings when the topic involves:
- Working on live circuits
- Motors or high voltage
- Control panels or switchboards
- Any hands-on electrical work

---

OUTPUT RULES (CRITICAL):
- Never add extra text before or after your answer
- Never explain what you are doing
- Never go off-topic
- Always use the correct format for the request type
- Keep it clean, structured, and simple"""
"""
=============================================================
  AI Super Assistant — Telegram Bot + OpenRouter (FREE)
  Supports: PDF, Images, Word (.docx), Text, and more
  Model: qwen/qwen3.6-plus:free (100% free, always on)
=============================================================

REQUIREMENTS:
    pip install python-telegram-bot requests pymupdf python-docx pillow pytesseract

FOR IMAGE OCR — install Tesseract:
    Windows : https://github.com/UB-Mannheim/tesseract/wiki
    Linux   : sudo apt install tesseract-ocr tesseract-ocr-nld tesseract-ocr-fra
    Mac     : brew install tesseract

HOW TO RUN LOCALLY:
    1. Fill in TELEGRAM_TOKEN and OPENROUTER_KEY below
    2. Run: python plc_bot.py

HOW TO USE ON TELEGRAM:
    - Send any file (PDF, image, Word, .txt) → bot reads it
    - Then ask questions about it in plain text
    /reset → clears all files and conversation
    /files → shows loaded files
    /help  → shows all commands
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
    print("⚠️  PyMuPDF not installed. Run: pip install pymupdf")

try:
    from docx import Document as DocxDocument
    DOCX_SUPPORT = True
except ImportError:
    DOCX_SUPPORT = False
    print("⚠️  python-docx not installed. Run: pip install python-docx")

try:
    from PIL import Image
    import pytesseract
    IMAGE_SUPPORT = True
except ImportError:
    IMAGE_SUPPORT = False
    print("⚠️  Pillow/pytesseract not installed. Run: pip install pillow pytesseract")


# ─────────────────────────────────────────────
#  CONFIGURATION — fill in your keys here
# ─────────────────────────────────────────────

# From @BotFather on Telegram
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_TELEGRAM_TOKEN_HERE")

# From openrouter.ai (free account, no credit card needed)
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "YOUR_OPENROUTER_KEY_HERE")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL          = "qwen/qwen3.6-plus:free"   # Free & very powerful

MAX_FILE_CHARS   = 12000   # Max characters extracted per file
MAX_CONTEXT_DOCS = 5       # Max files kept in memory per user
MAX_HISTORY_MSGS = 10      # Max conversation turns kept per user

SYSTEM_PROMPT = """You are an intelligent AI assistant helping a student in electrical automation and technical education.

Your expertise includes:
- PLC programming: LOGO!, Siemens S7, Allen-Bradley
- Grafcet / SFC diagrams (niveau 1 and 2)
- FBD, LAD, STL, SCL programming languages
- Circuit design, switchboard wiring, 24V DC systems
- QElectroTech, I/O lists, RS flip-flops, Merker/flag logic
- General technical, scientific, and educational topics

When the user shares files or documents:
1. Read and analyze the content carefully
2. Answer any questions about it accurately and clearly
3. Explain difficult concepts in simple terms
4. Summarize key points when asked
5. Help the user study or work with the material

Always respond in the same language the user writes in (French, Dutch, or English).
Be concise, practical, and helpful."""


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
        return "[Image received — no readable text found. You can still ask me questions about what is in it.]"
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
#  OPENROUTER API CALL
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
        "qwen/qwen3.6-plus:free",
        "qwen/qwen3-235b-a22b:free",
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
        except Exception as e:
            continue

    return "⏳ All models are busy right now. Wait a few seconds and try again!"

    except requests.exceptions.Timeout:
        return "⏳ The model is taking too long. Please try again."
    except requests.exceptions.ConnectionError:
        return "❌ Cannot connect to OpenRouter. Check your internet connection."
    except Exception as e:
        return f"❌ Error: {e}"


# ─────────────────────────────────────────────
#  TELEGRAM COMMANDS
# ─────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name
    await update.message.reply_text(
        f"👋 Hey {name}! I'm your AI assistant.\n\n"
        "📎 *Send me any file* — PDF, Word, image, text...\n"
        "💬 Then *ask me anything* about it!\n\n"
        "Commands:\n"
        "/files — see loaded files\n"
        "/reset — clear everything\n"
        "/help  — show this message",
        parse_mode="Markdown"
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *How to use me:*\n\n"
        "1️⃣ Send a file (PDF, image, Word, .txt...)\n"
        "2️⃣ I'll confirm I've read it\n"
        "3️⃣ Ask any question about it!\n\n"
        "*Commands:*\n"
        "/files — list loaded files\n"
        "/reset — clear files + conversation\n"
        "/help  — show this help\n\n"
        f"*Model:* `{MODEL}`",
        parse_mode="Markdown"
    )

async def cmd_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session(update.effective_user.id)
    docs = session["documents"]
    if not docs:
        await update.message.reply_text("📂 No files loaded yet. Send me a file!")
        return
    lines = [f"📂 *Loaded files ({len(docs)}):*"]
    for i, doc in enumerate(docs, 1):
        lines.append(f"{i}. {doc['name']} ({len(doc['content']):,} chars)")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_sessions[user_id] = {"history": [], "documents": []}
    await update.message.reply_text("🔄 Reset done! All files and conversation cleared.")


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
        await message.reply_text("❓ I couldn't read that. Try PDF, image, Word, or text.")
        return

    await message.reply_text(f"📥 Reading *{filename}*...", parse_mode="Markdown")

    try:
        file_bytes = bytes(await tg_file.download_as_bytearray())
    except Exception as e:
        await message.reply_text(f"❌ Failed to download file: {e}")
        return

    content = extract_file(file_bytes, filename)

    session["documents"].append({"name": filename, "content": content})
    if len(session["documents"]) > MAX_CONTEXT_DOCS:
        removed = session["documents"].pop(0)
        await message.reply_text(
            f"ℹ️ Removed oldest file *{removed['name']}* to free space.",
            parse_mode="Markdown"
        )

    preview = content[:300].replace("\n", " ")
    await message.reply_text(
        f"✅ *{filename}* loaded! ({len(content):,} characters extracted)\n\n"
        f"📄 _{preview}..._\n\n"
        "Now ask me anything about it!",
        parse_mode="Markdown"
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
    print(f"  Model : {MODEL}")
    print(f"  API   : OpenRouter (free)")
    print("=" * 50)

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CommandHandler("files", cmd_files))
    app.add_handler(CommandHandler("reset", cmd_reset))

    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.PHOTO,        handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("✅ Bot is running! Open Telegram and start chatting.")
    print("   Press Ctrl+C to stop.\n")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
