"""
Message ingestion engine with backfill, checkpointing, and overlap re-scanning.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from loguru import logger

from models import TelegramMessage, IngestCheckpoint, HighWaterMark, IngestionStats
from tg_client import TelegramClientWrapper
from store import DatabaseStore
from analyze import analyzer
from config import config


class IngestionEngine:
    """Manages message ingestion with backfill and live processing."""
    
    def __init__(self, tg_client: TelegramClientWrapper, store: DatabaseStore):
        self.tg_client = tg_client
        self.store = store
        self.chat_id = config.target_chat_id
        self.batch_size = config.batch_size
        self.overlap_minutes = config.overlap_minutes
        self.stats = IngestionStats()
        self._running = False
        self._overlap_task = None
        
    async def initialize(self):
        """Initialize the ingestion engine."""
        await analyzer.initialize()
        logger.info("Ingestion engine initialized")
    
    async def start_ingestion(self):
        """Start the complete ingestion process."""
        self._running = True
        
        try:
            # Step 1: Determine high water mark
            logger.info("Determining high water mark...")
            current_hwm = await self.tg_client.get_current_high_water_mark()
            await self.store.set_high_water_mark(current_hwm)
            logger.info(f"High water mark set: message_id={current_hwm.message_id}, ts={current_hwm.ts_utc}")
            
            # Step 2: Perform backfill
            await self._perform_backfill(current_hwm)
            
            # Step 3: Start live listener
            logger.info("Starting live message processing...")
            self.tg_client.add_message_handler(self._handle_new_message)
            self.tg_client.add_message_edit_handler(self._handle_message_edit)
            
            # Step 4: Start overlap re-scan task
            self._overlap_task = asyncio.create_task(self._overlap_rescan_loop())
            
            # Step 5: Start listening (this blocks)
            await self.tg_client.start_listening()
            
        except Exception as e:
            logger.error(f"Error in ingestion process: {e}")
            raise
        finally:
            self._running = False
            if self._overlap_task:
                self._overlap_task.cancel()
    
    async def stop_ingestion(self):
        """Stop the ingestion process."""
        self._running = False
        if self._overlap_task:
            self._overlap_task.cancel()
        logger.info("Ingestion stopped")
    
    async def _perform_backfill(self, high_water_mark: HighWaterMark):
        """Perform backfill from last checkpoint to high water mark."""
        # Get current checkpoint
        checkpoint = await self.store.get_checkpoint(self.chat_id)
        
        if checkpoint:
            start_message_id = checkpoint.last_message_id + 1
            logger.info(f"Resuming from checkpoint: message_id={checkpoint.last_message_id}")
        else:
            start_message_id = 1
            logger.info("No checkpoint found, starting from beginning")
        
        if start_message_id > high_water_mark.message_id:
            logger.info("Already up to date, no backfill needed")
            return
        
        logger.info(f"Starting backfill from message_id={start_message_id} to {high_water_mark.message_id}")
        
        current_id = start_message_id
        total_processed = 0
        
        while current_id <= high_water_mark.message_id and self._running:
            try:
                # Fetch batch of messages
                max_id = min(current_id + self.batch_size - 1, high_water_mark.message_id)
                
                logger.debug(f"Fetching messages {current_id} to {max_id}")
                messages = await self.tg_client.fetch_messages_batch(
                    min_id=current_id - 1,  # min_id is exclusive
                    max_id=max_id,
                    limit=self.batch_size
                )
                
                if not messages:
                    logger.debug(f"No messages found in range {current_id}-{max_id}")
                    current_id = max_id + 1
                    continue
                
                # Process batch
                processed_count = await self._process_message_batch(messages)
                total_processed += processed_count
                
                # Update checkpoint with the last message in this batch
                last_message = max(messages, key=lambda m: m.message_id)
                checkpoint = IngestCheckpoint(
                    chat_id=self.chat_id,
                    last_message_id=last_message.message_id,
                    last_ts_utc=last_message.ts_utc,
                    updated_at=datetime.utcnow()
                )
                await self.store.update_checkpoint(checkpoint)
                
                # Move to next batch
                current_id = last_message.message_id + 1
                
                # Log progress
                if total_processed % 100 == 0:
                    logger.info(f"Backfill progress: {total_processed} messages processed")
                
            except Exception as e:
                logger.error(f"Error in backfill batch {current_id}-{max_id}: {e}")
                # Skip this batch and continue
                current_id = max_id + 1
                await asyncio.sleep(5)  # Brief pause before retrying
        
        logger.info(f"Backfill completed: {total_processed} messages processed")
    
    async def _process_message_batch(self, messages: List[TelegramMessage]) -> int:
        """Process a batch of messages (store + analyze)."""
        processed_count = 0
        
        for message in messages:
            try:
                # Store message
                await self.store.upsert_message(message)
                self.stats.ingested_messages_total += 1
                
                # Analyze message
                analysis = await analyzer.analyze_message(message)
                await self.store.upsert_analysis(analysis)
                self.stats.analyzed_messages_total += 1
                
                processed_count += 1
                
            except Exception as e:
                logger.error(f"Error processing message {message.message_id}: {e}")
        
        return processed_count
    
    async def _handle_new_message(self, message: TelegramMessage):
        """Handle a new incoming message."""
        try:
            logger.debug(f"New message received: {message.message_id}")
            
            # Store and analyze
            await self.store.upsert_message(message)
            analysis = await analyzer.analyze_message(message)
            await self.store.upsert_analysis(analysis)
            
            # Update checkpoint
            checkpoint = IngestCheckpoint(
                chat_id=self.chat_id,
                last_message_id=message.message_id,
                last_ts_utc=message.ts_utc,
                updated_at=datetime.utcnow()
            )
            await self.store.update_checkpoint(checkpoint)
            
            self.stats.ingested_messages_total += 1
            self.stats.analyzed_messages_total += 1
            
        except Exception as e:
            logger.error(f"Error handling new message {message.message_id}: {e}")
    
    async def _handle_message_edit(self, message: TelegramMessage):
        """Handle a message edit."""
        try:
            logger.debug(f"Message edit received: {message.message_id}")
            
            # Update message
            await self.store.upsert_message(message)
            
            # Re-analyze
            analysis = await analyzer.analyze_message(message)
            await self.store.upsert_analysis(analysis)
            
        except Exception as e:
            logger.error(f"Error handling message edit {message.message_id}: {e}")
    
    async def _overlap_rescan_loop(self):
        """Periodically re-scan recent messages to catch edits and late deliveries."""
        while self._running:
            try:
                await asyncio.sleep(self.overlap_minutes * 60)  # Wait for overlap interval
                
                if not self._running:
                    break
                
                logger.info("Starting overlap re-scan...")
                await self._perform_overlap_rescan()
                self.stats.overlap_rescans_total += 1
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in overlap re-scan: {e}")
                await asyncio.sleep(60)  # Wait a minute before retrying
    
    async def _perform_overlap_rescan(self):
        """Perform overlap re-scan for recent messages."""
        # Calculate time range for overlap
        end_time = datetime.utcnow().replace(tzinfo=timezone.utc)
        start_time = end_time - timedelta(minutes=self.overlap_minutes)
        
        logger.debug(f"Overlap re-scan from {start_time} to {end_time}")
        
        try:
            # Fetch messages in the overlap window
            messages = await self.tg_client.fetch_messages_in_range(
                start_time, end_time, limit=1000
            )
            
            if not messages:
                logger.debug("No messages found in overlap window")
                return
            
            # Process messages (this will upsert, so duplicates are handled)
            processed_count = await self._process_message_batch(messages)
            
            # Check for messages that need re-analysis due to edits
            edited_messages = await self.store.get_messages_needing_reanalysis(self.chat_id)
            
            for message_id, edit_date in edited_messages:
                # Fetch the edited message
                message = await self.tg_client.get_message_by_id(message_id)
                if message:
                    analysis = await analyzer.analyze_message(message)
                    await self.store.upsert_analysis(analysis)
            
            logger.info(f"Overlap re-scan completed: {processed_count} messages, {len(edited_messages)} re-analyzed")
            
        except Exception as e:
            logger.error(f"Error in overlap re-scan: {e}")
    
    async def get_stats(self) -> IngestionStats:
        """Get current ingestion statistics."""
        self.stats.last_updated = datetime.utcnow()
        
        # Calculate lag if we have a checkpoint
        checkpoint = await self.store.get_checkpoint(self.chat_id)
        if checkpoint:
            lag = (datetime.utcnow() - checkpoint.last_ts_utc.replace(tzinfo=None)).total_seconds()
            self.stats.ingest_lag_seconds = max(0, lag)
        
        return self.stats
    
    async def manual_rescan_range(self, start_date: datetime, end_date: datetime):
        """Manually trigger a re-scan of a specific date range."""
        logger.info(f"Manual re-scan requested: {start_date} to {end_date}")
        
        try:
            messages = await self.tg_client.fetch_messages_in_range(
                start_date, end_date, limit=None
            )
            
            processed_count = await self._process_message_batch(messages)
            logger.info(f"Manual re-scan completed: {processed_count} messages processed")
            
        except Exception as e:
            logger.error(f"Error in manual re-scan: {e}")
            raise
