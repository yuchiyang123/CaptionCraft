<script setup>
import { ref, computed, watch, onBeforeUnmount } from "vue";
import { formatTime } from "../utils/time";

const props = defineProps({
  videoEl: { type: Object, default: null },
  currentTime: { type: Number, default: 0 },
  duration: { type: Number, default: 0 },
  playing: { type: Boolean, default: false },
  fullscreen: { type: Boolean, default: false },
  showCompare: { type: Boolean, default: false },
  comparing: { type: Boolean, default: false },
});

const emit = defineEmits(["toggle-play", "skip", "seek", "fullscreen", "compare"]);

const volume = ref(1);
const muted = ref(false);
const rate = ref(1);
const rates = [0.5, 0.75, 1, 1.25, 1.5, 2];
const scrubbing = ref(false);
const scrubValue = ref(0);
const buffered = ref(0);

function syncFromVideo() {
  const v = props.videoEl;
  if (!v) return;
  volume.value = v.volume;
  muted.value = v.muted;
  rate.value = v.playbackRate;
  if (v.buffered.length && props.duration) {
    buffered.value = v.buffered.end(v.buffered.length - 1) / props.duration;
  }
}

let bound = null;
watch(
  () => props.videoEl,
  (v, old) => {
    if (old && bound) {
      ["volumechange", "ratechange", "progress"].forEach((e) => old.removeEventListener(e, bound));
    }
    if (v) {
      bound = syncFromVideo;
      ["volumechange", "ratechange", "progress"].forEach((e) => v.addEventListener(e, bound));
      syncFromVideo();
    }
  },
  { immediate: true }
);

onBeforeUnmount(() => {
  if (props.videoEl && bound) {
    ["volumechange", "ratechange", "progress"].forEach((e) => props.videoEl.removeEventListener(e, bound));
  }
});

const shownTime = computed(() => (scrubbing.value ? scrubValue.value : props.currentTime));
const progress = computed(() => (props.duration ? (shownTime.value / props.duration) * 100 : 0));

function onScrubInput(e) {
  scrubbing.value = true;
  scrubValue.value = Number(e.target.value);
  emit("seek", scrubValue.value);
}
function onScrubEnd() {
  scrubbing.value = false;
}

function setVolume(e) {
  const v = props.videoEl;
  if (!v) return;
  v.volume = Number(e.target.value);
  v.muted = v.volume === 0;
}
function toggleMute() {
  const v = props.videoEl;
  if (v) v.muted = !v.muted;
}
function setRate(r) {
  if (props.videoEl) props.videoEl.playbackRate = r;
}
</script>

<template>
  <div class="controls" @click.stop>
    <div class="seek">
      <div class="seek-track">
        <div class="seek-buffered" :style="{ width: buffered * 100 + '%' }"></div>
        <div class="seek-fill" :style="{ width: progress + '%' }"></div>
      </div>
      <input
        type="range"
        class="seek-input"
        min="0"
        :max="duration || 0"
        step="0.01"
        :value="shownTime"
        @input="onScrubInput"
        @change="onScrubEnd"
        aria-label="播放位置"
      />
    </div>

    <div class="bar">
      <button class="cbtn" @click="emit('skip', -5)" title="倒退 5 秒（←）" aria-label="倒退 5 秒">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M11 17l-5-5 5-5M18 17l-5-5 5-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <span class="cbtn-num">5</span>
      </button>
      <button class="cbtn cbtn-play" @click="emit('toggle-play')" :title="playing ? '暫停（空白鍵）' : '播放（空白鍵）'" :aria-label="playing ? '暫停' : '播放'">
        <svg v-if="!playing" width="20" height="20" viewBox="0 0 24 24"><path d="M7 4.5v15l13-7.5z" fill="currentColor"/></svg>
        <svg v-else width="20" height="20" viewBox="0 0 24 24"><path d="M6 4h4v16H6zM14 4h4v16h-4z" fill="currentColor"/></svg>
      </button>
      <button class="cbtn" @click="emit('skip', 5)" title="快轉 5 秒（→）" aria-label="快轉 5 秒">
        <span class="cbtn-num">5</span>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M13 17l5-5-5-5M6 17l5-5-5-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </button>

      <span class="time">{{ formatTime(shownTime) }} / {{ formatTime(duration) }}</span>

      <div class="spacer"></div>

      <div class="volume">
        <button class="cbtn" @click="toggleMute" :title="muted ? '取消靜音（M）' : '靜音（M）'" :aria-label="muted ? '取消靜音' : '靜音'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M4 9v6h4l5 4V5L8 9H4z" fill="currentColor"/>
            <path v-if="!muted && volume > 0" d="M16 8.5a5 5 0 010 7M18.5 6a8.5 8.5 0 010 12" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
            <path v-else d="M16 9l5 6M21 9l-5 6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
          </svg>
        </button>
        <input type="range" class="vol-input" min="0" max="1" step="0.05" :value="muted ? 0 : volume" @input="setVolume" aria-label="音量" />
      </div>

      <div class="rate">
        <button class="cbtn cbtn-text" title="播放速度">{{ rate }}x</button>
        <div class="rate-menu">
          <button v-for="r in rates" :key="r" :class="{ active: r === rate }" @click="setRate(r)">{{ r }}x</button>
        </div>
      </div>

      <button
        v-if="showCompare"
        class="cbtn cbtn-text"
        :class="{ active: comparing }"
        @click="emit('compare')"
        title="切換顯示原始畫面 / 增強後畫面（C）"
      >
        {{ comparing ? "原始" : "增強" }}
      </button>

      <button class="cbtn" @click="emit('fullscreen')" :title="fullscreen ? '離開全螢幕（F）' : '全螢幕（F）'" :aria-label="fullscreen ? '離開全螢幕' : '全螢幕'">
        <svg v-if="!fullscreen" width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </button>
    </div>
  </div>
</template>

<style scoped>
.controls {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 18px 12px 8px;
  background: linear-gradient(to top, rgba(0, 0, 0, 0.82), rgba(0, 0, 0, 0));
  color: #fff;
  transition: opacity 0.2s ease;
  z-index: 3;
}
.seek {
  position: relative;
  height: 14px;
  display: flex;
  align-items: center;
}
.seek-track {
  position: absolute;
  left: 0;
  right: 0;
  height: 4px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 2px;
  overflow: hidden;
  transition: height 0.12s ease;
}
.seek:hover .seek-track {
  height: 6px;
}
.seek-buffered {
  position: absolute;
  inset: 0 auto 0 0;
  background: rgba(255, 255, 255, 0.25);
}
.seek-fill {
  position: absolute;
  inset: 0 auto 0 0;
  background: var(--accent);
}
.seek-input {
  position: relative;
  width: 100%;
  margin: 0;
  height: 14px;
  opacity: 0;
  cursor: pointer;
}
.bar {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 4px;
}
.spacer {
  flex: 1;
}
.cbtn {
  display: inline-flex;
  align-items: center;
  gap: 1px;
  background: transparent;
  border: none;
  color: #fff;
  padding: 6px;
  min-width: 32px;
  min-height: 32px;
  justify-content: center;
  cursor: pointer;
  border-radius: 4px;
  opacity: 0.9;
}
.cbtn:hover {
  background: rgba(255, 255, 255, 0.12);
  opacity: 1;
}
.cbtn:focus-visible {
  outline: 2px solid var(--accent);
}
.cbtn-num {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
}
.cbtn-text {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
  padding: 6px 8px;
}
.cbtn.active {
  color: var(--accent);
}
.time {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 12px;
  margin-left: 6px;
  opacity: 0.9;
}
.volume {
  display: flex;
  align-items: center;
}
.vol-input {
  width: 0;
  opacity: 0;
  transition: width 0.15s ease, opacity 0.15s ease;
  accent-color: var(--accent);
}
.volume:hover .vol-input,
.vol-input:focus {
  width: 72px;
  opacity: 1;
}
.rate {
  position: relative;
}
.rate-menu {
  display: none;
  position: absolute;
  bottom: 100%;
  right: 0;
  background: rgba(20, 20, 18, 0.96);
  border: 1px solid rgba(255, 255, 255, 0.12);
  padding: 4px;
  flex-direction: column;
  min-width: 64px;
}
.rate:hover .rate-menu,
.rate:focus-within .rate-menu {
  display: flex;
}
.rate-menu button {
  background: none;
  border: none;
  color: #fff;
  font-family: var(--font-mono);
  font-size: 12px;
  padding: 5px 10px;
  text-align: right;
  cursor: pointer;
}
.rate-menu button:hover {
  background: rgba(255, 255, 255, 0.1);
}
.rate-menu button.active {
  color: var(--accent);
}
</style>
