from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes.auth import router as auth_router
from app.api.routes.cache import router as cache_router
from app.api.routes.servers import router as servers_router
from app.api.routes.workspace import router as workspace_router
from app.services.platform import ApplicationContainer
from app.settings.config import get_settings
from app.settings.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings)
    app.state.container = ApplicationContainer(settings)
    await app.state.container.start()
    yield
    await app.state.container.close()


settings = get_settings()
app = FastAPI(title=settings.app_name, lifespan=lifespan, root_path=settings.root_path)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz", tags=["system"])
def healthz():
    return {"ok": True}


api_prefix = settings.api_prefix
app.include_router(auth_router, prefix=api_prefix)
app.include_router(cache_router, prefix=api_prefix)
app.include_router(servers_router, prefix=api_prefix)
app.include_router(workspace_router, prefix=api_prefix)

frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.exists():
    spa_index = frontend_dist / "index.html"

    @app.get("/workspace")
    @app.get("/workspace/{full_path:path}")
    def workspace_spa_fallback(full_path: str = ""):
        return FileResponse(spa_index)

    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
