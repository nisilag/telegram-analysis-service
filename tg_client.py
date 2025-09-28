"""
Telegram client wrapper using Telethon for message ingestion.
"""
import asyncio
from datetime import datetime, timezone
from typing import List, Optional, AsyncGenerator, Tuple
from urllib.parse import urlparse

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, ChannelPrivateError, ChatAdminRequiredError
from telethon.tl.types import Message, User, Channel, Chat
from loguru import logger

from models import TelegramMessage, HighWaterMark
from config import config


class TelegramClientWrapper:
    """Wrapper around Telethon client with rate limiting and error handling."""
    
    def __init__(self, api_id: int = None, api_hash: str = None, session_path: str = None):
        self.api_id = api_id or config.telegram_api_id
        self.api_hash = api_hash or config.telegram_api_hash
        self.session_path = session_path or config.telethon_session_path
        self.client = None
        self.target_chat_id = config.target_chat_id
        self._rate_limit_delay = config.rate_limit_delay
        
    async def initialize(self):
        """Initialize the Telegram client and connect."""
        self.client = TelegramClient(self.session_path, self.api_id, self.api_hash)
        await self.client.start()
        
        # Verify we can access the target chat
        try:
            entity = await self.client.get_entity(self.target_chat_id)
            logger.info(f"Connected to chat: {getattr(entity, 'title', 'Unknown')} (ID: {self.target_chat_id})")
        except (ChannelPrivateError, ChatAdminRequiredError, ValueError) as e:
            logger.error(f"Cannot access target chat {self.target_chat_id}: {e}")
            raise
            
        logger.info("Telegram client initialized successfully")
    
    async def disconnect(self):
        """Disconnect the Telegram client."""
        if self.client:
            await self.client.disconnect()
            logger.info("Telegram client disconnected")
    
    async def get_current_high_water_mark(self) -> HighWaterMark:
        """Get the current high water mark (latest message) for the target chat."""
        try:
            # Get the latest message
            async for message in self.client.iter_messages(self.target_chat_id, limit=1):
                return HighWaterMark(
                    chat_id=self.target_chat_id,
                    message_id=message.id,
                    ts_utc=message.date.replace(tzinfo=timezone.utc),
                    created_at=datetime.utcnow().replace(tzinfo=timezone.utc)
                )
            
            # If no messages found, return a default
            return HighWaterMark(
                chat_id=self.target_chat_id,
                message_id=0,
                ts_utc=datetime.utcnow().replace(tzinfo=timezone.utc),
                created_at=datetime.utcnow().replace(tzinfo=timezone.utc)
            )
            
        except Exception as e:
            logger.error(f"Error getting high water mark: {e}")
            raise
    
    async def fetch_messages_batch(self, 
                                 min_id: int = 0, 
                                 max_id: Optional[int] = None,
                                 limit: int = 100) -> List[TelegramMessage]:
        """
        Fetch a batch of messages from the target chat.
        
        Args:
            min_id: Minimum message ID (exclusive)
            max_id: Maximum message ID (inclusive), None for latest
            limit: Maximum number of messages to fetch
            
        Returns:
            List of TelegramMessage objects in ascending order by message_id
        """
        messages = []
        
        try:
            # Apply rate limiting
            await asyncio.sleep(self._rate_limit_delay)
            
            # Fetch messages
            async for message in self.client.iter_messages(
                self.target_chat_id,
                min_id=min_id,
                max_id=max_id,
                limit=limit,
                reverse=True  # Get in ascending order
            ):
                if isinstance(message, Message) and message.message:
                    tg_msg = await self._convert_message(message)
                    messages.append(tg_msg)
            
            logger.debug(f"Fetched {len(messages)} messages (min_id={min_id}, max_id={max_id})")
            return messages
            
        except FloodWaitError as e:
            logger.warning(f"Rate limited, waiting {e.seconds} seconds")
            await asyncio.sleep(e.seconds)
            # Retry once after flood wait
            return await self.fetch_messages_batch(min_id, max_id, limit)
            
        except Exception as e:
            logger.error(f"Error fetching messages: {e}")
            raise
    
    async def fetch_messages_in_range(self,
                                    start_date: datetime,
                                    end_date: datetime,
                                    limit: Optional[int] = None) -> List[TelegramMessage]:
        """
        Fetch messages within a specific date range.
        
        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            limit: Maximum number of messages to fetch
            
        Returns:
            List of TelegramMessage objects
        """
        messages = []
        
        try:
            await asyncio.sleep(self._rate_limit_delay)
            
            async for message in self.client.iter_messages(
                self.target_chat_id,
                offset_date=end_date,
                reverse=True,
                limit=limit
            ):
                if isinstance(message, Message) and message.message:
                    # Check if message is within date range
                    msg_date = message.date.replace(tzinfo=timezone.utc)
                    if msg_date < start_date:
                        break
                    if msg_date <= end_date:
                        tg_msg = await self._convert_message(message)
                        messages.append(tg_msg)
            
            logger.debug(f"Fetched {len(messages)} messages in date range {start_date} to {end_date}")
            return messages
            
        except FloodWaitError as e:
            logger.warning(f"Rate limited, waiting {e.seconds} seconds")
            await asyncio.sleep(e.seconds)
            return await self.fetch_messages_in_range(start_date, end_date, limit)
            
        except Exception as e:
            logger.error(f"Error fetching messages in range: {e}")
            raise
    
    async def _convert_message(self, message: Message) -> TelegramMessage:
        """Convert a Telethon Message to our TelegramMessage model."""
        # Extract URLs from message text
        urls = []
        if message.entities:
            for entity in message.entities:
                if hasattr(entity, 'url') and entity.url:
                    urls.append(entity.url)
        
        # Get sender information
        from_user_id = None
        from_username = None
        if message.sender_id:
            from_user_id = message.sender_id
            try:
                sender = await message.get_sender()
                if isinstance(sender, User) and sender.username:
                    from_username = sender.username
            except Exception:
                pass  # Ignore errors getting sender info
        
        # Handle forwarded messages
        is_forwarded = message.forward is not None
        forward_from = None
        if is_forwarded and message.forward:
            if message.forward.from_name:
                forward_from = message.forward.from_name
            elif message.forward.from_id:
                try:
                    forward_entity = await self.client.get_entity(message.forward.from_id)
                    if hasattr(forward_entity, 'title'):
                        forward_from = forward_entity.title
                    elif hasattr(forward_entity, 'username'):
                        forward_from = forward_entity.username
                except Exception:
                    forward_from = str(message.forward.from_id)
        
        return TelegramMessage(
            chat_id=self.target_chat_id,
            message_id=message.id,
            ts_utc=message.date.replace(tzinfo=timezone.utc),
            from_user_id=from_user_id,
            from_username=from_username,
            is_forwarded=is_forwarded,
            forward_from=forward_from,
            text=message.message or "",
            urls=urls,
            reply_to_id=message.reply_to_msg_id,
            edit_date=message.edit_date.replace(tzinfo=timezone.utc) if message.edit_date else None
        )
    
    def add_message_handler(self, handler_func):
        """Add a handler for new incoming messages."""
        @self.client.on(events.NewMessage(chats=self.target_chat_id))
        async def message_handler(event):
            try:
                if event.message and event.message.message:
                    tg_msg = await self._convert_message(event.message)
                    await handler_func(tg_msg)
            except Exception as e:
                logger.error(f"Error in message handler: {e}")
        
        logger.info("Message handler added for live updates")
    
    def add_message_edit_handler(self, handler_func):
        """Add a handler for message edits."""
        @self.client.on(events.MessageEdited(chats=self.target_chat_id))
        async def edit_handler(event):
            try:
                if event.message and event.message.message:
                    tg_msg = await self._convert_message(event.message)
                    await handler_func(tg_msg)
            except Exception as e:
                logger.error(f"Error in edit handler: {e}")
        
        logger.info("Message edit handler added")
    
    async def start_listening(self):
        """Start listening for live messages (blocking)."""
        logger.info("Starting live message listener...")
        await self.client.run_until_disconnected()
    
    async def get_message_by_id(self, message_id: int) -> Optional[TelegramMessage]:
        """Get a specific message by ID."""
        try:
            await asyncio.sleep(self._rate_limit_delay)
            
            message = await self.client.get_messages(self.target_chat_id, ids=message_id)
            if message and isinstance(message, Message) and message.message:
                return await self._convert_message(message)
            return None
            
        except Exception as e:
            logger.error(f"Error getting message {message_id}: {e}")
            return None
    
    async def validate_chat_access(self) -> Tuple[bool, str]:
        """
        Validate that we can access the target chat.
        
        Returns:
            Tuple of (success, error_message)
        """
        try:
            entity = await self.client.get_entity(self.target_chat_id)
            
            # Try to get at least one message to verify read access
            async for message in self.client.iter_messages(entity, limit=1):
                break
            
            chat_title = getattr(entity, 'title', 'Unknown')
            return True, f"Successfully connected to: {chat_title}"
            
        except ChannelPrivateError:
            return False, "Chat is private and bot doesn't have access"
        except ChatAdminRequiredError:
            return False, "Admin rights required for this chat"
        except ValueError as e:
            return False, f"Invalid chat ID or chat not found: {e}"
        except Exception as e:
            return False, f"Unexpected error: {e}"
