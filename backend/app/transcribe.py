import threading

from .config import WHISPER_MODEL_SIZE, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE
from .database import SessionLocal
from .media import get_media_duration
from .models import Video, Subtitle

_model = None
_model_lock = threading.Lock()


def get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from faster_whisper import WhisperModel

                _model = WhisperModel(
                    WHISPER_MODEL_SIZE, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE_TYPE
                )
    return _model


def run_transcription(video_id: str, media_path: str):
    db = SessionLocal()
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            return
        video.status = "transcribing"
        db.commit()

        duration = get_media_duration(media_path)
        if duration:
            video.duration = duration
            db.commit()

        model = get_model()
        segments, info = model.transcribe(media_path, beam_size=5, vad_filter=True)

        order = 0
        for seg in segments:
            text = seg.text.strip()
            if not text:
                continue
            db.add(
                Subtitle(
                    video_id=video_id,
                    start=round(seg.start, 2),
                    end=round(seg.end, 2),
                    text=text,
                    order_index=order,
                )
            )
            order += 1

        video.language = info.language if info else None
        if not video.duration and info and getattr(info, "duration", None):
            video.duration = info.duration
        video.status = "ready"
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        video = db.query(Video).filter(Video.id == video_id).first()
        if video:
            video.status = "error"
            video.error_message = str(exc)
            db.commit()
    finally:
        db.close()


def start_transcription_background(video_id: str, media_path: str):
    thread = threading.Thread(target=run_transcription, args=(video_id, media_path), daemon=True)
    thread.start()
