import os
import threading
from fractions import Fraction

from . import enhance, remote_upscale
from .config import MEDIA_DIR
from .database import SessionLocal
from .models import Video

_FONT_CANDIDATES = [
    # Windows
    r"C:\Windows\Fonts\msjh.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\mingliu.ttc",
    r"C:\Windows\Fonts\simsun.ttc",
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    # Debian/Ubuntu (fonts-noto-cjk package)
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    # Alpine (font-noto-cjk package)
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    # WenQuanYi (common fallback CJK font on minimal Linux images)
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc",
]

_font_path_cache = None


def _find_font():
    global _font_path_cache
    if _font_path_cache is not None:
        return _font_path_cache or None

    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            _font_path_cache = path
            return path

    # Fall back to scanning common Linux font directories for any CJK-capable font.
    search_roots = ["/usr/share/fonts", "/usr/local/share/fonts"]
    keywords = ("cjk", "noto", "wqy", "droid sans fallback", "source-han")
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                if name.lower().endswith((".ttc", ".ttf", ".otf")) and any(
                    kw in name.lower() for kw in keywords
                ):
                    found = os.path.join(dirpath, name)
                    _font_path_cache = found
                    return found

    _font_path_cache = ""
    return None


def rendered_path(video_filename: str) -> str:
    base = os.path.splitext(video_filename)[0]
    return os.path.join(MEDIA_DIR, f"{base}_captioned.mp4")


def invalidate_render(video):
    """Call whenever subtitles/style change so a stale ready/error render can't be re-downloaded."""
    if video.render_status in ("ready", "error"):
        video.render_status = "idle"
        video.render_error = None
        video.render_progress = 0.0


def _wrap_text(draw, text, font, max_width):
    if not text:
        return []
    words = list(text)
    lines = []
    current = ""
    for ch in words:
        trial = current + ch
        bbox = draw.textbbox((0, 0), trial, font=font)
        if bbox[2] - bbox[0] > max_width and current:
            lines.append(current)
            current = ch
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def _hex_to_rgb(hex_color):
    hex_color = (hex_color or "#ffffff").lstrip("#")
    if len(hex_color) != 6:
        return (255, 255, 255)
    try:
        return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (255, 255, 255)


def _draw_caption(img, text, font, position="bottom", color="#ffffff", bg_opacity=0.65):
    from PIL import ImageDraw

    draw = ImageDraw.Draw(img, "RGBA")
    max_width = int(img.width * 0.86)
    lines = _wrap_text(draw, text, font, max_width)
    if not lines:
        return

    line_heights = []
    max_line_w = 0
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_heights.append(bbox[3] - bbox[1])
        max_line_w = max(max_line_w, bbox[2] - bbox[0])

    padding = 10
    line_gap = 6
    total_h = sum(line_heights) + line_gap * (len(lines) - 1) + padding * 2
    box_w = max_line_w + padding * 2
    box_x0 = (img.width - box_w) / 2

    margin = int(img.height * 0.06)
    if position == "top":
        box_y0 = margin
        box_y1 = box_y0 + total_h
    elif position == "middle":
        box_y0 = (img.height - total_h) / 2
        box_y1 = box_y0 + total_h
    else:
        box_y1 = img.height - margin
        box_y0 = box_y1 - total_h

    bg_alpha = int(max(0.0, min(1.0, bg_opacity)) * 255)
    draw.rounded_rectangle(
        [box_x0, box_y0, box_x0 + box_w, box_y1], radius=8, fill=(0, 0, 0, bg_alpha)
    )

    text_rgb = _hex_to_rgb(color)
    y = box_y0 + padding
    for line, lh in zip(lines, line_heights):
        bbox = draw.textbbox((0, 0), line, font=font)
        line_w = bbox[2] - bbox[0]
        x = (img.width - line_w) / 2
        draw.text((x, y), line, font=font, fill=(*text_rgb, 255))
        y += lh + line_gap


def _active_text(subtitles, t):
    for sub in subtitles:
        if sub["start"] <= t <= sub["end"]:
            return sub["text"]
    return None


def _encode_video_track(input_path, output_path, subtitles, style, enhance_params, on_progress=None):
    """Re-encode the video track with picture enhancement and burned-in subtitles."""
    import av
    from PIL import ImageFont

    from .enhance import FrameFilter

    in_container = av.open(input_path)
    in_stream = in_container.streams.video[0]
    in_stream.thread_type = "AUTO"
    rate = in_stream.average_rate or 24

    total_duration = float(in_container.duration) / 1_000_000 if in_container.duration else None

    frame_filter = FrameFilter(in_stream, enhance_params)

    font_path = _find_font()
    # keep captions the same size relative to the picture when upscaling
    font_size = max(8, int(round(style.get("font_size", 32) * frame_filter.scale)))
    font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()

    out_container = av.open(output_path, mode="w")
    out_stream = out_container.add_stream("libx264", rate=rate)
    out_stream.pix_fmt = "yuv420p"
    out_stream.options = {"crf": "23", "preset": "veryfast"}
    size_set = False
    out_time_base = Fraction(1, 1) / Fraction(rate)
    frame_index = 0

    last_reported = -1.0

    def encode(frame):
        nonlocal size_set, last_reported, frame_index
        if not size_set:
            out_stream.width = frame.width
            out_stream.height = frame.height
            size_set = True

        tb = frame.time_base or in_stream.time_base
        t = float(frame.pts * tb) if frame.pts is not None else 0.0
        text = _active_text(subtitles, t)
        if text:
            img = frame.to_image().convert("RGBA")
            _draw_caption(
                img,
                text,
                font,
                position=style.get("position", "bottom"),
                color=style.get("color", "#ffffff"),
                bg_opacity=style.get("bg_opacity", 0.65),
            )
            new_frame = av.VideoFrame.from_image(img.convert("RGB"))
        else:
            # no caption on this frame: skip the slow PIL round-trip
            new_frame = frame.reformat(format="yuv420p")
        # number frames explicitly: a reformatted frame keeps the input time_base,
        # and leaving pts unset then makes the encoder emit duplicate timestamps
        new_frame.pts = frame_index
        new_frame.time_base = out_time_base
        frame_index += 1

        for packet in out_stream.encode(new_frame):
            out_container.mux(packet)

        if on_progress and total_duration:
            fraction = min(t / total_duration, 1.0)
            if fraction - last_reported >= 0.01:
                on_progress(fraction)
                last_reported = fraction

    try:
        for frame in in_container.decode(in_stream):
            for out_frame in frame_filter.process(frame):
                encode(out_frame)
        for out_frame in frame_filter.flush():
            encode(out_frame)

        for packet in out_stream.encode():
            out_container.mux(packet)
    finally:
        # always release the files, or Windows keeps them locked (video delete fails)
        out_container.close()
        in_container.close()


def _copy_audio_track(input_path, video_source_path, final_path, audio_offset=0.0, video_source_is_temp=True):
    """Mux the video track of video_source_path with the audio of input_path.
    A non-zero audio_offset re-encodes the audio shifted by that many seconds."""
    import av

    from .avsync import encode_shifted_audio

    in_container = av.open(input_path)
    audio_streams = in_container.streams.audio
    if not audio_streams and video_source_is_temp:
        in_container.close()
        os.replace(video_source_path, final_path)
        return

    in_audio = audio_streams[0] if audio_streams else None

    video_container = av.open(video_source_path)
    out_container = av.open(final_path, mode="w")
    try:
        video_stream = video_container.streams.video[0]
        out_video_stream = out_container.add_stream(template=video_stream)
        out_audio_stream = None
        if in_audio is not None:
            if audio_offset:
                out_audio_stream = out_container.add_stream("aac", rate=in_audio.rate or 48000)
                out_audio_stream.layout = in_audio.layout.name if in_audio.layout else "stereo"
            else:
                out_audio_stream = out_container.add_stream(template=in_audio)

        for packet in video_container.demux(video_stream):
            if packet.dts is None:
                continue
            packet.stream = out_video_stream
            out_container.mux(packet)

        if in_audio is not None:
            if audio_offset:
                encode_shifted_audio(in_container, in_audio, out_container, out_audio_stream, audio_offset)
            else:
                for packet in in_container.demux(in_audio):
                    if packet.dts is None:
                        continue
                    packet.stream = out_audio_stream
                    out_container.mux(packet)
    finally:
        out_container.close()
        video_container.close()
        in_container.close()
    if video_source_is_temp:
        os.remove(video_source_path)


def run_render(video_id: str):
    db = SessionLocal()
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            return
        video.render_status = "rendering"
        video.render_error = None
        video.render_note = None
        video.render_progress = 0.0
        db.commit()

        # progress band [lo, hi] of the overall bar for the current phase
        phase = {"lo": 0.0, "hi": 0.95}

        def on_progress(fraction):
            video.render_progress = round(phase["lo"] + fraction * (phase["hi"] - phase["lo"]), 3)
            db.commit()

        input_path = os.path.join(MEDIA_DIR, video.filename)
        audio_offset = video.av_offset or 0.0
        # subtitles were timed against the original audio, so by default they move with it
        sub_shift = audio_offset if video.sync_follow_subtitles != 0 else 0.0
        subtitles = [
            {"start": s.start + sub_shift, "end": s.end + sub_shift, "text": s.text}
            for s in sorted(video.subtitles, key=lambda s: s.start)
            if s.text.strip()
        ]

        style = {
            "font_size": video.style_font_size,
            "position": video.style_position,
            "color": video.style_color,
            "bg_opacity": video.style_bg_opacity,
        }

        final_path = rendered_path(video.filename)
        video_only_path = final_path + ".video_only.mp4"

        enhance_params = enhance.params_from_video(video)

        if subtitles or enhance.is_active(enhance_params):
            video_source = input_path
            upscaled_path = None
            target = enhance.upscale_target(input_path, enhance_params)
            if target and enhance_params["upscale_method"] == "ai":
                # Real-ESRGAN on the GPU box first; colour filters / captions / audio stay local
                phase.update(lo=0.0, hi=0.6)
                try:
                    upscaled_path = remote_upscale.upscale_video(
                        input_path,
                        *target,
                        model=enhance_params["sr_model"],
                        detail=enhance_params["sr_detail"],
                        on_progress=on_progress,
                    )
                    video_source = upscaled_path
                    enhance_params = dict(enhance_params, target_height=0)
                except remote_upscale.UpscalerUnavailable as exc:
                    video.render_note = f"{exc}；這次改用本機輕量 AI 放大（效果較弱）。"
                    db.commit()
                phase.update(lo=video.render_progress, hi=0.95)
            try:
                _encode_video_track(
                    video_source, video_only_path, subtitles, style, enhance_params, on_progress=on_progress
                )
            finally:
                if upscaled_path and os.path.exists(upscaled_path):
                    os.remove(upscaled_path)
            video.render_progress = 0.97
            db.commit()
            _copy_audio_track(input_path, video_only_path, final_path, audio_offset=audio_offset)
        else:
            # audio-only change: keep the original video packets, only shift the audio
            _copy_audio_track(
                input_path, input_path, final_path, audio_offset=audio_offset, video_source_is_temp=False
            )

        video.render_status = "ready"
        video.render_progress = 1.0
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        video = db.query(Video).filter(Video.id == video_id).first()
        if video:
            leftover = rendered_path(video.filename) + ".video_only.mp4"
            if os.path.exists(leftover):
                try:
                    os.remove(leftover)
                except OSError:
                    pass
            video.render_status = "error"
            video.render_error = str(exc)
            db.commit()
    finally:
        db.close()


def start_render_background(video_id: str):
    thread = threading.Thread(target=run_render, args=(video_id,), daemon=True)
    thread.start()
