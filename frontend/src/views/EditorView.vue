<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from "vue";
import { useRouter } from "vue-router";
import api from "../api/client";
import { formatTime } from "../utils/time";
import SubtitleTimeline from "../components/SubtitleTimeline.vue";
import SubtitleList from "../components/SubtitleList.vue";
import StylePanel from "../components/StylePanel.vue";
import SyncPanel from "../components/SyncPanel.vue";
import EnhancePanel from "../components/EnhancePanel.vue";
import PlayerControls from "../components/PlayerControls.vue";

const props = defineProps({ id: { type: String, required: true } });
const router = useRouter();

const video = ref(null);
const subtitles = ref([]);
const activeId = ref(null);
const dirty = ref(false);
const saving = ref(false);
const saveMsg = ref("");
const videoEl = ref(null);
const currentTime = ref(0);
const playing = ref(false);
const pxPerSecond = ref(70);
const showStylePanel = ref(false);
const showSyncPanel = ref(false);
const syncPreview = ref(false);
const audioEl = ref(null);
let styleSaveTimer = null;
let syncSaveTimer = null;
let syncAudioTimer = null;
const showEnhancePanel = ref(false);
const comparing = ref(false);
let enhanceSaveTimer = null;
let pendingEnhancePatch = {};
const playerWrap = ref(null);
const isFullscreen = ref(false);
const osdText = ref("");
let osdTimer = null;
const awaitingAutoDownload = ref(false);

let pollTimer = null;

function triggerDownload(url) {
  const a = document.createElement("a");
  a.href = url;
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

async function loadVideo() {
  const { data } = await api.get(`/videos/${props.id}`);
  const prevRenderStatus = video.value?.render_status;
  video.value = data;
  if (!dirty.value) {
    subtitles.value = data.subtitles.map((s) => ({ ...s }));
  }
  const busy =
    data.status === "transcribing" || data.render_status === "rendering" || data.sync_status === "analyzing";
  if (busy && !pollTimer) {
    pollTimer = setInterval(loadVideo, 2500);
  }
  if (!busy && pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }

  if (awaitingAutoDownload.value && prevRenderStatus === "rendering" && data.render_status === "ready") {
    awaitingAutoDownload.value = false;
    triggerDownload(`/api/videos/${props.id}/render/download`);
    await api.post(`/videos/${props.id}/render/ack`);
    await loadVideo();
  } else if (awaitingAutoDownload.value && data.render_status === "error") {
    awaitingAutoDownload.value = false;
  }
}

// while previewing a sync offset, subtitles follow the shifted audio (unless turned off)
const subtitleTime = computed(() =>
  syncPreview.value && video.value?.sync_follow_subtitles !== false
    ? currentTime.value - (video.value?.av_offset || 0)
    : currentTime.value
);

const enhanceValues = computed(() => {
  const v = video.value || {};
  return {
    brightness: v.enh_brightness ?? 1,
    contrast: v.enh_contrast ?? 1,
    saturation: v.enh_saturation ?? 1,
    sharpness: v.enh_sharpness ?? 0,
    denoise: v.enh_denoise ?? 0,
    targetHeight: v.enh_target_height ?? 0,
    upscaleMethod: v.enh_upscale_method ?? "lanczos",
    srModel: v.enh_sr_model ?? "fast",
    srDetail: v.enh_sr_detail ?? 0.5,
  };
});

const enhanceActive = computed(() => {
  const e = enhanceValues.value;
  return (
    e.brightness !== 1 ||
    e.contrast !== 1 ||
    e.saturation !== 1 ||
    e.sharpness > 0 ||
    e.denoise > 0 ||
    e.targetHeight > 0
  );
});

const sourceSize = ref({ w: 0, h: 0 });
function onLoadedMetadata() {
  if (videoEl.value) sourceSize.value = { w: videoEl.value.videoWidth, h: videoEl.value.videoHeight };
}

// live preview of the export filters (denoise / upscale are export-only)
const videoFilterStyle = computed(() => {
  const e = enhanceValues.value;
  if (comparing.value) return {};
  const parts = [];
  if (e.brightness !== 1) parts.push(`brightness(${e.brightness})`);
  if (e.contrast !== 1) parts.push(`contrast(${e.contrast})`);
  if (e.saturation !== 1) parts.push(`saturate(${e.saturation})`);
  if (e.sharpness > 0) parts.push("url(#cc-sharpen)");
  return parts.length ? { filter: parts.join(" ") } : {};
});

// 3x3 sharpen kernel matching the unsharp amount roughly
const sharpenKernel = computed(() => {
  const a = enhanceValues.value.sharpness * 0.5;
  return `0 ${-a} 0 ${-a} ${1 + 4 * a} ${-a} 0 ${-a} 0`;
});

const activeSubtitle = computed(() =>
  subtitles.value.find((s) => subtitleTime.value >= s.start && subtitleTime.value <= s.end)
);

const renderPercent = computed(() => Math.round((video.value?.render_progress ?? 0) * 100));

const captionStyle = computed(() => {
  if (!video.value) return {};
  const pos = video.value.style_position;
  const base = {
    fontSize: `${video.value.style_font_size}px`,
    color: video.value.style_color,
    backgroundColor: `rgba(0, 0, 0, ${video.value.style_bg_opacity})`,
  };
  if (pos === "top") {
    return { ...base, top: "20px", bottom: "auto", transform: "translateX(-50%)" };
  }
  if (pos === "middle") {
    return { ...base, top: "50%", bottom: "auto", transform: "translate(-50%, -50%)" };
  }
  return { ...base, bottom: "72px", top: "auto", transform: "translateX(-50%)" };
});

let pendingStylePatch = {};

async function updateStyle(patch) {
  Object.assign(video.value, {
    style_font_size: patch.font_size ?? video.value.style_font_size,
    style_position: patch.position ?? video.value.style_position,
    style_color: patch.color ?? video.value.style_color,
    style_bg_opacity: patch.bg_opacity ?? video.value.style_bg_opacity,
  });
  if (video.value.render_status === "ready" || video.value.render_status === "error") {
    video.value.render_status = "idle";
    video.value.render_error = null;
  }
  Object.assign(pendingStylePatch, patch);
  clearTimeout(styleSaveTimer);
  styleSaveTimer = setTimeout(async () => {
    const toSend = pendingStylePatch;
    pendingStylePatch = {};
    await api.patch(`/videos/${props.id}/style`, toSend);
  }, 300);
}

async function analyzeSync(range) {
  await api.post(`/videos/${props.id}/sync/analyze`, range || undefined);
  await loadVideo();
}

function updateOffset(value) {
  video.value.av_offset = Math.round(value * 1000) / 1000;
  if (video.value.render_status === "ready" || video.value.render_status === "error") {
    video.value.render_status = "idle";
    video.value.render_error = null;
  }
  syncPreviewAudio();
  clearTimeout(syncSaveTimer);
  syncSaveTimer = setTimeout(() => {
    api.patch(`/videos/${props.id}/sync`, { av_offset: video.value.av_offset });
  }, 300);
}

function setFollowSubtitles(on) {
  video.value.sync_follow_subtitles = on;
  if (video.value.render_status === "ready" || video.value.render_status === "error") {
    video.value.render_status = "idle";
    video.value.render_error = null;
  }
  api.patch(`/videos/${props.id}/sync`, { follow_subtitles: on });
}

function shiftAllSubtitles(delta) {
  subtitles.value.forEach((s) => {
    const len = s.end - s.start;
    s.start = Math.max(0, Math.round((s.start + delta) * 1000) / 1000);
    s.end = s.start + len;
  });
  markDirty();
  showOsd(`字幕整體${delta > 0 ? "延後" : "提前"} ${Math.abs(delta)} 秒（記得儲存）`);
}

function updateEnhance(patch) {
  for (const [k, v] of Object.entries(patch)) video.value[`enh_${k}`] = v;
  if (video.value.render_status === "ready" || video.value.render_status === "error") {
    video.value.render_status = "idle";
    video.value.render_error = null;
  }
  Object.assign(pendingEnhancePatch, patch);
  clearTimeout(enhanceSaveTimer);
  enhanceSaveTimer = setTimeout(async () => {
    const toSend = pendingEnhancePatch;
    pendingEnhancePatch = {};
    await api.patch(`/videos/${props.id}/enhance`, toSend);
  }, 300);
}

// Preview: mute the <video> and play the same file through a hidden <audio>
// element running `av_offset` seconds behind (or ahead of) the picture.
// Small drift is corrected by nudging the playback rate (inaudible) instead of
// seeking, which would click and re-buffer.
function syncPreviewAudio() {
  const v = videoEl.value;
  const a = audioEl.value;
  if (!v || !a) return;
  if (!syncPreview.value) {
    if (!a.paused) a.pause();
    return;
  }
  // the player's own volume / mute controls drive the preview track too
  a.volume = v.volume;
  a.muted = v.muted;
  const target = v.currentTime - (video.value?.av_offset || 0);
  if (target < 0 || (a.duration && target > a.duration)) {
    if (!a.paused) a.pause();
    return;
  }
  const drift = a.currentTime - target;
  // hard-seek when stopped, when (re)starting, or when far off
  if (v.paused || a.paused || Math.abs(drift) > 0.15) {
    if (Math.abs(drift) > 0.01) a.currentTime = target;
    a.playbackRate = v.playbackRate;
  } else {
    // proportional correction (up to ±6% speed), with a ±10 ms dead band so it
    // doesn't keep hunting around zero
    const correction = Math.abs(drift) < 0.01 ? 0 : Math.max(-0.06, Math.min(0.06, drift * 1.2));
    a.playbackRate = v.playbackRate * (1 - correction);
  }
  if (v.paused) {
    if (!a.paused) a.pause();
  } else if (a.paused) {
    a.play().catch(() => {});
  }
}

function showOsd(text) {
  osdText.value = text;
  clearTimeout(osdTimer);
  osdTimer = setTimeout(() => (osdText.value = ""), 900);
}

function skip(seconds) {
  const v = videoEl.value;
  if (!v) return;
  const max = v.duration || video.value?.duration || 0;
  seekTo(Math.max(0, Math.min(max, v.currentTime + seconds)));
  showOsd(seconds > 0 ? `快轉 ${seconds} 秒` : `倒退 ${-seconds} 秒`);
}

function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen();
  else playerWrap.value?.requestFullscreen?.();
}

function onFullscreenChange() {
  isFullscreen.value = document.fullscreenElement === playerWrap.value;
}

function toggleCompare() {
  comparing.value = !comparing.value;
  showOsd(comparing.value ? "顯示原始畫面" : "顯示增強畫面");
}

function onKeydown(e) {
  const el = e.target;
  const tag = el?.tagName;
  // don't steal keys while typing (subtitle text, time inputs, sliders…)
  if (el?.isContentEditable || tag === "TEXTAREA" || tag === "SELECT") return;
  if (tag === "INPUT" && !["checkbox", "button"].includes(el.type)) return;
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const v = videoEl.value;
  if (!v) return;

  switch (e.key) {
    case " ":
    case "k":
    case "K":
      togglePlay();
      break;
    case "ArrowLeft":
    case "j":
    case "J":
      skip(e.shiftKey ? -1 : -5);
      break;
    case "ArrowRight":
    case "l":
    case "L":
      skip(e.shiftKey ? 1 : 5);
      break;
    case "ArrowUp":
      v.volume = Math.min(1, Math.round((v.volume + 0.1) * 10) / 10);
      v.muted = false;
      showOsd(`音量 ${Math.round(v.volume * 100)}%`);
      break;
    case "ArrowDown":
      v.volume = Math.max(0, Math.round((v.volume - 0.1) * 10) / 10);
      showOsd(`音量 ${Math.round(v.volume * 100)}%`);
      break;
    case ",":
      v.pause();
      seekTo(Math.max(0, v.currentTime - 1 / 30));
      break;
    case ".":
      v.pause();
      seekTo(v.currentTime + 1 / 30);
      break;
    case "m":
    case "M":
      v.muted = !v.muted;
      showOsd(v.muted ? "靜音" : "取消靜音");
      break;
    case "f":
    case "F":
      toggleFullscreen();
      break;
    case "c":
    case "C":
      if (enhanceActive.value) toggleCompare();
      break;
    default:
      return;
  }
  e.preventDefault();
}

// The <video>'s own sound is silenced through Web Audio (gain 0) rather than
// `muted`, so the player's mute / volume controls stay usable during preview
// without bringing the original, unshifted track back alongside the preview one.
let audioCtx = null;
let videoGain = null;

function setVideoSoundEnabled(enabled) {
  const v = videoEl.value;
  if (!v) return;
  if (!audioCtx) {
    if (enabled) return; // never routed: the video plays its sound normally
    audioCtx = new AudioContext();
    videoGain = audioCtx.createGain();
    audioCtx.createMediaElementSource(v).connect(videoGain).connect(audioCtx.destination);
  }
  audioCtx.resume();
  videoGain.gain.value = enabled ? 1 : 0;
}

function onVideoPlay() {
  playing.value = true;
  // once the video's sound goes through Web Audio, a suspended context would mute it
  audioCtx?.resume();
  syncPreviewAudio();
}

function stopPreviewAudio() {
  const a = audioEl.value;
  if (a) {
    a.pause();
    a.removeAttribute("src");
    a.load(); // drop the stream so a detached element can't keep playing
  }
}

function setSyncPreview(on) {
  syncPreview.value = on;
  setVideoSoundEnabled(!on);
  clearInterval(syncAudioTimer);
  syncAudioTimer = on ? setInterval(syncPreviewAudio, 100) : null;
  if (on) syncPreviewAudio();
  else stopPreviewAudio();
}

watch(activeSubtitle, (s) => {
  if (s) activeId.value = s.id;
});

function markDirty() {
  dirty.value = true;
  saveMsg.value = "";
}

function onTimeUpdate() {
  if (videoEl.value) currentTime.value = videoEl.value.currentTime;
}

function seekTo(t) {
  if (videoEl.value) {
    videoEl.value.currentTime = t;
    currentTime.value = t;
  }
}

function selectSub(id) {
  activeId.value = id;
  const sub = subtitles.value.find((s) => s.id === id);
  if (sub) seekTo(sub.start);
}

function updateSub({ id, start, end, text }) {
  const sub = subtitles.value.find((s) => s.id === id);
  if (!sub) return;
  if (start !== undefined) sub.start = start;
  if (end !== undefined) sub.end = end;
  if (text !== undefined) sub.text = text;
  markDirty();
}

function deleteSub(id) {
  subtitles.value = subtitles.value.filter((s) => s.id !== id);
  markDirty();
}

function splitSub(id) {
  const idx = subtitles.value.findIndex((s) => s.id === id);
  if (idx === -1) return;
  const sub = subtitles.value[idx];
  const mid = (sub.start + sub.end) / 2;
  const words = sub.text.trim().split(/\s+/);
  let firstText = sub.text;
  let secondText = "";
  if (words.length > 1) {
    const half = Math.ceil(words.length / 2);
    firstText = words.slice(0, half).join(" ");
    secondText = words.slice(half).join(" ");
  }
  const newSub = {
    id: `new-${Date.now()}`,
    start: mid,
    end: sub.end,
    text: secondText,
    order_index: sub.order_index + 0.5,
  };
  sub.end = mid;
  sub.text = firstText;
  subtitles.value.splice(idx + 1, 0, newSub);
  reindex();
  markDirty();
}

function addSubtitle() {
  const t = currentTime.value || 0;
  const newSub = {
    id: `new-${Date.now()}`,
    start: t,
    end: t + 2,
    text: "",
    order_index: subtitles.value.length,
  };
  subtitles.value.push(newSub);
  subtitles.value.sort((a, b) => a.start - b.start);
  reindex();
  activeId.value = newSub.id;
  markDirty();
}

function reindex() {
  subtitles.value.sort((a, b) => a.start - b.start);
  subtitles.value.forEach((s, i) => (s.order_index = i));
}

async function saveAll() {
  saving.value = true;
  try {
    reindex();
    const payload = {
      subtitles: subtitles.value.map((s) => ({
        id: s.id.startsWith("new-") ? cryptoRandomId() : s.id,
        start: s.start,
        end: s.end,
        text: s.text,
        order_index: s.order_index,
      })),
    };
    const { data } = await api.put(`/videos/${props.id}/subtitles`, payload);
    subtitles.value = data.map((s) => ({ ...s }));
    dirty.value = false;
    if (video.value && (video.value.render_status === "ready" || video.value.render_status === "error")) {
      video.value.render_status = "idle";
      video.value.render_error = null;
    }
    saveMsg.value = "已儲存";
    setTimeout(() => (saveMsg.value = ""), 2000);
  } finally {
    saving.value = false;
  }
}

function cryptoRandomId() {
  return "id-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

async function runTranscribe() {
  if (dirty.value && !confirm("重新產生字幕會覆蓋目前未儲存的編輯內容，確定要繼續嗎？")) return;
  await api.post(`/videos/${props.id}/transcribe`);
  dirty.value = false;
  await loadVideo();
}

function downloadExport(fmt) {
  triggerDownload(`/api/videos/${props.id}/export?fmt=${fmt}`);
}

async function renderVideo() {
  if (dirty.value) {
    await saveAll();
  }
  awaitingAutoDownload.value = true;
  await api.post(`/videos/${props.id}/render`);
  await loadVideo();
}

async function downloadRendered() {
  triggerDownload(`/api/videos/${props.id}/render/download`);
  await api.post(`/videos/${props.id}/render/ack`);
  await loadVideo();
}

function togglePlay() {
  if (!videoEl.value) return;
  if (videoEl.value.paused) videoEl.value.play();
  else videoEl.value.pause();
}

function zoomIn() {
  pxPerSecond.value = Math.min(pxPerSecond.value + 20, 300);
}
function zoomOut() {
  pxPerSecond.value = Math.max(pxPerSecond.value - 20, 20);
}

onMounted(() => {
  loadVideo();
  window.addEventListener("keydown", onKeydown);
  document.addEventListener("fullscreenchange", onFullscreenChange);
});
onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer);
  clearInterval(syncAudioTimer);
  stopPreviewAudio();
  audioCtx?.close();
  clearTimeout(osdTimer);
  window.removeEventListener("keydown", onKeydown);
  document.removeEventListener("fullscreenchange", onFullscreenChange);
});
</script>

<template>
  <div class="editor" v-if="video">
    <div class="editor-top">
      <button class="btn btn-ghost" @click="router.push({ name: 'library' })">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M15 18l-6-6 6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        返回
      </button>
      <div class="title" :title="video.original_name">{{ video.original_name }}</div>
      <span class="tag" :class="`tag-${video.status}`"><span class="tag-dot"></span>
        {{ video.status === 'transcribing' ? '字幕產生中' : video.status === 'ready' ? '已完成' : video.status === 'error' ? '發生錯誤' : '尚未產生字幕' }}
      </span>
      <div class="spacer"></div>
      <span v-if="saveMsg" class="save-msg">{{ saveMsg }}</span>
      <button class="btn" :disabled="video.status === 'transcribing'" @click="runTranscribe">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M12 3a9 9 0 100 18 9 9 0 000-18zM12 7v5l3 3" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        AI 重新辨識
      </button>
      <button
        class="btn"
        :class="{ 'btn-active': showStylePanel }"
        @click="showStylePanel = !showStylePanel"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M4 6h16M4 12h10M4 18h6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
        字幕樣式
      </button>
      <button
        class="btn"
        :class="{ 'btn-active': showSyncPanel }"
        @click="showSyncPanel = !showSyncPanel"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M3 12h4l3-8 4 16 3-8h4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        音畫同步
      </button>
      <button
        class="btn"
        :class="{ 'btn-active': showEnhancePanel }"
        @click="showEnhancePanel = !showEnhancePanel"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M12 3v2M12 19v2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M3 12h2M19 12h2M5.6 18.4L7 17M17 7l1.4-1.4M12 8a4 4 0 100 8 4 4 0 000-8z" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
        畫質增強
      </button>
      <button class="btn" @click="downloadExport('srt')">匯出 SRT</button>
      <button class="btn" @click="downloadExport('vtt')">匯出 VTT</button>
      <button
        v-if="video.render_status === 'ready'"
        class="btn"
        @click="downloadRendered"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M12 3v12m0 0l-4-4m4 4l4-4M4 21h16" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        下載匯出影片
      </button>
      <button
        v-else
        class="btn"
        :disabled="video.render_status === 'rendering' || (!subtitles.length && !video.av_offset && !enhanceActive)"
        @click="renderVideo"
        title="匯出完整 MP4：燒錄字幕、套用音畫同步與畫質增強，完成後會自動下載"
      >
        <span v-if="video.render_status === 'rendering'" class="btn-spinner"></span>
        {{
          video.render_status === "rendering"
            ? `匯出影片中… ${renderPercent}%`
            : subtitles.length
              ? "匯出含字幕影片"
              : "匯出影片"
        }}
      </button>
      <button class="btn btn-primary" :disabled="!dirty || saving" @click="saveAll">
        {{ saving ? "儲存中…" : dirty ? "儲存變更" : "已儲存" }}
      </button>
    </div>
    <div v-if="video.render_status === 'rendering'" class="render-progress-bar">
      <div class="render-progress-fill" :style="{ width: renderPercent + '%' }"></div>
    </div>
    <div v-if="video.render_status === 'error'" class="error-banner">
      影片匯出失敗：{{ video.render_error }}
    </div>
    <div v-if="video.render_note" class="note-banner">{{ video.render_note }}</div>

    <div v-if="video.status === 'error'" class="error-banner">
      辨識失敗：{{ video.error_message }}
    </div>

    <div class="editor-body">
      <div class="player-col">
        <div ref="playerWrap" class="player-wrap card" :class="{ 'is-fullscreen': isFullscreen, 'is-paused': !playing }">
          <svg class="filter-defs" aria-hidden="true">
            <filter id="cc-sharpen" color-interpolation-filters="sRGB">
              <feConvolveMatrix order="3" :kernelMatrix="sharpenKernel" preserveAlpha="true" />
            </filter>
          </svg>
          <video
            ref="videoEl"
            :src="`/api/videos/${video.id}/stream`"
            :style="videoFilterStyle"
            @timeupdate="onTimeUpdate"
            @loadedmetadata="onLoadedMetadata"
            @play="onVideoPlay"
            @pause="playing = false; syncPreviewAudio()"
            @seeked="syncPreviewAudio"
            @ratechange="syncPreviewAudio"
            @volumechange="syncPreviewAudio"
            @click="togglePlay"
            @dblclick="toggleFullscreen"
          ></video>
          <audio v-if="syncPreview" ref="audioEl" :src="`/api/videos/${video.id}/stream`" preload="auto"></audio>
          <div v-if="activeSubtitle" class="caption-overlay" :style="captionStyle">{{ activeSubtitle.text }}</div>
          <div v-if="osdText" class="osd">{{ osdText }}</div>
          <PlayerControls
            :video-el="videoEl"
            :current-time="currentTime"
            :duration="video.duration"
            :playing="playing"
            :fullscreen="isFullscreen"
            :show-compare="enhanceActive"
            :comparing="comparing"
            @toggle-play="togglePlay"
            @skip="skip"
            @seek="seekTo"
            @fullscreen="toggleFullscreen"
            @compare="toggleCompare"
          />
          <div v-if="video.status === 'transcribing'" class="transcribing-overlay">
            <div class="spinner"></div>
            <div>AI 正在辨識語音並產生字幕…</div>
          </div>
        </div>

        <StylePanel
          v-if="showStylePanel"
          :font-size="video.style_font_size"
          :position="video.style_position"
          :color="video.style_color"
          :bg-opacity="video.style_bg_opacity"
          @update="updateStyle"
        />

        <SyncPanel
          v-if="showSyncPanel"
          :offset="video.av_offset || 0"
          :status="video.sync_status"
          :progress="video.sync_progress"
          :error="video.sync_error"
          :detected-offset="video.sync_detected_offset"
          :confidence="video.sync_confidence"
          :windows="video.sync_windows"
          :current-time="currentTime"
          :duration="video.duration"
          :follow-subtitles="video.sync_follow_subtitles !== false"
          :preview="syncPreview"
          @analyze="analyzeSync"
          @update="updateOffset"
          @preview="setSyncPreview"
          @follow="setFollowSubtitles"
          @shift-subtitles="shiftAllSubtitles"
        />

        <EnhancePanel
          v-if="showEnhancePanel"
          v-bind="enhanceValues"
          :source-width="sourceSize.w"
          :source-height="sourceSize.h"
          :duration="video.duration"
          :video-id="video.id"
          :current-time="currentTime"
          @update="updateEnhance"
        />

        <div class="shortcut-hint">
          快捷鍵：空白鍵 播放/暫停 · ← → 倒退/快轉 5 秒（Shift 為 1 秒） · , . 逐幀 · ↑ ↓ 音量 · M 靜音 · F 全螢幕
        </div>

        <div class="timeline-toolbar">
          <span class="time-label">{{ formatTime(currentTime) }} / {{ formatTime(video.duration) }}</span>
          <div class="spacer"></div>
          <button class="btn btn-icon" @click="zoomOut" title="縮小">−</button>
          <button class="btn btn-icon" @click="zoomIn" title="放大">+</button>
        </div>
        <SubtitleTimeline
          :subtitles="subtitles"
          :duration="video.duration"
          :current-time="currentTime"
          :active-id="activeId"
          :px-per-second="pxPerSecond"
          @seek="seekTo"
          @update="(payload) => (updateSub(payload))"
          @select="selectSub"
        />
      </div>

      <div class="list-col card">
        <div class="list-header">
          <span>字幕清單（{{ subtitles.length }}）</span>
          <button class="btn btn-icon" title="新增字幕" @click="addSubtitle">+</button>
        </div>
        <div class="list-scroll scroll-fade">
          <SubtitleList
            :subtitles="subtitles"
            :active-id="activeId"
            @select="selectSub"
            @change="updateSub"
            @delete="deleteSub"
            @split="splitSub"
            @seek="seekTo"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.editor {
  max-width: 1400px;
  margin: 0 auto;
  padding: 20px 24px 40px;
  width: 100%;
}

.editor-top {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px 12px;
  margin-bottom: 16px;
}
.title {
  font-family: var(--font-mono);
  font-weight: 500;
  font-size: 13.5px;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-dim);
}
.spacer {
  flex: 1;
}
.save-msg {
  color: var(--success);
  font-size: 13px;
}

.error-banner {
  background: rgba(217, 99, 79, 0.1);
  border: 1px solid rgba(217, 99, 79, 0.35);
  color: #ef9686;
  padding: 10px 14px;
  border-radius: var(--radius-sm);
  margin-bottom: 16px;
  font-size: 13px;
}

.note-banner {
  background: rgba(232, 196, 106, 0.1);
  border: 1px solid rgba(232, 196, 106, 0.35);
  color: #e8c46a;
  padding: 10px 14px;
  border-radius: var(--radius-sm);
  margin-bottom: 16px;
  font-size: 13px;
}

.render-progress-bar {
  height: 3px;
  background: var(--panel-2);
  margin: -8px 0 16px;
  overflow: hidden;
}
.render-progress-fill {
  height: 100%;
  background: var(--accent);
  transition: width 0.4s ease;
}

.editor-body {
  display: grid;
  grid-template-columns: 1.5fr 1fr;
  gap: 20px;
  align-items: start;
}

.player-col {
  min-width: 0;
}

.player-wrap {
  position: relative;
  overflow: hidden;
  background: #000;
}
.player-wrap video {
  width: 100%;
  max-height: 480px;
  display: block;
  background: #000;
  cursor: pointer;
}
.player-wrap.is-fullscreen {
  display: flex;
  align-items: center;
  justify-content: center;
}
.player-wrap.is-fullscreen video {
  max-height: none;
  height: 100vh;
  object-fit: contain;
}
/* hide the control bar while playing unless the pointer is over the player */
.player-wrap:not(:hover):not(.is-paused) :deep(.controls) {
  opacity: 0;
  pointer-events: none;
}
.player-wrap:not(:hover):not(.is-paused) {
  cursor: none;
}
.filter-defs {
  position: absolute;
  width: 0;
  height: 0;
  overflow: hidden;
}
.osd {
  position: absolute;
  top: 16px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(0, 0, 0, 0.72);
  color: #fff;
  padding: 6px 14px;
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: 13px;
  pointer-events: none;
  z-index: 4;
}
.shortcut-hint {
  margin-top: 10px;
  font-size: 11.5px;
  color: var(--text-faint);
}
.caption-overlay {
  position: absolute;
  z-index: 2;
  left: 50%;
  bottom: 72px;
  transform: translateX(-50%);
  background: rgba(0, 0, 0, 0.7);
  color: #fff;
  padding: 6px 14px;
  border-radius: var(--radius-sm);
  font-size: 16px;
  max-width: 85%;
  text-align: center;
  pointer-events: none;
}
.transcribing-overlay {
  position: absolute;
  inset: 0;
  background: rgba(8, 8, 7, 0.8);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--text-dim);
  font-size: 14px;
}
.spinner {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  border: 2px solid rgba(255, 106, 44, 0.2);
  border-top-color: var(--accent);
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.btn-spinner {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 2px solid rgba(255, 255, 255, 0.25);
  border-top-color: currentColor;
  animation: spin 0.7s linear infinite;
  display: inline-block;
}

.timeline-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 14px 0 8px;
  font-size: 12px;
  color: var(--text-dim);
}
.time-label {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}

.list-col {
  display: flex;
  flex-direction: column;
  max-height: 720px;
  min-width: 0;
  padding: 14px;
}
.list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 500;
  color: var(--text-dim);
  margin-bottom: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
}
.list-scroll {
  overflow-y: auto;
  flex: 1;
}

@media (max-width: 980px) {
  .editor-body {
    grid-template-columns: 1fr;
  }
}
</style>
