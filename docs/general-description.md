# My-Stats - General Project Description

## Overview

My-Stats is a FastAPI-based statistics tracking service designed to collect and store statistics data in ClickHouse database. The service includes YouTube transcript fetching capabilities with optional Tor proxy support for anonymized requests. The project is containerized using Docker and provides both development and production deployment configurations.

## Project Purpose

The service serves as a backend API for:
1. Collecting and storing statistics data (language learning statistics based on word repetition patterns)
2. Fetching YouTube video transcripts in multiple languages
3. Managing transcript retrieval with proxy support for rate-limiting avoidance

## Technology Stack

### Core Technologies
- **Python 3.11**: Primary programming language
- **FastAPI**: Modern, high-performance web framework for building APIs
- **Uvicorn**: ASGI server for development
- **Gunicorn**: Production-grade WSGI HTTP server with Uvicorn workers
- **Pydantic**: Data validation using Python type annotations
- **ClickHouse**: Column-oriented database for analytics and statistics storage

### Additional Libraries
- **youtube-transcript-api**: YouTube transcript fetching
- **requests[socks]**: HTTP library with SOCKS proxy support
- **pysocks**: SOCKS proxy implementation
- **clickhouse-connect**: ClickHouse database client
- **pydantic-settings**: Settings management from environment variables

### Infrastructure
- **Docker**: Containerization platform
- **Docker Compose**: Multi-container orchestration
- **Tor Proxy (dperson/torproxy)**: Anonymous proxy service

## Project Structure

```
my-stats/
├── app/                          # Application package
│   ├── config.py                 # Configuration management
│   └── database.py               # ClickHouse database client setup
├── docker/                       # Docker configurations
│   └── python/
│       ├── dev/                  # Development Dockerfile
│       │   └── Dockerfile
│       └── prod/                 # Production Dockerfile
│           └── Dockerfile
├── scripts/                      # Deployment scripts
│   └── start.sh                  # Production startup script
├── main.py                       # FastAPI application entry point
├── requirements.txt              # Production dependencies
├── requirements-dev.txt          # Development dependencies
├── .env.example                  # Development environment template
├── .env.prod.example             # Production environment template
├── docker-compose.yaml           # Base Docker Compose configuration
├── docker-compose.dev.yaml       # Development Docker Compose
└── docker-compose.prod.yaml      # Production Docker Compose
```

## Architecture

### Application Architecture

The application follows a modular architecture with clear separation of concerns:

```
┌─────────────────────────────────────────────────────┐
│                   FastAPI Application                │
│                      (main.py)                       │
├─────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────┐  │
│  │   Config     │  │   Database   │  │  Routes  │  │
│  │  (app/)      │  │   (app/)     │  │ (main.py)│  │
│  └──────────────┘  └──────────────┘  └──────────┘  │
└─────────────────────────────────────────────────────┘
           ↓                ↓                 ↓
    ┌──────────────┐  ┌────────────┐  ┌─────────────┐
    │ Environment  │  │ ClickHouse │  │  YouTube    │
    │  Variables   │  │  Database  │  │   API       │
    └──────────────┘  └────────────┘  └─────────────┘
                                              ↓
                                      ┌──────────────┐
                                      │  Tor Proxy   │
                                      │  (Optional)  │
                                      └──────────────┘
```

### Deployment Architecture

The service runs in a Docker containerized environment with two main services:

1. **Tor Proxy Container**: Provides SOCKS5 proxy for anonymized requests
2. **FastAPI Server Container**: Main application server

Both containers communicate through a Docker network (`devnetwork`).

## Detailed Component Description

### 1. Configuration Management (`app/config.py`)

**Purpose**: Centralized configuration management using Pydantic settings.

**Key Features**:
- Environment-based configuration using `pydantic-settings`
- Type-safe configuration with validation
- Default values for all settings
- Case-sensitive configuration keys

**Configuration Groups**:

#### Application Settings
- `APP_NAME`: Application identifier (default: "my-stats")
- `APP_VERSION`: Application version (default: "1.0.0")
- `APP_ENV`: Environment (production/development)
- `DEBUG`: Debug mode flag

#### ClickHouse Database Settings
- `CLICKHOUSE_HOST`: Database host (default: "v_clickhouse")
- `CLICKHOUSE_PORT`: Database port (default: 8123)
- `CLICKHOUSE_USERNAME`: Database username
- `CLICKHOUSE_PASSWORD`: Database password
- `CLICKHOUSE_DATABASE`: Database name (default: "default")
- `CLICKHOUSE_SECURE`: SSL connection flag

#### Tor Proxy Settings
- `USE_TOR_PROXY`: Enable/disable Tor proxy (default: True)
- `TOR_PROXY_HOST`: Proxy hostname (default: "tor-proxy")
- `TOR_PROXY_PORT`: Proxy port (default: 9050)

**Implementation Details**:
- Uses `os.getenv()` to read environment variables
- Allows extra fields for flexibility
- Single `settings` instance exported for application-wide use

### 2. Database Management (`app/database.py`)

**Purpose**: ClickHouse database client initialization and management.

**Key Features**:
- Lazy client initialization
- Configuration-driven connection parameters
- Singleton pattern through function-based access

**Function**: `get_clickhouse_client()`
- Creates and returns ClickHouse client instance
- Uses settings from configuration
- Supports secure and non-secure connections

**Connection Parameters**:
- Host and port from configuration
- Username/password authentication
- Database selection
- Optional SSL/TLS support

### 3. Main Application (`main.py`)

**Purpose**: FastAPI application with API endpoints and business logic.

#### Custom Route Class

**SlashInsensitiveAPIRoute**
- Custom route class for handling trailing slashes
- Normalizes paths by removing trailing slashes
- Provides logging for path matching
- Ensures consistent URL handling

**Implementation**:
```python
class SlashInsensitiveAPIRoute(APIRoute):
    def matches(self, scope):
        path = scope["path"]
        if path != "/" and path.endswith("/"):
            scope["path"] = path.rstrip("/")
        return super().matches(scope)
```

#### Data Models

**StatItem** (Pydantic Model)
Represents individual statistics entry for language learning:
- `language`: Language ID
- `translationLanguage`: Translation language ID
- `wordId`: Word identifier
- `externalId`: External reference ID
- `interval`: Learning interval
- `repetitions`: Number of repetitions
- `lastRes`: Last result score
- `timestampAdded`: Creation timestamp
- `timestampUpdated`: Last update timestamp
- `nextStartTS`: Next review timestamp
- `type`: Statistics type

**StatData** (Pydantic Model)
Batch statistics submission:
- `table`: Target table name
- `data`: List of StatItem objects

#### Middleware

**Request Logging Middleware**
- Logs all incoming HTTP requests
- Format: `>>> {METHOD} {PATH}`
- Executes before request processing
- Non-blocking implementation

#### API Endpoints

##### 1. Health Check Endpoint
```
GET /health
```
**Purpose**: Service health monitoring

**Response**:
```json
{
  "status": "healthy"
}
```

**Use Cases**:
- Container health checks
- Load balancer monitoring
- Service availability verification

##### 2. Tor Proxy Test Endpoint
```
GET /test-tor
```
**Purpose**: Verify Tor proxy functionality

**Logic**:
1. Makes direct request to httpbin.org/ip (without proxy)
2. Makes proxied request through Tor (if enabled)
3. Compares IP addresses to verify proxy is working

**Response (Tor Enabled)**:
```json
{
  "tor_enabled": true,
  "tor_proxy": "tor-proxy:9050",
  "direct_ip": "xx.xx.xx.xx",
  "proxied_ip": "yy.yy.yy.yy",
  "tor_working": true
}
```

**Response (Tor Disabled)**:
```json
{
  "tor_enabled": false,
  "direct_ip": "xx.xx.xx.xx"
}
```

**Error Handling**:
- Returns error message if test fails
- Includes Tor enabled status in error response

##### 3. Statistics Collection Endpoint
```
POST /stats/
```
**Purpose**: Store statistics data in ClickHouse

**Request Body**:
```json
{
  "table": "statistics_table_name",
  "data": [
    {
      "language": 1,
      "translationLanguage": 2,
      "wordId": 12345,
      "externalId": 67890,
      "interval": 3,
      "repetitions": 5,
      "lastRes": 4,
      "timestampAdded": 1234567890,
      "timestampUpdated": 1234567900,
      "nextStartTS": 1234567910,
      "type": 1
    }
  ]
}
```

**Logic**:
1. Validates incoming data using Pydantic models
2. Converts Pydantic models to dictionaries
3. Extracts column names and data using `extract_columns_and_data()`
4. Inserts data into ClickHouse table
5. Returns success status

**Response**:
```json
{
  "status": "success"
}
```

**Helper Function**: `extract_columns_and_data(rows: list[dict]) -> tuple[list[str], list[list]]`
- Extracts union of all column names from rows
- Creates sorted list of column names
- Builds data matrix with consistent column ordering
- Handles missing columns by inserting `None` values

##### 4. YouTube Transcript Endpoint
```
GET /yt?videoId={video_id}&language={language_code}
```
**Purpose**: Fetch YouTube video transcript in specified language

**Query Parameters**:
- `videoId`: YouTube video identifier (11 characters)
- `language`: Language code (e.g., "en", "es", "fr")

**Logic**:
1. Logs request details (video ID and language)
2. Logs Tor proxy usage if enabled
3. Creates SOCKS5 proxy configuration
4. Calls YouTubeTranscriptApi with proxy settings
5. Returns transcript data

**Proxy Configuration**:
```python
proxies = {
    'http': f'socks5://{settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}',
    'https': f'socks5://{settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}'
}
```

**Response**:
```json
{
  "transcript": [
    {
      "text": "Hello world",
      "start": 0.0,
      "duration": 2.5
    },
    {
      "text": "This is a transcript",
      "start": 2.5,
      "duration": 3.0
    }
  ]
}
```

**Error Handling**:
- Connection errors (503): Tor-related connectivity issues
- Not found errors (404): Video or transcript not available
- Logs all errors for debugging

##### 5. Available Transcripts Endpoint
```
GET /yt-list?videoId={video_id}
```
**Purpose**: List all available transcript languages for a video

**Query Parameters**:
- `videoId`: YouTube video identifier

**Logic**:
1. Logs request with video ID
2. Logs Tor proxy usage if enabled
3. Fetches available transcripts through proxy
4. Transforms transcript objects to JSON-serializable format

**Response**:
```json
{
  "available_transcripts": [
    {
      "language": "English",
      "language_code": "en",
      "is_generated": false,
      "is_translatable": true
    },
    {
      "language": "Spanish",
      "language_code": "es",
      "is_generated": true,
      "is_translatable": false
    }
  ]
}
```

**Error Handling**:
- Connection errors (503): Proxy or network issues
- Not found errors (404): Video not found
- Detailed logging for troubleshooting

### 4. Docker Configuration

#### Development Dockerfile (`docker/python/dev/Dockerfile`)

**Build Strategy**: Single-stage build optimized for development

**Key Features**:
- Based on `python:3.11-slim`
- Installs development dependencies
- Volume mounting for live code updates
- No optimization for image size
- Includes debugging tools

**Build Steps**:
1. Set working directory to `/app`
2. Configure Python environment variables
3. Install system dependencies (gcc for compilation)
4. Install Python dependencies from requirements-dev.txt
5. Copy project files
6. Expose port 8000
7. Run uvicorn with hot-reload

**Environment Variables**:
- `PYTHONDONTWRITEBYTECODE=1`: Prevents .pyc file creation
- `PYTHONUNBUFFERED=1`: Ensures real-time logging
- `PYTHONPATH=/app`: Sets Python import path

#### Production Dockerfile (`docker/python/prod/Dockerfile`)

**Build Strategy**: Multi-stage build for optimized image size

**Stage 1: Builder**
- Compiles Python packages into wheels
- Includes build dependencies
- Creates `/app/wheels` directory with compiled packages

**Stage 2: Runtime**
- Minimal runtime image
- Installs only pre-compiled wheels
- Non-root user execution for security
- Health check configuration

**Security Features**:
- Non-root user (`app:app`)
- Minimal system dependencies
- No build tools in final image
- Proper file permissions

**Build Steps**:
1. Create non-root user and group
2. Install runtime dependencies (curl, netcat)
3. Copy and install pre-built wheels
4. Copy application code with proper ownership
5. Copy and configure startup script
6. Create directories for static/media files
7. Switch to non-root user
8. Configure health check
9. Set startup command

**Health Check**:
```dockerfile
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:80/health || exit 1
```

#### Production Startup Script (`scripts/start.sh`)

**Purpose**: Production server initialization with Gunicorn

**Features**:
- Dynamic worker calculation based on CPU cores
- Configurable resource limits
- Production-grade settings

**Worker Configuration**:
```bash
WEB_CONCURRENCY = CPU_CORES * WORKERS_PER_CORE
WEB_CONCURRENCY = min(WEB_CONCURRENCY, MAX_WORKERS)
```

**Gunicorn Parameters**:
- `--bind 0.0.0.0:80`: Listen on all interfaces, port 80
- `--workers $WEB_CONCURRENCY`: Dynamic worker count
- `--worker-class uvicorn.workers.UvicornWorker`: ASGI worker
- `--worker-connections $WORKER_CONNECTIONS`: Concurrent connections per worker
- `--timeout $TIMEOUT`: Request timeout (60s default)
- `--keep-alive $KEEP_ALIVE`: Connection keep-alive (5s default)
- `--graceful-timeout $GRACEFUL_TIMEOUT`: Graceful shutdown timeout (120s default)
- `--forwarded-allow-ips="*"`: Trust all proxies (for load balancers)

**Environment Variables**:
- `WORKERS_PER_CORE`: Workers per CPU core (default: 1)
- `MAX_WORKERS`: Maximum worker limit (default: 16)
- `WORKER_CONNECTIONS`: Connections per worker (default: 1000)
- `TIMEOUT`: Request timeout in seconds (default: 60)
- `KEEP_ALIVE`: Keep-alive timeout (default: 5)
- `GRACEFUL_TIMEOUT`: Graceful shutdown timeout (default: 120)

### 5. Docker Compose Configuration

#### Base Configuration (`docker-compose.yaml`)

**Services**:

1. **Tor Service**
   - Image: `dperson/torproxy`
   - Container name: `tor-proxy`
   - Exposes SOCKS5 proxy on port 9050
   - Always restart policy
   - Connected to `devnetwork`

2. **Server Service**
   - Image: `vovanvh/voca:stats-dev`
   - Container name: `krys-stats`
   - Command: `uvicorn main:app --host 0.0.0.0 --port 8000 --reload`
   - Volume mounts current directory to `/app`
   - Depends on Tor service
   - Environment variables from `.env` file
   - Exposes port 8000

**Network**:
- External network: `devnetwork`
- Shared between services
- Enables service discovery by container name

#### Production Configuration (`docker-compose.prod.yaml`)

**Differences from Development**:

1. **Server Configuration**
   - Image: `vovanvh/voca:stats-prod`
   - Container name: `krys-stats-prod`
   - Command: `/start.sh` (Gunicorn with multiple workers)
   - No volume mounts (code in image)
   - Environment from `.env.prod`

2. **Resource Limits**
   - CPU: 0.5 cores
   - Memory: 512MB
   - Prevents resource exhaustion

3. **Health Check**
   - Test: `curl -f http://localhost:80/health`
   - Interval: 30 seconds
   - Timeout: 10 seconds
   - Retries: 3
   - Start period: 40 seconds

4. **No Port Exposure**
   - Ports not published to host
   - Service accessed through reverse proxy/load balancer

#### Development Configuration (`docker-compose.dev.yaml`)

**Features**:
- Same as base configuration
- Uses development Dockerfile
- Volume mounting for live reload
- Port 8000 exposed
- Reload on file changes

## Data Flow Diagrams

### Statistics Collection Flow

```
Client Request
    ↓
POST /stats/
    ↓
Validate with StatData model
    ↓
Extract columns and data
    ↓
Get ClickHouse client
    ↓
Insert into table
    ↓
Return success response
```

### YouTube Transcript Flow

```
Client Request
    ↓
GET /yt?videoId=xxx&language=en
    ↓
Check Tor proxy settings
    ↓
Create proxy configuration
    ↓
YouTubeTranscriptApi.get_transcript()
    ↓         ↓
    ↓     Tor Proxy (optional)
    ↓         ↓
    ↓     YouTube API
    ↓         ↓
Parse transcript
    ↓
Return JSON response
```

## Environment Configuration

### Development Environment (`.env.example`)

**Application Settings**:
- Debug mode enabled
- Development environment
- Port 8000

**Database**:
- ClickHouse host: `v_clickhouse`
- Non-secure connection
- Default database

**Security**:
- Development JWT secret
- Permissive CORS (localhost)

### Production Environment (`.env.prod.example`)

**Key Differences**:
- Debug mode disabled
- Port 80
- Shorter token expiration (15 min vs 30 min)
- Restricted CORS origins
- Production log level (WARNING vs INFO)
- Gunicorn worker configuration
- Resource limits

## Security Considerations

### Implemented Security Measures

1. **Non-root Container Execution**
   - Production containers run as `app` user
   - Limits privilege escalation risks

2. **Environment Variable Management**
   - Sensitive data in environment files
   - Example files without secrets
   - `.gitignore` includes environment files

3. **Resource Limits**
   - CPU and memory constraints in production
   - Prevents DoS through resource exhaustion

4. **Health Checks**
   - Automated container health monitoring
   - Automatic restart on failure

5. **Request Validation**
   - Pydantic models for input validation
   - Type checking at runtime
   - Automatic error responses for invalid data

6. **Proxy Isolation**
   - Tor proxy in separate container
   - Network isolation through Docker networks

### Security Recommendations

1. **Database Security**
   - Change default ClickHouse credentials
   - Enable secure connections in production
   - Use database user with minimal privileges

2. **API Security**
   - Implement authentication for /stats/ endpoint
   - Add rate limiting
   - Enable CORS restrictions
   - Use JWT tokens (infrastructure present)

3. **Container Security**
   - Regular base image updates
   - Vulnerability scanning
   - Secrets management (Docker secrets, Vault)

4. **Network Security**
   - Use reverse proxy (nginx, traefik)
   - Enable HTTPS/TLS
   - Firewall rules
   - Private Docker network in production

## Tor Proxy Integration

### Purpose
- Anonymize YouTube API requests
- Avoid rate limiting
- Bypass geographic restrictions
- Distribute requests across exit nodes

### Configuration

**Proxy Type**: SOCKS5
**Host**: `tor-proxy` (container name)
**Port**: 9050

### Usage Pattern

All YouTube API calls include proxy configuration:
```python
proxies = {
    'http': f'socks5://{settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}',
    'https': f'socks5://{settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}'
}
```

### Toggle Mechanism
- Controlled by `USE_TOR_PROXY` environment variable
- Can be disabled without code changes
- Fallback to direct connection

### Monitoring
- `/test-tor` endpoint verifies proxy functionality
- Logs proxy usage for each request
- Differentiates connection vs. content errors

## Deployment Procedures

### Development Deployment

```bash
# 1. Create external network (first time only)
docker network create devnetwork

# 2. Copy and configure environment
cp .env.example .env
# Edit .env with your settings

# 3. Start services
docker-compose -f docker-compose.dev.yaml up -d

# 4. View logs
docker-compose logs -f server

# 5. Access API
curl http://localhost:8000/health
```

### Production Deployment

```bash
# 1. Create external network (first time only)
docker network create devnetwork

# 2. Configure production environment
cp .env.prod.example .env.prod
# Edit .env.prod with production settings

# 3. Build production image
docker-compose -f docker-compose.prod.yaml build

# 4. Start services
docker-compose -f docker-compose.prod.yaml up -d

# 5. Verify health
docker-compose ps
docker-compose logs server

# 6. Access API (internal port 80)
docker exec krys-stats-prod curl http://localhost:80/health
```

### Updates and Maintenance

```bash
# Pull latest code
git pull

# Rebuild containers
docker-compose -f docker-compose.prod.yaml build --no-cache

# Restart services (zero-downtime with multiple workers)
docker-compose -f docker-compose.prod.yaml up -d

# Check logs
docker-compose logs --tail=100 -f
```

## Monitoring and Logging

### Log Sources

1. **Application Logs**
   - Request logging middleware
   - API endpoint logs
   - Tor proxy usage logs
   - Error logs

2. **Gunicorn Logs**
   - Access logs (stdout)
   - Error logs (stderr)
   - Worker management logs

3. **Container Logs**
   - Docker container stdout/stderr
   - Health check results

### Log Format

**Request Logs**:
```
>>> GET /health
>>> POST /stats/
[YT] Getting transcript for video abc123 in language en
[YT] Using Tor proxy: tor-proxy:9050
```

**Error Logs**:
```
[YT] Connection error (possibly Tor-related): Connection timeout
[YT] Error: Video not found
```

### Monitoring Endpoints

1. **Health Check**: `GET /health`
   - Container health monitoring
   - Load balancer checks

2. **Tor Test**: `GET /test-tor`
   - Proxy functionality verification
   - IP comparison

## Performance Considerations

### Production Optimizations

1. **Multi-worker Configuration**
   - Dynamic worker count based on CPU cores
   - Uvicorn workers for async support
   - Configurable worker connections

2. **Resource Management**
   - CPU and memory limits
   - Connection pooling in ClickHouse client
   - Keep-alive connections

3. **Docker Optimizations**
   - Multi-stage builds (smaller images)
   - Wheel-based installation (faster startup)
   - Minimal base image

### Scalability Options

1. **Horizontal Scaling**
   - Multiple container instances
   - Load balancer distribution
   - Shared ClickHouse database

2. **Vertical Scaling**
   - Increase CPU/memory limits
   - More workers per container
   - Higher connection limits

3. **Database Scaling**
   - ClickHouse cluster
   - Separate read/write nodes
   - Sharding strategies

## API Usage Examples

### Health Check
```bash
curl http://localhost:8000/health
```

### Test Tor Connection
```bash
curl http://localhost:8000/test-tor
```

### Submit Statistics
```bash
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

### Get YouTube Transcript
```bash
curl "http://localhost:8000/yt?videoId=dQw4w9WgXcQ&language=en"
```

### List Available Transcripts
```bash
curl "http://localhost:8000/yt-list?videoId=dQw4w9WgXcQ"
```

## Troubleshooting Guide

### Common Issues

1. **Connection Refused to ClickHouse**
   - Verify ClickHouse is running
   - Check CLICKHOUSE_HOST configuration
   - Ensure network connectivity

2. **Tor Proxy Errors**
   - Check Tor container is running: `docker ps | grep tor`
   - Verify proxy settings in environment
   - Test connectivity: `curl http://localhost:8000/test-tor`
   - Check Tor logs: `docker logs tor-proxy`

3. **YouTube API Failures**
   - Verify video ID is correct
   - Check language code is valid
   - Review Tor proxy status
   - Check rate limiting

4. **Container Won't Start**
   - Check logs: `docker logs krys-stats`
   - Verify environment variables
   - Ensure network exists
   - Check port conflicts

5. **Health Check Failures**
   - Check application logs
   - Verify port 80 is accessible (production)
   - Test endpoint manually
   - Review resource limits

## Future Enhancements

### Recommended Features

1. **Authentication & Authorization**
   - JWT token implementation
   - User management
   - Role-based access control

2. **API Improvements**
   - Rate limiting
   - Request throttling
   - API versioning
   - OpenAPI documentation

3. **Monitoring & Observability**
   - Prometheus metrics
   - Grafana dashboards
   - Distributed tracing
   - Alert management

4. **Database Enhancements**
   - Connection pooling
   - Query optimization
   - Batch operations
   - Data retention policies

5. **Cache Layer**
   - Redis integration
   - Transcript caching
   - Response caching
   - Session management

6. **Error Handling**
   - Retry mechanisms
   - Circuit breakers
   - Fallback strategies
   - Better error messages

## Dependencies

### Production Requirements (`requirements.txt`)

```
annotated-types==0.7.0      # Type annotation support
anyio==4.9.0                # Async I/O library
click==8.2.0                # CLI utilities
fastapi==0.115.12           # Web framework
h11==0.16.0                 # HTTP/1.1 protocol
idna==3.10                  # Internationalized domain names
pydantic==2.11.4            # Data validation
pydantic_core==2.33.2       # Pydantic core
sniffio==1.3.1              # Async library detection
starlette==0.46.2           # ASGI framework (FastAPI dependency)
typing_extensions==4.13.2   # Type hints backport
uvicorn==0.34.2             # ASGI server
clickhouse-connect==0.8.17  # ClickHouse client
pydantic-settings==2.9.1    # Settings management
gunicorn==23.0.0            # Production WSGI server
numpy==2.2.6                # Numerical computing
youtube-transcript-api==1.1.0  # YouTube transcripts
requests[socks]==2.32.3     # HTTP library with SOCKS support
pysocks==1.7.1              # SOCKS proxy support
```

## Git Repository

### Recent Commits
- Add pysocks dependency for enhanced proxy support
- Refactor YouTube API proxy configuration
- Update Tor proxy to use 'tor-proxy' hostname
- Add Tor proxying functionality

### Branch Structure
- `main`: Primary development and production branch

## Conclusion

This project provides a robust, scalable, and production-ready API service for statistics collection and YouTube transcript retrieval. The architecture emphasizes:

- **Modularity**: Clear separation of concerns
- **Scalability**: Horizontal and vertical scaling support
- **Security**: Non-root execution, resource limits, input validation
- **Observability**: Comprehensive logging and health checks
- **Flexibility**: Environment-based configuration
- **Performance**: Multi-worker production setup
- **Privacy**: Optional Tor proxy integration

The Docker-based deployment ensures consistency across environments and simplifies operations, while the FastAPI framework provides modern async capabilities and automatic API documentation.
