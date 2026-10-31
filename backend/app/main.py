from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.collection import CollectionBusy, close_collection_pool
from app.storage.db import init_db

PACKAGE_DIR = Path(__file__).resolve().parent
# Wheels keep assets inside the package; the source checkout keeps them beside app/.
STATIC_DIR = PACKAGE_DIR / "static"
if not STATIC_DIR.is_dir():
    STATIC_DIR = PACKAGE_DIR.parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    try:
        yield
    finally:
        close_collection_pool()


app = FastAPI(title="shopping-agent", version="0.0.1", lifespan=lifespan)


@app.exception_handler(CollectionBusy)
async def collection_busy(request, exc):
    return JSONResponse(status_code=429, content={"detail": str(exc)}, headers={"Retry-After": "2"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# API 路由先注册，静态页挂根路径兜底
app.include_router(router)
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
