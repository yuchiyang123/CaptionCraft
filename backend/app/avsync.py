"""Audio/video sync detection and audio shifting.

Detection compares the speaker's mouth movement (MediaPipe face landmarks and
the "jawOpen" blendshape, per video frame) against the speech-band loudness
of the audio track. Speech is loudest while the mouth is open, so the time lag
at which the two signals correlate best is how far the audio is ahead of /
behind the picture.

Several windows spread across the whole video are analysed; their correlation
curves are combined for the final estimate, and the per-window results are
kept so a drifting offset (sync getting worse over time) can be flagged.
"""

import json
import math
import os
import threading
import urllib.request
from fractions import Fraction

import numpy as np

from .config import (
    AVSYNC_MAX_OFFSET,
    AVSYNC_MAX_SECONDS,
    AVSYNC_WINDOW_SECONDS,
    MEDIA_DIR,
    MODELS_DIR,
)
from .database import SessionLocal
from .media import get_media_duration
from .models import Video

FACE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/latest/face_landmarker.task"
)
FACE_MODEL_PATH = os.path.join(MODELS_DIR, "face_landmarker.task")

GRID_HZ = 100  # both signals are resampled to 10 ms steps before correlating
ANALYSIS_WIDTH = 480  # frames are downscaled to this width for face tracking
MIN_FACE_SECONDS = 3.0  # per window
AUDIO_RATE = 16000
SPEECH_BAND = (300.0, 3000.0)  # Hz
DRIFT_WARN_SECONDS = 0.12

# MediaPipe face mesh landmark indices
_UPPER_INNER_LIP = 13
_LOWER_INNER_LIP = 14
_FOREHEAD = 10
_CHIN = 152

_model_lock = threading.Lock()


def _ensure_face_model():
    if os.path.exists(FACE_MODEL_PATH):
        return
    with _model_lock:
        if os.path.exists(FACE_MODEL_PATH):
            return
        tmp_path = FACE_MODEL_PATH + ".download"
        urllib.request.urlretrieve(FACE_MODEL_URL, tmp_path)
        os.replace(tmp_path, FACE_MODEL_PATH)


def plan_windows(duration, total=AVSYNC_MAX_SECONDS, window=AVSYNC_WINDOW_SECONDS):
    """(start, end) ranges to analyse: the whole video if it is short enough,
    otherwise evenly spread windows adding up to about `total` seconds."""
    if duration <= 0:
        return [(0.0, total)]
    if duration <= total:
        count = max(1, int(round(duration / window)))
        step = duration / count
        return [(i * step, (i + 1) * step) for i in range(count)]
    count = max(1, int(total // window))
    span = duration - window
    return [(span * (i + 0.5) / count, span * (i + 0.5) / count + window) for i in range(count)]


def _mouth_tracks(path, windows, on_progress=None):
    """Per video frame inside the windows: (times, lip_ratio, jaw_open).
    Values are NaN where no face was found."""
    import av
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision

    # pass the model as bytes: MediaPipe can't open non-ASCII paths on Windows
    with open(FACE_MODEL_PATH, "rb") as f:
        model_bytes = f.read()
    # IMAGE mode on purpose: VIDEO mode smooths landmarks across frames, which
    # makes the mouth lag slightly behind the picture and biases the offset
    options = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_buffer=model_bytes),
        running_mode=vision.RunningMode.IMAGE,
        num_faces=2,
        output_face_blendshapes=True,
    )

    total = sum(end - start for start, end in windows) or 1.0
    done = 0.0
    times, lips, jaws = [], [], []
    last_reported = -1.0
    with vision.FaceLandmarker.create_from_options(options) as landmarker, av.open(path) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        for start, end in windows:
            if start > 0:
                container.seek(int(start * 1_000_000), backward=True)
            for frame in container.decode(stream):
                if frame.pts is None:
                    continue
                t = float(frame.pts * stream.time_base)
                if t < start:
                    continue
                if t > end:
                    break

                w = min(ANALYSIS_WIDTH, frame.width)
                h = max(2, int(round(frame.height * w / frame.width / 2)) * 2)
                rgb = np.ascontiguousarray(frame.to_ndarray(format="rgb24", width=w, height=h))

                result = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))

                lip = jaw = np.nan
                best_h = 0.0
                for i, lm in enumerate(result.face_landmarks or []):

                    def pt(k):
                        return (lm[k].x * w, lm[k].y * h)

                    # the largest (closest) face is most likely the speaker
                    face_h = math.dist(pt(_FOREHEAD), pt(_CHIN))
                    if face_h <= best_h:
                        continue
                    best_h = face_h
                    lip = math.dist(pt(_UPPER_INNER_LIP), pt(_LOWER_INNER_LIP)) / face_h
                    jaw = np.nan
                    if result.face_blendshapes and i < len(result.face_blendshapes):
                        for cat in result.face_blendshapes[i]:
                            if cat.category_name == "jawOpen":
                                jaw = cat.score
                                break

                times.append(t)
                lips.append(lip)
                jaws.append(jaw)

                if on_progress:
                    fraction = min((done + t - start) / total, 1.0)
                    if fraction - last_reported >= 0.02:
                        on_progress(fraction)
                        last_reported = fraction
            done += end - start

    return np.asarray(times), np.asarray(lips, dtype=np.float64), np.asarray(jaws, dtype=np.float64)


def _speech_energy(samples, start_time):
    """Speech-band amplitude envelope of mono 16 kHz samples, at GRID_HZ.

    Kept linear on purpose: a dB scale jumps the instant a sound starts while
    mouth opening grows gradually, which biased the match ~15 ms early."""
    hop = AUDIO_RATE // GRID_HZ
    n_fft = 512
    if samples.size < n_fft:
        return np.zeros(0), np.zeros(0)
    frames = np.lib.stride_tricks.sliding_window_view(samples, n_fft)[::hop]
    spectrum = np.abs(np.fft.rfft(frames * np.hanning(n_fft), axis=1)) ** 2
    freqs = np.fft.rfftfreq(n_fft, 1.0 / AUDIO_RATE)
    band = (freqs >= SPEECH_BAND[0]) & (freqs <= SPEECH_BAND[1])
    energy = np.sqrt(spectrum[:, band].sum(axis=1))
    times = start_time + (np.arange(energy.size) * hop + n_fft / 2) / AUDIO_RATE
    return times, energy


def _audio_track(path, start, end):
    """Speech-band amplitude between start and end: (times, envelope) at GRID_HZ."""
    import av

    chunks = []
    first_time = None
    with av.open(path) as container:
        if not container.streams.audio:
            raise ValueError("這部影片沒有音軌，無法比對音畫同步")
        stream = container.streams.audio[0]
        if start > 0:
            container.seek(int(start * 1_000_000), backward=True)
        resampler = av.AudioResampler(format="flt", layout="mono", rate=AUDIO_RATE)
        total = 0
        for frame in container.decode(stream):
            if frame.pts is None:
                continue
            frame_time = float(frame.pts * stream.time_base)
            if first_time is None:
                first_time = frame_time
            frame.pts = None
            for out in resampler.resample(frame):
                arr = out.to_ndarray().reshape(-1)
                chunks.append(arr)
                total += arr.size
            if first_time + total / AUDIO_RATE > end + 1.0:
                break

    if not chunks:
        raise ValueError("無法讀取音軌內容")

    samples = np.concatenate(chunks).astype(np.float64)
    skip = max(0, int((start - first_time) * AUDIO_RATE))
    samples = samples[skip:]
    return _speech_energy(samples, first_time + skip / AUDIO_RATE)


def _moving_average(x, n):
    if n <= 1:
        return x
    return np.convolve(x, np.ones(n) / n, mode="same")


def _normalize(x):
    # keep short-term movement (syllables), drop slow drift, smooth jitter, unit variance
    x = x - _moving_average(x, GRID_HZ)
    x = _moving_average(x, max(1, GRID_HZ // 25))
    sd = x.std()
    return x / sd if sd > 0 else x


def _onsets(x):
    # rising edges: mouth starting to open / sound starting
    d = np.diff(x, prepend=x[:1])
    return _moving_average(np.maximum(d, 0), max(1, GRID_HZ // 25))


def _masked_corr(m, a, mask, lag, n, min_overlap):
    if lag >= 0:
        m, a, mk = m[: n - lag], a[lag:], mask[: n - lag]
    else:
        m, a, mk = m[-lag:], a[: n + lag], mask[-lag:]
    m, a = m[mk], a[mk]
    if m.size < min_overlap:
        return np.nan
    m = m - m.mean()
    a = a - a.mean()
    denom = math.sqrt(float((m * m).sum() * (a * a).sum()))
    return float((m * a).sum()) / denom if denom > 0 else np.nan


def correlation_curve(mouth_t, mouth_features, audio_t, audio_v, max_offset=AVSYNC_MAX_OFFSET):
    """Correlation between mouth movement and audio for each lag.

    mouth_features: 1-D array, or list of 1-D arrays (e.g. lip ratio, jaw
    score) sampled at mouth_t, NaN where no face. Returns (lag_steps, corr,
    valid_samples); lag > 0 means the audio is late.
    """
    if isinstance(mouth_features, np.ndarray) and mouth_features.ndim == 1:
        mouth_features = [mouth_features]

    valid = np.zeros(mouth_t.size, dtype=bool)
    for f in mouth_features:
        valid |= ~np.isnan(f)
    if valid.sum() < 2 or audio_t.size < 2:
        return None

    t0 = max(mouth_t[0], audio_t[0])
    t1 = min(mouth_t[-1], audio_t[-1])
    grid = np.arange(t0, t1, 1.0 / GRID_HZ)
    if grid.size < 2:
        return None

    # a grid point counts only if the video frame nearest to it had a face
    idx = np.clip(np.searchsorted(mouth_t, grid), 1, len(mouth_t) - 1)
    nearest = np.where(grid - mouth_t[idx - 1] <= mouth_t[idx] - grid, idx - 1, idx)
    mask = valid[nearest]
    if mask.sum() < MIN_FACE_SECONDS * GRID_HZ:
        return None

    level = np.zeros(grid.size)
    for f in mouth_features:
        ok = ~np.isnan(f)
        if ok.sum() >= 2:
            level += _normalize(np.interp(grid, mouth_t[ok], f[ok]))
    mouth_level = _normalize(level)
    mouth_onset = _onsets(mouth_level)
    audio_level = _normalize(np.interp(grid, audio_t, audio_v))
    audio_onset = _onsets(audio_level)

    n = grid.size
    max_lag = min(int(max_offset * GRID_HZ), n // 4)
    lags = np.arange(-max_lag, max_lag + 1)
    min_overlap = int(MIN_FACE_SECONDS * GRID_HZ)
    corr = np.full(lags.size, np.nan)
    for i, lag in enumerate(lags):
        c_level = _masked_corr(mouth_level, audio_level, mask, lag, n, min_overlap)
        c_onset = _masked_corr(mouth_onset, audio_onset, mask, lag, n, min_overlap)
        if not (np.isnan(c_level) or np.isnan(c_onset)):
            corr[i] = 0.5 * (c_level + c_onset)
    if np.all(np.isnan(corr)):
        return None
    return lags, corr, int(mask.sum())


def pick_peak(lags, corr):
    """Returns (lag_seconds, confidence, z_score) from a correlation curve."""
    best = int(np.nanargmax(corr))
    peak = corr[best]
    lag = float(lags[best])
    # parabolic interpolation for sub-step precision
    if 0 < best < lags.size - 1 and not np.isnan(corr[best - 1]) and not np.isnan(corr[best + 1]):
        y0, y1, y2 = corr[best - 1], peak, corr[best + 1]
        denom = y0 - 2 * y1 + y2
        if denom != 0:
            lag += 0.5 * (y0 - y2) / denom

    spread = np.nanstd(corr)
    z = float((peak - np.nanmean(corr)) / spread) if spread > 0 else 0.0
    at_edge = best in (0, lags.size - 1)
    if at_edge or z < 2.5:
        confidence = "low"
    elif peak >= 0.2 and z >= 4:
        confidence = "high"
    else:
        confidence = "medium"
    return lag / GRID_HZ, confidence, z


def estimate_offset(mouth_t, mouth_features, audio_t, audio_v, max_offset=AVSYNC_MAX_OFFSET):
    """Returns (lag_seconds, confidence) for a single stretch of video.
    lag > 0 means the audio is late (sound comes after the mouth moves)."""
    curve = correlation_curve(mouth_t, mouth_features, audio_t, audio_v, max_offset)
    if curve is None:
        raise ValueError("畫面中找不到足夠清楚的人臉，無法用嘴型比對（請確認影片中有人正面說話）")
    lags, corr, _ = curve
    lag, confidence, _ = pick_peak(lags, corr)
    return lag, confidence


MIN_RANGE_SECONDS = 5.0


def analyze_file(path, on_progress=None, start=None, end=None):
    """Returns (suggested av_offset in seconds, confidence, per-window details).
    start/end (seconds) limit the analysis to that part of the video."""
    _ensure_face_model()
    duration = get_media_duration(path)
    range_start = max(0.0, start or 0.0)
    range_end = min(duration, end) if end and duration else (end or duration)
    if range_end - range_start < MIN_RANGE_SECONDS:
        raise ValueError(f"檢測範圍至少要 {MIN_RANGE_SECONDS:.0f} 秒")
    windows = [(range_start + a, range_start + b) for a, b in plan_windows(range_end - range_start)]

    def face_progress(fraction):
        if on_progress:
            on_progress(0.9 * fraction)

    mouth_t, lips, jaws = _mouth_tracks(path, windows, on_progress=face_progress)

    combined = None
    weight_total = 0.0
    details = []
    for start, end in windows:
        sel = (mouth_t >= start) & (mouth_t <= end)
        if sel.sum() < 2:
            continue
        audio_t, audio_v = _audio_track(path, start, end)
        curve = correlation_curve(mouth_t[sel], [lips[sel], jaws[sel]], audio_t, audio_v)
        if curve is None:
            continue
        lags, corr, n_valid = curve
        lag, confidence, z = pick_peak(lags, corr)
        details.append(
            {"start": round(float(start), 2), "end": round(float(end), 2), "offset": round(float(-lag), 3),
             "confidence": confidence}
        )
        # combine curves (aligned on lag) weighted by how much face time each window had
        weight = math.sqrt(n_valid)
        filled = np.nan_to_num(corr, nan=0.0) * weight
        if combined is None:
            combined_lags, combined = lags, filled
        else:
            size = min(combined.size, filled.size)
            mid_c, mid_f = combined.size // 2, filled.size // 2
            half = size // 2
            combined = combined[mid_c - half : mid_c + half + 1] + filled[mid_f - half : mid_f + half + 1]
            combined_lags = combined_lags[mid_c - half : mid_c + half + 1]
        weight_total += weight

    if on_progress:
        on_progress(0.97)
    if combined is None:
        raise ValueError("畫面中找不到足夠清楚的人臉，無法用嘴型比對（請確認影片中有人正面說話）")

    lag, confidence, _ = pick_peak(combined_lags, combined / weight_total)

    reliable = [d["offset"] for d in details if d["confidence"] != "low"]
    drift = bool(len(reliable) >= 3 and (max(reliable) - min(reliable)) > DRIFT_WARN_SECONDS)
    if drift and confidence == "high":
        confidence = "medium"

    # audio late by `lag` -> play it `lag` seconds earlier
    return round(-lag, 3), confidence, {"windows": details, "drift": drift}


def run_sync_analysis(video_id: str, start=None, end=None):
    db = SessionLocal()
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            return
        video.sync_status = "analyzing"
        video.sync_error = None
        video.sync_progress = 0.0
        db.commit()

        def on_progress(fraction):
            video.sync_progress = round(fraction, 3)
            db.commit()

        offset, confidence, details = analyze_file(
            os.path.join(MEDIA_DIR, video.filename), on_progress=on_progress, start=start, end=end
        )
        if start is not None or end is not None:
            details["range"] = [start or 0.0, end]

        video.sync_detected_offset = offset
        video.sync_confidence = confidence
        video.sync_windows = json.dumps(details)
        video.sync_status = "ready"
        video.sync_progress = 1.0
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        video = db.query(Video).filter(Video.id == video_id).first()
        if video:
            video.sync_status = "error"
            video.sync_error = str(exc)
            db.commit()
    finally:
        db.close()


def start_sync_analysis_background(video_id: str, start=None, end=None):
    thread = threading.Thread(target=run_sync_analysis, args=(video_id, start, end), daemon=True)
    thread.start()


def encode_shifted_audio(in_container, in_audio, out_container, out_stream, shift):
    """Re-encode in_audio into out_stream, delayed by `shift` seconds
    (negative = earlier: the first -shift seconds of audio are dropped)."""
    import av

    ctx = out_stream.codec_context
    rate = ctx.sample_rate
    layout = ctx.layout.name
    fmt = ctx.format.name
    frame_size = ctx.frame_size or 1024
    channels = len(ctx.layout.channels)

    resampler = av.AudioResampler(format=fmt, layout=layout, rate=rate)
    fifo = av.AudioFifo()
    written = 0

    def push(arr):
        frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(arr, dtype=np.float32), format=fmt, layout=layout)
        frame.sample_rate = rate
        fifo.write(frame)

    def drain(final=False):
        nonlocal written
        while fifo.samples >= frame_size or (final and fifo.samples > 0):
            frame = fifo.read(min(frame_size, fifo.samples))
            frame.pts = written
            frame.time_base = Fraction(1, rate)
            written += frame.samples
            for packet in out_stream.encode(frame):
                out_container.mux(packet)

    skip = int(round(-shift * rate)) if shift < 0 else 0
    if shift > 0:
        pad = int(round(shift * rate))
        while pad > 0:
            n = min(pad, rate)
            push(np.zeros((channels, n), dtype=np.float32))
            pad -= n
        drain()

    def feed(frames):
        nonlocal skip
        for out in frames:
            arr = out.to_ndarray()
            if skip > 0:
                cut = min(skip, arr.shape[1])
                arr = arr[:, cut:]
                skip -= cut
            if arr.shape[1]:
                push(arr)
        drain()

    for frame in in_container.decode(in_audio):
        frame.pts = None  # resampler only needs the samples
        feed(resampler.resample(frame))
    feed(resampler.resample(None))
    drain(final=True)

    for packet in out_stream.encode(None):
        out_container.mux(packet)
