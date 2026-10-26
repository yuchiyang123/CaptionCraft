from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine, add_missing_columns
from . import models  # noqa: F401
from . import remote_upscale
from .routers import videos, subtitles

Base.metadata.create_all(bind=engine)
add_missing_columns()

app = FastAPI(title="AI 字幕生成器 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(videos.router)
app.include_router(subtitles.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/upscaler/status")
def upscaler_status():
    info = remote_upscale.status()
    return {"available": bool(info), "device": (info or {}).get("device"), "cuda": (info or {}).get("cuda", False)}
