# Proxy Usage Guide

This API supports two proxy tiers for all scraping operations:

| Tier | Provider | Cost | Best For |
|------|----------|------|----------|
| Free | Tor | $0 | Low-volume, non-critical requests |
| Paid | Residential (configurable) | $1-15/GB | High success rate, YouTube, anti-bot sites |

## Quick Start

All endpoints accept an `isFree` query parameter:

```
isFree=false  (default) - Use paid residential proxy
isFree=true             - Use free Tor proxy
```

---

## YouTube Transcript API

### Get Transcript

```bash
# Using paid proxy (recommended for YouTube)
GET /yt?videoId=dQw4w9WgXcQ&language=en

# Using free Tor proxy
GET /yt?videoId=dQw4w9WgXcQ&language=en&isFree=true
```

### List Available Transcripts

```bash
# Using paid proxy
GET /yt-list?videoId=dQw4w9WgXcQ

# Using free Tor proxy
GET /yt-list?videoId=dQw4w9WgXcQ&isFree=true
```

### Handling IP Blocks (429 errors)

YouTube aggressively blocks IPs. When you receive a 429 error, rotate the IP:

```bash
# If using paid proxy (isFree=false)
POST /proxy/new-identity

# If using Tor (isFree=true)
POST /proxy/new-identity?isFree=true
```

Then retry the request.

---

## Web Scraper API

### Scrape a Website

```bash
# Using paid proxy (default)
GET /scrape?url=https://example.com

# Using free Tor proxy
GET /scrape?url=https://example.com&isFree=true

# Full example with all options
GET /scrape?url=https://example.com&waitForSelector=.content&timeout=60000&screenshot=true&isFree=false
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | string | required | Target URL to scrape |
| `waitForSelector` | string | null | CSS selector to wait for before scraping |
| `timeout` | int | 30000 | Max wait time in milliseconds |
| `screenshot` | bool | false | Return base64 PNG screenshot |
| `isFree` | bool | false | Use Tor instead of paid proxy |

---

## Proxy Management API

### Test Proxy Connection

Verify the proxy is working and see current IP:

```bash
# Test paid proxy
GET /proxy/test

# Test Tor
GET /proxy/test?isFree=true
```

Response:
```json
{
  "provider": "floppydata",
  "session_id": "a1b2c3d4e5f6g7h8",
  "direct_ip": "203.0.113.1",
  "proxied_ip": "198.51.100.42",
  "proxy_working": true
}
```

### Rotate IP (New Identity)

Get a new IP address when the current one is blocked:

```bash
# Rotate paid proxy session (instant)
POST /proxy/new-identity

# Rotate Tor circuit (~10 sec cooldown)
POST /proxy/new-identity?isFree=true
```

Response (paid proxy):
```json
{
  "status": "success",
  "provider": "floppydata",
  "old_session_id": "a1b2c3d4e5f6g7h8",
  "new_session_id": "x9y8z7w6v5u4t3s2",
  "new_ip": "203.0.113.99",
  "message": "Session rotated for floppydata. New requests will use a different IP."
}
```

Response (Tor):
```json
{
  "status": "success",
  "provider": "tor",
  "new_ip": "185.220.101.42",
  "message": "New Tor identity requested. New circuit established.",
  "note": "Tor rate-limits this request to approximately once per 10 seconds."
}
```

---

## Client Implementation Examples

### Python

```python
import requests

BASE_URL = "http://localhost:8000"

def get_youtube_transcript(video_id: str, language: str = "en", use_free: bool = False):
    """Fetch a YouTube transcript with automatic IP rotation on the block."""
    params = {
        "videoId": video_id,
        "language": language,
        "isFree": str(use_free).lower()
    }

    response = requests.get(f"{BASE_URL}/yt", params=params)

    if response.status_code == 429:
        # IP blocked - rotate and retry
        requests.post(f"{BASE_URL}/proxy/new-identity", params={"isFree": use_free})
        response = requests.get(f"{BASE_URL}/yt", params=params)

    return response.json()


def scrape_website(url: str, use_free: bool = False):
    """Scrape website with proxy."""
    params = {
        "url": url,
        "isFree": str(use_free).lower()
    }
    return requests.get(f"{BASE_URL}/scrape", params=params).json()
```

### JavaScript/TypeScript

```typescript
const BASE_URL = "http://localhost:8000";

async function getYouTubeTranscript(
  videoId: string,
  language: string = "en",
  isFree: boolean = false
): Promise<any> {
  const params = new URLSearchParams({
    videoId,
    language,
    isFree: String(isFree),
  });

  let response = await fetch(`${BASE_URL}/yt?${params}`);

  if (response.status === 429) {
    // IP blocked - rotate and retry
    await fetch(`${BASE_URL}/proxy/new-identity?isFree=${isFree}`, {
      method: "POST",
    });
    response = await fetch(`${BASE_URL}/yt?${params}`);
  }

  return response.json();
}

async function scrapeWebsite(url: string, isFree: boolean = false): Promise<any> {
  const params = new URLSearchParams({ url, isFree: String(isFree) });
  const response = await fetch(`${BASE_URL}/scrape?${params}`);
  return response.json();
}
```

### cURL

```bash
# YouTube transcript with paid proxy
curl "http://localhost:8000/yt?videoId=dQw4w9WgXcQ&language=en"

# Scrape with Tor
curl "http://localhost:8000/scrape?url=https://example.com&isFree=true"

# Rotate paid proxy IP
curl -X POST "http://localhost:8000/proxy/new-identity"

# Rotate Tor IP
curl -X POST "http://localhost:8000/proxy/new-identity?isFree=true"
```

---

## Recommendations

| Use Case | Recommended Setting |
|----------|---------------------|
| YouTube scraping | `isFree=false` (paid proxy) |
| High-volume scraping | `isFree=false` (paid proxy) |
| Testing/development | `isFree=true` (Tor) |
| Onion sites (.onion) | `isFree=true` (Tor) |
| Cost-sensitive, low-volume | `isFree=true` (Tor) |

### Error Handling Best Practices

1. **Always handle 429 errors** - Rotate IP and retry
2. **Implement exponential backoff** - Wait 1s, 2s, 4s between retries
3. **Set reasonable timeouts** - YouTube pages can be slow (use 60000ms+)
4. **Monitor proxy health** - Periodically call `/proxy/test` to verify connectivity
