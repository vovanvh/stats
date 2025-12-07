# Deployment Environments Guide

This document describes how the my-stats application runs in test/development and production environments, including configuration, deployment procedures, and key differences between the environments.

## Table of Contents

1. [Overview](#overview)
2. [Development/Test Environment](#developmenttest-environment)
3. [Production Environment](#production-environment)
4. [Environment Comparison](#environment-comparison)
5. [Common Operations](#common-operations)

---

## Overview

The my-stats application uses Docker containers for both development and production deployments. The architecture consists of two main services:

- **Tor Proxy Service**: Provides SOCKS5 proxy for anonymized YouTube API requests
- **FastAPI Server**: The main application server

Both environments share the same external Docker network (`devnetwork`) but differ significantly in their configuration, optimization, and security settings.

---

## Development/Test Environment

### Architecture

The development environment is optimized for rapid development with live code reloading and debugging capabilities.

```
┌─────────────────────────────────────────────────┐
│              Development Setup                   │
├─────────────────────────────────────────────────┤
│                                                  │
│  ┌──────────────┐          ┌─────────────────┐ │
│  │  Tor Proxy   │          │  FastAPI Server │ │
│  │  Container   │◄────────►│   (Uvicorn)     │ │
│  │  :9050       │          │   :8000         │ │
│  └──────────────┘          └─────────────────┘ │
│                                   ▲             │
│                                   │             │
│                            Volume Mount         │
│                            (Live Reload)        │
│                                   │             │
└───────────────────────────────────┼─────────────┘
                                    │
                           Host Machine Code
```

### Dockerfile Configuration

**File**: `docker/python/dev/Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
COPY requirements-dev.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements-dev.txt

# Copy project files
COPY . .

# Expose port
EXPOSE 8000

# Command to run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Key Features**:
- Single-stage build for faster rebuilds
- Includes development dependencies from `requirements-dev.txt`
- No optimization for image size
- Runs as root user for easier debugging
- Uses Uvicorn directly for ASGI serving

### Docker Compose Configuration

**File**: `docker-compose.dev.yaml`

```yaml
services:
  tor:
    image: dperson/torproxy
    container_name: tor-proxy
    restart: always
    ports:
      - "9050:9050"
    networks:
      - devnetwork

  server:
    image: vovanvh/voca:stats-dev
    container_name: krys-stats
    build: docker/python/dev
    command: uvicorn main:app --host 0.0.0.0 --port 8000
    restart: always
    env_file:
      - .env
    environment:
      - TOR_PROXY_HOST=tor-proxy
      - TOR_PROXY_PORT=9050
    ports:
      - 8000:8000
    volumes:
      - .:/app
    depends_on:
      - tor
    networks:
      - devnetwork

networks:
  devnetwork:
    external: true
```

**Key Features**:
- **Volume Mounting**: `.:/app` enables live code reloading
- **Port Exposure**: Port 8000 exposed to host for direct access
- **Restart Policy**: `always` for automatic recovery
- **Environment**: Uses `.env` file for configuration
- **Command**: Simple Uvicorn with hot-reload capability

### Environment Configuration

**File**: `.env.example` (copy to `.env` for development)

```bash
# Application settings
APP_NAME=fastapi-app
APP_VERSION=0.1.0
APP_ENV=development
DEBUG=True

# Server settings
HOST=0.0.0.0
PORT=8000

# Database settings
CLICKHOUSE_HOST="v_clickhouse"
CLICKHOUSE_PORT=8123
CLICKHOUSE_USERNAME="root"
CLICKHOUSE_PASSWORD="111-111-111"
CLICKHOUSE_DATABASE="default"
CLICKHOUSE_SECURE=False

# JWT settings
JWT_SECRET_KEY=your_super_secret_key_here
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# CORS settings
CORS_ORIGINS=["http://localhost:3000", "http://localhost:8080"]

# Logging
LOG_LEVEL=INFO
```

**Development-Specific Settings**:
- `DEBUG=True`: Enables detailed error messages and auto-reload
- `LOG_LEVEL=INFO`: Verbose logging for debugging
- `PORT=8000`: Development port
- `ACCESS_TOKEN_EXPIRE_MINUTES=30`: Longer token expiration
- `CORS_ORIGINS`: Permissive CORS for local development

### Deployment Procedure

#### Initial Setup

```bash
# 1. Create external Docker network (only needed once)
docker network create devnetwork

# 2. Copy environment configuration
cp .env.example .env

# 3. Edit environment variables (optional)
nano .env  # or your preferred editor
```

#### Building and Starting Services

```bash
# Build the development image
docker-compose -f docker-compose.dev.yaml build

# Start all services in detached mode
docker-compose -f docker-compose.dev.yaml up -d

# Or start with logs visible (Ctrl+C to stop)
docker-compose -f docker-compose.dev.yaml up
```

#### Verifying the Deployment

```bash
# Check running containers
docker-compose -f docker-compose.dev.yaml ps

# Expected output:
# NAME           IMAGE                      COMMAND                  SERVICE   STATUS
# krys-stats     vovanvh/voca:stats-dev     "uvicorn main:app --…"   server    Up 2 minutes
# tor-proxy      dperson/torproxy           "/sbin/tini -- tor"      tor       Up 2 minutes

# View logs
docker-compose -f docker-compose.dev.yaml logs -f server

# Test the health endpoint
curl http://localhost:8000/health

# Expected response:
# {"status":"healthy"}

# Test Tor proxy functionality
curl http://localhost:8000/test-tor
```

#### Making Code Changes

With volume mounting enabled, any code changes are immediately reflected:

```bash
# 1. Edit your Python files
nano main.py

# 2. Uvicorn automatically detects changes and reloads
# Watch the logs to see the reload:
docker-compose -f docker-compose.dev.yaml logs -f server

# You should see: "Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)"
```

#### Stopping Services

```bash
# Stop all services
docker-compose -f docker-compose.dev.yaml down

# Stop and remove volumes (careful: this deletes data)
docker-compose -f docker-compose.dev.yaml down -v

# Stop a specific service
docker-compose -f docker-compose.dev.yaml stop server
```

### Testing API Endpoints

```bash
# Health check
curl http://localhost:8000/health

# Test Tor connection
curl http://localhost:8000/test-tor

# Get YouTube transcript
curl "http://localhost:8000/yt?videoId=dQw4w9WgXcQ&language=en"

# List available transcripts
curl "http://localhost:8000/yt-list?videoId=dQw4w9WgXcQ"

# Submit statistics data
curl -X POST http://localhost:8000/stats/ \
  -H "Content-Type: application/json" \
  -d '{
    "table": "word_statistics",
    "data": [{
      "language": 1,
      "translationLanguage": 2,
      "wordId": 12345,
      "externalId": 67890,
      "interval": 3,
      "repetitions": 5,
      "lastRes": 4,
      "timestampAdded": 1634567890,
      "timestampUpdated": 1634567900,
      "nextStartTS": 1634567910,
      "type": 1
    }]
  }'
```

---

## Production Environment

### Architecture

The production environment is optimized for performance, security, and reliability.

```
┌─────────────────────────────────────────────────────┐
│              Production Setup                        │
├─────────────────────────────────────────────────────┤
│                                                      │
│  ┌──────────────┐          ┌──────────────────────┐│
│  │  Tor Proxy   │          │  FastAPI Server      ││
│  │  Container   │◄────────►│  (Gunicorn+Uvicorn)  ││
│  │  :9050       │          │  :80 (internal)      ││
│  └──────────────┘          └──────────────────────┘│
│                                                      │
│  Resource Limits:                                   │
│  - CPU: 0.5 cores                                   │
│  - Memory: 512MB                                    │
│  - Multi-worker (CPU-based)                         │
│  - Non-root user execution                          │
│  - Health checks enabled                            │
│                                                      │
└─────────────────────────────────────────────────────┘
```

### Dockerfile Configuration

**File**: `docker/python/prod/Dockerfile`

```dockerfile
# Stage 1: Builder - compile dependencies
FROM python:3.11-slim AS builder

WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

# Install build dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    gcc \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Build wheel packages for faster installation
COPY requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt


# Stage 2: Runtime - minimal production image
FROM python:3.11-slim

WORKDIR /app

# Create non-root user for security
RUN addgroup --system app && adduser --system --group app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/home/app/.local/bin:$PATH"

# Install only runtime dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    curl \
    netcat-traditional \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy and install pre-built wheels
COPY --from=builder /app/wheels /wheels
RUN pip install --no-cache /wheels/*

# Copy application code with proper ownership
COPY --chown=app:app . .

# Copy and set permissions for startup script
COPY --chown=app:app ./scripts/start.sh /start.sh
RUN chmod +x /start.sh

# Create necessary directories
RUN mkdir -p /app/static /app/media \
    && chown -R app:app /app/static /app/media

# Switch to non-root user
USER app

# Expose port
EXPOSE 80

# Configure health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:80/health || exit 1

# Start command
CMD ["/start.sh"]
```

**Key Features**:
- **Multi-stage build**: Separates build and runtime for smaller images
- **Non-root user**: Runs as `app:app` for security
- **Wheel-based installation**: Pre-compiled packages for faster startup
- **Health checks**: Automatic monitoring and recovery
- **Minimal dependencies**: Only curl and netcat for runtime
- **Proper permissions**: All files owned by app user

### Production Startup Script

**File**: `scripts/start.sh`

```bash
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
```

**Worker Calculation Logic**:

```
# On a 4-core machine with WORKERS_PER_CORE=1:
WEB_CONCURRENCY = 4 * 1 = 4 workers

# With MAX_WORKERS=2 (from .env.prod):
WEB_CONCURRENCY = min(4, 2) = 2 workers

# Each worker can handle WORKER_CONNECTIONS=1000 concurrent connections
Total capacity = 2 workers × 1000 connections = 2000 concurrent connections
```

### Docker Compose Configuration

**File**: `docker-compose.prod.yaml`

```yaml
services:
  tor:
    image: dperson/torproxy
    container_name: tor-proxy
    restart: always
    ports:
      - "9050:9050"
    networks:
      - devnetwork

  server:
    image: vovanvh/voca:stats-prod
    container_name: krys-stats-prod
    build: docker/python/prod
    command: /start.sh
    env_file:
      - .env.prod
    environment:
      - TOR_PROXY_HOST=tor-proxy
      - TOR_PROXY_PORT=9050
    restart: always
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:80/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    cpus: "0.5"
    mem_limit: "512m"
    depends_on:
      - tor
    networks:
      - devnetwork

networks:
  devnetwork:
    external: true
```

**Production-Specific Features**:
- **No volume mounts**: Code is baked into the image
- **No port exposure**: Service accessed through reverse proxy
- **Resource limits**: CPU (0.5 cores) and memory (512MB) constraints
- **Health checks**: Automated monitoring with retry logic
- **Separate environment**: Uses `.env.prod` file
- **Start period**: 40s grace period for application startup

### Environment Configuration

**File**: `.env.prod.example` (copy to `.env.prod` for production)

```bash
# Application settings
APP_NAME=fastapi-app
APP_VERSION=1.0.0
APP_ENV=production
DEBUG=False

# Server settings
HOST=0.0.0.0
PORT=80

# Database settings
CLICKHOUSE_HOST="v_clickhouse"
CLICKHOUSE_PORT=8123
CLICKHOUSE_USERNAME="root"
CLICKHOUSE_PASSWORD="111-111-111"
CLICKHOUSE_DATABASE="default"
CLICKHOUSE_SECURE=False

# JWT settings
JWT_SECRET_KEY=replace_with_secure_production_key
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15

# CORS settings - restrict to your frontend domains
CORS_ORIGINS=["https://yourdomain.com", "https://api.yourdomain.com"]

# Logging
LOG_LEVEL=WARNING

# Gunicorn settings
WORKERS_PER_CORE=1
MAX_WORKERS=2
WORKER_CONNECTIONS=1000
TIMEOUT=60
KEEP_ALIVE=5
GRACEFUL_TIMEOUT=120
```

**Production-Specific Settings**:
- `DEBUG=False`: Disables debug mode for security
- `LOG_LEVEL=WARNING`: Minimal logging for performance
- `PORT=80`: Standard HTTP port
- `ACCESS_TOKEN_EXPIRE_MINUTES=15`: Shorter token expiration for security
- `CORS_ORIGINS`: Restricted to specific production domains
- `MAX_WORKERS=2`: Limited workers to control resource usage
- `JWT_SECRET_KEY`: Strong, unique production secret

### Deployment Procedure

#### Initial Setup

```bash
# 1. Create external Docker network (if not exists)
docker network create devnetwork

# 2. Copy and configure production environment
cp .env.prod.example .env.prod

# 3. Edit production settings
nano .env.prod

# CRITICAL: Update these values before deploying:
# - JWT_SECRET_KEY: Generate a strong secret (32+ characters)
# - CLICKHOUSE_PASSWORD: Use production database password
# - CORS_ORIGINS: Set to your actual domain
# - LOG_LEVEL: Keep as WARNING or ERROR
```

#### Building Production Image

```bash
# Build the production image (multi-stage build)
docker-compose -f docker-compose.prod.yaml build --no-cache

# Verify the image was created
docker images | grep stats-prod

# Expected output:
# vovanvh/voca    stats-prod    <IMAGE_ID>    <TIME>    <SIZE>
```

#### Starting Production Services

```bash
# Start services in detached mode
docker-compose -f docker-compose.prod.yaml up -d

# Monitor startup logs
docker-compose -f docker-compose.prod.yaml logs -f server

# Expected output:
# Running in production mode
# Starting Gunicorn with 2 workers
# [INFO] Starting gunicorn 23.0.0
# [INFO] Listening at: http://0.0.0.0:80
# [INFO] Using worker: uvicorn.workers.UvicornWorker
# [INFO] Booting worker with pid: 15
# [INFO] Booting worker with pid: 16
```

#### Verifying Production Deployment

```bash
# Check container status
docker-compose -f docker-compose.prod.yaml ps

# Expected output shows "healthy" status:
# NAME               STATUS
# krys-stats-prod    Up 2 minutes (healthy)
# tor-proxy          Up 2 minutes

# Check health from inside container
docker exec krys-stats-prod curl -f http://localhost:80/health

# Expected response:
# {"status":"healthy"}

# View resource usage
docker stats krys-stats-prod

# Expected output shows CPU and memory limits:
# CONTAINER          CPU %    MEM USAGE / LIMIT     MEM %
# krys-stats-prod    5.23%    145MiB / 512MiB      28.32%

# Test Tor proxy functionality
docker exec krys-stats-prod curl http://localhost:80/test-tor
```

#### Accessing the Production Service

Since the production container doesn't expose ports to the host, access it through:

1. **From another container in the same network**:
```bash
# Example: From another service
curl http://krys-stats-prod:80/health
```

2. **Using docker exec**:
```bash
docker exec krys-stats-prod curl http://localhost:80/health
```

3. **Through a reverse proxy** (recommended setup):
```nginx
# Nginx configuration example
server {
    listen 80;
    server_name api.yourdomain.com;

    location / {
        proxy_pass http://krys-stats-prod:80;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

#### Updating Production Deployment

```bash
# 1. Pull latest code changes
git pull origin main

# 2. Rebuild the image with no cache
docker-compose -f docker-compose.prod.yaml build --no-cache

# 3. Stop old containers
docker-compose -f docker-compose.prod.yaml down

# 4. Start new containers
docker-compose -f docker-compose.prod.yaml up -d

# 5. Verify health
docker-compose -f docker-compose.prod.yaml ps
docker-compose -f docker-compose.prod.yaml logs --tail=50 -f server
```

#### Monitoring Production

```bash
# View real-time logs
docker-compose -f docker-compose.prod.yaml logs -f server

# View last 100 log lines
docker-compose -f docker-compose.prod.yaml logs --tail=100 server

# Monitor resource usage
docker stats krys-stats-prod

# Check health check history
docker inspect krys-stats-prod | grep -A 10 Health

# Monitor Gunicorn workers
docker exec krys-stats-prod ps aux | grep gunicorn
```

---

## Environment Comparison

### Side-by-Side Comparison

| Feature | Development | Production |
|---------|------------|------------|
| **Server** | Uvicorn (single process) | Gunicorn + Uvicorn workers |
| **Workers** | 1 | Dynamic (CPU-based, max 2) |
| **Port** | 8000 (exposed) | 80 (internal only) |
| **Code Updates** | Live reload via volumes | Baked into image |
| **User** | root | app (non-root) |
| **Debug Mode** | Enabled | Disabled |
| **Log Level** | INFO | WARNING |
| **Token Expiration** | 30 minutes | 15 minutes |
| **CORS** | Permissive (localhost) | Restricted (production domains) |
| **Resource Limits** | None | CPU: 0.5, Memory: 512MB |
| **Health Checks** | None | Yes (30s interval) |
| **Image Build** | Single-stage | Multi-stage (optimized) |
| **Image Size** | Larger (~500MB+) | Smaller (~300MB) |
| **Dependencies** | Dev + prod | Production only |
| **Startup Time** | Fast (~5s) | Slower (~40s with workers) |
| **Restart Policy** | always | always |
| **Security** | Relaxed | Hardened |

### Performance Characteristics

#### Development Environment

```python
# Single Uvicorn worker
Concurrent Requests: ~100-500
Response Time: Fast (no worker overhead)
Memory Usage: ~150-200MB
CPU Usage: Variable, spikes during reload
Startup Time: ~5 seconds
```

#### Production Environment

```python
# 2 Gunicorn workers with Uvicorn workers
Concurrent Requests: ~2000 (2 workers × 1000 connections)
Response Time: Consistent (load balanced)
Memory Usage: ~300-400MB (multiple workers)
CPU Usage: Distributed across workers
Startup Time: ~40 seconds (worker initialization)
```

### Security Comparison

| Security Feature | Development | Production |
|------------------|-------------|------------|
| Non-root user | No | Yes (app:app) |
| Debug info exposure | Yes | No |
| Verbose logging | Yes | Minimal |
| CORS restrictions | Loose | Strict |
| JWT secret | Weak | Strong |
| File permissions | Permissive | Restricted |
| Build tools in image | Yes | No |
| Volume access | Full | None |
| Secret management | .env file | .env.prod + secrets |

---

## Common Operations

### Switching Between Environments

```bash
# Currently running development, switch to production:
docker-compose -f docker-compose.dev.yaml down
docker-compose -f docker-compose.prod.yaml up -d

# Currently running production, switch to development:
docker-compose -f docker-compose.prod.yaml down
docker-compose -f docker-compose.dev.yaml up -d
```

### Viewing Logs

```bash
# Development logs
docker-compose -f docker-compose.dev.yaml logs -f server

# Production logs
docker-compose -f docker-compose.prod.yaml logs -f server

# All services logs
docker-compose -f docker-compose.dev.yaml logs -f

# Specific time range
docker-compose logs --since 30m server
```

### Debugging Issues

#### Development Debugging

```bash
# Enter the container
docker exec -it krys-stats bash

# Run Python commands
docker exec -it krys-stats python -c "from app.config import settings; print(settings)"

# Check environment variables
docker exec -it krys-stats env | grep APP_

# Test database connection
docker exec -it krys-stats python -c "from app.database import get_clickhouse_client; client = get_clickhouse_client(); print('Connected')"
```

#### Production Debugging

```bash
# Enter the container (as app user)
docker exec -it -u app krys-stats-prod bash

# Check worker processes
docker exec -it krys-stats-prod ps aux

# Test health endpoint
docker exec -it krys-stats-prod curl http://localhost:80/health

# Check Gunicorn master process
docker exec -it krys-stats-prod ps aux | grep gunicorn
```

### Database Operations

```bash
# Development: Access ClickHouse
docker exec -it krys-stats python -c "
from app.database import get_clickhouse_client
client = get_clickhouse_client()
result = client.query('SHOW DATABASES')
print(result.result_rows)
"

# Production: Same, but specify user
docker exec -it -u app krys-stats-prod python -c "
from app.database import get_clickhouse_client
client = get_clickhouse_client()
result = client.query('SELECT version()')
print(result.result_rows)
"
```

### Rebuilding Images

```bash
# Development: Rebuild without cache
docker-compose -f docker-compose.dev.yaml build --no-cache

# Production: Rebuild without cache
docker-compose -f docker-compose.prod.yaml build --no-cache

# Rebuild specific service
docker-compose -f docker-compose.dev.yaml build server
```

### Cleanup Operations

```bash
# Stop and remove containers
docker-compose -f docker-compose.dev.yaml down

# Remove containers and volumes
docker-compose -f docker-compose.dev.yaml down -v

# Remove containers, volumes, and images
docker-compose -f docker-compose.dev.yaml down -v --rmi all

# Clean up unused Docker resources
docker system prune -a
```

### Testing Tor Proxy

```bash
# Development environment
curl http://localhost:8000/test-tor

# Production environment (from inside container)
docker exec krys-stats-prod curl http://localhost:80/test-tor

# Expected response (when working):
{
  "tor_enabled": true,
  "tor_proxy": "tor-proxy:9050",
  "direct_ip": "1.2.3.4",
  "proxied_ip": "5.6.7.8",
  "tor_working": true
}
```

### Performance Testing

```bash
# Install Apache Bench (if not installed)
sudo apt-get install apache2-utils

# Test development endpoint
ab -n 1000 -c 10 http://localhost:8000/health

# Test production endpoint (from another container)
docker run --rm --network devnetwork alpine/curl \
  sh -c "apk add apache2-utils && ab -n 1000 -c 10 http://krys-stats-prod:80/health"
```

---

## Best Practices

### Development Environment

1. **Always use volume mounts** for instant code updates
2. **Keep DEBUG=True** for detailed error messages
3. **Use verbose logging** (LOG_LEVEL=INFO or DEBUG)
4. **Expose ports** for easy testing from host
5. **Use development secrets** (not production secrets)
6. **Commit .env.example**, not .env

### Production Environment

1. **Never use DEBUG=True** in production
2. **Use strong, unique secrets** for JWT and database
3. **Limit resource usage** with CPU and memory constraints
4. **Enable health checks** for automatic recovery
5. **Use non-root user** for security
6. **Minimize logging** (LOG_LEVEL=WARNING or ERROR)
7. **Restrict CORS** to specific domains
8. **Use reverse proxy** (Nginx, Traefik) for SSL/TLS
9. **Monitor resource usage** regularly
10. **Backup .env.prod** securely (encrypted storage)

### Security Checklist

Before deploying to production:

- [ ] Change JWT_SECRET_KEY to a strong, unique value
- [ ] Update database credentials (CLICKHOUSE_PASSWORD)
- [ ] Set CORS_ORIGINS to production domains only
- [ ] Verify DEBUG=False
- [ ] Set LOG_LEVEL to WARNING or ERROR
- [ ] Review and restrict API access if needed
- [ ] Enable HTTPS through reverse proxy
- [ ] Set up monitoring and alerting
- [ ] Configure backup procedures
- [ ] Document recovery procedures

---

## Troubleshooting

### Common Issues

#### Issue: Container won't start

```bash
# Check logs
docker-compose -f docker-compose.prod.yaml logs server

# Common causes:
# 1. Missing .env.prod file
# 2. Syntax error in .env.prod
# 3. Port already in use
# 4. Network doesn't exist

# Solutions:
docker network ls  # Check if devnetwork exists
docker network create devnetwork  # Create if missing
lsof -i :8000  # Check what's using port 8000
```

#### Issue: Health check failing

```bash
# Check health status
docker inspect krys-stats-prod | grep -A 10 Health

# Test endpoint manually
docker exec krys-stats-prod curl -v http://localhost:80/health

# Common causes:
# 1. Application not listening on correct port
# 2. Application startup taking too long
# 3. Health endpoint not responding

# Solutions:
# Increase start_period in docker-compose.prod.yaml
# Check application logs for errors
# Verify PORT in .env.prod matches Dockerfile EXPOSE
```

#### Issue: Tor proxy not working

```bash
# Check Tor container
docker logs tor-proxy

# Test proxy connectivity
docker exec krys-stats curl http://localhost:8000/test-tor

# Common causes:
# 1. Tor container not running
# 2. Incorrect TOR_PROXY_HOST setting
# 3. Network connectivity issues

# Solutions:
docker-compose restart tor
# Verify TOR_PROXY_HOST=tor-proxy in environment
# Check both containers are on same network
```

#### Issue: Out of memory

```bash
# Check memory usage
docker stats krys-stats-prod

# If memory usage is at limit (512MB):
# Solutions:
# 1. Increase mem_limit in docker-compose.prod.yaml
# 2. Reduce MAX_WORKERS
# 3. Optimize application code
# 4. Add swap memory to host
```

---

## Conclusion

This guide provides comprehensive instructions for deploying and managing the my-stats application in both development and production environments. Always test changes in development before deploying to production, and maintain separate configuration files for each environment.

For additional support and updates, refer to the project repository and general documentation.
