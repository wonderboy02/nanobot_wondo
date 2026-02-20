"""Telegram channel implementation using python-telegram-bot."""

import asyncio
import json
import re
import time
from pathlib import Path

from loguru import logger
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import TelegramConfig


def _markdown_to_telegram_html(text: str) -> str:
    """
    Convert markdown to Telegram-safe HTML.
    """
    if not text:
        return ""
    
    # 1. Extract and protect code blocks (preserve content from other processing)
    code_blocks: list[str] = []
    def save_code_block(m: re.Match) -> str:
        code_blocks.append(m.group(1))
        return f"\x00CB{len(code_blocks) - 1}\x00"
    
    text = re.sub(r'```[\w]*\n?([\s\S]*?)```', save_code_block, text)
    
    # 2. Extract and protect inline code
    inline_codes: list[str] = []
    def save_inline_code(m: re.Match) -> str:
        inline_codes.append(m.group(1))
        return f"\x00IC{len(inline_codes) - 1}\x00"
    
    text = re.sub(r'`([^`]+)`', save_inline_code, text)
    
    # 3. Headers # Title -> just the title text
    text = re.sub(r'^#{1,6}\s+(.+)$', r'\1', text, flags=re.MULTILINE)
    
    # 4. Blockquotes > text -> just the text (before HTML escaping)
    text = re.sub(r'^>\s*(.*)$', r'\1', text, flags=re.MULTILINE)
    
    # 5. Escape HTML special characters
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    
    # 6. Links [text](url) - must be before bold/italic to handle nested cases
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    
    # 7. Bold **text** or __text__
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)
    
    # 8. Italic _text_ (avoid matching inside words like some_var_name)
    text = re.sub(r'(?<![a-zA-Z0-9])_([^_]+)_(?![a-zA-Z0-9])', r'<i>\1</i>', text)
    
    # 9. Strikethrough ~~text~~
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text)
    
    # 10. Bullet lists - item -> • item
    text = re.sub(r'^[-*]\s+', '• ', text, flags=re.MULTILINE)
    
    # 11. Restore inline code with HTML tags
    for i, code in enumerate(inline_codes):
        # Escape HTML in code content
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00IC{i}\x00", f"<code>{escaped}</code>")
    
    # 12. Restore code blocks with HTML tags
    for i, code in enumerate(code_blocks):
        # Escape HTML in code content
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00CB{i}\x00", f"<pre><code>{escaped}</code></pre>")
    
    return text


class TelegramChannel(BaseChannel):
    """
    Telegram channel using long polling.
    
    Simple and reliable - no webhook/public IP needed.
    """
    
    name = "telegram"
    
    _CACHE_TTL = 3600  # 1 hour
    _CACHE_MAX_SIZE = 100

    def __init__(
        self,
        config: TelegramConfig,
        bus: MessageBus,
        groq_api_key: str = "",
        workspace: Path | None = None,
    ):
        super().__init__(config, bus)
        self.config: TelegramConfig = config
        self.groq_api_key = groq_api_key
        self.workspace = workspace
        self._app: Application | None = None
        self._chat_ids: dict[str, int] = {}  # Map sender_id to chat_id for replies
        # Question cache: {chat_id: {"mapping": {number: question_id}, "created_at": float}}
        self._question_cache: dict[int, dict] = {}
    
    async def start(self) -> None:
        """Start the Telegram bot with long polling."""
        if not self.config.token:
            logger.error("Telegram bot token not configured")
            return
        
        self._running = True
        
        # Build the application
        self._app = (
            Application.builder()
            .token(self.config.token)
            .build()
        )
        
        # Add message handler for text, photos, voice, documents
        self._app.add_handler(
            MessageHandler(
                (filters.TEXT | filters.PHOTO | filters.VOICE | filters.AUDIO | filters.Document.ALL) 
                & ~filters.COMMAND, 
                self._on_message
            )
        )
        
        # Add command handlers
        self._app.add_handler(CommandHandler("start", self._on_start))
        self._app.add_handler(CommandHandler("questions", self._on_questions))
        self._app.add_handler(CommandHandler("tasks", self._on_tasks))
        
        logger.info("Starting Telegram bot (polling mode)...")
        
        # Initialize and start polling
        await self._app.initialize()
        await self._app.start()
        
        # Get bot info
        bot_info = await self._app.bot.get_me()
        logger.info(f"Telegram bot @{bot_info.username} connected")
        
        # Start polling (this runs until stopped)
        await self._app.updater.start_polling(
            allowed_updates=["message"],
            drop_pending_updates=True  # Ignore old messages on startup
        )
        
        # Keep running until stopped
        while self._running:
            await asyncio.sleep(1)
    
    async def stop(self) -> None:
        """Stop the Telegram bot."""
        self._running = False
        
        if self._app:
            logger.info("Stopping Telegram bot...")
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            self._app = None
    
    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Telegram."""
        if not self._app:
            logger.warning("Telegram bot not running")
            return
        
        try:
            # chat_id should be the Telegram chat ID (integer)
            chat_id = int(msg.chat_id)
            # Convert markdown to Telegram HTML
            html_content = _markdown_to_telegram_html(msg.content)
            await self._app.bot.send_message(
                chat_id=chat_id,
                text=html_content,
                parse_mode="HTML"
            )
        except ValueError:
            logger.error(f"Invalid chat_id: {msg.chat_id}")
        except Exception as e:
            # Fallback to plain text if HTML parsing fails
            logger.warning(f"HTML parse failed, falling back to plain text: {e}")
            try:
                await self._app.bot.send_message(
                    chat_id=int(msg.chat_id),
                    text=msg.content
                )
            except Exception as e2:
                logger.error(f"Error sending Telegram message: {e2}")
    
    async def _on_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        if not update.message or not update.effective_user:
            return
        
        user = update.effective_user
        await update.message.reply_text(
            f"👋 Hi {user.first_name}! I'm nanobot.\n\n"
            "Send me a message and I'll respond!"
        )
    
    async def _on_questions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /questions command — show unanswered questions with numbered mapping."""
        if not update.message or not update.effective_user:
            return

        user = update.effective_user
        sender_id = str(user.id)
        if user.username:
            sender_id = f"{sender_id}|{user.username}"

        if not self.is_allowed(sender_id):
            return

        chat_id = update.message.chat_id

        if not self.workspace:
            await update.message.reply_text("Workspace not configured.")
            return

        # Load questions.json
        questions_path = self.workspace / "dashboard" / "questions.json"
        if not questions_path.exists():
            await update.message.reply_text("No questions yet.")
            return

        try:
            data = json.loads(questions_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to read questions.json: {e}")
            await update.message.reply_text("Failed to read questions.")
            return

        # Filter unanswered questions
        unanswered = [q for q in data.get("questions", []) if not q.get("answered")]

        if not unanswered:
            await update.message.reply_text("No unanswered questions! 🎉")
            return

        # Build numbered mapping and display
        mapping: dict[int, str] = {}
        lines = ["📋 <b>Unanswered Questions</b>\n"]
        for i, q in enumerate(unanswered, start=1):
            q_id = q.get("id", "?")
            question_text = q.get("question", "")
            priority = q.get("priority", "")
            related = q.get("related_task_id", "")

            mapping[i] = q_id
            line = f"<b>{i}.</b> {question_text}"
            if priority:
                line += f"  [{priority}]"
            if related:
                line += f"  (→{related})"
            lines.append(line)

        lines.append("\n💡 번호로 답변하세요 (예: 1. 답변)")

        # Save to cache (one-time use)
        self._evict_cache()
        self._question_cache[chat_id] = {
            "mapping": mapping,
            "created_at": time.time(),
        }

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    async def _on_tasks(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /tasks command — show active tasks."""
        if not update.message or not update.effective_user:
            return

        user = update.effective_user
        sender_id = str(user.id)
        if user.username:
            sender_id = f"{sender_id}|{user.username}"

        if not self.is_allowed(sender_id):
            return

        if not self.workspace:
            await update.message.reply_text("Workspace not configured.")
            return

        # Load tasks.json
        tasks_path = self.workspace / "dashboard" / "tasks.json"
        if not tasks_path.exists():
            await update.message.reply_text("No tasks yet.")
            return

        try:
            data = json.loads(tasks_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to read tasks.json: {e}")
            await update.message.reply_text("Failed to read tasks.")
            return

        # Filter active tasks
        active = [t for t in data.get("tasks", []) if t.get("status") == "active"]

        if not active:
            await update.message.reply_text("No active tasks.")
            return

        lines = ["📋 <b>Active Tasks</b>\n"]
        for t in active:
            t_id = t.get("id", "?")
            title = t.get("title", "")
            raw_progress = t.get("progress", 0)
            if isinstance(raw_progress, dict):
                pct = raw_progress.get("percentage", 0)
            else:
                pct = raw_progress
            priority = t.get("priority", "")
            blocked = raw_progress.get("blocked", False) if isinstance(raw_progress, dict) else False

            line = f"• <b>{title}</b> ({pct}%)"
            if priority:
                line += f"  [{priority}]"
            if blocked:
                line += " ⚠️ Blocked"
            line += f"\n  <code>{t_id}</code>"
            lines.append(line)

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    @staticmethod
    def _parse_numbered_answers(
        text: str, mapping: dict[int, str]
    ) -> tuple[dict[str, str], list[str]]:
        """Parse numbered answers from text using a mapping of number→question_id.

        Pattern: line starts with a digit followed by a separator (. ) : or space).
        Lines that don't match are appended to the previous answer (multi-line support).

        Returns:
            (numbered_answers: {question_id: answer}, unmatched_lines: [str])
        """
        pattern = re.compile(r"^(\d+)[.):\s]\s*(.*)", re.DOTALL)
        numbered: dict[str, str] = {}
        unmatched: list[str] = []
        last_qid: str | None = None

        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue

            m = pattern.match(stripped)
            if m:
                num = int(m.group(1))
                answer_text = m.group(2).strip()
                if num in mapping:
                    qid = mapping[num]
                    numbered[qid] = answer_text
                    last_qid = qid
                else:
                    # Number not in mapping — treat as unmatched
                    unmatched.append(stripped)
                    last_qid = None
            elif last_qid is not None:
                # Continuation of previous answer (multi-line)
                numbered[last_qid] += "\n" + stripped
            else:
                unmatched.append(stripped)

        return numbered, unmatched

    def _evict_cache(self) -> None:
        """Remove expired and excess cache entries."""
        now = time.time()
        # Remove expired entries
        expired = [
            cid for cid, entry in self._question_cache.items()
            if now - entry["created_at"] > self._CACHE_TTL
        ]
        for cid in expired:
            del self._question_cache[cid]

        # Evict oldest if over size limit
        while len(self._question_cache) > self._CACHE_MAX_SIZE:
            oldest_cid = min(
                self._question_cache, key=lambda c: self._question_cache[c]["created_at"]
            )
            del self._question_cache[oldest_cid]

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming messages (text, photos, voice, documents)."""
        if not update.message or not update.effective_user:
            return
        
        message = update.message
        user = update.effective_user
        chat_id = message.chat_id
        
        # Use stable numeric ID, but keep username for allowlist compatibility
        sender_id = str(user.id)
        if user.username:
            sender_id = f"{sender_id}|{user.username}"
        
        # Store chat_id for replies
        self._chat_ids[sender_id] = chat_id
        
        # Build content from text and/or media
        content_parts = []
        media_paths = []
        
        # Text content
        if message.text:
            content_parts.append(message.text)
        if message.caption:
            content_parts.append(message.caption)
        
        # Handle media files
        media_file = None
        media_type = None
        
        if message.photo:
            media_file = message.photo[-1]  # Largest photo
            media_type = "image"
        elif message.voice:
            media_file = message.voice
            media_type = "voice"
        elif message.audio:
            media_file = message.audio
            media_type = "audio"
        elif message.document:
            media_file = message.document
            media_type = "file"
        
        # Download media if present
        if media_file and self._app:
            try:
                file = await self._app.bot.get_file(media_file.file_id)
                ext = self._get_extension(media_type, getattr(media_file, 'mime_type', None))
                
                # Save to workspace/media/
                media_dir = Path.home() / ".nanobot" / "media"
                media_dir.mkdir(parents=True, exist_ok=True)
                
                file_path = media_dir / f"{media_file.file_id[:16]}{ext}"
                await file.download_to_drive(str(file_path))
                
                media_paths.append(str(file_path))
                
                # Handle voice transcription
                if media_type == "voice" or media_type == "audio":
                    from nanobot.providers.transcription import GroqTranscriptionProvider
                    transcriber = GroqTranscriptionProvider(api_key=self.groq_api_key)
                    transcription = await transcriber.transcribe(file_path)
                    if transcription:
                        logger.info(f"Transcribed {media_type}: {transcription[:50]}...")
                        content_parts.append(f"[transcription: {transcription}]")
                    else:
                        content_parts.append(f"[{media_type}: {file_path}]")
                else:
                    content_parts.append(f"[{media_type}: {file_path}]")
                    
                logger.debug(f"Downloaded {media_type} to {file_path}")
            except Exception as e:
                logger.error(f"Failed to download media: {e}")
                content_parts.append(f"[{media_type}: download failed]")
        
        content = "\n".join(content_parts) if content_parts else "[empty message]"

        logger.debug(f"Telegram message from {sender_id}: {content[:50]}...")

        # Check question cache for numbered answer parsing
        extra_metadata: dict = {}
        cache_entry = self._question_cache.get(chat_id)
        if cache_entry and content != "[empty message]":
            mapping = cache_entry["mapping"]
            answers, unmatched = self._parse_numbered_answers(content, mapping)
            if answers:
                extra_metadata["question_answers"] = answers
                # Replace content with unmatched lines only (or empty note)
                content = "\n".join(unmatched) if unmatched else ""
                logger.info(
                    f"Parsed {len(answers)} numbered answer(s), "
                    f"{len(unmatched)} unmatched line(s)"
                )
            # One-time use: always delete cache after attempt
            del self._question_cache[chat_id]

        # Forward to the message bus
        await self._handle_message(
            sender_id=sender_id,
            chat_id=str(chat_id),
            content=content,
            media=media_paths,
            metadata={
                "message_id": message.message_id,
                "user_id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "is_group": message.chat.type != "private",
                **extra_metadata,
            }
        )
    
    def _get_extension(self, media_type: str, mime_type: str | None) -> str:
        """Get file extension based on media type."""
        if mime_type:
            ext_map = {
                "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
                "audio/ogg": ".ogg", "audio/mpeg": ".mp3", "audio/mp4": ".m4a",
            }
            if mime_type in ext_map:
                return ext_map[mime_type]
        
        type_map = {"image": ".jpg", "voice": ".ogg", "audio": ".mp3", "file": ""}
        return type_map.get(media_type, "")
