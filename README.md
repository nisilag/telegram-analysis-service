# Telegram Ingestion + Analysis Service

A comprehensive Telegram message ingestion and analysis service that monitors Telegram groups, analyzes messages for investment-related content and sentiment, and provides query interfaces for generating reports.

## Features

### Core Functionality
- **📥 Message Ingestion**: Real-time ingestion with backfill support
- **🔄 Gap Prevention**: High-water marks, checkpointing, and overlap re-scanning
- **🧠 AI Analysis**: FinBERT-powered sentiment analysis and token extraction
- **📊 Reporting**: Flexible query interface with date ranges and filters
- **🤖 Bot Interface**: Telegram bot for interactive queries and CSV exports

### Technical Highlights
- **Idempotent Operations**: No duplicates across restarts
- **Rate Limiting**: Automatic FloodWait handling
- **Database Agnostic**: PostgreSQL and SQLite support
- **Scalable Architecture**: Async/await throughout
- **Comprehensive Logging**: Structured logging with observability metrics

## Quick Start

### Option 1: Docker (Recommended)

```bash
# Clone the repository
git clone <repository-url>
cd telegram-analysis-service

# Set up environment
cp .env.docker .env
# Edit .env with your Telegram credentials and settings

# Start with Docker Compose
docker-compose up -d

# View logs and follow authentication prompts
docker-compose logs -f app
```

### Option 2: Local Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.template .env
# Edit .env with your settings

# Run the service
python app.py
```

### First Run Authentication

On first run, you'll need to authenticate with Telegram:
1. Prompt for phone number and verification code
2. Determine high-water mark (latest message)
3. Backfill entire chat history
4. Switch to live monitoring
5. Start overlap re-scanning

**For Docker:** Follow prompts in `docker-compose logs -f app`  
**For Local:** Follow prompts in terminal

## Architecture

### Data Flow
```
Telegram Chat → Telethon Client → Message Store → Analysis Pipeline → Database
                      ↓
              Live Listener + Overlap Re-scan
                      ↓
              Bot Commands ← Report Generator ← Query Interface
```

### Core Components

#### 1. **TelegramClientWrapper** (`tg_client.py`)
- Telethon-based client with rate limiting
- Backfill and live message fetching
- FloodWait error handling
- Message format normalization

#### 2. **IngestionEngine** (`ingest.py`)
- Orchestrates backfill and live processing
- Maintains checkpoints and high-water marks
- Overlap re-scanning for gap prevention
- Statistics and monitoring

#### 3. **MessageAnalyzer** (`analyze.py`)
- FinBERT sentiment analysis (BULLISH/BEARISH/NEUTRAL)
- Cryptocurrency token extraction ($BTC, $ETH, etc.)
- Investment relevance detection
- Key point extraction

#### 4. **DatabaseStore** (`store.py`)
- Dual PostgreSQL/SQLite support
- Idempotent upserts with conflict resolution
- Efficient querying with indexes
- Migration-ready schema

#### 5. **TelegramBot** (`bot_commands.py`)
- Interactive command interface
- Report generation and CSV exports
- Admin-only audit commands
- Flexible date range parsing

## Usage

### Bot Commands

Once running, use these Telegram bot commands:

#### Reports
```
/report last 24h
/report last 7d topic:BTC
/report 2024-01-01 to 2024-01-31 limit:100
```

#### Data Export
```
/export last 7d
/export 2024-01-01 to 2024-01-31 topic:ETH
```

#### Statistics
```
/stats
```

#### Admin Commands
```
/audit last 24h          # Re-scan date range
/help                     # Show help
```

### Date Range Formats

- **Relative**: `last 24h`, `last 7d`, `last 30d`
- **Range**: `2024-01-01 to 2024-01-31`
- **Single**: `2024-01-15` (full day)

### Filters

- **Topic**: `topic:BTC` or `topic:DEFI`
- **Limit**: `limit:100` (max results)

## Analysis Pipeline

### Investment Detection
Messages are classified as investment-related if they contain:
1. **Cryptocurrency tokens**: $BTC, $ETH, etc.
2. **Finance keywords**: 2+ words from extensive finance vocabulary

### Sentiment Analysis
- **Model**: ProsusAI/FinBERT (financial sentiment)
- **Output**: BULLISH, BEARISH, NEUTRAL
- **Confidence**: Threshold-based classification

### Token Extraction
- **Cashtags**: `$TOKEN` format recognition
- **Aliases**: Common name mapping (Bitcoin → BTC)
- **Normalization**: Consistent uppercase formatting

### Key Points
- **Cleaning**: URL and emoji removal
- **Extraction**: Meaningful sentence identification
- **Summarization**: Top 3 key points per message

## Database Schema

### Messages Table
```sql
CREATE TABLE messages (
    chat_id BIGINT,
    message_id BIGINT,
    ts_utc TIMESTAMP,
    from_user_id BIGINT,
    from_username TEXT,
    is_forwarded BOOLEAN,
    forward_from TEXT,
    text TEXT,
    urls TEXT[],
    reply_to_id BIGINT,
    edit_date TIMESTAMP,
    PRIMARY KEY (chat_id, message_id)
);
```

### Analysis Table
```sql
CREATE TABLE analysis (
    chat_id BIGINT,
    message_id BIGINT,
    is_investment BOOLEAN,
    sentiment TEXT CHECK (sentiment IN ('BULLISH','BEARISH','NEUTRAL')),
    tokens TEXT[],
    topic_key TEXT,
    key_points TEXT[],
    confidence REAL,
    model_version INTEGER,
    analyzed_at TIMESTAMP,
    PRIMARY KEY (chat_id, message_id)
);
```

## Configuration Options

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_API_ID` | Telegram API ID | Required |
| `TELEGRAM_API_HASH` | Telegram API Hash | Required |
| `TARGET_CHAT_ID` | Chat to monitor | Required |
| `DB_URL` | Database connection | `sqlite:///./telegram_analysis.db` |
| `OVERLAP_MINUTES` | Re-scan overlap | `120` |
| `BATCH_SIZE` | Fetch batch size | `100` |
| `RATE_LIMIT_DELAY` | API delay (seconds) | `1.0` |
| `BOT_TOKEN` | Bot token (optional) | None |
| `ADMIN_USER_IDS` | Admin user IDs | `[]` |
| `LOG_LEVEL` | Logging level | `INFO` |

### Finance Keywords
Extensive vocabulary including: price, market, liquidity, TVL, APR, mainnet, testnet, TGE, CEX, emission, airdrop, DeFi, trading, staking, governance, etc.

## Monitoring & Observability

### Metrics
- `ingested_messages_total`: Total messages processed
- `analyzed_messages_total`: Total messages analyzed
- `overlap_rescans_total`: Re-scan operations
- `flood_wait_seconds_total`: Rate limit delays
- `ingest_lag_seconds`: Processing lag

### Logging
- **Structured**: JSON-compatible format
- **Levels**: DEBUG, INFO, WARNING, ERROR
- **Rotation**: 10MB files, 7-day retention
- **Compression**: Gzip for archived logs

## Deployment

### Docker Deployment (Recommended)

See [Docker Setup Guide](docker-setup.md) for detailed instructions.

**Quick Commands:**
```bash
# Start services
docker-compose up -d

# View logs
docker-compose logs -f

# Backup database
docker-compose --profile backup run --rm backup

# Stop services
docker-compose down
```

**Production Considerations:**
- Use strong passwords in `.env`
- Set up log rotation and monitoring
- Configure automated backups
- Use Docker secrets for sensitive data
- Monitor resource usage

### Local/Systemd Deployment

```ini
[Unit]
Description=Telegram Analysis Service
After=network.target postgresql.service

[Service]
Type=simple
User=telegram
WorkingDirectory=/opt/telegram-analysis
ExecStart=/opt/telegram-analysis/venv/bin/python app.py
Restart=always
RestartSec=10
Environment=DB_URL=postgresql://user:pass@localhost:5432/telegram_analysis

[Install]
WantedBy=multi-user.target
```

## Testing

### Test Plan
1. **Setup**: Create test supergroup with 30+ messages
2. **Content**: Include cashtags, finance terms, and edits
3. **Restart**: Stop/restart mid-run to verify checkpoints
4. **Edits**: Modify messages to test overlap re-scan
5. **Commands**: Test `/report` and `/export` functionality

### Validation
- No duplicate messages after restart
- Edit detection and re-analysis
- Accurate sentiment classification
- Complete data in CSV exports

## Troubleshooting

### Common Issues

#### Authentication Errors
- Verify API ID and hash from https://my.telegram.org
- Check session file permissions
- Ensure phone number format is correct

#### Chat Access Issues
- Verify chat ID is correct (negative for supergroups)
- Ensure account has read access to target chat
- Check for private chat restrictions

#### Database Errors
- Verify connection string format
- Check database permissions
- Ensure PostgreSQL/SQLite is running

#### Rate Limiting
- Service automatically handles FloodWait errors
- Increase `RATE_LIMIT_DELAY` if needed
- Monitor `flood_wait_seconds_total` metric

### Performance Tuning

#### Database Optimization
- Use PostgreSQL for large datasets
- Add indexes for frequent queries
- Consider partitioning for very large tables

#### Memory Usage
- Adjust `BATCH_SIZE` for memory constraints
- Monitor FinBERT model memory usage
- Use CPU-only inference if GPU unavailable

## Contributing

1. Fork the repository
2. Create feature branch
3. Add tests for new functionality
4. Ensure code follows style guidelines
5. Submit pull request

## License

MIT License - see LICENSE file for details.

## Support

For issues and questions:
1. Check troubleshooting section
2. Review logs for error details
3. Open GitHub issue with reproduction steps
4. Include configuration (without secrets)
