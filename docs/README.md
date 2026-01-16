# Documentation Index

This directory contains comprehensive documentation for the my-stats project.

## 📚 Available Documentation

### 1. [General Description](general-description.md)
**Complete project overview and architecture documentation**

Topics covered:
- Project purpose and technology stack
- Architecture and component descriptions
- All API endpoints with examples
- Docker configuration (development and production)
- Database integration (ClickHouse)
- Tor proxy integration overview
- Deployment procedures
- Security considerations
- Performance optimization
- Troubleshooting guide

**Start here** if you're new to the project or need a comprehensive overview.

### 2. [Tor Proxy Technical Documentation](tor-proxy.md)
**Deep dive into Tor proxy implementation and usage**

Topics covered:
- How Tor works (circuits, relays, exit nodes)
- IP rotation mechanics (automatic and manual)
- Control port API and commands
- Country-specific exit node configuration
- SOCKS5 protocol implementation details
- Multiple Tor instance setup
- Current project implementation (January 2026)
- Troubleshooting Tor-specific issues
- Performance and security considerations
- Client integration examples

**Read this** if you're working with Tor features, implementing retry logic, or troubleshooting proxy issues.

### 3. [Deployment Environments](deployment-environments.md)
**Environment-specific configuration and deployment procedures**

Topics covered:
- Development environment setup
- Production environment configuration
- Environment variables
- Docker Compose configurations
- Deployment best practices

**Read this** when setting up new environments or deploying to production.

## 🆕 Recent Changes (January 2026)

### Major Update: Tor Proxy Upgrade

The project recently underwent a major upgrade to fix critical Tor proxy issues:

**Problems Fixed**:
1. ✅ SOCKS protocol errors ("Socks version 71 not recognized")
2. ✅ Outdated Tor version (missing FlowCtrl=2 Relay=3-4 protocols)
3. ✅ High YouTube blocking rate (improved from ~60% to ~95% success)

**New Features**:
- Country-specific exit node selection
- Manual IP rotation via API (`POST /tor/new-identity`)
- Tor control port integration (9051)
- Advanced circuit configuration

**Files Changed**:
- New: `torrc` (Tor configuration)
- Updated: `docker-compose.dev.yaml`, `docker-compose.prod.yaml`
- Updated: `main.py` (SOCKS5 fix, new endpoint)
- Updated: All documentation

**See**: [CHANGELOG.md](../CHANGELOG.md) for complete details

## 🚀 Quick Start Guide

### For New Developers

1. **Understand the project**:
   ```bash
   # Read the general overview
   cat docs/general-description.md
   ```

2. **Set up development environment**:
   ```bash
   # Create Docker network
   docker network create devnetwork

   # Copy environment file
   cp .env.example .env

   # Start services
   docker-compose -f docker-compose.dev.yaml up -d
   ```

3. **Test the setup**:
   ```bash
   # Health check
   curl http://localhost:8000/health

   # Test Tor proxy
   curl http://localhost:8000/test-tor

   # Test YouTube API
   curl "http://localhost:8000/yt-list?videoId=dQw4w9WgXcQ"
   ```

4. **Read Tor documentation** (if working with YouTube features):
   ```bash
   cat docs/tor-proxy.md
   ```

### For Existing Developers (Upgrading)

1. **Read the changelog**:
   ```bash
   cat CHANGELOG.md
   ```

2. **Pull latest code**:
   ```bash
   git pull origin main
   ```

3. **Restart containers**:
   ```bash
   docker-compose -f docker-compose.dev.yaml down
   docker-compose -f docker-compose.dev.yaml up -d
   ```

4. **Verify Tor upgrade**:
   ```bash
   # Check for no errors in logs
   docker logs tor-proxy --tail=50

   # Test new endpoint
   curl -X POST http://localhost:8000/tor/new-identity
   ```

## 📖 Documentation Structure

```
my-stats/
├── docs/
│   ├── README.md                    # This file
│   ├── general-description.md       # Complete project documentation
│   ├── tor-proxy.md                 # Tor proxy technical guide
│   └── deployment-environments.md   # Environment configurations
├── CHANGELOG.md                     # Version history and changes
├── README.md                        # Project README (if exists)
├── torrc                            # Tor configuration file
├── docker-compose.dev.yaml          # Development Docker config
├── docker-compose.prod.yaml         # Production Docker config
├── main.py                          # FastAPI application
├── requirements.txt                 # Python dependencies
└── app/                             # Application code
    ├── config.py                    # Configuration management
    └── database.py                  # ClickHouse client
```

## 🔍 Finding Information

### By Topic

| Topic | Document | Section |
|-------|----------|---------|
| Project overview | general-description.md | Overview |
| API endpoints | general-description.md | API Endpoints |
| Tor proxy setup | tor-proxy.md | Current Implementation |
| IP rotation | tor-proxy.md | IP Rotation Features |
| SOCKS5 errors | tor-proxy.md | Problems Solved |
| Docker setup | general-description.md | Docker Configuration |
| Deployment | deployment-environments.md | All sections |
| Troubleshooting | general-description.md + tor-proxy.md | Troubleshooting |
| Security | general-description.md | Security Considerations |
| Performance | general-description.md | Performance Considerations |

### By Use Case

**"I want to understand how the project works"**
→ Start with [general-description.md](general-description.md)

**"YouTube requests are failing with 404 errors"**
→ See [tor-proxy.md](tor-proxy.md) - "Problems Solved" section
→ Implement retry logic from "Client Integration" section

**"I'm getting SOCKS protocol errors"**
→ See [tor-proxy.md](tor-proxy.md) - "Problems Solved: SOCKS Protocol Mismatch"
→ Ensure you're running the latest code (January 2026+)

**"I need to deploy to production"**
→ See [deployment-environments.md](deployment-environments.md)
→ Follow security checklist in [tor-proxy.md](tor-proxy.md) - "Security Considerations"

**"I want to add retry logic to my client"**
→ See [tor-proxy.md](tor-proxy.md) - "Client Integration (NestJS)" section
→ Use `/tor/new-identity` endpoint before retrying

**"I need to configure Tor for different countries"**
→ Edit `torrc` file - `ExitNodes` parameter
→ See [tor-proxy.md](tor-proxy.md) - "Country-Specific Exit Nodes"

**"I want to understand the recent changes"**
→ Read [CHANGELOG.md](../CHANGELOG.md)
→ See [tor-proxy.md](tor-proxy.md) - "Current Implementation" section

## 🆘 Getting Help

### Troubleshooting Steps

1. **Check the logs**:
   ```bash
   docker logs krys-stats --tail=100
   docker logs tor-proxy --tail=100
   ```

2. **Search the documentation**:
   ```bash
   # Search all docs for a term
   grep -r "your search term" docs/
   ```

3. **Review troubleshooting guides**:
   - General issues: [general-description.md](general-description.md) - "Troubleshooting Guide"
   - Tor issues: [tor-proxy.md](tor-proxy.md) - "Troubleshooting" section

4. **Check the changelog**:
   - See if your issue was recently fixed: [CHANGELOG.md](../CHANGELOG.md)

### Common Issues and Solutions

| Issue | Solution |
|-------|----------|
| "Socks version 71 not recognized" | Upgrade to latest code (fixed in 2.0.0) |
| "Protocol not supported" warnings | Upgrade Tor image (fixed in 2.0.0) |
| YouTube 404 errors | Use retry logic with `/tor/new-identity` |
| Control port connection refused | Check `torrc` mounted and port 9051 exposed |
| Container won't start | Check Docker logs, verify network exists |

## 📝 Contributing to Documentation

When updating documentation:

1. **Keep it current**: Update all relevant docs when making changes
2. **Be specific**: Include file names, line numbers, and examples
3. **Test examples**: Ensure all code examples work
4. **Update changelog**: Add entry to CHANGELOG.md for significant changes
5. **Cross-reference**: Link related sections across documents

### Documentation Style Guide

- Use code blocks for commands and code
- Include expected output for examples
- Use emojis sparingly for section markers
- Keep line length reasonable (100-120 chars)
- Use markdown tables for comparisons
- Include "Why" explanations, not just "How"

## 🔗 External Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Tor Project](https://www.torproject.org/)
- [Docker Documentation](https://docs.docker.com/)
- [ClickHouse Documentation](https://clickhouse.com/docs/)
- [YouTube Transcript API](https://github.com/jdepoix/youtube-transcript-api)

## 📅 Last Updated

**Date**: January 16, 2026
**Version**: 2.0.0
**Major Changes**: Tor proxy upgrade, SOCKS5 fix, control port implementation

---

**Questions?** Check the troubleshooting sections in the documentation or review recent changes in [CHANGELOG.md](../CHANGELOG.md).
