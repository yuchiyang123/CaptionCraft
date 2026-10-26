"""Client for the GPU upscaler service (../upscaler/server.py).

The service runs on the GPU box and is reached through an SSH tunnel, by
default at http://127.0.0.1:12130 (UPSCALER_URL). Everything here raises
UpscalerUnavailable when it can't be used, so callers can fall back to the
local (CPU) path.
"""

import os
import time

import requests

from .config import MEDIA_DIR, UPSCALER_URL

_status_cache = {"at": 0.0, "value": None}


class UpscalerUnavailable(Exception):
    pass


def status(max_age=10.0):
    """{'device': ..., 'cuda': bool} when the service answers, else None (cached briefly)."""
    if not UPSCALER_URL:
        return None
    now = time.time()
    if now - _status_cache["at"] < max_age:
        return _status_cache["value"]
    try:
        r = requests.get(f"{UPSCALER_URL}/health", timeout=(2, 60))
        value = r.json() if r.ok else None
    except (requests.RequestException, ValueError):
        value = None
    _status_cache.update(at=now, value=value)
    return value


def upscale_video(input_path, width, height, model="fast", detail=0.5, on_progress=None):
    """Upscale the video track of input_path on the GPU box; returns a local
    path to the result (video only, same frame count and rate). Caller deletes it."""
    if not status(max_age=0):
        raise UpscalerUnavailable(f"連不到 AI 放大伺服器（{UPSCALER_URL}），請確認 SSH 通道有開")

    try:
        with open(input_path, "rb") as f:
            r = requests.post(
                f"{UPSCALER_URL}/jobs",
                params={"width": width, "height": height, "model": model, "detail": detail},
                data=f,
                timeout=(5, 3600),
            )
        r.raise_for_status()
        job_id = r.json()["id"]
    except requests.RequestException as exc:
        raise UpscalerUnavailable(f"上傳影片到 AI 放大伺服器失敗：{exc}") from exc

    try:
        failures = 0
        while True:
            time.sleep(2)
            try:
                st = requests.get(f"{UPSCALER_URL}/jobs/{job_id}", timeout=(5, 30)).json()
                failures = 0
            except (requests.RequestException, ValueError):
                failures += 1
                if failures >= 15:
                    raise UpscalerUnavailable("AI 放大伺服器連線中斷")
                continue
            if on_progress:
                on_progress(st.get("progress") or 0.0)
            if st["status"] == "done":
                break
            if st["status"] == "error":
                raise RuntimeError(f"AI 放大伺服器處理失敗：{st.get('error')}")

        out_path = os.path.join(MEDIA_DIR, f"upscaled_{job_id}.mp4")
        with requests.get(f"{UPSCALER_URL}/jobs/{job_id}/result", stream=True, timeout=(5, 600)) as r:
            r.raise_for_status()
            with open(out_path, "wb") as out:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    out.write(chunk)
        return out_path
    finally:
        try:
            requests.delete(f"{UPSCALER_URL}/jobs/{job_id}", timeout=(2, 10))
        except requests.RequestException:
            pass


def upscale_frame_jpeg(jpeg_bytes, width, height, model="fast", detail=0.5):
    if not status():
        raise UpscalerUnavailable("AI 放大伺服器未連線")
    try:
        r = requests.post(
            f"{UPSCALER_URL}/frame",
            params={"width": width, "height": height, "model": model, "detail": detail},
            data=jpeg_bytes,
            headers={"Content-Type": "image/jpeg"},
            timeout=(3, 120),
        )
        r.raise_for_status()
        return r.content
    except requests.RequestException as exc:
        raise UpscalerUnavailable(str(exc)) from exc
