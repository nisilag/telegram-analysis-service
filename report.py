"""
Report generation for Telegram analysis data.
"""
import csv
import io
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import tempfile
import os

from loguru import logger

from models import ReportRequest, ReportResult, SentimentType
from store import DatabaseStore


class ReportGenerator:
    """Generates reports from analyzed Telegram data."""
    
    def __init__(self, store: DatabaseStore):
        self.store = store
    
    async def generate_report(self, request: ReportRequest) -> ReportResult:
        """Generate a comprehensive report based on the request parameters."""
        logger.info(f"Generating report: {request.start_date} to {request.end_date}")
        
        result = await self.store.generate_report(
            start_date=request.start_date,
            end_date=request.end_date,
            chat_id=request.chat_id,
            topic_filter=request.topic_filter,
            limit=request.limit
        )
        
        logger.info(f"Report generated: {result.total_messages} messages, {result.investment_messages} investment-related")
        return result
    
    def format_report_markdown(self, result: ReportResult, 
                             start_date: datetime, end_date: datetime,
                             topic_filter: Optional[str] = None) -> str:
        """Format report results as Markdown table."""
        
        # Header
        header = f"📊 **Telegram Analysis Report**\n"
        header += f"📅 Period: {start_date.strftime('%Y-%m-%d %H:%M')} to {end_date.strftime('%Y-%m-%d %H:%M')}\n"
        if topic_filter:
            header += f"🎯 Topic Filter: {topic_filter}\n"
        header += "\n"
        
        # Summary stats
        investment_pct = (result.investment_messages / result.total_messages * 100) if result.total_messages > 0 else 0
        
        summary = f"**📈 Summary**\n"
        summary += f"• Total Messages: {result.total_messages:,}\n"
        summary += f"• Investment-Related: {result.investment_messages:,} ({investment_pct:.1f}%)\n\n"
        
        # Sentiment breakdown
        sentiment_section = "**💭 Sentiment Analysis**\n"
        if result.investment_messages > 0:
            for sentiment, count in result.sentiment_breakdown.items():
                pct = (count / result.investment_messages * 100) if result.investment_messages > 0 else 0
                emoji = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "⚪"}.get(sentiment.value, "⚪")
                sentiment_section += f"• {emoji} {sentiment.value}: {count:,} ({pct:.1f}%)\n"
        else:
            sentiment_section += "• No investment messages found\n"
        sentiment_section += "\n"
        
        # Top tokens
        tokens_section = "**🪙 Top Tokens**\n"
        if result.top_tokens:
            for i, (token, count) in enumerate(result.top_tokens[:5], 1):
                tokens_section += f"{i}. ${token}: {count:,} mentions\n"
        else:
            tokens_section += "• No tokens found\n"
        tokens_section += "\n"
        
        # Recent messages preview (if not too many)
        messages_section = ""
        if len(result.messages) <= 10:
            messages_section = "**📝 Recent Messages**\n"
            for msg in result.messages[:5]:
                timestamp = msg['ts_utc'].strftime('%m-%d %H:%M') if isinstance(msg['ts_utc'], datetime) else msg['ts_utc']
                username = msg.get('from_username', 'Unknown')
                text_preview = msg['text'][:100] + "..." if len(msg['text']) > 100 else msg['text']
                
                sentiment_emoji = ""
                if msg.get('sentiment'):
                    sentiment_emoji = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "⚪"}.get(msg['sentiment'], "")
                
                tokens_str = ""
                if msg.get('tokens'):
                    tokens_str = f" [{', '.join(['$' + t for t in msg['tokens'][:3]])}]"
                
                messages_section += f"• {timestamp} @{username}{sentiment_emoji}{tokens_str}\n"
                messages_section += f"  {text_preview}\n\n"
        
        return header + summary + sentiment_section + tokens_section + messages_section
    
    def format_token_analysis_report(self, result: ReportResult, 
                                   start_date: datetime, end_date: datetime) -> str:
        """Format report in the enhanced token analysis format similar to the provided example."""
        
        # Header summary
        investment_pct = (result.investment_messages / result.total_messages * 100) if result.total_messages > 0 else 0
        
        header = f"**📊 Token Analysis Report**\n"
        header += f"📅 {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}\n\n"
        
        summary = f"Total posts retrieved in the search: **{result.total_messages}**\n"
        summary += f"Posts that received Investment Related = TRUE: **{result.investment_messages}**\n"
        
        # Group messages by token
        token_data = self._group_messages_by_token(result.messages)
        summary += f"Rows in the table: **{len(token_data)}**\n\n"
        
        if not token_data:
            return header + summary + "No investment-related tokens found in this period.\n"
        
        # Create the main table
        table = "```\n"
        table += f"{'Investment Topic':<15} | {'Account':<40} | {'Key Points'}\n"
        table += f"{'-' * 15} | {'-' * 40} | {'-' * 50}\n"
        
        for token, data in token_data.items():
            # Filter out None values from contributors
            valid_contributors = [str(c) for c in data['contributors'][:8] if c is not None]
            contributors = ", ".join(valid_contributors)  # Limit to 8 contributors
            if len(data['contributors']) > 8:
                contributors += f", +{len(data['contributors']) - 8} more"
            
            # Format key points by sentiment (filter out None values)
            bullish_points = [f"- {point}" for point in data['bullish_points'][:3] if point and str(point).strip()]
            bearish_points = [f"- {point}" for point in data['bearish_points'][:3] if point and str(point).strip()]
            
            key_points = ""
            if bullish_points:
                key_points += "BULLISH\\n" + "\\n".join(bullish_points)
            if bearish_points:
                if key_points:
                    key_points += "\\n"
                key_points += "BEARISH\\n" + "\\n".join(bearish_points)
            
            if not key_points:
                key_points = "NEUTRAL\\n- No strong sentiment detected"
            
            # Format the row (handle multi-line key points)
            lines = key_points.split("\\n")
            first_line = lines[0] if lines else ""
            
            table += f"{token:<15} | {contributors:<40} | {first_line}\n"
            
            # Add remaining key points lines
            for line in lines[1:]:
                table += f"{'':<15} | {'':<40} | {line}\n"
            
            table += f"{'-' * 15} | {'-' * 40} | {'-' * 50}\n"
        
        table += "```\n"
        
        return header + summary + table
    
    def _group_messages_by_token(self, messages: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Group messages by token and aggregate data."""
        token_data = {}
        
        for msg in messages:
            # Skip non-investment messages
            if not msg.get('is_investment'):
                continue
                
            tokens = msg.get('tokens', [])
            if not tokens:
                continue
                
            username = msg.get('from_username') or 'Unknown'  # Handle None usernames
            sentiment = msg.get('sentiment', 'NEUTRAL')
            key_points = msg.get('key_points', [])
            
            for token in tokens:
                if not token:  # Skip None/empty tokens
                    continue
                    
                token_key = f"${token}"
                
                if token_key not in token_data:
                    token_data[token_key] = {
                        'contributors': set(),
                        'bullish_points': [],
                        'bearish_points': [],
                        'neutral_points': [],
                        'message_count': 0
                    }
                
                token_data[token_key]['contributors'].add(username)
                token_data[token_key]['message_count'] += 1
                
                # Categorize key points by sentiment (filter out None/empty values)
                valid_key_points = [point for point in key_points[:2] if point and str(point).strip()]
                if sentiment == 'BULLISH':
                    token_data[token_key]['bullish_points'].extend(valid_key_points)
                elif sentiment == 'BEARISH':
                    token_data[token_key]['bearish_points'].extend(valid_key_points)
                else:
                    token_data[token_key]['neutral_points'].extend(valid_key_points)
        
        # Convert sets to sorted lists and limit points
        for token_key in token_data:
            token_data[token_key]['contributors'] = sorted(list(token_data[token_key]['contributors']))
            # Limit to top points to avoid overwhelming output
            token_data[token_key]['bullish_points'] = token_data[token_key]['bullish_points'][:4]
            token_data[token_key]['bearish_points'] = token_data[token_key]['bearish_points'][:4]
        
        # Sort by message count (most discussed tokens first)
        return dict(sorted(token_data.items(), 
                          key=lambda x: x[1]['message_count'], 
                          reverse=True))
    
    async def export_to_csv(self, result: ReportResult, 
                          start_date: datetime, end_date: datetime) -> str:
        """Export report results to CSV and return file path."""
        
        # Create temporary file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"telegram_analysis_{timestamp}.csv"
        filepath = os.path.join(tempfile.gettempdir(), filename)
        
        try:
            with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = [
                    'message_id', 'timestamp', 'username', 'text', 'is_investment',
                    'sentiment', 'tokens', 'topic_key', 'key_points'
                ]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                # Write header
                writer.writeheader()
                
                # Write data
                for msg in result.messages:
                    writer.writerow({
                        'message_id': msg['message_id'],
                        'timestamp': msg['ts_utc'].isoformat() if isinstance(msg['ts_utc'], datetime) else msg['ts_utc'],
                        'username': msg.get('from_username', ''),
                        'text': msg['text'],
                        'is_investment': msg.get('is_investment', False),
                        'sentiment': msg.get('sentiment', ''),
                        'tokens': ', '.join([str(t) for t in msg.get('tokens', []) if t is not None]),
                        'topic_key': msg.get('topic_key', ''),
                        'key_points': '; '.join([str(p) for p in msg.get('key_points', []) if p is not None])
                    })
            
            logger.info(f"CSV export created: {filepath}")
            return filepath
            
        except Exception as e:
            logger.error(f"Error creating CSV export: {e}")
            raise
    
    def parse_date_range(self, date_str: str) -> tuple[datetime, datetime]:
        """
        Parse various date range formats.
        
        Supported formats:
        - "last 24h", "last 7d", "last 30d"
        - "2024-01-01 to 2024-01-31"
        - "2024-01-01" (single day)
        """
        date_str = date_str.strip().lower()
        now = datetime.utcnow()
        
        # Relative dates
        if date_str.startswith("last "):
            duration_str = date_str[5:]
            
            if duration_str.endswith("h"):
                hours = int(duration_str[:-1])
                start_date = now - timedelta(hours=hours)
                return start_date, now
            elif duration_str.endswith("d"):
                days = int(duration_str[:-1])
                start_date = now - timedelta(days=days)
                return start_date, now
            elif duration_str.endswith("w"):
                weeks = int(duration_str[:-1])
                start_date = now - timedelta(weeks=weeks)
                return start_date, now
        
        # Date range with "to"
        if " to " in date_str:
            start_str, end_str = date_str.split(" to ")
            start_date = self._parse_single_date(start_str.strip())
            end_date = self._parse_single_date(end_str.strip())
            # Make end_date end of day
            end_date = end_date.replace(hour=23, minute=59, second=59)
            return start_date, end_date
        
        # Single date (assume full day)
        try:
            single_date = self._parse_single_date(date_str)
            start_date = single_date.replace(hour=0, minute=0, second=0)
            end_date = single_date.replace(hour=23, minute=59, second=59)
            return start_date, end_date
        except:
            raise ValueError(f"Unable to parse date range: {date_str}")
    
    def _parse_single_date(self, date_str: str) -> datetime:
        """Parse a single date string."""
        date_str = date_str.strip()
        
        # Try various formats
        formats = [
            "%Y-%m-%d",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%m-%d",  # This year
            "%m/%d",  # This year
            "%m/%d/%Y",
            "%m-%d-%Y"
        ]
        
        for fmt in formats:
            try:
                parsed = datetime.strptime(date_str, fmt)
                # If no year specified, use current year
                if fmt in ["%m-%d", "%m/%d"]:
                    parsed = parsed.replace(year=datetime.now().year)
                return parsed
            except ValueError:
                continue
        
        raise ValueError(f"Unable to parse date: {date_str}")
    
    def parse_topic_filter(self, filter_str: str) -> Optional[str]:
        """Parse topic filter from command."""
        if not filter_str:
            return None
        
        filter_str = filter_str.strip()
        
        # Remove "topic:" prefix if present
        if filter_str.lower().startswith("topic:"):
            filter_str = filter_str[6:].strip()
        
        # Remove $ prefix if present
        if filter_str.startswith("$"):
            filter_str = filter_str[1:]
        
        return filter_str.upper() if filter_str else None
    
    def parse_limit(self, limit_str: str) -> Optional[int]:
        """Parse limit from command."""
        if not limit_str:
            return None
        
        limit_str = limit_str.strip()
        
        # Remove "limit:" prefix if present
        if limit_str.lower().startswith("limit:"):
            limit_str = limit_str[6:].strip()
        
        try:
            limit = int(limit_str)
            return max(1, min(limit, 10000))  # Clamp between 1 and 10000
        except ValueError:
            return None
