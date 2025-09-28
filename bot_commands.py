"""
Telegram bot interface for querying and reporting.
"""
import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional, List

from telethon import TelegramClient, events
from telethon.tl.types import DocumentAttributeFilename
from loguru import logger

from models import ReportRequest
from store import DatabaseStore
from report import ReportGenerator
from ingest import IngestionEngine
from config import config


class TelegramBot:
    """Telegram bot for handling user commands and reports."""
    
    def __init__(self, store: DatabaseStore, ingestion_engine: IngestionEngine):
        self.store = store
        self.ingestion_engine = ingestion_engine
        self.report_generator = ReportGenerator(store)
        self.bot_token = config.bot_token
        self.admin_user_ids = set(config.get_admin_user_ids())
        self.target_chat_id = config.target_chat_id
        self.client = None
        
    async def initialize(self):
        """Initialize the bot client."""
        if not self.bot_token:
            logger.warning("No bot token provided, bot commands will not be available")
            return
        
        # Create bot client
        self.client = TelegramClient('bot_session', config.telegram_api_id, config.telegram_api_hash)
        await self.client.start(bot_token=self.bot_token)
        
        # Add command handlers
        self._add_command_handlers()
        
        logger.info("Telegram bot initialized and ready for commands")
    
    def _add_command_handlers(self):
        """Add command handlers for the bot."""
        
        @self.client.on(events.NewMessage(pattern=r'/report\s*(.*)'))
        async def handle_report_command(event):
            try:
                await self._handle_report_command(event)
            except Exception as e:
                logger.error(f"Error in report command: {e}")
                await event.reply(f"❌ Error generating report: {str(e)}")
        
        @self.client.on(events.NewMessage(pattern=r'/export\s*(.*)'))
        async def handle_export_command(event):
            try:
                await self._handle_export_command(event)
            except Exception as e:
                logger.error(f"Error in export command: {e}")
                await event.reply(f"❌ Error exporting data: {str(e)}")
        
        @self.client.on(events.NewMessage(pattern=r'/stats'))
        async def handle_stats_command(event):
            try:
                await self._handle_stats_command(event)
            except Exception as e:
                logger.error(f"Error in stats command: {e}")
                await event.reply(f"❌ Error getting stats: {str(e)}")
        
        @self.client.on(events.NewMessage(pattern=r'/audit\s*(.*)'))
        async def handle_audit_command(event):
            try:
                if not self._is_admin(event.sender_id):
                    await event.reply("❌ Admin access required for audit commands")
                    return
                await self._handle_audit_command(event)
            except Exception as e:
                logger.error(f"Error in audit command: {e}")
                await event.reply(f"❌ Error in audit: {str(e)}")
        
        @self.client.on(events.NewMessage(pattern=r'/tokenreport\s*(.*)'))
        async def handle_token_report_command(event):
            try:
                await self._handle_token_report_command(event)
            except Exception as e:
                logger.error(f"Error in token report command: {e}")
                await event.reply(f"❌ Error generating token report: {str(e)}")
        
        @self.client.on(events.NewMessage(pattern=r'/help'))
        async def handle_help_command(event):
            await self._handle_help_command(event)
    
    def _is_admin(self, user_id: int) -> bool:
        """Check if user is an admin."""
        return user_id in self.admin_user_ids
    
    async def _handle_report_command(self, event):
        """Handle /report command."""
        args = event.pattern_match.group(1).strip()
        
        if not args:
            await event.reply("""
📊 **Report Command Usage:**

`/report <date_range> [topic:<TOKEN>] [limit:<N>]`

**Date Range Examples:**
• `last 24h` - Last 24 hours
• `last 7d` - Last 7 days  
• `2024-01-01 to 2024-01-31` - Date range
• `2024-01-15` - Single day

**Optional Filters:**
• `topic:BTC` - Filter by token/topic
• `limit:100` - Limit results

**Examples:**
• `/report last 24h`
• `/report last 7d topic:ETH`
• `/report 2024-01-01 to 2024-01-31 limit:50`
            """)
            return
        
        # Parse arguments
        parts = args.split()
        date_range_parts = []
        topic_filter = None
        limit = None
        
        for part in parts:
            if part.lower().startswith("topic:"):
                topic_filter = self.report_generator.parse_topic_filter(part)
            elif part.lower().startswith("limit:"):
                limit = self.report_generator.parse_limit(part)
            else:
                date_range_parts.append(part)
        
        date_range_str = " ".join(date_range_parts)
        
        try:
            # Parse date range
            start_date, end_date = self.report_generator.parse_date_range(date_range_str)
            
            # Send "generating..." message
            status_msg = await event.reply("🔄 Generating report...")
            
            # Generate report
            request = ReportRequest(
                start_date=start_date,
                end_date=end_date,
                topic_filter=topic_filter,
                limit=limit,
                chat_id=self.target_chat_id
            )
            
            result = await self.report_generator.generate_report(request)
            
            # Format as markdown
            markdown_report = self.report_generator.format_report_markdown(
                result, start_date, end_date, topic_filter
            )
            
            # Delete status message
            await status_msg.delete()
            
            # Send report
            if len(markdown_report) > 4000:  # Telegram message limit
                # Send summary and offer CSV
                summary_lines = markdown_report.split('\n')[:20]  # First 20 lines
                summary = '\n'.join(summary_lines) + f"\n\n📎 Report too long. Use `/export {date_range_str}` for full data."
                await event.reply(summary)
            else:
                await event.reply(markdown_report)
                
        except ValueError as e:
            await event.reply(f"Invalid date format: {str(e)}")
        except Exception as e:
            logger.error(f"Error generating token report: {e}")
            await event.reply(f"Error generating token report: {str(e)}")
    
    def _split_message(self, message: str, max_length: int) -> List[str]:
        """Split a long message into chunks that fit Telegram's limits."""
        if len(message) <= max_length:
            return [message]
        
        chunks = []
        current_chunk = ""
        
        for line in message.split('\n'):
            if len(current_chunk) + len(line) + 1 <= max_length:
                current_chunk += line + '\n'
            else:
                if current_chunk:
                    chunks.append(current_chunk.rstrip())
                current_chunk = line + '\n'
        
        if current_chunk:
            chunks.append(current_chunk.rstrip())
        
        return chunks
    
    def _parse_date_range(self, date_str: str) -> tuple[datetime, datetime]:
        """Parse date range string into start and end datetime objects."""
        # This is a simplified version - you might want to move the full logic from report.py
        now = datetime.utcnow()
        
        if "last" in date_str.lower():
            if "24h" in date_str or "1d" in date_str:
                start_date = now - timedelta(days=1)
            elif "7d" in date_str:
                start_date = now - timedelta(days=7)
            elif "30d" in date_str:
                start_date = now - timedelta(days=30)
            else:
                raise ValueError("Unsupported date range. Use: last 24h, last 7d, or last 30d")
            return start_date, now
        else:
            raise ValueError("Only 'last X' date ranges supported for now. Use: last 24h, last 7d, or last 30d")
    
    async def _handle_token_report_command(self, event):
        """Handle /tokenreport command - enhanced token analysis format."""
        args = event.pattern_match.group(1).strip()
        
        if not args:
            await event.reply("""
📊 **Token Report Command Usage:**

`/tokenreport <date_range>`

**Date Range Examples:**
• `last 24h` - Last 24 hours
• `last 7d` - Last 7 days  
• `last 30d` - Last 30 days
• `2024-01-01 to 2024-01-31` - Date range

**Examples:**
• `/tokenreport last 24h`
• `/tokenreport last 7d`
• `/tokenreport last 30d`

This generates an enhanced report showing tokens, contributors, and sentiment-categorized key points.
            """)
            return
        
        try:
            # Parse date range (reuse existing logic)
            start_date, end_date = self._parse_date_range(args)
            
            # Send "generating..." message
            status_msg = await event.reply("🔄 Generating token analysis report...")
            
            # Generate report
            request = ReportRequest(
                start_date=start_date,
                end_date=end_date,
                topic_filter=None,  # No topic filter for token analysis
                limit=None,         # No limit for comprehensive analysis
                chat_id=self.target_chat_id
            )
            
            result = await self.report_generator.generate_report(request)
            
            # Format using the new token analysis format
            token_report = self.report_generator.format_token_analysis_report(
                result, start_date, end_date
            )
            
            # Delete status message
            await status_msg.delete()
            
            # Send report with pagination (limit to 5 tokens per page for readability)
            if len(token_report) > 4000:  # Telegram message limit
                # Split the report into chunks
                chunks = self._split_message(token_report, 3500)  # Smaller chunks for better readability
                for i, chunk in enumerate(chunks):
                    if i == 0:
                        await event.reply(chunk)
                    else:
                        await event.reply(f"**📊 Token Report - Page {i+1}/{len(chunks)}**\n\n{chunk}")
            else:
                await event.reply(token_report)
                
        except ValueError as e:
            await event.reply(f"❌ {str(e)}")
        except Exception as e:
            logger.error(f"Error generating token report: {e}")
            await event.reply(f"❌ Error generating token report: {str(e)}")
    
    async def _handle_export_command(self, event):
        """Handle /export command."""
        args = event.pattern_match.group(1).strip()
        
        if not args:
            await event.reply("""
📎 **Export Command Usage:**

`/export <date_range> [topic:<TOKEN>]`

**Examples:**
• `/export last 7d`
• `/export 2024-01-01 to 2024-01-31`
• `/export last 24h topic:BTC`
            """)
            return
        
        # Parse arguments (similar to report)
        parts = args.split()
        date_range_parts = []
        topic_filter = None
        
        for part in parts:
            if part.lower().startswith("topic:"):
                topic_filter = self.report_generator.parse_topic_filter(part)
            else:
                date_range_parts.append(part)
        
        date_range_str = " ".join(date_range_parts)
        
        try:
            # Parse date range
            start_date, end_date = self.report_generator.parse_date_range(date_range_str)
            
            # Send "exporting..." message
            status_msg = await event.reply("📎 Exporting data...")
            
            # Generate report data
            request = ReportRequest(
                start_date=start_date,
                end_date=end_date,
                topic_filter=topic_filter,
                limit=None,  # No limit for exports
                chat_id=self.target_chat_id
            )
            
            result = await self.report_generator.generate_report(request)
            
            if result.total_messages == 0:
                await status_msg.edit("❌ No data found for the specified date range")
                return
            
            # Export to CSV
            csv_path = await self.report_generator.export_to_csv(result, start_date, end_date)
            
            # Send CSV file
            await self.client.send_file(
                event.chat_id,
                csv_path,
                caption=f"📊 Export: {result.total_messages:,} messages ({start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')})",
                attributes=[DocumentAttributeFilename(os.path.basename(csv_path))]
            )
            
            # Clean up
            await status_msg.delete()
            os.unlink(csv_path)  # Delete temporary file
            
        except ValueError as e:
            await event.reply(f"❌ Invalid date format: {str(e)}")
        except Exception as e:
            logger.error(f"Error exporting data: {e}")
            await event.reply(f"❌ Error exporting data: {str(e)}")
    
    async def _handle_stats_command(self, event):
        """Handle /stats command."""
        try:
            stats = await self.ingestion_engine.get_stats()
            
            stats_text = f"""
📈 **Ingestion Statistics**

**Messages:**
• Total Ingested: {stats.ingested_messages_total:,}
• Total Analyzed: {stats.analyzed_messages_total:,}

**Operations:**
• Overlap Re-scans: {stats.overlap_rescans_total:,}
• Flood Wait Time: {stats.flood_wait_seconds_total:.1f}s

**Performance:**
• Ingest Lag: {stats.ingest_lag_seconds:.1f}s
• Last Updated: {stats.last_updated.strftime('%Y-%m-%d %H:%M:%S')} UTC
            """
            
            await event.reply(stats_text)
            
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            await event.reply(f"❌ Error getting stats: {str(e)}")
    
    async def _handle_audit_command(self, event):
        """Handle /audit command (admin only)."""
        args = event.pattern_match.group(1).strip()
        
        if not args:
            await event.reply("""
🔍 **Audit Command Usage (Admin Only):**

`/audit <date_range>`

**Examples:**
• `/audit last 24h`
• `/audit 2024-01-01 to 2024-01-31`
            """)
            return
        
        try:
            # Parse date range
            start_date, end_date = self.report_generator.parse_date_range(args)
            
            # Send "auditing..." message
            status_msg = await event.reply("🔍 Running audit...")
            
            # Trigger manual re-scan
            await self.ingestion_engine.manual_rescan_range(start_date, end_date)
            
            await status_msg.edit(f"✅ Audit completed for {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
            
        except ValueError as e:
            await event.reply(f"❌ Invalid date format: {str(e)}")
        except Exception as e:
            logger.error(f"Error in audit: {e}")
            await event.reply(f"❌ Error in audit: {str(e)}")
    
    async def _handle_help_command(self, event):
        """Handle /help command."""
        help_text = """
🤖 **Telegram Analysis Bot Commands**

**📊 Reports:**
• `/report <date_range>` - Generate standard analysis report
• `/tokenreport <date_range>` - Generate enhanced token analysis report
• `/export <date_range>` - Export data as CSV
• `/stats` - Show ingestion statistics

**📅 Date Range Formats:**
• `last 24h`, `last 7d`, `last 30d`
• `2024-01-01 to 2024-01-31`
• `2024-01-15` (single day)

**🎯 Filters:**
• `topic:BTC` - Filter by token/topic
• `limit:100` - Limit results

**Examples:**
• `/report last 24h`
• `/report last 7d topic:ETH limit:50`
• `/export 2024-01-01 to 2024-01-31`

**ℹ️ Other:**
• `/help` - Show this help message
        """
        
        if self._is_admin(event.sender_id):
            help_text += """
**🔧 Admin Commands:**
• `/audit <date_range>` - Manual re-scan of date range
            """
        
        await event.reply(help_text)
    
    async def start_bot(self):
        """Start the bot (non-blocking)."""
        if not self.client:
            logger.warning("Bot not initialized, skipping bot start")
            return
        
        logger.info("Telegram bot started and listening for commands")
        # Bot runs in the background, commands are handled by event handlers
    
    async def stop_bot(self):
        """Stop the bot."""
        if self.client:
            await self.client.disconnect()
            logger.info("Telegram bot stopped")
