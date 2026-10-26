import uuid
from datetime import datetime

from sqlalchemy import Column, String, Float, Integer, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship

from .database import Base


def gen_id():
    return uuid.uuid4().hex


class Video(Base):
    __tablename__ = "videos"

    id = Column(String, primary_key=True, default=gen_id)
    filename = Column(String, nullable=False)
    original_name = Column(String, nullable=False)
    duration = Column(Float, default=0)
    has_thumbnail = Column(Integer, default=0)
    status = Column(String, default="uploaded")  # uploaded, transcribing, ready, error
    error_message = Column(Text, nullable=True)
    language = Column(String, nullable=True)
    render_status = Column(String, default="idle")  # idle, rendering, ready, error
    render_error = Column(Text, nullable=True)
    render_progress = Column(Float, default=0.0)
    render_note = Column(Text, nullable=True)  # non-fatal info, e.g. GPU upscaler fallback

    style_font_size = Column(Integer, default=32)
    style_position = Column(String, default="bottom")  # top, middle, bottom
    style_color = Column(String, default="#ffffff")
    style_bg_opacity = Column(Float, default=0.65)

    # Seconds to shift the audio track on export (negative = play audio earlier).
    av_offset = Column(Float, default=0.0)
    sync_status = Column(String, default="idle")  # idle, analyzing, ready, error
    sync_error = Column(Text, nullable=True)
    sync_progress = Column(Float, default=0.0)
    sync_detected_offset = Column(Float, nullable=True)
    sync_confidence = Column(String, nullable=True)  # high, medium, low
    sync_windows = Column(Text, nullable=True)  # JSON: per-window detections, for drift display
    sync_follow_subtitles = Column(Integer, default=1)  # shift subtitles together with the audio

    # Picture enhancement applied on export (see app/enhance.py)
    enh_brightness = Column(Float, default=1.0)
    enh_contrast = Column(Float, default=1.0)
    enh_saturation = Column(Float, default=1.0)
    enh_sharpness = Column(Float, default=0.0)
    enh_denoise = Column(Float, default=0.0)
    enh_target_height = Column(Integer, default=0)  # 0 = source resolution, else e.g. 1080
    enh_upscale_method = Column(String, default="lanczos")  # lanczos, ai
    enh_sr_model = Column(String, default="fast")  # GPU server model: fast, quality
    enh_sr_detail = Column(Float, default=0.5)  # fast model: 0 = smoothest, 1 = keep most texture
    created_at = Column(DateTime, default=datetime.utcnow)

    subtitles = relationship(
        "Subtitle", back_populates="video", cascade="all, delete-orphan", order_by="Subtitle.start"
    )


class Subtitle(Base):
    __tablename__ = "subtitles"

    id = Column(String, primary_key=True, default=gen_id)
    video_id = Column(String, ForeignKey("videos.id"), nullable=False)
    start = Column(Float, nullable=False)
    end = Column(Float, nullable=False)
    text = Column(Text, nullable=False, default="")
    order_index = Column(Integer, default=0)

    video = relationship("Video", back_populates="subtitles")
