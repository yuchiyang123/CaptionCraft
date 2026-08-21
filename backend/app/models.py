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

    style_font_size = Column(Integer, default=32)
    style_position = Column(String, default="bottom")  # top, middle, bottom
    style_color = Column(String, default="#ffffff")
    style_bg_opacity = Column(Float, default=0.65)
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
