from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.storage.db import init_db

PACKAGE_DIR = Path(__file__).resolve().parent
# Wheels keep assets inside the package; the source checkout keeps them beside app/.
STATIC_DIR = PACKAGE_DIR / "static"
if not STATIC_DIR.is_dir():
    STATIC_DIR = PACKAGE_DIR.parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="shopping-agent", version="0.0.1", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# API 路由先注册，静态页挂根路径兜底
app.include_router(router)
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
