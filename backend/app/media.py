import os

from .config import MEDIA_DIR


def thumbnail_path(video_filename: str) -> str:
    base = os.path.splitext(video_filename)[0]
    return os.path.join(MEDIA_DIR, f"{base}.jpg")


def get_media_duration(path: str) -> float:
    try:
        import av

        with av.open(path) as container:
            if container.duration:
                return float(container.duration) / 1_000_000
    except Exception:
        pass
    return 0.0


def generate_thumbnail(video_path: str, video_filename: str) -> bool:
    out_path = thumbnail_path(video_filename)
    try:
        import av
        from PIL import Image

        with av.open(video_path) as container:
            stream = next((s for s in container.streams if s.type == "video"), None)
            if stream is None:
                return False

            target_ts = 0
            if container.duration:
                target_pos = min(0.5 * container.duration, container.duration * 0.5)
                target_ts = int(target_pos)

            if target_ts:
                container.seek(target_ts, stream=stream)

            frame = next(container.decode(stream), None)
            if frame is None:
                return False

            img = frame.to_image()
            img.thumbnail((640, 640))
            img.convert("RGB").save(out_path, "JPEG", quality=82)
            return True
    except Exception:
        return False
