-- Migration script to fix timezone issues in PostgreSQL schema
-- This converts all TIMESTAMP columns to TIMESTAMP WITH TIME ZONE

-- First, let's create backup tables (optional, but recommended)
CREATE TABLE IF NOT EXISTS messages_backup AS SELECT * FROM messages;
CREATE TABLE IF NOT EXISTS analysis_backup AS SELECT * FROM analysis;
CREATE TABLE IF NOT EXISTS ingest_checkpoint_backup AS SELECT * FROM ingest_checkpoint;
CREATE TABLE IF NOT EXISTS high_water_marks_backup AS SELECT * FROM high_water_marks;

-- Fix messages table
ALTER TABLE messages 
    ALTER COLUMN ts_utc TYPE TIMESTAMP WITH TIME ZONE USING ts_utc AT TIME ZONE 'UTC',
    ALTER COLUMN edit_date TYPE TIMESTAMP WITH TIME ZONE USING edit_date AT TIME ZONE 'UTC',
    ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE USING created_at AT TIME ZONE 'UTC';

-- Fix analysis table
ALTER TABLE analysis
    ALTER COLUMN analyzed_at TYPE TIMESTAMP WITH TIME ZONE USING analyzed_at AT TIME ZONE 'UTC';

-- Fix ingest_checkpoint table
ALTER TABLE ingest_checkpoint
    ALTER COLUMN last_ts_utc TYPE TIMESTAMP WITH TIME ZONE USING last_ts_utc AT TIME ZONE 'UTC',
    ALTER COLUMN updated_at TYPE TIMESTAMP WITH TIME ZONE USING updated_at AT TIME ZONE 'UTC';

-- Fix high_water_marks table
ALTER TABLE high_water_marks
    ALTER COLUMN ts_utc TYPE TIMESTAMP WITH TIME ZONE USING ts_utc AT TIME ZONE 'UTC',
    ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE USING created_at AT TIME ZONE 'UTC';

-- Update default values to use timezone-aware timestamps
ALTER TABLE messages ALTER COLUMN created_at SET DEFAULT NOW();
ALTER TABLE analysis ALTER COLUMN analyzed_at SET DEFAULT NOW();
ALTER TABLE ingest_checkpoint ALTER COLUMN updated_at SET DEFAULT NOW();
ALTER TABLE high_water_marks ALTER COLUMN created_at SET DEFAULT NOW();

-- Verify the changes
\d+ messages
\d+ analysis
\d+ ingest_checkpoint
\d+ high_water_marks
