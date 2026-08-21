from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..render import invalidate_render

router = APIRouter(prefix="/api", tags=["subtitles"])


@router.post("/videos/{video_id}/subtitles", response_model=schemas.SubtitleOut)
def create_subtitle(video_id: str, payload: schemas.SubtitleCreate, db: Session = Depends(get_db)):
    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    if not video:
        raise HTTPException(404, "找不到影片")

    max_order = db.query(models.Subtitle).filter(models.Subtitle.video_id == video_id).count()
    sub = models.Subtitle(
        video_id=video_id,
        start=payload.start,
        end=payload.end,
        text=payload.text,
        order_index=max_order,
    )
    invalidate_render(video)
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


@router.put("/videos/{video_id}/subtitles", response_model=list[schemas.SubtitleOut])
def bulk_update_subtitles(video_id: str, payload: schemas.SubtitlesBulkUpdate, db: Session = Depends(get_db)):
    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    if not video:
        raise HTTPException(404, "找不到影片")

    invalidate_render(video)
    existing = {s.id: s for s in video.subtitles}
    kept_ids = set()
    for i, item in enumerate(payload.subtitles):
        if item.id in existing:
            sub = existing[item.id]
            sub.start = item.start
            sub.end = item.end
            sub.text = item.text
            sub.order_index = i
        else:
            sub = models.Subtitle(
                id=item.id,
                video_id=video_id,
                start=item.start,
                end=item.end,
                text=item.text,
                order_index=i,
            )
            db.add(sub)
        kept_ids.add(item.id)

    for sid, sub in existing.items():
        if sid not in kept_ids:
            db.delete(sub)

    db.commit()
    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    return sorted(video.subtitles, key=lambda s: s.order_index)


@router.patch("/subtitles/{subtitle_id}", response_model=schemas.SubtitleOut)
def update_subtitle(subtitle_id: str, payload: schemas.SubtitleUpdate, db: Session = Depends(get_db)):
    sub = db.query(models.Subtitle).filter(models.Subtitle.id == subtitle_id).first()
    if not sub:
        raise HTTPException(404, "找不到字幕")
    if payload.start is not None:
        sub.start = payload.start
    if payload.end is not None:
        sub.end = payload.end
    if payload.text is not None:
        sub.text = payload.text
    invalidate_render(sub.video)
    db.commit()
    db.refresh(sub)
    return sub


@router.delete("/subtitles/{subtitle_id}")
def delete_subtitle(subtitle_id: str, db: Session = Depends(get_db)):
    sub = db.query(models.Subtitle).filter(models.Subtitle.id == subtitle_id).first()
    if not sub:
        raise HTTPException(404, "找不到字幕")
    invalidate_render(sub.video)
    db.delete(sub)
    db.commit()
    return {"ok": True}
