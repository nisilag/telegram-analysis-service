"""
Database store for Telegram messages and analysis.
Supports both PostgreSQL and SQLite.
"""
import asyncio
import json
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict, Any
from urllib.parse import urlparse

import asyncpg
import aiosqlite
from loguru import logger

from models import (
    TelegramMessage, MessageAnalysis, IngestCheckpoint, 
    HighWaterMark, ReportResult, SentimentType, IngestionStats
)
from config import config


class DatabaseStore:
    """Database abstraction layer supporting PostgreSQL and SQLite."""
    
    def __init__(self, db_url: str = None):
        self.db_url = db_url or config.db_url
        self.is_postgres = self.db_url.startswith("postgresql://")
        self.pool = None
        self.connection = None
        
    async def initialize(self):
        """Initialize database connection and create tables."""
        if self.is_postgres:
            # Parse URL to avoid DNS resolution issues in asyncpg
            from urllib.parse import urlparse
            parsed = urlparse(self.db_url)
            
            # Use direct connection parameters instead of URL
            self.pool = await asyncpg.create_pool(
                host=parsed.hostname,
                port=parsed.port or 5432,
                user=parsed.username,
                password=parsed.password,
                database=parsed.path.lstrip('/'),
                ssl=False  # Disable SSL to avoid DNS issues
            )
            async with self.pool.acquire() as conn:
                await self._create_tables_postgres(conn)
        else:
            # SQLite
            db_path = self.db_url.replace("sqlite:///", "")
            self.connection = await aiosqlite.connect(db_path)
            await self._create_tables_sqlite(self.connection)
            
        logger.info(f"Database initialized: {'PostgreSQL' if self.is_postgres else 'SQLite'}")
    
    async def close(self):
        """Close database connections."""
        if self.is_postgres and self.pool:
            await self.pool.close()
        elif self.connection:
            await self.connection.close()
    
    async def _create_tables_postgres(self, conn):
        """Create tables for PostgreSQL."""
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                chat_id BIGINT NOT NULL,
                message_id BIGINT NOT NULL,
                ts_utc TIMESTAMP NOT NULL,
                from_user_id BIGINT,
                from_username TEXT,
                is_forwarded BOOLEAN DEFAULT FALSE,
                forward_from TEXT,
                text TEXT NOT NULL,
                urls TEXT[],
                reply_to_id BIGINT,
                edit_date TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (chat_id, message_id)
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS analysis (
                chat_id BIGINT NOT NULL,
                message_id BIGINT NOT NULL,
                is_investment BOOLEAN NOT NULL,
                sentiment TEXT NOT NULL CHECK (sentiment IN ('BULLISH','BEARISH','NEUTRAL')),
                tokens TEXT[],
                topic_key TEXT NOT NULL,
                key_points TEXT[],
                confidence REAL,
                model_version INTEGER DEFAULT 1,
                analyzed_at TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (chat_id, message_id),
                FOREIGN KEY (chat_id, message_id) REFERENCES messages(chat_id, message_id)
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ingest_checkpoint (
                chat_id BIGINT PRIMARY KEY,
                last_message_id BIGINT NOT NULL,
                last_ts_utc TIMESTAMP NOT NULL,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS high_water_marks (
                chat_id BIGINT PRIMARY KEY,
                message_id BIGINT NOT NULL,
                ts_utc TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # Create indexes
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts_utc)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_analysis_investment ON analysis(is_investment)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_analysis_sentiment ON analysis(sentiment)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_analysis_tokens ON analysis USING GIN(tokens)")
    
    async def _create_tables_sqlite(self, conn):
        """Create tables for SQLite."""
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                ts_utc TEXT NOT NULL,
                from_user_id INTEGER,
                from_username TEXT,
                is_forwarded BOOLEAN DEFAULT 0,
                forward_from TEXT,
                text TEXT NOT NULL,
                urls TEXT,
                reply_to_id INTEGER,
                edit_date TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, message_id)
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS analysis (
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                is_investment BOOLEAN NOT NULL,
                sentiment TEXT NOT NULL CHECK (sentiment IN ('BULLISH','BEARISH','NEUTRAL')),
                tokens TEXT,
                topic_key TEXT NOT NULL,
                key_points TEXT,
                confidence REAL,
                model_version INTEGER DEFAULT 1,
                analyzed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, message_id),
                FOREIGN KEY (chat_id, message_id) REFERENCES messages(chat_id, message_id)
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ingest_checkpoint (
                chat_id INTEGER PRIMARY KEY,
                last_message_id INTEGER NOT NULL,
                last_ts_utc TEXT NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS high_water_marks (
                chat_id INTEGER PRIMARY KEY,
                message_id INTEGER NOT NULL,
                ts_utc TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create indexes
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts_utc)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_analysis_investment ON analysis(is_investment)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_analysis_sentiment ON analysis(sentiment)")
        
        await conn.commit()
    
    async def upsert_message(self, message: TelegramMessage) -> bool:
        """Insert or update a message. Returns True if inserted/updated."""
        if self.is_postgres:
            async with self.pool.acquire() as conn:
                result = await conn.execute("""
                    INSERT INTO messages (
                        chat_id, message_id, ts_utc, from_user_id, from_username,
                        is_forwarded, forward_from, text, urls, reply_to_id, edit_date
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    ON CONFLICT (chat_id, message_id) DO UPDATE SET
                        text = EXCLUDED.text,
                        edit_date = EXCLUDED.edit_date,
                        urls = EXCLUDED.urls
                    WHERE messages.edit_date IS NULL OR messages.edit_date < EXCLUDED.edit_date
                """, message.chat_id, message.message_id, message.ts_utc,
                    message.from_user_id, message.from_username, message.is_forwarded,
                    message.forward_from, message.text, message.urls, message.reply_to_id,
                    message.edit_date)
                return True
        else:
            async with self.connection.execute("""
                INSERT OR REPLACE INTO messages (
                    chat_id, message_id, ts_utc, from_user_id, from_username,
                    is_forwarded, forward_from, text, urls, reply_to_id, edit_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (message.chat_id, message.message_id, message.ts_utc.isoformat(),
                  message.from_user_id, message.from_username, message.is_forwarded,
                  message.forward_from, message.text, json.dumps(message.urls),
                  message.reply_to_id, message.edit_date.isoformat() if message.edit_date else None)):
                pass
            await self.connection.commit()
            return True
    
    async def upsert_analysis(self, analysis: MessageAnalysis) -> bool:
        """Insert or update message analysis."""
        if self.is_postgres:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO analysis (
                        chat_id, message_id, is_investment, sentiment, tokens,
                        topic_key, key_points, confidence, model_version, analyzed_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    ON CONFLICT (chat_id, message_id) DO UPDATE SET
                        is_investment = EXCLUDED.is_investment,
                        sentiment = EXCLUDED.sentiment,
                        tokens = EXCLUDED.tokens,
                        topic_key = EXCLUDED.topic_key,
                        key_points = EXCLUDED.key_points,
                        confidence = EXCLUDED.confidence,
                        model_version = EXCLUDED.model_version,
                        analyzed_at = EXCLUDED.analyzed_at
                """, analysis.chat_id, analysis.message_id, analysis.is_investment,
                    analysis.sentiment.value, analysis.tokens, analysis.topic_key,
                    analysis.key_points, analysis.confidence, analysis.model_version,
                    analysis.analyzed_at)
        else:
            async with self.connection.execute("""
                INSERT OR REPLACE INTO analysis (
                    chat_id, message_id, is_investment, sentiment, tokens,
                    topic_key, key_points, confidence, model_version, analyzed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (analysis.chat_id, analysis.message_id, analysis.is_investment,
                  analysis.sentiment.value, json.dumps(analysis.tokens),
                  analysis.topic_key, json.dumps(analysis.key_points),
                  analysis.confidence, analysis.model_version,
                  analysis.analyzed_at.isoformat())):
                pass
            await self.connection.commit()
        return True
    
    async def get_checkpoint(self, chat_id: int) -> Optional[IngestCheckpoint]:
        """Get the latest checkpoint for a chat."""
        if self.is_postgres:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM ingest_checkpoint WHERE chat_id = $1", chat_id
                )
                if row:
                    return IngestCheckpoint(**dict(row))
        else:
            async with self.connection.execute(
                "SELECT * FROM ingest_checkpoint WHERE chat_id = ?", (chat_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return IngestCheckpoint(
                        chat_id=row[0],
                        last_message_id=row[1],
                        last_ts_utc=datetime.fromisoformat(row[2]),
                        updated_at=datetime.fromisoformat(row[3])
                    )
        return None
    
    async def update_checkpoint(self, checkpoint: IngestCheckpoint):
        """Update the checkpoint for a chat."""
        if self.is_postgres:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO ingest_checkpoint (chat_id, last_message_id, last_ts_utc, updated_at)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (chat_id) DO UPDATE SET
                        last_message_id = EXCLUDED.last_message_id,
                        last_ts_utc = EXCLUDED.last_ts_utc,
                        updated_at = EXCLUDED.updated_at
                """, checkpoint.chat_id, checkpoint.last_message_id,
                    checkpoint.last_ts_utc, checkpoint.updated_at)
        else:
            async with self.connection.execute("""
                INSERT OR REPLACE INTO ingest_checkpoint 
                (chat_id, last_message_id, last_ts_utc, updated_at)
                VALUES (?, ?, ?, ?)
            """, (checkpoint.chat_id, checkpoint.last_message_id,
                  checkpoint.last_ts_utc.isoformat(), checkpoint.updated_at.isoformat())):
                pass
            await self.connection.commit()
    
    async def set_high_water_mark(self, hwm: HighWaterMark):
        """Set the high water mark for a chat."""
        if self.is_postgres:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO high_water_marks (chat_id, message_id, ts_utc, created_at)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (chat_id) DO UPDATE SET
                        message_id = EXCLUDED.message_id,
                        ts_utc = EXCLUDED.ts_utc,
                        created_at = EXCLUDED.created_at
                """, hwm.chat_id, hwm.message_id, hwm.ts_utc, hwm.created_at)
        else:
            async with self.connection.execute("""
                INSERT OR REPLACE INTO high_water_marks 
                (chat_id, message_id, ts_utc, created_at)
                VALUES (?, ?, ?, ?)
            """, (hwm.chat_id, hwm.message_id, hwm.ts_utc.isoformat(),
                  hwm.created_at.isoformat())):
                pass
            await self.connection.commit()
    
    async def get_high_water_mark(self, chat_id: int) -> Optional[HighWaterMark]:
        """Get the high water mark for a chat."""
        if self.is_postgres:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM high_water_marks WHERE chat_id = $1", chat_id
                )
                if row:
                    return HighWaterMark(**dict(row))
        else:
            async with self.connection.execute(
                "SELECT * FROM high_water_marks WHERE chat_id = ?", (chat_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return HighWaterMark(
                        chat_id=row[0],
                        message_id=row[1],
                        ts_utc=datetime.fromisoformat(row[2]),
                        created_at=datetime.fromisoformat(row[3])
                    )
        return None
    
    async def get_messages_needing_reanalysis(self, chat_id: int) -> List[Tuple[int, datetime]]:
        """Get messages that need re-analysis due to edits."""
        if self.is_postgres:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT m.message_id, m.edit_date
                    FROM messages m
                    LEFT JOIN analysis a ON m.chat_id = a.chat_id AND m.message_id = a.message_id
                    WHERE m.chat_id = $1 
                    AND m.edit_date IS NOT NULL
                    AND (a.analyzed_at IS NULL OR m.edit_date > a.analyzed_at)
                """, chat_id)
                return [(row['message_id'], row['edit_date']) for row in rows]
        else:
            async with self.connection.execute("""
                SELECT m.message_id, m.edit_date
                FROM messages m
                LEFT JOIN analysis a ON m.chat_id = a.chat_id AND m.message_id = a.message_id
                WHERE m.chat_id = ? 
                AND m.edit_date IS NOT NULL
                AND (a.analyzed_at IS NULL OR m.edit_date > a.analyzed_at)
            """, (chat_id,)) as cursor:
                rows = await cursor.fetchall()
                return [(row[0], datetime.fromisoformat(row[1])) for row in rows if row[1]]
    
    async def generate_report(self, start_date: datetime, end_date: datetime, 
                            chat_id: int, topic_filter: Optional[str] = None,
                            limit: Optional[int] = None) -> ReportResult:
        """Generate a report for the specified date range."""
        base_query = """
            SELECT m.*, a.*
            FROM messages m
            LEFT JOIN analysis a ON m.chat_id = a.chat_id AND m.message_id = a.message_id
            WHERE m.chat_id = {} AND m.ts_utc BETWEEN {} AND {}
        """
        
        params = [chat_id]
        
        if self.is_postgres:
            query = base_query.format("$1", "$2", "$3")
            params.extend([start_date, end_date])
            
            if topic_filter:
                query += " AND (a.topic_key ILIKE $4 OR $4 = ANY(a.tokens))"
                params.append(f"%{topic_filter}%")
            
            query += " ORDER BY m.ts_utc DESC"
            if limit:
                query += f" LIMIT ${len(params) + 1}"
                params.append(limit)
                
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
        else:
            query = base_query.format("?", "?", "?")
            params.extend([start_date.isoformat(), end_date.isoformat()])
            
            if topic_filter:
                query += " AND (a.topic_key LIKE ? OR a.tokens LIKE ?)"
                params.extend([f"%{topic_filter}%", f"%{topic_filter}%"])
            
            query += " ORDER BY m.ts_utc DESC"
            if limit:
                query += " LIMIT ?"
                params.append(limit)
                
            async with self.connection.execute(query, params) as cursor:
                rows = await cursor.fetchall()
        
        # Process results
        total_messages = len(rows)
        investment_messages = 0
        sentiment_breakdown = {SentimentType.BULLISH: 0, SentimentType.BEARISH: 0, SentimentType.NEUTRAL: 0}
        token_counts = {}
        messages = []
        
        for row in rows:
            if self.is_postgres:
                row_dict = dict(row)
                is_investment = row_dict.get('is_investment', False)
                sentiment = row_dict.get('sentiment')
                tokens = row_dict.get('tokens', []) or []
                key_points = row_dict.get('key_points', []) or []
            else:
                # SQLite row handling
                is_investment = bool(row[12]) if len(row) > 12 and row[12] is not None else False
                sentiment = row[13] if len(row) > 13 else None
                tokens_json = row[14] if len(row) > 14 else None
                try:
                    tokens = json.loads(tokens_json) if tokens_json else []
                except (json.JSONDecodeError, TypeError):
                    tokens = []
            
            if is_investment:
                investment_messages += 1
                
                # Only count sentiment for investment-related messages
                if sentiment:
                    sentiment_breakdown[SentimentType(sentiment)] += 1
                
            for token in tokens:
                token_counts[token] = token_counts.get(token, 0) + 1
            
            # Build message dict
            msg_dict = {
                'message_id': row[1],
                'ts_utc': row[2] if self.is_postgres else datetime.fromisoformat(row[2]),
                'from_username': row[4],
                'text': row[7],
                'is_investment': is_investment,
                'sentiment': sentiment,
                'tokens': tokens,
                'key_points': key_points if self.is_postgres else (json.loads(row[16]) if len(row) > 16 and row[16] else []),
                'topic_key': row[15] if len(row) > 15 else None
            }
            messages.append(msg_dict)
        
        top_tokens = sorted(token_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        
        return ReportResult(
            total_messages=total_messages,
            investment_messages=investment_messages,
            sentiment_breakdown=sentiment_breakdown,
            top_tokens=top_tokens,
            messages=messages
        )
