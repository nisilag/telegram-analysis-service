"""
Configuration management using Pydantic settings.
"""
from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings


class Config(BaseSettings):
    """Application configuration loaded from environment variables."""
    
    # Telegram API credentials
    telegram_api_id: int = Field(..., description="Telegram API ID")
    telegram_api_hash: str = Field(..., description="Telegram API Hash")
    telethon_session_path: str = Field(default="./telegram_session", description="Path to Telethon session file")
    
    # Target chat configuration
    target_chat_id: int = Field(..., description="Chat ID to monitor")
    
    # Database configuration
    db_url: str = Field(default="sqlite:///./telegram_analysis.db", description="Database connection URL")
    
    # Ingestion settings
    overlap_minutes: int = Field(default=120, description="Minutes to overlap in re-scan")
    batch_size: int = Field(default=100, description="Batch size for message fetching")
    rate_limit_delay: float = Field(default=1.0, description="Delay between API calls in seconds")
    
    # Analysis settings
    model_version: int = Field(default=1, description="Analysis model version")
    confidence_threshold: float = Field(default=0.7, description="Minimum confidence for analysis")
    
    # Bot settings (optional)
    bot_token: Optional[str] = Field(default=None, description="Telegram bot token for commands")
    admin_user_ids: List[int] = Field(default_factory=list, description="Admin user IDs")
    
    # Logging
    log_level: str = Field(default="INFO", description="Logging level")
    log_file: Optional[str] = Field(default=None, description="Log file path")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        
        @classmethod
        def parse_env_var(cls, field_name: str, raw_val: str) -> any:
            """Custom parser for environment variables."""
            if field_name == 'admin_user_ids':
                if not raw_val:
                    return []
                return [int(x.strip()) for x in raw_val.split(',') if x.strip()]
            return cls.json_loads(raw_val)


# Global config instance
config = Config()


# Finance keywords for investment detection
FINANCE_KEYWORDS = {
    "price", "market", "cap", "liquidity", "tvl", "apr", "apy", "yield",
    "mainnet", "testnet", "tge", "cex", "dex", "emission", "airdrop",
    "token", "coin", "crypto", "blockchain", "defi", "trading", "exchange",
    "volume", "pump", "dump", "moon", "bull", "bear", "hodl", "fud",
    "ath", "atl", "mcap", "fdv", "roi", "pnl", "leverage", "margin",
    "staking", "farming", "mining", "validator", "node", "consensus",
    "fork", "upgrade", "governance", "dao", "proposal", "vote",
    "bridge", "cross-chain", "layer", "scaling", "gas", "fee",
    "wallet", "custody", "keys", "seed", "phrase", "security",
    "audit", "exploit", "hack", "rug", "scam", "ponzi",
    "ico", "ido", "ipo", "listing", "delisting", "burn", "mint",
    "supply", "circulation", "inflation", "deflation", "halving"
}


# Token alias mapping (extend as needed)
TOKEN_ALIASES = {
    "BTC": ["BITCOIN", "₿"],
    "ETH": ["ETHEREUM", "ETHER"],
    "BNB": ["BINANCE"],
    "ADA": ["CARDANO"],
    "SOL": ["SOLANA"],
    "MATIC": ["POLYGON"],
    "AVAX": ["AVALANCHE"],
    "DOT": ["POLKADOT"],
    "LINK": ["CHAINLINK"],
    "UNI": ["UNISWAP"],
    # Add more as needed
}
