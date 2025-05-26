import os
import re
import requests
import logging
import urllib3
from io import BytesIO
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters, CallbackQueryHandler

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("LOG_CHAT_ID", "123456789"))  # Replace 123456789 with your admin/chat ID
API_URL = "https://terabox.sg61x.workers.dev"

# Expanded supported domains regex pattern
TERABOX_PATTERN = r'https?://(?:www\.)?(?:freeterabox|terabox|1024terabox|teraboxapp|4funbox|mirrobox|nephobox|teraboxlink|1024tera|terabox\.app|terabox\.fun|terabox\.com|momerybox|tibibox)\.(?:com|co|app)/s/[^\s]+'

FOOTER = "✨ [Powered by RetrivedMods](https://t.me/RetrivedMods)"

# /start command
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Hello! I'm your Premium TeraBox Video Downloader Bot.*\n\n"
        "📥 Just send me a TeraBox link and I’ll fetch the video for you.\n"
        "🔎 Use /supported to view all supported sites.\n\n"
        + FOOTER,
        parse_mode='Markdown'
    )

# /supported command
async def supported_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    supported_sites = """
✅ *Supported TeraBox Domains*:

• terabox.com / www.terabox.com
• freeterabox.com / www.freeterabox.com
• 1024terabox.com / 1024tera.com / www.1024tera.co
• teraboxapp.com / www.teraboxapp.com / terabox.app / www.terabox.app / terabox.fun
• mirrobox.com / www.mirrobox.com
• nephobox.com / www.nephobox.com
• 4funbox.co / www.4funbox.com
• momerybox.com / www.momerybox.com
• tibibox.com / www.tibibox.com

Send any valid link from these sites and I’ll download the video for you!

""" + FOOTER
    await update.message.reply_text(supported_sites, parse_mode='Markdown')

# Send file details with download button
async def send_file_details(update, filename, file_size, thumb, download_url):
    keyboard = [[InlineKeyboardButton("📥 Download", url=download_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    caption = f"📁 *{filename}*\n📊 *Size:* {file_size}\n\nClick below to download.\n\n{FOOTER}"

    if thumb:
        await update.message.reply_photo(photo=thumb, caption=caption, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text=caption, reply_markup=reply_markup, parse_mode='Markdown')

# Log details to admin chat with or without video
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

    if video_buffer:
        video_buffer.seek(0)
        await context.bot.send_video(
            chat_id=ADMIN_CHAT_ID,
            video=video_buffer,
            filename=filename,
            caption=log_text,
            parse_mode='Markdown'
        )
    else:
        keyboard = [[InlineKeyboardButton("📥 Download", url=download_url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=log_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

# Handles any message with a link
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text
    match = re.search(TERABOX_PATTERN, message)

    user_id = update.message.from_user.id
    username = update.message.from_user.username or "N/A"
    first_name = update.message.from_user.first_name or "N/A"

    if not match:
        await update.message.reply_text("❌ Please send a valid TeraBox link.\n\n" + FOOTER, parse_mode='Markdown')
        return

    link = match.group()
    fetching_msg = await update.message.reply_text("⏳ Fetching video...")

    try:
        encoded_link = requests.utils.quote(link, safe='')
        response = requests.get(f"{API_URL}?url={encoded_link}", verify=False, timeout=60)

        if response.status_code != 200:
            await fetching_msg.edit_text("⚠️ API is unavailable. Please try again later.\n\n" + FOOTER, parse_mode='Markdown')
            return

        data = response.json()

        download_url = (
            data.get('downloadUrl') or data.get('download_url') or
            data.get('directLink') or data.get('data', {}).get('structure', {}).get('download_url')
        )
        filename = data.get('filename') or data.get('file_name') or "video.mp4"
        file_size = data.get('size', 'Unknown')
        thumb = data.get('thumbnail') or data.get('thumb_url') or None

        if not download_url:
            await fetching_msg.edit_text("❌ Could not extract the download link.\n\n" + FOOTER, parse_mode='Markdown')
            return

    except Exception as e:
        logger.error(e)
        await fetching_msg.edit_text("⚠️ An unexpected error occurred. Please try again later.\n\n" + FOOTER, parse_mode='Markdown')
        return

    try:
        await fetching_msg.edit_text("⬇️ Downloading video...")

        head = requests.head(download_url, verify=False, timeout=30)
        size = int(head.headers.get('content-length', 0))

        if size > 50 * 1024 * 1024:
            await fetching_msg.delete()
            await send_file_details(update, filename, file_size, thumb, download_url)
            await send_log(context, user_id, username, first_name, filename, file_size, link, download_url, None)
            return

        response = requests.get(download_url, stream=True, timeout=120, verify=False)
        buffer = BytesIO()

        for chunk in response.iter_content(chunk_size=8192):
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
            parse_mode='Markdown'
        )

        # Send log with video attached
        await send_log(context, user_id, username, first_name, filename, file_size, link, download_url, buffer)

    except Exception as e:
        logger.error(e)
        await fetching_msg.delete()
        await send_file_details(update, filename, file_size, thumb, download_url)
        await send_log(context, user_id, username, first_name, filename, file_size, link, download_url, None)

# Handle inline button callback (optional, currently no action)
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

# Main entry point
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("supported", supported_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.run_polling()
