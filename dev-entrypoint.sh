#!/bin/bash
# Development entrypoint script

set -e

echo "🚀 Starting Telegram Analysis Service (Development Mode)"
echo "📁 Working directory: $(pwd)"
echo "🐍 Python version: $(python --version)"
echo "📦 Installed packages:"
pip list | grep -E "(telethon|transformers|pydantic|asyncpg|loguru)"

# Wait for database to be ready
echo "⏳ Waiting for PostgreSQL..."
while ! pg_isready -h postgres -U telegram_user -d telegram_analysis; do
    sleep 1
done
echo "✅ PostgreSQL is ready"

# Run diagnostics in development mode
echo "🧪 Running development diagnostics..."
python setup.py test || echo "⚠️  Some tests failed, but continuing..."

# Start the application
echo "🎯 Starting application..."
exec python -u app.py
