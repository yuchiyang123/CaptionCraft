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
    render_note: Optional[str] = None
    style_font_size: int = 32
    style_position: str = "bottom"
    style_color: str = "#ffffff"
    style_bg_opacity: float = 0.65
    av_offset: float = 0.0
    sync_status: str = "idle"
    sync_error: Optional[str] = None
    sync_progress: float = 0.0
    sync_detected_offset: Optional[float] = None
    sync_confidence: Optional[str] = None
    sync_windows: Optional[str] = None
    sync_follow_subtitles: bool = True
    enh_brightness: float = 1.0
    enh_contrast: float = 1.0
    enh_saturation: float = 1.0
    enh_sharpness: float = 0.0
    enh_denoise: float = 0.0
    enh_target_height: int = 0
    enh_upscale_method: str = "lanczos"
    enh_sr_model: str = "fast"
    enh_sr_detail: float = 0.5


class SyncAnalyzeRequest(BaseModel):
    start: Optional[float] = None  # seconds; omit both for the whole video
    end: Optional[float] = None


class SyncUpdate(BaseModel):
    av_offset: Optional[float] = None
    follow_subtitles: Optional[bool] = None


class EnhanceUpdate(BaseModel):
    brightness: Optional[float] = None
    contrast: Optional[float] = None
    saturation: Optional[float] = None
    sharpness: Optional[float] = None
    denoise: Optional[float] = None
    target_height: Optional[int] = None
    upscale_method: Optional[str] = None
    sr_model: Optional[str] = None
    sr_detail: Optional[float] = None


class StyleUpdate(BaseModel):
    font_size: Optional[int] = None
    position: Optional[str] = None
    color: Optional[str] = None
    bg_opacity: Optional[float] = None


class VideoDetailOut(VideoOut):
    subtitles: List[SubtitleOut] = []


class SubtitlesBulkUpdate(BaseModel):
    subtitles: List[SubtitleOut]
