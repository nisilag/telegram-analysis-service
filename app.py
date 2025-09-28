"""
Main application orchestrator for the Telegram analysis service.
"""
import asyncio
import signal
import sys
from datetime import datetime

from loguru import logger

from config import config
from store import DatabaseStore
from tg_client import TelegramClientWrapper
from ingest import IngestionEngine
from bot_commands import TelegramBot


class TelegramAnalysisService:
    """Main service orchestrator."""
    
    def __init__(self):
        self.store = None
        self.tg_client = None
        self.ingestion_engine = None
        self.bot = None
        self._shutdown_event = asyncio.Event()
        
    async def initialize(self):
        """Initialize all service components."""
        logger.info("Initializing Telegram Analysis Service...")
        
        # Initialize database store
        logger.info("Initializing database...")
        self.store = DatabaseStore()
        await self.store.initialize()
        
        # Initialize Telegram client
        logger.info("Initializing Telegram client...")
        self.tg_client = TelegramClientWrapper()
        await self.tg_client.initialize()
        
        # Validate chat access
        success, message = await self.tg_client.validate_chat_access()
        if not success:
            logger.error(f"Cannot access target chat: {message}")
            raise RuntimeError(f"Chat access validation failed: {message}")
        logger.info(f"Chat access validated: {message}")
        
        # Initialize ingestion engine
        logger.info("Initializing ingestion engine...")
        self.ingestion_engine = IngestionEngine(self.tg_client, self.store)
        await self.ingestion_engine.initialize()
        
        # Initialize bot (optional)
        if config.bot_token:
            logger.info("Initializing Telegram bot...")
            self.bot = TelegramBot(self.store, self.ingestion_engine)
            await self.bot.initialize()
        else:
            logger.info("No bot token provided, bot commands will not be available")
        
        logger.info("Service initialization completed successfully")
    
    async def start(self):
        """Start the service."""
        logger.info("Starting Telegram Analysis Service...")
        
        try:
            # Set up signal handlers for graceful shutdown
            self._setup_signal_handlers()
            
            # Start bot if available
            if self.bot:
                await self.bot.start_bot()
            
            # Start ingestion (this will block until shutdown)
            ingestion_task = asyncio.create_task(self.ingestion_engine.start_ingestion())
            shutdown_task = asyncio.create_task(self._wait_for_shutdown())
            
            # Wait for either ingestion to complete or shutdown signal
            done, pending = await asyncio.wait(
                [ingestion_task, shutdown_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # Cancel pending tasks
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            
            logger.info("Service stopped")
            
        except Exception as e:
            logger.error(f"Error in service execution: {e}")
            raise
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        """Gracefully shutdown all components."""
        logger.info("Shutting down service...")
        
        try:
            # Stop ingestion
            if self.ingestion_engine:
                await self.ingestion_engine.stop_ingestion()
            
            # Stop bot
            if self.bot:
                await self.bot.stop_bot()
            
            # Disconnect Telegram client
            if self.tg_client:
                await self.tg_client.disconnect()
            
            # Close database
            if self.store:
                await self.store.close()
            
            logger.info("Service shutdown completed")
            
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
    
    def _setup_signal_handlers(self):
        """Set up signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating shutdown...")
            self._shutdown_event.set()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    async def _wait_for_shutdown(self):
        """Wait for shutdown signal."""
        await self._shutdown_event.wait()


async def main():
    """Main entry point."""
    # Configure logging
    logger.remove()  # Remove default handler
    
    log_format = "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    
    # Console logging
    logger.add(
        sys.stderr,
        format=log_format,
        level=config.log_level,
        colorize=True
    )
    
    # File logging (if configured)
    if config.log_file:
        logger.add(
            config.log_file,
            format=log_format,
            level=config.log_level,
            rotation="10 MB",
            retention="7 days",
            compression="gz"
        )
    
    logger.info("Starting Telegram Analysis Service")
    logger.info(f"Configuration: chat_id={config.target_chat_id}, db_url={config.db_url}")
    
    # Create and run service
    service = TelegramAnalysisService()
    
    try:
        await service.initialize()
        await service.start()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Service failed: {e}")
        sys.exit(1)
    finally:
        await service.shutdown()


if __name__ == "__main__":
    # Use uvloop if available for better performance
    try:
        import uvloop
        uvloop.install()
        logger.info("Using uvloop for better performance")
    except ImportError:
        logger.info("uvloop not available, using default event loop")
    
    # Run the service
    asyncio.run(main())
