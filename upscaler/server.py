"""CaptionCraft GPU upscaler: Real-ESRGAN behind a tiny HTTP API.

Models (query param `model`):
  fast     realesr-general-x4v3 blended with its weak-denoise twin; `detail` (0-1)
           picks the blend: 0 = smoothest, 1 = keeps the most original texture/grain
  quality  RealESRGAN_x4plus (RRDBNet): more generated texture and sharper edges, ~5-10x slower

Runs on the GPU box and only listens on 127.0.0.1; the CaptionCraft backend
reaches it through an SSH tunnel (see README "AI 超解析伺服器").

    POST   /jobs?width=W&height=H[&model=&detail=]  body: video file -> {"id": ...}
    GET    /jobs/{id}                                  -> status / progress
    GET    /jobs/{id}/result                           -> upscaled video (video track only)
    DELETE /jobs/{id}
    POST   /frame?width=W&height=H[&model=&detail=] body: JPEG/PNG -> upscaled JPEG (previews)
    GET    /health                                     -> device info

The output keeps the source frame count and frame rate (frames are numbered
in decode order), so the caller can lay the original audio and subtitles back
on top unchanged.
"""

import io
import os
import shutil
import tempfile
import threading
import time
import urllib.request
import uuid
from fractions import Fraction

import av
import numpy as np
import torch
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from PIL import Image
from torch import nn
from torch.nn import functional as F

RELEASES = "https://github.com/xinntao/Real-ESRGAN/releases/download"
WEIGHTS = {
    # fast video model, strong denoise
    "general": (f"{RELEASES}/v0.2.5.0/realesr-general-x4v3.pth", "params"),
    # same network trained with weak denoise; blended with "general" for the detail slider
    "general_wdn": (f"{RELEASES}/v0.2.5.0/realesr-general-wdn-x4v3.pth", "params"),
    # large RRDB model: much more texture/detail, ~5-10x slower
    "x4plus": (f"{RELEASES}/v0.1.0/RealESRGAN_x4plus.pth", "params_ema"),
}
DATA_DIR = os.environ.get("UPSCALER_DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
JOBS_DIR = os.path.join(DATA_DIR, "jobs")
TILE = 512  # x4plus falls back to tiles of this size (input px) if a frame doesn't fit in VRAM
TILE_PAD = 16
JOB_TTL_SECONDS = 6 * 3600
MAX_OUTPUT_PIXELS = 3840 * 2160

os.makedirs(JOBS_DIR, exist_ok=True)


class SRVGGNetCompact(nn.Module):
    """Real-ESRGAN's compact video model (same layout as the official
    realesrgan.archs.srvgg_arch, BSD-3-Clause), so the released weights load as-is."""

    def __init__(self, num_in_ch=3, num_out_ch=3, num_feat=64, num_conv=32, upscale=4):
        super().__init__()
        self.upscale = upscale
        self.body = nn.ModuleList()
        self.body.append(nn.Conv2d(num_in_ch, num_feat, 3, 1, 1))
        self.body.append(nn.PReLU(num_parameters=num_feat))
        for _ in range(num_conv):
            self.body.append(nn.Conv2d(num_feat, num_feat, 3, 1, 1))
            self.body.append(nn.PReLU(num_parameters=num_feat))
        self.body.append(nn.Conv2d(num_feat, num_out_ch * upscale * upscale, 3, 1, 1))
        self.upsampler = nn.PixelShuffle(upscale)

    def forward(self, x):
        out = x
        for layer in self.body:
            out = layer(out)
        out = self.upsampler(out)
        return out + F.interpolate(x, scale_factor=self.upscale, mode="nearest")


class ResidualDenseBlock(nn.Module):
    def __init__(self, num_feat=64, num_grow_ch=32):
        super().__init__()
        self.conv1 = nn.Conv2d(num_feat, num_grow_ch, 3, 1, 1)
        self.conv2 = nn.Conv2d(num_feat + num_grow_ch, num_grow_ch, 3, 1, 1)
        self.conv3 = nn.Conv2d(num_feat + 2 * num_grow_ch, num_grow_ch, 3, 1, 1)
        self.conv4 = nn.Conv2d(num_feat + 3 * num_grow_ch, num_grow_ch, 3, 1, 1)
        self.conv5 = nn.Conv2d(num_feat + 4 * num_grow_ch, num_feat, 3, 1, 1)
        self.lrelu = nn.LeakyReLU(negative_slope=0.2, inplace=True)

    def forward(self, x):
        x1 = self.lrelu(self.conv1(x))
        x2 = self.lrelu(self.conv2(torch.cat((x, x1), 1)))
        x3 = self.lrelu(self.conv3(torch.cat((x, x1, x2), 1)))
        x4 = self.lrelu(self.conv4(torch.cat((x, x1, x2, x3), 1)))
        x5 = self.conv5(torch.cat((x, x1, x2, x3, x4), 1))
        return x5 * 0.2 + x


class RRDB(nn.Module):
    def __init__(self, num_feat, num_grow_ch=32):
        super().__init__()
        self.rdb1 = ResidualDenseBlock(num_feat, num_grow_ch)
        self.rdb2 = ResidualDenseBlock(num_feat, num_grow_ch)
        self.rdb3 = ResidualDenseBlock(num_feat, num_grow_ch)

    def forward(self, x):
        return self.rdb3(self.rdb2(self.rdb1(x))) * 0.2 + x


class RRDBNet(nn.Module):
    """ESRGAN generator used by RealESRGAN_x4plus (same layout as basicsr.archs.rrdbnet_arch,
    Apache-2.0), so the released weights load as-is."""

    def __init__(self, num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32):
        super().__init__()
        self.conv_first = nn.Conv2d(num_in_ch, num_feat, 3, 1, 1)
        self.body = nn.Sequential(*[RRDB(num_feat, num_grow_ch) for _ in range(num_block)])
        self.conv_body = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_up1 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_up2 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_hr = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_last = nn.Conv2d(num_feat, num_out_ch, 3, 1, 1)
        self.lrelu = nn.LeakyReLU(negative_slope=0.2, inplace=True)

    def forward(self, x):
        feat = self.conv_first(x)
        feat = feat + self.conv_body(self.body(feat))
        feat = self.lrelu(self.conv_up1(F.interpolate(feat, scale_factor=2, mode="nearest")))
        feat = self.lrelu(self.conv_up2(F.interpolate(feat, scale_factor=2, mode="nearest")))
        return self.conv_last(self.lrelu(self.conv_hr(feat)))


def _load_state(name):
    url, key = WEIGHTS[name]
    path = os.path.join(DATA_DIR, os.path.basename(url))
    if not os.path.exists(path):
        tmp = path + ".download"
        urllib.request.urlretrieve(url, tmp)
        os.replace(tmp, path)
    state = torch.load(path, map_location="cpu", weights_only=True)
    return state.get(key, state)


class Upscaler:
    """Holds the networks on the GPU. Models load lazily on first use."""

    def __init__(self):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.half = self.device.type == "cuda"
        self.lock = threading.Lock()  # one GPU, one inference at a time
        self._states = {}
        self._general = {}  # detail level -> blended compact model (few distinct values in practice)
        self._x4plus = None

    def _prepare(self, model):
        model.eval().to(self.device)
        model = model.half() if self.half else model
        # channels_last is ~25% faster on the RTX 2070 (compact model: 99 -> 76 ms @ 480p)
        return model.to(memory_format=torch.channels_last)

    def _state(self, name):
        if name not in self._states:
            self._states[name] = _load_state(name)
        return self._states[name]

    def general_model(self, detail):
        """detail 0 = strongest denoise (smoothest), 1 = weakest denoise (keeps most texture).
        Official Real-ESRGAN "denoise strength": interpolate the two networks' weights."""
        detail = round(min(max(detail, 0.0), 1.0), 2)
        if detail not in self._general:
            strong, weak = self._state("general"), self._state("general_wdn")
            blended = {k: (1 - detail) * strong[k] + detail * weak[k] for k in strong}
            model = SRVGGNetCompact()
            model.load_state_dict(blended, strict=True)
            if len(self._general) >= 4:
                self._general.pop(next(iter(self._general)))
            self._general[detail] = self._prepare(model)
        return self._general[detail]

    def x4plus_model(self):
        if self._x4plus is None:
            model = RRDBNet()
            model.load_state_dict(self._state("x4plus"), strict=True)
            self._x4plus = self._prepare(model)
        return self._x4plus

    @property
    def device_name(self):
        if self.device.type == "cuda":
            return torch.cuda.get_device_name(0)
        return "CPU"

    def _run_tiled(self, model, x):
        """Run model on overlapping tiles (for frames too big for VRAM in one go)."""
        _, c, h, w = x.shape
        out = torch.empty((1, c, h * 4, w * 4), dtype=x.dtype, device=x.device)
        for y0 in range(0, h, TILE):
            for x0 in range(0, w, TILE):
                y1, x1 = min(y0 + TILE, h), min(x0 + TILE, w)
                py0, px0 = max(y0 - TILE_PAD, 0), max(x0 - TILE_PAD, 0)
                py1, px1 = min(y1 + TILE_PAD, h), min(x1 + TILE_PAD, w)
                tile = model(x[:, :, py0:py1, px0:px1])
                oy, ox = (y0 - py0) * 4, (x0 - px0) * 4
                out[:, :, y0 * 4 : y1 * 4, x0 * 4 : x1 * 4] = tile[:, :, oy : oy + (y1 - y0) * 4, ox : ox + (x1 - x0) * 4]
        return out

    @torch.inference_mode()
    def upscale(self, rgb, out_w, out_h, model="fast", detail=0.5):
        """rgb: HxWx3 uint8 -> out_h x out_w x 3 uint8."""
        x = torch.from_numpy(rgb).to(self.device).permute(2, 0, 1).unsqueeze(0)
        x = x.half() if self.half else x.float()
        x = (x / 255.0).contiguous(memory_format=torch.channels_last)
        with self.lock:
            if model == "quality":
                net = self.x4plus_model()
                try:
                    y = net(x)
                except torch.cuda.OutOfMemoryError:
                    torch.cuda.empty_cache()
                    y = self._run_tiled(net, x)
            else:
                y = self.general_model(detail)(x)
        if (y.shape[3], y.shape[2]) != (out_w, out_h):
            shrinking = y.shape[2] > out_h
            y = F.interpolate(y, size=(out_h, out_w), mode="bicubic" if not shrinking else "area",
                              align_corners=False if not shrinking else None)
        y = (y.clamp(0, 1) * 255.0).round().byte()
        return y.squeeze(0).permute(1, 2, 0).cpu().numpy()


app = FastAPI(title="CaptionCraft upscaler")
_upscaler = None
_upscaler_lock = threading.Lock()
jobs = {}
jobs_lock = threading.Lock()


def get_upscaler():
    global _upscaler
    if _upscaler is None:
        with _upscaler_lock:
            if _upscaler is None:
                _upscaler = Upscaler()
    return _upscaler


def _check_size(width, height):
    if width <= 0 or height <= 0 or width % 2 or height % 2 or width * height > MAX_OUTPUT_PIXELS:
        raise HTTPException(400, "width/height must be positive even numbers, at most 4K")


def _cleanup_old_jobs():
    now = time.time()
    with jobs_lock:
        stale = [jid for jid, j in jobs.items() if now - j["updated"] > JOB_TTL_SECONDS]
        for jid in stale:
            shutil.rmtree(jobs[jid]["dir"], ignore_errors=True)
            del jobs[jid]


def _run_job(job_id):
    job = jobs[job_id]
    try:
        up = get_upscaler()
        src = os.path.join(job["dir"], "input")
        out = os.path.join(job["dir"], "output.mp4")
        with av.open(src) as in_c:
            in_s = in_c.streams.video[0]
            in_s.thread_type = "AUTO"
            rate = in_s.average_rate or 24
            total = in_s.frames or 0
            if not total and in_c.duration:
                total = int(float(in_c.duration) / 1_000_000 * float(rate))
            with av.open(out, "w") as out_c:
                out_s = out_c.add_stream("libx264", rate=rate)
                out_s.width, out_s.height = job["width"], job["height"]
                out_s.pix_fmt = "yuv420p"
                # near-lossless intermediate: CaptionCraft re-encodes it again afterwards
                out_s.options = {"crf": "14", "preset": "veryfast"}
                time_base = Fraction(1, 1) / Fraction(rate)
                started = time.time()
                for i, frame in enumerate(in_c.decode(in_s)):
                    rgb = frame.to_ndarray(format="rgb24")
                    big = up.upscale(rgb, job["width"], job["height"], job["model"], job["detail"])
                    nf = av.VideoFrame.from_ndarray(big, format="rgb24")
                    nf.pts = i
                    nf.time_base = time_base
                    for p in out_s.encode(nf):
                        out_c.mux(p)
                    job["frames_done"] = i + 1
                    if total:
                        job["progress"] = min((i + 1) / total, 0.999)
                    job["fps"] = round((i + 1) / max(time.time() - started, 1e-6), 2)
                    job["updated"] = time.time()
                    if job.get("cancel"):
                        raise RuntimeError("cancelled")
                for p in out_s.encode():
                    out_c.mux(p)
        os.remove(src)
        job["status"] = "done"
        job["progress"] = 1.0
    except Exception as exc:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = str(exc)
    finally:
        job["updated"] = time.time()


@app.get("/health")
def health():
    up = get_upscaler()
    return {"status": "ok", "device": up.device_name, "cuda": up.device.type == "cuda", "models": list(MODELS)}


MODELS = ("fast", "quality")


def _check_model(model, detail):
    if model not in MODELS:
        raise HTTPException(400, f"model must be one of {MODELS}")
    if not 0.0 <= detail <= 1.0:
        raise HTTPException(400, "detail must be between 0 and 1")


@app.post("/jobs")
async def create_job(request: Request, width: int, height: int, model: str = "fast", detail: float = 0.5):
    _check_size(width, height)
    _check_model(model, detail)
    _cleanup_old_jobs()
    job_id = uuid.uuid4().hex
    job_dir = os.path.join(JOBS_DIR, job_id)
    os.makedirs(job_dir)
    with open(os.path.join(job_dir, "input"), "wb") as f:
        async for chunk in request.stream():
            f.write(chunk)
    job = {"id": job_id, "dir": job_dir, "width": width, "height": height, "model": model, "detail": detail,
           "status": "running",
           "progress": 0.0, "frames_done": 0, "fps": 0.0, "error": None, "updated": time.time()}
    with jobs_lock:
        jobs[job_id] = job
    threading.Thread(target=_run_job, args=(job_id,), daemon=True).start()
    return {"id": job_id}


def _get_job(job_id):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "no such job")
    return job


@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    job = _get_job(job_id)
    return {k: job[k] for k in ("id", "status", "progress", "frames_done", "fps", "error", "width", "height")}


@app.get("/jobs/{job_id}/result")
def job_result(job_id: str):
    job = _get_job(job_id)
    if job["status"] != "done":
        raise HTTPException(409, "job not finished")
    return FileResponse(os.path.join(job["dir"], "output.mp4"), media_type="video/mp4")


@app.delete("/jobs/{job_id}")
def delete_job(job_id: str):
    job = _get_job(job_id)
    job["cancel"] = True
    if job["status"] != "running":
        with jobs_lock:
            jobs.pop(job_id, None)
        shutil.rmtree(job["dir"], ignore_errors=True)
    return {"ok": True}


@app.post("/frame")
async def upscale_frame(request: Request, width: int, height: int, model: str = "fast", detail: float = 0.5):
    _check_size(width, height)
    _check_model(model, detail)
    data = await request.body()
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "not an image")
    big = get_upscaler().upscale(np.array(img), width, height, model, detail)  # writable copy for torch
    buf = io.BytesIO()
    Image.fromarray(big).save(buf, "JPEG", quality=92)
    return Response(content=buf.getvalue(), media_type="image/jpeg")


@app.exception_handler(torch.cuda.OutOfMemoryError)
def _oom(_request, _exc):
    torch.cuda.empty_cache()
    return JSONResponse({"detail": "GPU out of memory"}, status_code=503)
