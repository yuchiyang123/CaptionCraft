"""Picture enhancement applied on export: colour/detail filters plus upscaling
to a target resolution (e.g. 480p -> 1080p).

Filters are ffmpeg filters run through PyAV. brightness / contrast /
saturation are multipliers (1 = unchanged, matching the editor's CSS preview),
sharpness is an unsharp-mask amount and denoise an hqdn3d strength.

Upscaling either uses lanczos inside the ffmpeg graph ("lanczos", fast) or an
ESPCN super-resolution network through OpenCV ("ai", slower but recovers more
detail): the picture is doubled by the network, then resized to the exact
target with lanczos.
"""

import os
import shutil
import tempfile
import threading
import urllib.request

from .config import MODELS_DIR

DEFAULTS = {
    "brightness": 1.0,
    "contrast": 1.0,
    "saturation": 1.0,
    "sharpness": 0.0,
    "denoise": 0.0,
}

LIMITS = {
    "brightness": (0.5, 1.5),
    "contrast": (0.5, 2.0),
    "saturation": (0.0, 2.0),
    "sharpness": (0.0, 2.0),
    "denoise": (0.0, 10.0),
}

TARGET_HEIGHTS = (0, 720, 1080, 1440, 2160)  # 0 = keep the source resolution
UPSCALE_METHODS = ("lanczos", "ai")
SR_MODELS = ("fast", "quality")  # models on the GPU upscaler service

SR_MODEL_URL = "https://raw.githubusercontent.com/fannymonori/TF-ESPCN/master/export/ESPCN_x2.pb"
SR_MODEL_PATH = os.path.join(MODELS_DIR, "ESPCN_x2.pb")

_sr_lock = threading.Lock()


def clamp(name, value):
    lo, hi = LIMITS[name]
    return max(lo, min(hi, float(value)))


def params_from_video(video):
    params = {}
    for name, default in DEFAULTS.items():
        value = getattr(video, f"enh_{name}", None)
        params[name] = default if value is None else value
    params["target_height"] = video.enh_target_height or 0
    params["upscale_method"] = video.enh_upscale_method or "lanczos"
    params["sr_model"] = video.enh_sr_model or "fast"
    params["sr_detail"] = 0.5 if video.enh_sr_detail is None else video.enh_sr_detail
    return params


def output_size(src_w, src_h, target_height):
    """Only ever upscales; returns even dimensions keeping the aspect ratio."""
    if not target_height or target_height <= src_h:
        return src_w, src_h
    w = int(round(src_w * target_height / src_h / 2)) * 2
    # 854x480 etc. are "almost" 16:9: snap to the standard width (1920x1080, not 1922)
    standard_w = int(round(target_height * 16 / 9 / 2)) * 2
    if abs(w - standard_w) <= 4:
        w = standard_w
    return w, int(target_height)


def upscale_target(path, params):
    """(width, height) the video will be upscaled to, or None if no upscaling applies."""
    if not params.get("target_height"):
        return None
    import av

    with av.open(path) as container:
        ctx = container.streams.video[0].codec_context
        src_w, src_h = ctx.width, ctx.height
    out = output_size(src_w, src_h, params["target_height"])
    return out if out != (src_w, src_h) else None


def is_active(params):
    return params.get("target_height", 0) > 0 or any(
        abs(params[k] - DEFAULTS[k]) > 1e-6 for k in DEFAULTS
    )


def filter_chain(params, src_w=None, src_h=None):
    """List of (filter_name, args) in the order they are applied."""
    chain = []
    d = params["denoise"]
    if d > 0:
        chain.append(("hqdn3d", f"{d:.2f}:{d * 0.75:.2f}:{d * 1.5:.2f}:{d * 1.125:.2f}"))
    if src_w and src_h and params.get("upscale_method") != "ai":
        out_w, out_h = output_size(src_w, src_h, params.get("target_height", 0))
        if (out_w, out_h) != (src_w, src_h):
            chain.append(("scale", f"w={out_w}:h={out_h}:flags=lanczos"))
    b = params["brightness"]
    if abs(b - 1) > 1e-6:
        chain.append(("colorchannelmixer", f"rr={b:.3f}:gg={b:.3f}:bb={b:.3f}"))
    c, sat = params["contrast"], params["saturation"]
    if abs(c - 1) > 1e-6 or abs(sat - 1) > 1e-6:
        chain.append(("eq", f"contrast={c:.3f}:saturation={sat:.3f}"))
    sh = params["sharpness"]
    if sh > 0:
        chain.append(("unsharp", f"luma_msize_x=5:luma_msize_y=5:luma_amount={sh:.3f}"))
    return chain


def _load_sr_model_path():
    if not os.path.exists(SR_MODEL_PATH):
        with _sr_lock:
            if not os.path.exists(SR_MODEL_PATH):
                tmp_path = SR_MODEL_PATH + ".download"
                urllib.request.urlretrieve(SR_MODEL_URL, tmp_path)
                os.replace(tmp_path, SR_MODEL_PATH)
    if SR_MODEL_PATH.isascii():
        return SR_MODEL_PATH
    # OpenCV can't open non-ASCII paths on Windows: use an ASCII temp copy
    ascii_path = os.path.join(tempfile.gettempdir(), "captioncraft_ESPCN_x2.pb")
    if not os.path.exists(ascii_path) or os.path.getsize(ascii_path) != os.path.getsize(SR_MODEL_PATH):
        shutil.copyfile(SR_MODEL_PATH, ascii_path)
    return ascii_path


class SuperResolver:
    """ESPCN x2 network; repeated (at most twice) then resized to the exact target."""

    def __init__(self, out_w, out_h):
        import cv2

        self.cv2 = cv2
        self.out_w, self.out_h = out_w, out_h
        self.sr = cv2.dnn_superres.DnnSuperResImpl_create()
        self.sr.readModel(_load_sr_model_path())
        self.sr.setModel("espcn", 2)

    def upscale(self, frame):
        import av

        img = frame.to_ndarray(format="bgr24")
        img = self.sr.upsample(img)
        # a second x2 pass only if it doesn't overshoot the target by much: the
        # network is the slow part, and a pass on an already large image just to
        # shrink it back down costs ~4x for little gain (480p->1080p: one pass)
        if img.shape[0] < self.out_h and img.shape[0] * 2 <= self.out_h * 1.1:
            img = self.sr.upsample(img)
        if (img.shape[1], img.shape[0]) != (self.out_w, self.out_h):
            shrinking = img.shape[0] > self.out_h
            interp = self.cv2.INTER_AREA if shrinking else self.cv2.INTER_LANCZOS4
            img = self.cv2.resize(img, (self.out_w, self.out_h), interpolation=interp)
        out = av.VideoFrame.from_ndarray(img, format="bgr24")
        out.pts = frame.pts
        out.time_base = frame.time_base
        return out


class FrameFilter:
    """Pushes decoded frames through the enhancement filters and upscaler.
    With nothing active it passes frames straight through."""

    def __init__(self, in_stream, params):
        import av.filter

        src_w = in_stream.codec_context.width
        src_h = in_stream.codec_context.height
        self.out_width, self.out_height = output_size(src_w, src_h, params.get("target_height", 0))
        self.scale = self.out_height / src_h if src_h else 1.0

        self.upscaler = None
        if params.get("upscale_method") == "ai" and self.out_height > src_h:
            self.upscaler = SuperResolver(self.out_width, self.out_height)

        self.graph = None
        chain = filter_chain(params, src_w, src_h)
        if not chain:
            return
        graph = av.filter.Graph()
        nodes = [graph.add_buffer(template=in_stream)]
        for name, args in chain:
            nodes.append(graph.add(name, args))
        nodes.append(graph.add("format", "yuv420p"))
        nodes.append(graph.add("buffersink"))
        for a, b in zip(nodes, nodes[1:]):
            a.link_to(b)
        graph.configure()
        self.graph = graph

    def _drain(self):
        import av

        out = []
        while True:
            try:
                out.append(self.graph.pull())
            except (BlockingIOError, av.error.EOFError):
                break
            except av.error.FFmpegError as exc:
                if getattr(exc, "errno", None) in (11, 35):  # EAGAIN
                    break
                raise
        return out

    def _finish(self, frames):
        if self.upscaler is None:
            return frames
        return [self.upscaler.upscale(f) for f in frames]

    def process(self, frame):
        if self.graph is None:
            return self._finish([frame])
        self.graph.push(frame)
        return self._finish(self._drain())

    def flush(self):
        if self.graph is None:
            return []
        self.graph.push(None)
        return self._finish(self._drain())


def render_preview_jpeg(path, t, params, quality=90):
    """One frame at time t with all enhancements applied, as JPEG bytes."""
    import io

    import av

    with av.open(path) as container:
        stream = container.streams.video[0]
        container.seek(int(max(0.0, t) * 1_000_000), backward=True)
        frame = None
        for f in container.decode(stream):
            frame = f
            if f.pts is not None and float(f.pts * stream.time_base) >= t:
                break
        if frame is None:
            raise ValueError("無法讀取這個時間點的畫面")
        frame_filter = FrameFilter(stream, params)
        outs = frame_filter.process(frame) + frame_filter.flush()
        out = outs[-1] if outs else frame
    buf = io.BytesIO()
    out.to_image().convert("RGB").save(buf, "JPEG", quality=quality)
    return buf.getvalue()
