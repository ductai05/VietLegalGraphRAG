#!/bin/bash
set -e

# Forward shutdown signals to Open WebUI background process for graceful shutdown
cleanup() {
    echo "Stopping Open WebUI container gracefully..."
    if [ -n "$WEBUI_PID" ]; then
        kill -TERM "$WEBUI_PID" 2>/dev/null
        wait "$WEBUI_PID"
    fi
    exit 0
}
trap cleanup SIGTERM SIGINT

# Start Open WebUI server in the background
echo "Starting Open WebUI backend server..."
cd /app/backend
bash start.sh &
WEBUI_PID=$!

# Run the Pipe initialization script in the background to avoid blocking
echo "Running pipe initialization script..."
python /app/init_pipe.py &

# Wait for the Open WebUI background process to keep container alive
wait $WEBUI_PID
