from typing import Optional, List
from pydantic import BaseModel, ConfigDict


class SubtitleBase(BaseModel):
    start: float
    end: float
    text: str


class SubtitleCreate(SubtitleBase):
    pass


class SubtitleUpdate(BaseModel):
    start: Optional[float] = None
    end: Optional[float] = None
    text: Optional[str] = None


class SubtitleOut(SubtitleBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    order_index: int


class VideoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    filename: str
    original_name: str
    duration: float
    status: str
    error_message: Optional[str] = None
    language: Optional[str] = None
    has_thumbnail: bool = False
    render_status: str = "idle"
    render_error: Optional[str] = None
    render_progress: float = 0.0
    style_font_size: int = 32
    style_position: str = "bottom"
    style_color: str = "#ffffff"
    style_bg_opacity: float = 0.65


class StyleUpdate(BaseModel):
    font_size: Optional[int] = None
    position: Optional[str] = None
    color: Optional[str] = None
    bg_opacity: Optional[float] = None


class VideoDetailOut(VideoOut):
    subtitles: List[SubtitleOut] = []


class SubtitlesBulkUpdate(BaseModel):
    subtitles: List[SubtitleOut]
