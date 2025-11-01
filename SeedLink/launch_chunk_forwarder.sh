#!/bin/bash

echo "🌋 Starting SeedLink Chunk Forwarder..."
echo "================================"

# Kill any existing processes
echo "🧹 Cleaning up existing processes..."
pkill -9 -f "chunk_forwarder.py" 2>/dev/null
sleep 1

# Get the script's directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Clear old log
> /tmp/chunk_forwarder.log

# Start SeedLink Chunk Forwarder
echo "🔊 Starting SeedLink Chunk Forwarder on localhost:8889..."
cd "$SCRIPT_DIR" && python3 chunk_forwarder.py > /tmp/chunk_forwarder.log 2>&1 &
FORWARDER_PID=$!

# Wait for forwarder to load (ObsPy takes time)
echo "   Waiting for backend to load dependencies..."
MAX_WAIT=15
WAIT_COUNT=0

while [ $WAIT_COUNT -lt $MAX_WAIT ]; do
    if lsof -i :8889 2>/dev/null | grep -q LISTEN; then
        break
    fi
    sleep 1
    WAIT_COUNT=$((WAIT_COUNT + 1))
done

echo ""
echo "================================"
echo "🔍 Checking Service Status..."
echo "================================"

# Check SeedLink Chunk Forwarder
FORWARDER_RUNNING=false
if lsof -i :8889 2>/dev/null | grep -q LISTEN; then
    echo "✅ SeedLink Chunk Forwarder:  http://localhost:8889 (RUNNING)"
    FORWARDER_RUNNING=true
else
    echo "❌ SeedLink Chunk Forwarder:  FAILED TO START"
    echo ""
    echo "📋 Forwarder Logs (last 30 lines):"
    echo "-----------------------------------"
    tail -30 /tmp/chunk_forwarder.log
    echo "-----------------------------------"
    echo ""
fi

echo ""
echo "================================"

if [ "$FORWARDER_RUNNING" = true ]; then
    echo "✅ Service Running Successfully!"
    echo ""
    echo "📡 Dashboard: http://localhost:8889"
    echo ""
    echo "View Live Logs:"
    echo "   tail -f /tmp/chunk_forwarder.log"
    echo ""
    echo "To stop:"
    echo "   • Run: pkill -f 'chunk_forwarder.py'"
    echo ""
    echo "✅ Ready to forward seismic chunks!"
else
    echo "⚠️  Service failed to start. Check logs above."
    echo ""
    echo "📋 Troubleshooting:"
    echo "   • Check conda environment: conda env list"
    echo "   • Install dependencies: pip install -r requirements.txt"
    echo "   • Full logs: tail -f /tmp/chunk_forwarder.log"
    exit 1
fi

