import os
import threading

from .config import MEDIA_DIR
from .database import SessionLocal
from .models import Video

_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msjh.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\mingliu.ttc",
    r"C:\Windows\Fonts\simsun.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]


def _find_font():
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            return path
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


def _burn_video_track(input_path, output_path, subtitles, style, on_progress=None):
    import av
    from PIL import ImageFont

    font_path = _find_font()
    font_size = style.get("font_size", 32)
    font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()

    in_container = av.open(input_path)
    in_stream = in_container.streams.video[0]
    rate = in_stream.average_rate or 24

    total_duration = float(in_container.duration) / 1_000_000 if in_container.duration else None

    out_container = av.open(output_path, mode="w")
    out_stream = out_container.add_stream("libx264", rate=rate)
    out_stream.width = in_stream.width
    out_stream.height = in_stream.height
    out_stream.pix_fmt = "yuv420p"
    out_stream.options = {"crf": "23", "preset": "veryfast"}

    last_reported = -1.0
    for frame in in_container.decode(in_stream):
        t = float(frame.pts * in_stream.time_base) if frame.pts is not None else float(frame.time or 0)
        text = _active_text(subtitles, t)
        img = frame.to_image().convert("RGBA")
        if text:
            _draw_caption(
                img,
                text,
                font,
                position=style.get("position", "bottom"),
                color=style.get("color", "#ffffff"),
                bg_opacity=style.get("bg_opacity", 0.65),
            )
        new_frame = av.VideoFrame.from_image(img.convert("RGB"))

        for packet in out_stream.encode(new_frame):
            out_container.mux(packet)

        if on_progress and total_duration:
            fraction = min(t / total_duration, 1.0)
            if fraction - last_reported >= 0.01:
                on_progress(fraction)
                last_reported = fraction

    for packet in out_stream.encode():
        out_container.mux(packet)

    out_container.close()
    in_container.close()


def _copy_audio_track(input_path, video_only_path, final_path):
    import av

    in_container = av.open(input_path)
    audio_streams = in_container.streams.audio
    if not audio_streams:
        in_container.close()
        os.replace(video_only_path, final_path)
        return

    in_audio = audio_streams[0]

    video_container = av.open(video_only_path)
    video_stream = video_container.streams.video[0]

    out_container = av.open(final_path, mode="w")
    out_video_stream = out_container.add_stream(template=video_stream)
    out_audio_stream = out_container.add_stream(template=in_audio)

    for packet in video_container.demux(video_stream):
        if packet.dts is None:
            continue
        packet.stream = out_video_stream
        out_container.mux(packet)

    for packet in in_container.demux(in_audio):
        if packet.dts is None:
            continue
        packet.stream = out_audio_stream
        out_container.mux(packet)

    out_container.close()
    video_container.close()
    in_container.close()
    os.remove(video_only_path)


def run_render(video_id: str):
    db = SessionLocal()
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            return
        video.render_status = "rendering"
        video.render_error = None
        video.render_progress = 0.0
        db.commit()

        def on_progress(fraction):
            video.render_progress = round(fraction * 0.95, 3)
            db.commit()

        input_path = os.path.join(MEDIA_DIR, video.filename)
        subtitles = [
            {"start": s.start, "end": s.end, "text": s.text}
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

        _burn_video_track(input_path, video_only_path, subtitles, style, on_progress=on_progress)
        video.render_progress = 0.97
        db.commit()

        _copy_audio_track(input_path, video_only_path, final_path)

        video.render_status = "ready"
        video.render_progress = 1.0
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        video = db.query(Video).filter(Video.id == video_id).first()
        if video:
            video.render_status = "error"
            video.render_error = str(exc)
            db.commit()
    finally:
        db.close()


def start_render_background(video_id: str):
    thread = threading.Thread(target=run_render, args=(video_id,), daemon=True)
    thread.start()
