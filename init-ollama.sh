#!/bin/bash

# Ollama initialization script for Docker
# This script pulls the required model and ensures Ollama is ready

echo "🤖 Initializing Ollama with Llama 3.2 3B model..."

# Wait for Ollama service to be ready
echo "⏳ Waiting for Ollama service to start..."
until curl -f http://localhost:11434/api/version > /dev/null 2>&1; do
    echo "   Ollama not ready yet, waiting 5 seconds..."
    sleep 5
done

echo "✅ Ollama service is ready!"

# Pull the model if it doesn't exist
echo "📥 Checking if llama3.2:3b model exists..."
if ! ollama list | grep -q "llama3.2:3b"; then
    echo "📦 Pulling llama3.2:3b model (this may take a few minutes)..."
    ollama pull llama3.2:3b
    echo "✅ Model downloaded successfully!"
else
    echo "✅ Model already exists!"
fi

# Test the model
echo "🧪 Testing model inference..."
response=$(ollama run llama3.2:3b "Extract crypto insight: BTC looking strong" --timeout 10s 2>/dev/null || echo "timeout")
if [[ "$response" != "timeout" && -n "$response" ]]; then
    echo "✅ Model test successful!"
    echo "   Response: ${response:0:100}..."
else
    echo "⚠️  Model test failed or timed out, but continuing..."
fi

echo "🎉 Ollama initialization complete!"
