import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.config import load_config
from app.credential_store import CredentialStore
from app.routers.vms import init_router, router as vms_router
from app.vsphere_client import VSphereClient

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

_client: Optional[VSphereClient] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client
    store = CredentialStore()
    config = load_config(store=store)

    _client = VSphereClient(config)
    try:
        _client.connect()
        logger.info("Connected to vCenter at startup")
    except Exception as e:
        logger.warning("Starting without active vCenter connection: %s", e)
    init_router(_client, store)
    logger.info("Dashboard-X ready")
    yield
    if _client:
        _client.disconnect()


app = FastAPI(
    title="Ctera-Dashboard-X",
    description="Local dashboard for managing vSphere environments",
    lifespan=lifespan,
)


class NoCacheAPIMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response


app.add_middleware(NoCacheAPIMiddleware)
app.include_router(vms_router)
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
