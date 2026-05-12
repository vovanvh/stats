#!/bin/sh
set -e

docker pull 100.110.75.66:54321/krys-stats:latest
docker stop krys-stats-prod || true
docker rm krys-stats-prod || true
docker run -d \
  --name krys-stats-prod \
  --restart unless-stopped \
  --network devnetwork \
  --env-file ~/stats/.env.prod \
  -e TOR_PROXY_HOST=tor-proxy \
  -e TOR_PROXY_PORT=9050 \
  -e TIMEOUT=180 \
  100.110.75.66:54321/krys-stats:latest
