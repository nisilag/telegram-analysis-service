#!/usr/bin/env python3
"""
Telegram authentication script for Docker environment.
Run this once to create the session file, then use it in the main app.
"""
import asyncio
import sys
from telethon import TelegramClient
from config import config

async def authenticate():
    """Authenticate with Telegram and create session file."""
    print("🔐 Starting Telegram authentication...")
    print(f"📱 API ID: {config.telegram_api_id}")
    print(f"📁 Session path: {config.telethon_session_path}")
    
    client = TelegramClient(config.telethon_session_path, config.telegram_api_id, config.telegram_api_hash)
    
    try:
        # Start with interactive authentication
        await client.start()
        
        # Test the connection
        me = await client.get_me()
        print(f"✅ Authentication successful!")
        print(f"👤 Logged in as: {me.first_name} {me.last_name or ''} (@{me.username or 'no username'})")
        print(f"📞 Phone: {me.phone}")
        
        # Test chat access
        try:
            entity = await client.get_entity(config.target_chat_id)
            print(f"✅ Can access target chat: {getattr(entity, 'title', 'Unknown')} (ID: {config.target_chat_id})")
        except Exception as e:
            print(f"⚠️  Warning: Cannot access target chat {config.target_chat_id}: {e}")
            print("   Make sure you have access to this chat/channel")
        
        print(f"💾 Session file created: {config.telethon_session_path}")
        print("🚀 You can now run the main application!")
        
    except Exception as e:
        print(f"❌ Authentication failed: {e}")
        sys.exit(1)
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(authenticate())
