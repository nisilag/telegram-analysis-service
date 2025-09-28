"""
Setup and testing utilities for the Telegram Analysis Service.
"""
import asyncio
import sys
from datetime import datetime, timedelta

from config import config
from store import DatabaseStore
from tg_client import TelegramClientWrapper


async def test_database_connection():
    """Test database connection and schema creation."""
    print("🔍 Testing database connection...")
    
    try:
        store = DatabaseStore()
        await store.initialize()
        print("✅ Database connection successful")
        
        # Test basic operations
        from models import IngestCheckpoint
        checkpoint = IngestCheckpoint(
            chat_id=123456789,
            last_message_id=1,
            last_ts_utc=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        await store.update_checkpoint(checkpoint)
        retrieved = await store.get_checkpoint(123456789)
        
        if retrieved and retrieved.last_message_id == 1:
            print("✅ Database operations working")
        else:
            print("❌ Database operations failed")
            
        await store.close()
        
    except Exception as e:
        print(f"❌ Database test failed: {e}")
        return False
    
    return True


async def test_telegram_connection():
    """Test Telegram client connection and chat access."""
    print("🔍 Testing Telegram connection...")
    
    try:
        client = TelegramClientWrapper()
        await client.initialize()
        
        success, message = await client.validate_chat_access()
        if success:
            print(f"✅ Telegram connection successful: {message}")
        else:
            print(f"❌ Telegram connection failed: {message}")
            await client.disconnect()
            return False
        
        # Test fetching a few messages
        hwm = await client.get_current_high_water_mark()
        print(f"✅ High water mark: message_id={hwm.message_id}, ts={hwm.ts_utc}")
        
        await client.disconnect()
        
    except Exception as e:
        print(f"❌ Telegram test failed: {e}")
        return False
    
    return True


async def test_analysis_pipeline():
    """Test the analysis pipeline."""
    print("🔍 Testing analysis pipeline...")
    
    try:
        from analyze import analyzer
        from models import TelegramMessage
        
        await analyzer.initialize()
        print("✅ FinBERT model loaded successfully")
        
        # Test message
        test_message = TelegramMessage(
            chat_id=123456789,
            message_id=1,
            ts_utc=datetime.utcnow(),
            text="$BTC is looking bullish! Great price action and volume. To the moon! 🚀",
            urls=[],
            from_user_id=123,
            from_username="test_user",
            is_forwarded=False,
            forward_from=None,
            reply_to_id=None
        )
        
        analysis = await analyzer.analyze_message(test_message)
        
        print(f"✅ Analysis completed:")
        print(f"   - Investment related: {analysis.is_investment}")
        print(f"   - Sentiment: {analysis.sentiment}")
        print(f"   - Tokens: {analysis.tokens}")
        print(f"   - Topic: {analysis.topic_key}")
        print(f"   - Confidence: {analysis.confidence}")
        
        await analyzer.close()
        
    except Exception as e:
        print(f"❌ Analysis test failed: {e}")
        return False
    
    return True


async def run_diagnostics():
    """Run comprehensive diagnostics."""
    print("🚀 Telegram Analysis Service - Diagnostics")
    print("=" * 50)
    
    # Check configuration
    print(f"📋 Configuration:")
    print(f"   - API ID: {'✅ Set' if config.telegram_api_id else '❌ Missing'}")
    print(f"   - API Hash: {'✅ Set' if config.telegram_api_hash else '❌ Missing'}")
    print(f"   - Target Chat: {config.target_chat_id}")
    print(f"   - Database: {config.db_url}")
    print(f"   - Bot Token: {'✅ Set' if config.bot_token else '❌ Not set (optional)'}")
    print()
    
    if not config.telegram_api_id or not config.telegram_api_hash:
        print("❌ Missing required Telegram credentials. Please check your .env file.")
        return False
    
    # Test components
    tests = [
        ("Database", test_database_connection),
        ("Telegram", test_telegram_connection),
        ("Analysis", test_analysis_pipeline),
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n🧪 Testing {test_name}...")
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} test crashed: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 Test Summary:")
    
    all_passed = True
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"   - {test_name}: {status}")
        if not passed:
            all_passed = False
    
    if all_passed:
        print("\n🎉 All tests passed! Service is ready to run.")
        print("   Run: python app.py")
    else:
        print("\n⚠️  Some tests failed. Please check the configuration and try again.")
    
    return all_passed


async def create_sample_data():
    """Create sample data for testing."""
    print("🔍 Creating sample data for testing...")
    
    try:
        from models import TelegramMessage, MessageAnalysis, SentimentType
        from analyze import analyzer
        
        store = DatabaseStore()
        await store.initialize()
        await analyzer.initialize()
        
        # Sample messages
        sample_messages = [
            {
                "text": "$BTC is pumping hard! Great bullish momentum. 🚀",
                "tokens": ["BTC"],
                "sentiment": SentimentType.BULLISH
            },
            {
                "text": "$ETH looking weak, might dump soon. Bearish signals everywhere.",
                "tokens": ["ETH"],
                "sentiment": SentimentType.BEARISH
            },
            {
                "text": "Market is sideways, no clear direction. Waiting for a breakout.",
                "tokens": [],
                "sentiment": SentimentType.NEUTRAL
            },
            {
                "text": "$SOL $MATIC both showing strong volume. DeFi season incoming!",
                "tokens": ["SOL", "MATIC"],
                "sentiment": SentimentType.BULLISH
            },
            {
                "text": "Just had lunch. Nice weather today! 😊",
                "tokens": [],
                "sentiment": SentimentType.NEUTRAL
            }
        ]
        
        chat_id = config.target_chat_id
        base_time = datetime.utcnow()
        
        for i, sample in enumerate(sample_messages):
            # Create message
            message = TelegramMessage(
                chat_id=chat_id,
                message_id=i + 1,
                ts_utc=base_time - timedelta(hours=i),
                text=sample["text"],
                urls=[],
                from_user_id=123456 + i,
                from_username=f"test_user_{i}",
                is_forwarded=False,
                forward_from=None,
                reply_to_id=None
            )
            
            # Store message
            await store.upsert_message(message)
            
            # Analyze and store analysis
            analysis = await analyzer.analyze_message(message)
            await store.upsert_analysis(analysis)
            
            print(f"   ✅ Created sample message {i + 1}: {sample['text'][:50]}...")
        
        print(f"✅ Created {len(sample_messages)} sample messages")
        
        await analyzer.close()
        await store.close()
        
    except Exception as e:
        print(f"❌ Sample data creation failed: {e}")
        return False
    
    return True


def main():
    """Main CLI interface."""
    if len(sys.argv) < 2:
        print("Usage: python setup.py <command>")
        print("Commands:")
        print("  test     - Run diagnostics")
        print("  sample   - Create sample data")
        return
    
    command = sys.argv[1].lower()
    
    if command == "test":
        asyncio.run(run_diagnostics())
    elif command == "sample":
        asyncio.run(create_sample_data())
    else:
        print(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
