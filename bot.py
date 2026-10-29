import logging
import os
import asyncio
import itertools
import google.generativeai as genai
from urllib.parse import quote_plus
from dotenv import load_dotenv
from telegram import Update, ReplyParameters, PhotoSize, File
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, filters as Filters
from typing import List, Optional
import re
import json

# Load environment variables
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MAIN_CHANNEL_ID = os.getenv("MAIN_CHANNEL_ID")
DISCUSSION_GROUP_IDS_STR = os.getenv("DISCUSSION_GROUP_IDS")

# Configure logging
LOG_FILE = "bot.log"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

if logger.hasHandlers():
    logger.handlers.clear()

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
logger.addHandler(console_handler)

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "name": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_record['exc_info'] = self.formatException(record.exc_info)
        return json.dumps(log_record)

file_handler = logging.FileHandler(LOG_FILE)
file_handler.setFormatter(JsonFormatter())
logger.addHandler(file_handler)

logging.getLogger("httpx").setLevel(logging.WARNING)

# --- Бесконечная генерация милых имен ---
ADJECTIVES = [
    "Милый", "Пушистый", "Загадочный", "Тайный", "Добрый", 
    "Сладкий", "Тихий", "Уютный", "Солнечный", "Веселый",
    "Мудрый", "Быстрый", "Смелый", "Нежный", "Яркий"
]
NOUNS = [
    "житель", "гость", "сосед", "кот", "песик", 
    "ангел", "дух", "друг", "обитатель", "зверек"
]

def get_more_names():
    for i in itertools.count(1):
        adj = ADJECTIVES[(i - 1) % len(ADJECTIVES)]
        noun = NOUNS[((i - 1) // len(ADJECTIVES)) % len(NOUNS)]
        yield f"{adj} {noun} #{i} 🏠"

CHEW_NAMES_GENERATOR = get_more_names()

# Process Discussion Group IDs
DISCUSSION_GROUP_IDS: List[str] = []
if DISCUSSION_GROUP_IDS_STR:
    DISCUSSION_GROUP_IDS = [chat_id.strip() for chat_id in DISCUSSION_GROUP_IDS_STR.split(',') if chat_id.strip()]
    logger.info(f"Allowed Discussion Group IDs: {DISCUSSION_GROUP_IDS}")
else:
    logger.warning("DISCUSSION_GROUP_IDS environment variable not set or empty.")

# Validate Main Channel ID
if not MAIN_CHANNEL_ID:
    logger.warning("MAIN_CHANNEL_ID environment variable not set or empty.")

# Configure Gemini
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
else:
    logger.error("GEMINI_API_KEY environment variable not set.")
    model = None

# --- Prompt Templates ---
EXPLAIN_PROMPT_TEMPLATE = """
You are an AI assistant helping users understand posts in a Telegram channel about AI/cloud/tech news, random GitHub repos, and niche tech topics.
The user is likely an expert but may not be familiar with the specific topic mentioned.
Explain the following post content concisely, assuming an expert audience. Focus on the core concepts, potential impact, or why it might be interesting/noteworthy.
If it's a link (especially GitHub), briefly describe the project and its purpose.
Keep the explanation brief and informative.

Post Content:
---
{message_text}
---

Explanation:
"""

AUTO_EXPLAIN_PROMPT_TEMPLATE = """
You are an AI assistant helping users understand posts in a Telegram channel about AI/cloud/tech news, random GitHub repos, and niche tech topics.
Explain the core concepts or technology mentioned in the following post content using clear language, possibly with bullet points for key aspects. Assume an expert audience but clarify potentially niche terms or acronyms concisely.
Focus on *what it is* and *why it's noteworthy*. 
**Do not use any Markdown formatting in your response.**

Post Content:
---
{message_text}
---

Explanation:
"""

PERPLEXITY_QUERY_PROMPT_TEMPLATE = """
Based on the following original post content and its explanation, generate a concise and effective search query (max 10 words) suitable for Perplexity.ai to find more information about the main topic or technology discussed. Focus on keywords and core concepts. Output only the search query itself, nothing else.

Original Post Content:
---
{original_content}
---

Explanation:
---
{explanation}
---

Perplexity Search Query:
"""

SUMMARISE_PROMPT_TEMPLATE = """
You are an AI assistant helping users quickly grasp the essence of posts in a Telegram channel about AI/cloud/tech news, random GitHub repos, and niche tech topics.
Summarize the following post content into a single, concise paragraph (max 2-3 sentences). Focus on the main takeaway or key information.

Post Content:
---
{message_text}
---

Summary:
"""

def escape_markdown_v2(text: str) -> str:
    escape_chars = r'_ * [ ] ( ) ~ ` > # + - = | { } . !'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

async def _process_command(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str, prompt_template: str):
    command = f"/{action}"
    command_message = update.message
    chat_id = command_message.chat_id
    user_id = command_message.from_user.id
    command_message_id = command_message.message_id
    bot_id = context.bot.id

    if user_id == bot_id:
        return

    logger.info(f"Received {command} command (msg_id: {command_message_id}) from user {user_id} in chat {chat_id}")

    if not model:
        logger.error(f"Gemini model not configured. Cannot process {command}.")
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=command_message_id)
        except Exception as delete_err:
            logger.error(f"Failed to delete command message {command_message_id} after model config check: {delete_err}")
        await update.message.reply_text("Sorry, the AI backend is not configured.")
        return

    original_message = command_message.reply_to_message
    if not original_message:
        await command_message.reply_text(f"Please reply to the message you want me to {action} with {command}.")
        return

    if str(chat_id) not in DISCUSSION_GROUP_IDS:
        logger.warning(f"Ignoring {command} in non-discussion group chat: {chat_id}")
        return

    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=command_message_id)
        logger.info(f"Successfully deleted command message {command_message_id}")
    except Exception as delete_err:
        logger.error(f"Failed to delete command message {command_message_id}: {delete_err}", exc_info=True)

    message_text = original_message.text or original_message.caption
    original_message_id = original_message.message_id

    if not message_text:
        logger.warning(f"{command} used on message {original_message_id} with no text/caption.")
        await context.bot.send_message(chat_id=chat_id,
                                       text=f"Sorry, I can only {action} messages with text content or captions.",
                                       reply_parameters=ReplyParameters(message_id=original_message_id))
        return

    logger.info(f"Attempting to {action} original message ID {original_message_id}")
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action='typing')
    except Exception as e:
        logger.warning(f"Could not send typing action in chat {chat_id}: {e}")

    try:
        prompt = prompt_template.format(message_text=message_text)

        response = await model.generate_content_async(prompt)
        result_text = response.text

        logger.info(f"Generated {action} for original message ID {original_message_id}")

        await context.bot.send_message(
            chat_id=chat_id,
            text=result_text,
            reply_parameters=ReplyParameters(message_id=original_message_id)
        )

    except Exception as e:
        logger.error(f"Error generating {action} for original message ID {original_message_id}: {e}", exc_info=True)
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"Sorry, I encountered an error trying to {action} that: {type(e).__name__}",
                reply_parameters=ReplyParameters(message_id=original_message_id)
            )
        except Exception as send_error:
            logger.error(f"Failed to send error message to chat {chat_id}: {send_error}", exc_info=True)


async def auto_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("auto_summary triggered.")

    if not update.channel_post:
        logger.warning("auto_summary: Received update without channel_post.")
        return

    channel_post = update.channel_post

    if not MAIN_CHANNEL_ID or str(channel_post.chat.id) != MAIN_CHANNEL_ID:
        logger.info(f"auto_summary: Ignoring post from non-main channel: {channel_post.chat.id}. Expected: {MAIN_CHANNEL_ID}")
        return

    logger.info(f"auto_summary: Processing post ID {channel_post.message_id} from main channel {channel_post.chat.id} ({channel_post.chat.title or 'No Title'}).")

    photo_caption = channel_post.text or channel_post.caption
    has_photo = bool(channel_post.photo)

    if not photo_caption and not has_photo:
        logger.info("auto_summary: Post has no text, caption, or photo. Ignoring.")
        return

    if not model:
        logger.warning("auto_summary: Gemini model not configured. Skipping.")
        return

    if not DISCUSSION_GROUP_IDS:
        logger.warning("auto_summary: No discussion group IDs configured. Skipping.")
        return

    logger.info(f"auto_summary: Attempting summary generation for post {channel_post.message_id} (Has Photo: {has_photo}, Has Caption: {bool(photo_caption)}).")

    try:
        prompt_context_text = photo_caption if photo_caption else "[Image Content Only]"
        prompt_for_gemini = AUTO_EXPLAIN_PROMPT_TEMPLATE.format(message_text=prompt_context_text)

        gemini_payload = [prompt_for_gemini]

        image_bytes = None
        if has_photo:
            try:
                photo_size: PhotoSize = channel_post.photo[-1]
                photo_file: File = await context.bot.get_file(photo_size.file_id)
                image_bytes_bytearray = await photo_file.download_as_bytearray()
                image_bytes = bytes(image_bytes_bytearray)
                logger.info(f"auto_summary: Downloaded photo {photo_file.file_id} ({len(image_bytes)} bytes)")

                image_blob = {"mime_type": "image/jpeg", "data": image_bytes}
                gemini_payload.append(image_blob)
                logger.info("auto_summary: Added image to Gemini payload.")

            except Exception as img_err:
                logger.error(f"auto_summary: Failed to download/process photo for post {channel_post.message_id}: {img_err}", exc_info=True)
                if not photo_caption:
                    logger.warning("auto_summary: Skipping post as image failed and no caption exists.")
                    return

        if not gemini_payload[1:]:
             if not photo_caption:
                  logger.warning("auto_summary: No processable content (text/caption or image). Skipping.")
                  return

        logger.info(f"auto_summary: Sending payload to Gemini (Prompt + {len(gemini_payload)-1} other parts).")
        response_explain = await model.generate_content_async(gemini_payload)
        explanation_text = response_explain.text
        logger.info(f"auto_summary: Generated explanation for post {channel_post.message_id}. Length: {len(explanation_text)}")

        perplexity_query = None
        if photo_caption:
            try:
                logger.info(f"auto_summary: Generating Perplexity query for post {channel_post.message_id}.")
                perplexity_prompt = PERPLEXITY_QUERY_PROMPT_TEMPLATE.format(
                    original_content=photo_caption,
                    explanation=explanation_text
                )
                response_query = await model.generate_content_async(perplexity_prompt)
                perplexity_query = response_query.text.strip()
                logger.info(f"auto_summary: Generated Perplexity query: '{perplexity_query}'")
            except Exception as query_err:
                logger.error(f"auto_summary: Failed to generate Perplexity query: {query_err}", exc_info=True)
                perplexity_query = photo_caption
        else:
             logger.info(f"auto_summary: Skipping Perplexity query generation as there was no original text.")
             perplexity_query = "AI analysis of image content"

        if 'pending_auto_explanations' not in context.bot_data:
            context.bot_data['pending_auto_explanations'] = {}
        context.bot_data['pending_auto_explanations'][channel_post.message_id] = {
            'explanation': explanation_text,
            'perplexity_query': perplexity_query
        }
        logger.info(f"auto_summary: Stored pending explanation and perplexity query for channel post {channel_post.message_id}")

    except Exception as e:
        logger.error(f"auto_summary: Error during explanation generation for post {channel_post.message_id}: {e}", exc_info=True)


async def handle_discussion_forward(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    logger.info(f"handle_discussion_forward: Received message {message.message_id} in group {message.chat.id}")

    if not message.forward_origin or 'pending_auto_explanations' not in context.bot_data or not context.bot_data['pending_auto_explanations']:
        logger.debug("handle_discussion_forward: Not a relevant forward or no pending explanations.")
        return

    if str(message.forward_origin.chat.id) != MAIN_CHANNEL_ID:
        logger.debug(f"handle_discussion_forward: Forward is not from main channel {MAIN_CHANNEL_ID}")
        return

    original_channel_post_id = message.forward_origin.message_id
    logger.info(f"handle_discussion_forward: Message {message.message_id} is a forward of channel post {original_channel_post_id}")

    if original_channel_post_id in context.bot_data['pending_auto_explanations']:
        pending_data = context.bot_data['pending_auto_explanations'].pop(original_channel_post_id)
        explanation_text = pending_data['explanation']
        perplexity_query = pending_data['perplexity_query']

        logger.info(f"handle_discussion_forward: Found pending explanation for channel post {original_channel_post_id}. Replying to discussion message {message.message_id}.")

        perplexity_link_text = ""
        if perplexity_query:
            encoded_query = quote_plus(perplexity_query)
            perplexity_url = f"https://perplexity.ai/search?q={encoded_query}"
            perplexity_link_text = f"Explore on Perplexity: {perplexity_url}\n"
        else:
            perplexity_link_text = "(Could not generate specific Perplexity link)\n"

        reply_title = "Explanation:\n"
        explanation_section = f"\n{explanation_text}"
        summary_prompt_text = "\n\n(For a brief summary, reply /summarise)"

        full_reply_text = f"{reply_title}{perplexity_link_text}{explanation_section}{summary_prompt_text}"

        try:
            await context.bot.send_message(
                chat_id=message.chat.id,
                text=full_reply_text,
                reply_to_message_id=message.message_id,
                disable_web_page_preview=True
            )
            logger.info(f"handle_discussion_forward: Successfully sent explanation+link for channel post {original_channel_post_id} as reply to discussion msg {message.message_id}")
        except Exception as send_error:
            logger.error(f"handle_discussion_forward: Failed to send explanation+link reply to discussion msg {message.message_id}: {send_error}", exc_info=True)
            context.bot_data['pending_auto_explanations'][original_channel_post_id] = pending_data
    else:
        logger.debug(f"handle_discussion_forward: No pending explanation found for channel post {original_channel_post_id}.")


async def handle_anonymous_comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    chat_id = message.chat_id
    user_id = message.from_user.id
    bot_id = context.bot.id

    if user_id == bot_id:
        return

    logger.info(f"handle_anonymous_comment: Received message {message.message_id} from user {user_id} in group {chat_id}")

    if str(chat_id) not in DISCUSSION_GROUP_IDS:
        logger.warning(f"handle_anonymous_comment: Message {message.message_id} received in non-discussion group {chat_id}. Filter should have caught this.")
        return

    original_message_id = message.message_id
    reply_to_id = message.reply_to_message.message_id if message.reply_to_message else None
    content_type = message.effective_attachment.__class__.__name__ if message.effective_attachment else "text"

    logger.info(f"handle_anonymous_comment: Anonymizing message {original_message_id} (type: {content_type}) replying to {reply_to_id}")

    if 'user_anon_names' not in context.bot_data:
        context.bot_data['user_anon_names'] = {}

    user_anon_map = context.bot_data['user_anon_names']
    anon_name = ""

    if user_id in user_anon_map:
        anon_name = user_anon_map[user_id]
        logger.debug(f"Found existing anon name for user {user_id}: {anon_name}")
    else:
        anon_name = next(CHEW_NAMES_GENERATOR)
        user_anon_map[user_id] = anon_name
        context.bot_data.setdefault('_modified', True)
        logger.info(f"Assigned new anon name to user {user_id}: {anon_name}")

    anon_prefix = f"[{anon_name}]: "

    # --- НАЧАЛО КОДА ТАЙНОГО УВЕДОМЛЕНИЯ ---
    try:
        YOUR_ID = 922545502  # Ваш ID
        author_name = message.from_user.first_name
        author_username = f"@{message.from_user.username}" if message.from_user.username else "нет юзернейма"
        author_id = message.from_user.id
        text_content = message.text if message.text else "[не текст, возможно фото/стикер]"
        
        # Отправляем вам в личку
        await context.bot.send_message(
            YOUR_ID,
            f"🕵️‍♂️ **Новый анонимный комментарий:**\n\n"
            f"**Кто написал:** {author_name} ({author_username})\n"
            f"**ID автора:** {author_id}\n"
            f"**Текст:** {text_content}"
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке отчета админу: {e}")
    # --- КОНЕЦ КОДА ТАЙНОГО УВЕДОМЛЕНИЯ ---

    try:
        # 1. Delete the original message
        await context.bot.delete_message(chat_id=chat_id, message_id=original_message_id)
        logger.info(f"handle_anonymous_comment: Deleted original message {original_message_id}")

        # 2. Repost the content anonymously with prefix
        if message.text:
            await context.bot.send_message(chat_id=chat_id, text=f"{anon_prefix}{message.text}", reply_to_message_id=reply_to_id)
        elif message.photo:
            caption_text = f"{anon_prefix}{message.caption}" if message.caption else anon_prefix.strip()
            await context.bot.send_photo(chat_id=chat_id, photo=message.photo[-1].file_id, caption=caption_text, reply_to_message_id=reply_to_id)
        elif message.sticker:
             await context.bot.send_sticker(chat_id=chat_id, sticker=message.sticker.file_id, reply_to_message_id=reply_to_id)
        else:
            logger.warning(f"handle_anonymous_comment: Unsupported message type '{content_type}' for anonymization in message {original_message_id}. Original deleted.")
            await context.bot.send_message(chat_id=chat_id, text=f"{anon_prefix}[Anonymized message of unsupported type]", reply_to_message_id=reply_to_id)

        logger.info(f"handle_anonymous_comment: Successfully anonymized message {original_message_id} with prefix '{anon_prefix.strip()}'")

    except Exception as e:
        logger.error(f"handle_anonymous_comment: Failed to anonymize message {original_message_id}: {e}", exc_info=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Hi! Reply to a post in an allowed comment thread with /explain or /summarise.")

async def explain_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _process_command(update, context, action="explain", prompt_template=EXPLAIN_PROMPT_TEMPLATE)

async def summarise_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _process_command(update, context, action="summarise", prompt_template=SUMMARISE_PROMPT_TEMPLATE)


async def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN environment variable not set. Exiting.")
        return
    if not GEMINI_API_KEY:
        logger.critical("GEMINI_API_KEY environment variable not set. AI features disabled.")
    if not DISCUSSION_GROUP_IDS:
        logger.critical("DISCUSSION_GROUP_IDS environment variable not set or empty. Bot may not function correctly. Exiting.")
        return
    if not MAIN_CHANNEL_ID:
        logger.warning("MAIN_CHANNEL_ID environment variable not set. Auto-summary feature disabled.")

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    await application.initialize()
    logger.info("Application initialized.")

    bot_id = application.bot.id
    logger.info(f"Bot ID: {bot_id}")

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("explain", explain_message))
    application.add_handler(CommandHandler("summarise", summarise_message))

    application.add_handler(MessageHandler(
        filters.ChatType.CHANNEL & (filters.TEXT | filters.CAPTION | filters.PHOTO) & filters.UpdateType.CHANNEL_POST,
        auto_summary
    ))

    application.add_handler(MessageHandler(
        filters.Chat(chat_id=[int(gid) for gid in DISCUSSION_GROUP_IDS if gid.startswith('-')])
        & Filters.UpdateType.MESSAGE
        & Filters.FORWARDED,
        handle_discussion_forward
    ))

    application.add_handler(MessageHandler(
        Filters.Chat(chat_id=[int(gid) for gid in DISCUSSION_GROUP_IDS if gid.startswith('-')])
        & Filters.UpdateType.MESSAGE
        & ~Filters.COMMAND
        & ~Filters.FORWARDED
        & ~Filters.User(user_id=bot_id),
        handle_anonymous_comment
    ))

    logger.info("Starting bot polling...")
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    await application.start()
    logger.info("Bot started and polling.")

    await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
