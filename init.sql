-- PostgreSQL initialization script
-- This runs when the database container starts for the first time

-- Create the database user (already created by POSTGRES_USER env var)
-- Create extensions if needed
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Set timezone to UTC
SET timezone = 'UTC';

-- Create indexes that might be useful for performance
-- Note: Tables are created by the application, these are additional optimizations

-- Function to create indexes after tables exist
CREATE OR REPLACE FUNCTION create_performance_indexes()
RETURNS void AS $$
BEGIN
    -- Check if tables exist before creating indexes
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'messages') THEN
        -- Additional indexes for common queries
        CREATE INDEX IF NOT EXISTS idx_messages_chat_ts ON messages(chat_id, ts_utc DESC);
        CREATE INDEX IF NOT EXISTS idx_messages_from_user ON messages(from_user_id) WHERE from_user_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_messages_text_search ON messages USING gin(to_tsvector('english', text));
        
        RAISE NOTICE 'Performance indexes created for messages table';
    END IF;
    
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'analysis') THEN
        -- Indexes for analysis queries
        CREATE INDEX IF NOT EXISTS idx_analysis_chat_investment ON analysis(chat_id, is_investment) WHERE is_investment = true;
        CREATE INDEX IF NOT EXISTS idx_analysis_sentiment_confidence ON analysis(sentiment, confidence) WHERE confidence IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_analysis_topic ON analysis(topic_key);
        
        RAISE NOTICE 'Performance indexes created for analysis table';
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Grant necessary permissions
GRANT ALL PRIVILEGES ON DATABASE telegram_analysis TO telegram_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO telegram_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO telegram_user;

-- Set default privileges for future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON TABLES TO telegram_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON SEQUENCES TO telegram_user;

-- Log initialization
DO $$
BEGIN
    RAISE NOTICE 'Telegram Analysis Database initialized successfully';
    RAISE NOTICE 'Database: telegram_analysis';
    RAISE NOTICE 'User: telegram_user';
    RAISE NOTICE 'Timezone: %', current_setting('timezone');
END;
$$;
