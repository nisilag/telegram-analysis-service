"""
Data models for the Telegram analysis service.
"""
from datetime import datetime, timezone
from typing import List, Optional
from enum import Enum
from pydantic import BaseModel, Field


class SentimentType(str, Enum):
    """Sentiment classification types."""
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class TelegramMessage(BaseModel):
    """Raw Telegram message data."""
    chat_id: int
    message_id: int
    ts_utc: datetime
    from_user_id: Optional[int] = None
    from_username: Optional[str] = None
    is_forwarded: bool = False
    forward_from: Optional[str] = None
    text: str
    urls: List[str] = Field(default_factory=list)
    reply_to_id: Optional[int] = None
    edit_date: Optional[datetime] = None
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class MessageAnalysis(BaseModel):
    """Analysis results for a message."""
    chat_id: int
    message_id: int
    is_investment: bool
    sentiment: SentimentType
    tokens: List[str] = Field(default_factory=list)
    topic_key: str
    key_points: List[str] = Field(default_factory=list)
    confidence: Optional[float] = None
    model_version: int = 1
    analyzed_at: datetime = Field(default_factory=lambda: datetime.utcnow().replace(tzinfo=timezone.utc))
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class IngestCheckpoint(BaseModel):
    """Checkpoint for message ingestion progress."""
    chat_id: int
    last_message_id: int
    last_ts_utc: datetime
    updated_at: datetime = Field(default_factory=lambda: datetime.utcnow().replace(tzinfo=timezone.utc))
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class HighWaterMark(BaseModel):
    """High water mark for backfill boundary."""
    chat_id: int
    message_id: int
    ts_utc: datetime
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow().replace(tzinfo=timezone.utc))


class ReportRequest(BaseModel):
    """Request parameters for generating reports."""
    start_date: datetime
    end_date: datetime
    topic_filter: Optional[str] = None
    limit: Optional[int] = None
    chat_id: Optional[int] = None


class ReportResult(BaseModel):
    """Results from a report query."""
    total_messages: int
    investment_messages: int
    sentiment_breakdown: dict[SentimentType, int]
    top_tokens: List[tuple[str, int]]
    messages: List[dict]
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class IngestionStats(BaseModel):
    """Statistics for ingestion monitoring."""
    ingested_messages_total: int = 0
    analyzed_messages_total: int = 0
    overlap_rescans_total: int = 0
    flood_wait_seconds_total: float = 0.0
    ingest_lag_seconds: float = 0.0
    last_updated: datetime = Field(default_factory=lambda: datetime.utcnow().replace(tzinfo=timezone.utc))
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
