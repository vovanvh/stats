#!/bin/bash
set -e

echo "Running in production mode"
# Calculate number of workers based on CPU cores
WORKERS_PER_CORE=${WORKERS_PER_CORE:-1}
MAX_WORKERS=${MAX_WORKERS:-16}
WEB_CONCURRENCY=${WEB_CONCURRENCY:-$(( $(nproc) * $WORKERS_PER_CORE ))}

# Ensure we don't exceed max workers
if [ "$WEB_CONCURRENCY" -gt "$MAX_WORKERS" ]; then
    WEB_CONCURRENCY=$MAX_WORKERS
fi

# Gunicorn settings
WORKER_CONNECTIONS=${WORKER_CONNECTIONS:-1000}
TIMEOUT=${TIMEOUT:-60}
KEEP_ALIVE=${KEEP_ALIVE:-5}
GRACEFUL_TIMEOUT=${GRACEFUL_TIMEOUT:-120}

# Start Gunicorn with production settings
echo "Starting Gunicorn with $WEB_CONCURRENCY workers"
exec gunicorn main:app \
    --bind 0.0.0.0:80 \
    --workers $WEB_CONCURRENCY \
    --worker-class uvicorn.workers.UvicornWorker \
    --worker-connections $WORKER_CONNECTIONS \
    --timeout $TIMEOUT \
    --keep-alive $KEEP_ALIVE \
    --graceful-timeout $GRACEFUL_TIMEOUT \
    --log-level $LOG_LEVEL \
    --access-logfile - \
    --error-logfile - \
    --forwarded-allow-ips="*"
