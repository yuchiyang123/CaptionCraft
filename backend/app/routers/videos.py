import os
import re
import shutil
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from sqlalchemy.orm import Session

from .. import models, schemas
from ..config import MEDIA_DIR
from ..database import get_db
from ..media import get_media_duration, generate_thumbnail, thumbnail_path
from ..render import invalidate_render, rendered_path, start_render_background
from ..transcribe import start_transcription_background

router = APIRouter(prefix="/api/videos", tags=["videos"])

ALLOWED_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


@router.get("", response_model=list[schemas.VideoOut])
def list_videos(db: Session = Depends(get_db)):
    return db.query(models.Video).order_by(models.Video.created_at.desc()).all()


@router.post("/upload", response_model=schemas.VideoOut)
async def upload_video(file: UploadFile = File(...), db: Session = Depends(get_db)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"不支援的檔案格式: {ext}")

    stored_name = f"{uuid.uuid4().hex}{ext}"
    dest_path = os.path.join(MEDIA_DIR, stored_name)

    with open(dest_path, "wb") as out:
        shutil.copyfileobj(file.file, out)

    duration = get_media_duration(dest_path)
    has_thumb = generate_thumbnail(dest_path, stored_name)

    video = models.Video(
        filename=stored_name,
        original_name=file.filename or stored_name,
        duration=duration,
        status="uploaded",
        has_thumbnail=1 if has_thumb else 0,
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    return video


@router.post("/{video_id}/transcribe", response_model=schemas.VideoOut)
def transcribe_video(video_id: str, db: Session = Depends(get_db)):
    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    if not video:
        raise HTTPException(404, "找不到影片")
    if video.status == "transcribing":
        raise HTTPException(409, "字幕正在產生中")

    db.query(models.Subtitle).filter(models.Subtitle.video_id == video_id).delete()
    video.status = "transcribing"
    video.error_message = None
    invalidate_render(video)
    db.commit()

    media_path = os.path.join(MEDIA_DIR, video.filename)
    start_transcription_background(video_id, media_path)

    db.refresh(video)
    return video


@router.get("/{video_id}", response_model=schemas.VideoDetailOut)
def get_video(video_id: str, db: Session = Depends(get_db)):
    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    if not video:
        raise HTTPException(404, "找不到影片")
    return video


@router.delete("/{video_id}")
def delete_video(video_id: str, db: Session = Depends(get_db)):
    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    if not video:
        raise HTTPException(404, "找不到影片")
    media_path = os.path.join(MEDIA_DIR, video.filename)
    if os.path.exists(media_path):
        os.remove(media_path)
    thumb_path = thumbnail_path(video.filename)
    if os.path.exists(thumb_path):
        os.remove(thumb_path)
    render_out_path = rendered_path(video.filename)
    if os.path.exists(render_out_path):
        os.remove(render_out_path)
    db.delete(video)
    db.commit()
    return {"ok": True}


@router.get("/{video_id}/thumbnail")
def get_thumbnail(video_id: str, db: Session = Depends(get_db)):
    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    if not video:
        raise HTTPException(404, "找不到影片")
    thumb_path = thumbnail_path(video.filename)
    if not video.has_thumbnail or not os.path.exists(thumb_path):
        raise HTTPException(404, "尚無縮圖")
    return FileResponse(thumb_path, media_type="image/jpeg")


@router.get("/{video_id}/stream")
def stream_video(video_id: str, request: Request, db: Session = Depends(get_db)):
    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    if not video:
        raise HTTPException(404, "找不到影片")
    media_path = os.path.join(MEDIA_DIR, video.filename)
    if not os.path.exists(media_path):
        raise HTTPException(404, "找不到檔案")
    return _ranged_file_response(media_path, request, _content_type_for(video.filename))


CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".avi": "video/x-msvideo",
}


def _content_type_for(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    return CONTENT_TYPES.get(ext, "application/octet-stream")


def _content_disposition(filename: str) -> str:
    ascii_fallback = filename.encode("ascii", "ignore").decode("ascii").strip() or "download"
    return f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{quote(filename)}'


def _ranged_file_response(
    path: str, request: Request, content_type: str, chunk_size: int = 1024 * 1024, download_filename: str | None = None
):
    file_size = os.path.getsize(path)
    range_header = request.headers.get("range")
    extra_headers = {"Content-Disposition": _content_disposition(download_filename)} if download_filename else {}

    if range_header:
        match = re.match(r"bytes=(\d*)-(\d*)", range_header)
        start_str, end_str = match.groups() if match else ("", "")
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else file_size - 1
        end = min(end, file_size - 1)

        if start > end or start >= file_size:
            return StreamingResponse(
                iter(()),
                status_code=416,
                headers={"Content-Range": f"bytes */{file_size}"},
            )

        def iter_range():
            with open(path, "rb") as f:
                f.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    data = f.read(min(chunk_size, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(end - start + 1),
            **extra_headers,
        }
        return StreamingResponse(iter_range(), status_code=206, media_type=content_type, headers=headers)

    def iter_all():
        with open(path, "rb") as f:
            while True:
                data = f.read(chunk_size)
                if not data:
                    break
                yield data

    headers = {"Accept-Ranges": "bytes", "Content-Length": str(file_size), **extra_headers}
    return StreamingResponse(iter_all(), status_code=200, media_type=content_type, headers=headers)


def _format_srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _format_vtt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


@router.get("/{video_id}/export")
def export_subtitles(video_id: str, fmt: str = "srt", db: Session = Depends(get_db)):
    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    if not video:
        raise HTTPException(404, "找不到影片")

    subs = sorted(video.subtitles, key=lambda s: s.start)

    if fmt == "vtt":
        lines = ["WEBVTT", ""]
        for i, sub in enumerate(subs, start=1):
            lines.append(str(i))
            lines.append(f"{_format_vtt_time(sub.start)} --> {_format_vtt_time(sub.end)}")
            lines.append(sub.text)
            lines.append("")
        content = "\n".join(lines)
        media_type = "text/vtt"
    else:
        lines = []
        for i, sub in enumerate(subs, start=1):
            lines.append(str(i))
            lines.append(f"{_format_srt_time(sub.start)} --> {_format_srt_time(sub.end)}")
            lines.append(sub.text)
            lines.append("")
        content = "\n".join(lines)
        media_type = "text/plain"

    base_name = os.path.splitext(video.original_name)[0]
    ext = "vtt" if fmt == "vtt" else "srt"
    headers = {"Content-Disposition": _content_disposition(f"{base_name}.{ext}")}
    return PlainTextResponse(content, media_type=media_type, headers=headers)


@router.patch("/{video_id}/style", response_model=schemas.VideoOut)
def update_style(video_id: str, payload: schemas.StyleUpdate, db: Session = Depends(get_db)):
    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    if not video:
        raise HTTPException(404, "找不到影片")

    if payload.font_size is not None:
        video.style_font_size = max(12, min(96, payload.font_size))
    if payload.position is not None and payload.position in ("top", "middle", "bottom"):
        video.style_position = payload.position
    if payload.color is not None:
        video.style_color = payload.color
    if payload.bg_opacity is not None:
        video.style_bg_opacity = max(0.0, min(1.0, payload.bg_opacity))

    invalidate_render(video)
    db.commit()
    db.refresh(video)
    return video


@router.post("/{video_id}/render", response_model=schemas.VideoOut)
def render_video(video_id: str, db: Session = Depends(get_db)):
    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    if not video:
        raise HTTPException(404, "找不到影片")
    if video.render_status == "rendering":
        raise HTTPException(409, "影片正在匯出中")
    if not video.subtitles:
        raise HTTPException(400, "尚無字幕可以匯出")

    video.render_status = "rendering"
    video.render_error = None
    video.render_progress = 0.0
    db.commit()

    start_render_background(video_id)

    db.refresh(video)
    return video


@router.get("/{video_id}/render/download")
def download_rendered_video(video_id: str, request: Request, db: Session = Depends(get_db)):
    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    if not video:
        raise HTTPException(404, "找不到影片")
    if video.render_status != "ready":
        raise HTTPException(409, "尚未完成匯出")
    out_path = rendered_path(video.filename)
    if not os.path.exists(out_path):
        raise HTTPException(404, "找不到匯出的檔案")
    base_name = os.path.splitext(video.original_name)[0]
    return _ranged_file_response(
        out_path, request, "video/mp4", download_filename=f"{base_name}_captioned.mp4"
    )


@router.post("/{video_id}/render/ack", response_model=schemas.VideoOut)
def acknowledge_rendered_video(video_id: str, db: Session = Depends(get_db)):
    """Called by the client right after the browser download starts, so a finished
    export can't be re-downloaded later once it may no longer match the current
    subtitles/style."""
    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    if not video:
        raise HTTPException(404, "找不到影片")

    # Don't delete the file here: the browser may still be mid-download (streaming
    # a large mp4 can take a while) and on Windows an open file can't be removed,
    # which would 500 this call. Flipping render_status to idle is what actually
    # blocks re-downloading a stale export (see /render/download's status check);
    # the on-disk file is simply overwritten next render, or removed on video delete.
    video.render_status = "idle"
    video.render_error = None
    video.render_progress = 0.0
    db.commit()
    db.refresh(video)
    return video
