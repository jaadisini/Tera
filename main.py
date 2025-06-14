import os
import re
import requests
import logging
import urllib3
from io import BytesIO
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler,
)
from flask import Flask
import threading

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "7918013937:AAFKZItUUExUPJubRGcDLWgPgj0kdgb3ydI")
ADMIN_CHAT_ID = int(os.getenv("LOG_CHAT_ID", "-1002651549822"))
API_URL = "https://terabox.sg61x.workers.dev"

TERABOX_PATTERN = re.compile(
    r"https?://(?:www\.)?(?:freeterabox|terabox|1024terabox|teraboxapp|4funbox|mirrobox|nephobox|"
    r"teraboxlink|1024tera|terabox\.app|terabox\.fun|terabox\.com|momerybox|tibibox)\.(?:com|co|app)/s/[^\s]+",
    re.IGNORECASE
)

FOOTER = "✨ [Powered by RetrivedMods](https://t.me/RetrivedMods)"

# === Flask ===
flask_app = Flask("")

@flask_app.route("/")
def home():
    return "Bot is running!"

def run_flask():
    flask_app.run(host="0.0.0.0", port=8000)


# === Commands ===

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Hello! I'm your Premium TeraBox Video Downloader Bot.*\n\n"
        "📥 Just send me a TeraBox link and I’ll fetch the video for you.\n"
        "🔎 Use /supported to view all supported sites.\n\n"
        + FOOTER,
        parse_mode="Markdown",
    )

async def supported_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "✅ *Supported TeraBox Domains*:\n\n"
        "- terabox.com / freeterabox.com\n"
        "- 1024terabox.com / 1024tera.com\n"
        "- teraboxapp.com / terabox.app / terabox.fun\n"
        "- mirrobox.com / nephobox.com\n"
        "- 4funbox.co / momerybox.com / tibibox.com\n\n"
        "Send a valid link from one of these sites.\n\n"
        + FOOTER
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# === Core Handlers ===

async def send_file_details(update, filename, file_size, thumb, download_url):
    keyboard = [[InlineKeyboardButton("📥 Download", url=download_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    caption = f"📁 *{filename}*\n📊 *Size:* {file_size}\n\nClick below to download.\n\n{FOOTER}"

    try:
        if thumb:
            await update.message.reply_photo(
                photo=thumb, caption=caption, reply_markup=reply_markup, parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                caption, reply_markup=reply_markup, parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Send file details failed: {e}")


async def send_log(context, user_id, username, first_name, filename, file_size, link, download_url, video_buffer):
    log_text = (
        f"📥 *New TeraBox Request*\n"
        f"👤 *User:* {first_name} (@{username})\n"
        f"🆔 *User ID:* `{user_id}`\n"
        f"🔗 *Link:* {link}\n"
        f"📁 *File:* {filename}\n"
        f"📦 *Size:* {file_size}\n"
        f"📎 *Download:* [Click here]({download_url})"
    )

    try:
        if video_buffer:
            video_buffer.seek(0)
            await context.bot.send_video(
                chat_id=ADMIN_CHAT_ID,
                video=video_buffer,
                filename=filename,
                caption=log_text,
                parse_mode="Markdown",
            )
        else:
            keyboard = [[InlineKeyboardButton("📥 Download", url=download_url)]]
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=log_text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
    except Exception as e:
        logger.error(f"Send log failed: {e}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text
    match = TERABOX_PATTERN.search(message)

    user = update.message.from_user
    user_id = user.id
    username = user.username or "N/A"
    first_name = user.first_name or "N/A"

    if not match:
        await update.message.reply_text("❌ Please send a valid TeraBox link.\n\n" + FOOTER, parse_mode="Markdown")
        return

    link = match.group()
    fetching_msg = await update.message.reply_text("⏳ Fetching video...")

    try:
        encoded_link = requests.utils.quote(link, safe="")
        res = requests.get(f"{API_URL}?url={encoded_link}", timeout=60, verify=False)
        if res.status_code != 200:
            await fetching_msg.edit_text("⚠️ API is unavailable. Please try again later.\n\n" + FOOTER, parse_mode="Markdown")
            return

        data = res.json()
        download_url = (
            data.get("downloadUrl") or data.get("download_url") or
            data.get("directLink") or data.get("data", {}).get("structure", {}).get("download_url")
        )
        filename = data.get("filename") or data.get("file_name") or "video.mp4"
        file_size = data.get("size") or "Unknown"
        thumb = data.get("thumbnail") or data.get("thumb_url")

        if not download_url:
            await fetching_msg.edit_text("❌ Could not extract download link.\n\n" + FOOTER, parse_mode="Markdown")
            return

        await fetching_msg.edit_text("⬇️ Downloading video...")

        head = requests.head(download_url, timeout=30, verify=False)
        content_length = head.headers.get("content-length")
        size = int(content_length) if content_length else 0

        if size > 50 * 1024 * 1024:
            await fetching_msg.delete()
            await send_file_details(update, filename, file_size, thumb, download_url)
            await send_log(context, user_id, username, first_name, filename, file_size, link, download_url, None)
            return

        resp = requests.get(download_url, stream=True, timeout=120, verify=False)
        buffer = BytesIO()

        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                buffer.write(chunk)
            if buffer.tell() > 50 * 1024 * 1024:
                await fetching_msg.delete()
                await send_file_details(update, filename, file_size, thumb, download_url)
                await send_log(context, user_id, username, first_name, filename, file_size, link, download_url, None)
                return

        buffer.seek(0)
        await fetching_msg.delete()

        await update.message.reply_video(
            video=buffer,
            filename=filename,
            caption=f"📁 {filename}\n📊 {file_size}\n\n{FOOTER}",
            parse_mode="Markdown",
        )
        await send_log(context, user_id, username, first_name, filename, file_size, link, download_url, buffer)

    except Exception as e:
        logger.exception("Download error")
        await fetching_msg.delete()
        await send_file_details(update, filename, file_size, thumb, download_url)
        await send_log(context, user_id, username, first_name, filename, file_size, link, download_url, None)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()


# === MAIN ===
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("supported", supported_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.run_polling()
