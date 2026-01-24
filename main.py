from fastapi import FastAPI, Request
from fastapi.routing import APIRoute

from app.routers import stats, youtube, scrape, tor


class SlashInsensitiveAPIRoute(APIRoute):
    def matches(self, scope):
        path = scope["path"]
        print(f"[MATCHES] incoming path: {path}")
        if path != "/" and path.endswith("/"):
            scope["path"] = path.rstrip("/")
            print(f"[MATCHES] normalized path: {scope['path']}")
        return super().matches(scope)


app = FastAPI(route_class=SlashInsensitiveAPIRoute)

# Include routers
app.include_router(stats.router)
app.include_router(youtube.router)
app.include_router(scrape.router)
app.include_router(tor.router)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f">>> {request.method} {request.url.path}")
    return await call_next(request)


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
