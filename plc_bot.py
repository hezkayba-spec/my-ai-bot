# ==============================================================
# DOMOTEK AI — FULL ADVANCED TELEGRAM BOT (ALL FEATURES)
# Features:
# - File reading (PDF, DOCX, Images OCR)
# - Real PDF generation
# - Image generation (DALL·E via OpenAI)
# - Diagram generation (image-based)
# - Student UI (buttons)
# - Memory per user
# ==============================================================

import os
import io
import logging
import requests

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler,
    CommandHandler, CallbackQueryHandler,
    filters, ContextTypes
)

import fitz
from docx import Document as DocxDocument
from PIL import Image
import pytesseract

from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet

# ================= CONFIG =================
TELEGRAM_TOKEN = "YOUR_TELEGRAM_TOKEN"
OPENROUTER_KEY = "YOUR_OPENROUTER_KEY"
OPENAI_API_KEY = "YOUR_OPENAI_KEY"  # for images

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "qwen/qwen3.6-plus:free"

# ================= PROMPT =================
SYSTEM_PROMPT = """
You are DOMOTEK, an AI teacher for beginner electrical students.

Explain simply.
Use structure.

TITLE:
EXPLANATION:
STEPS:
SAFETY:

Special modes:
PDF_CONTENT:
IMAGE_PROMPT:
SCHEMA:
"""

# ================= MEMORY =================
user_memory = {}

# ================= LOGGING =================
logging.basicConfig(level=logging.INFO)

# ================= FILE EXTRACTION =================

def extract_pdf(file_bytes):
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    return "\n".join([p.get_text() for p in doc])


def extract_docx(file_bytes):
    doc = DocxDocument(io.BytesIO(file_bytes))
    return "\n".join([p.text for p in doc.paragraphs])


def extract_image(file_bytes):
    image = Image.open(io.BytesIO(file_bytes))
    return pytesseract.image_to_string(image)


def extract_file(file_bytes, filename):
    ext = filename.lower().split(".")[-1]

    if ext == "pdf":
        return extract_pdf(file_bytes)
    elif ext in ["docx", "doc"]:
        return extract_docx(file_bytes)
    elif ext in ["png", "jpg", "jpeg"]:
        return extract_image(file_bytes)
    else:
        return file_bytes.decode(errors="ignore")

# ================= AI =================

def ask_ai(user_id, message, context_text=""):
    history = user_memory.get(user_id, [])

    messages = [{"role": "system", "content": SYSTEM_PROMPT + context_text}]
    messages += history
    messages.append({"role": "user", "content": message})

    response = requests.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "messages": messages,
        }
    )

    reply = response.json()["choices"][0]["message"]["content"]

    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": reply})

    user_memory[user_id] = history[-10:]

    return reply

# ================= IMAGE GENERATION =================

def generate_image(prompt):
    response = requests.post(
        "https://api.openai.com/v1/images/generations",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "gpt-image-1",
            "prompt": prompt,
            "size": "1024x1024"
        }
    )

    return response.json()["data"][0]["url"]

# ================= UI =================

def main_menu():
    keyboard = [
        [InlineKeyboardButton("⚙️ Motor", callback_data="motor")],
        [InlineKeyboardButton("🔌 PLC", callback_data="plc")],
        [InlineKeyboardButton("📐 Diagram", callback_data="diagram")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ================= HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome to DOMOTEK AI", reply_markup=main_menu())


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "motor":
        await query.message.reply_text("Ask me about motors")
    elif query.data == "plc":
        await query.message.reply_text("Ask me about PLC")
    elif query.data == "diagram":
        await query.message.reply_text("Ask for a diagram")


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.document.get_file()
    file_bytes = bytes(await file.download_as_bytearray())

    content = extract_file(file_bytes, update.message.document.file_name)
    context.user_data["file"] = content

    await update.message.reply_text("File loaded.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text
    context_text = context.user_data.get("file", "")

    reply = ask_ai(user_id, user_text, context_text)

    # PDF
    if reply.startswith("PDF_CONTENT:"):
        content = reply.replace("PDF_CONTENT:", "")

        doc = SimpleDocTemplate("file.pdf")
        styles = getSampleStyleSheet()
        story = [Paragraph(line, styles["Normal"]) for line in content.split("\n")]
        doc.build(story)

        await update.message.reply_document(open("file.pdf", "rb"))
        return

    # IMAGE
    if reply.startswith("IMAGE_PROMPT:"):
        prompt = reply.replace("IMAGE_PROMPT:", "")
        img_url = generate_image(prompt)
        await update.message.reply_photo(img_url)
        return

    # SCHEMA → IMAGE
    if reply.startswith("SCHEMA:"):
        prompt = "Electrical diagram: " + reply.replace("SCHEMA:", "")
        img_url = generate_image(prompt)
        await update.message.reply_photo(img_url)
        return

    await update.message.reply_text(reply)

# ================= MAIN =================

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))

    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("DOMOTEK running...")
    app.run_polling()


if __name__ == "__main__":
    main()
