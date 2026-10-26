<script setup>
import { computed, ref, onMounted } from "vue";
import api from "../api/client";

const props = defineProps({
  brightness: { type: Number, required: true },
  contrast: { type: Number, required: true },
  saturation: { type: Number, required: true },
  sharpness: { type: Number, required: true },
  denoise: { type: Number, required: true },
  targetHeight: { type: Number, required: true },
  upscaleMethod: { type: String, required: true },
  srModel: { type: String, default: "fast" },
  srDetail: { type: Number, default: 0.5 },
  sourceWidth: { type: Number, default: 0 },
  sourceHeight: { type: Number, default: 0 },
  duration: { type: Number, default: 0 },
  videoId: { type: String, required: true },
  currentTime: { type: Number, default: 0 },
});

const emit = defineEmits(["update"]);

const NEUTRAL = { brightness: 1, contrast: 1, saturation: 1, sharpness: 0, denoise: 0, target_height: 0, upscale_method: "lanczos" };

const presets = [
  { label: "原始", values: { ...NEUTRAL } },
  {
    label: "一鍵增強",
    values: { brightness: 1.03, contrast: 1.1, saturation: 1.15, sharpness: 0.8, denoise: 3, target_height: 0, upscale_method: "lanczos" },
  },
  {
    label: "鮮豔",
    values: { brightness: 1.05, contrast: 1.2, saturation: 1.4, sharpness: 0.5, denoise: 0, target_height: 0, upscale_method: "lanczos" },
  },
  {
    label: "高畫質 1080P",
    values: { brightness: 1, contrast: 1.05, saturation: 1.05, sharpness: 0.6, denoise: 3, target_height: 1080, upscale_method: "ai" },
  },
];

const sliders = [
  { key: "brightness", label: "亮度", min: 0.5, max: 1.5, step: 0.01, fmt: (v) => `${Math.round(v * 100)}%` },
  { key: "contrast", label: "對比", min: 0.5, max: 2, step: 0.01, fmt: (v) => `${Math.round(v * 100)}%` },
  { key: "saturation", label: "飽和度", min: 0, max: 2, step: 0.01, fmt: (v) => `${Math.round(v * 100)}%` },
  { key: "sharpness", label: "銳利度", min: 0, max: 2, step: 0.05, fmt: (v) => v.toFixed(2) },
  { key: "denoise", label: "降噪", min: 0, max: 10, step: 0.5, fmt: (v) => (v ? v.toFixed(1) : "關"), exportOnly: true },
];

const resolutions = [
  { value: 0, label: "原始" },
  { value: 720, label: "720P" },
  { value: 1080, label: "1080P" },
  { value: 1440, label: "2K" },
  { value: 2160, label: "4K" },
];

const current = computed(() => ({
  brightness: props.brightness,
  contrast: props.contrast,
  saturation: props.saturation,
  sharpness: props.sharpness,
  denoise: props.denoise,
  target_height: props.targetHeight,
  upscale_method: props.upscaleMethod,
}));

function isPreset(p) {
  return Object.entries(p.values).every(([k, v]) =>
    typeof v === "number" ? Math.abs(current.value[k] - v) < 0.001 : current.value[k] === v
  );
}

const outputSize = computed(() => {
  const w = props.sourceWidth;
  const h = props.sourceHeight;
  const th = props.targetHeight;
  if (!w || !h) return null;
  if (!th || th <= h) return { w, h, upscaled: false };
  let ow = Math.round((w * th) / h / 2) * 2;
  const std = Math.round((th * 16) / 9 / 2) * 2;
  if (Math.abs(ow - std) <= 4) ow = std;
  return { w: ow, h: th, upscaled: true };
});

const tooSmallTarget = computed(
  () => props.targetHeight && props.sourceHeight && props.targetHeight <= props.sourceHeight
);

const server = ref(null); // { available, device } of the GPU upscaler
const serverChecking = ref(false);

async function checkServer() {
  serverChecking.value = true;
  try {
    const { data } = await api.get("/upscaler/status");
    server.value = data;
  } catch {
    server.value = { available: false };
  } finally {
    serverChecking.value = false;
  }
}
onMounted(checkServer);

// Rough export time, from measurements on a 480p source: GPU fast model ~3.2x the
// video length, GPU quality model ~1.2 s/frame, local CPU fallback ~4x.
const aiEstimate = computed(() => {
  if (props.upscaleMethod !== "ai" || !outputSize.value?.upscaled || !props.duration) return "";
  const pixels = (props.sourceWidth * props.sourceHeight) / (854 * 480);
  const fmt = (sec) => (sec >= 3600 ? `${(sec / 3600).toFixed(1)} 小時` : `${Math.max(1, Math.round(sec / 60))} 分鐘`);
  if (!server.value?.available) {
    return `GPU 伺服器未連線：會改用本機輕量版（效果有限），預估匯出約 ${fmt(props.duration * 4 * pixels)}。`;
  }
  if (props.srModel === "quality") {
    return `高品質模型很慢：這部影片預估約 ${fmt(props.duration * 30 * 1.25 * pixels)}（以 30fps 估算），建議先用「預覽目前畫面」確認效果。`;
  }
  return `預估匯出約 ${fmt(props.duration * 3.2 * pixels)}。`;
});

const previewUrl = ref("");
const previewSource = ref("");
const previewLoading = ref(false);
const previewError = ref("");

async function loadPreview() {
  previewLoading.value = true;
  previewError.value = "";
  const t = props.currentTime.toFixed(2);
  try {
    const res = await fetch(`/api/videos/${props.videoId}/enhance/preview?t=${t}`);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
    if (previewUrl.value) URL.revokeObjectURL(previewUrl.value);
    previewUrl.value = URL.createObjectURL(await res.blob());
    previewSource.value = res.headers.get("X-Upscaler") === "gpu" ? "GPU 伺服器（Real-ESRGAN）" : "本機";
  } catch (e) {
    previewError.value = `預覽失敗：${e.message}`;
  } finally {
    previewLoading.value = false;
  }
}
</script>

<template>
  <div class="enhance-panel card">
    <div class="row">
      <label>預設</label>
      <div class="seg">
        <button
          v-for="p in presets"
          :key="p.label"
          class="seg-btn"
          :class="{ active: isPreset(p) }"
          @click="emit('update', { ...p.values })"
        >
          {{ p.label }}
        </button>
      </div>
    </div>

    <div class="row">
      <label>
        輸出解析度
        <span v-if="outputSize" class="value">
          {{ sourceWidth }}×{{ sourceHeight }} → {{ outputSize.w }}×{{ outputSize.h }}
        </span>
      </label>
      <div class="seg">
        <button
          v-for="r in resolutions"
          :key="r.value"
          class="seg-btn"
          :class="{ active: targetHeight === r.value }"
          :disabled="r.value && sourceHeight && r.value <= sourceHeight"
          @click="emit('update', { target_height: r.value })"
        >
          {{ r.label }}
        </button>
      </div>
      <div v-if="tooSmallTarget" class="hint">來源已經是這個解析度以上，不會縮小。</div>
    </div>

    <div v-if="targetHeight" class="row">
      <label>放大方式</label>
      <div class="seg">
        <button
          class="seg-btn"
          :class="{ active: upscaleMethod === 'lanczos' }"
          @click="emit('update', { upscale_method: 'lanczos' })"
        >
          標準放大（快）
        </button>
        <button
          class="seg-btn"
          :class="{ active: upscaleMethod === 'ai' }"
          @click="emit('update', { upscale_method: 'ai' })"
        >
          AI 超解析（Real-ESRGAN）
        </button>
      </div>
      <div v-if="upscaleMethod === 'ai'" class="server-row">
        <span v-if="serverChecking" class="hint">檢查 GPU 伺服器中…</span>
        <span v-else-if="server?.available" class="ok">● GPU 伺服器已連線：{{ server.device }}</span>
        <span v-else class="warn">● GPU 伺服器未連線（請確認 SSH 通道有開）</span>
        <button class="btn btn-sm btn-ghost" :disabled="serverChecking" @click="checkServer">重新檢查</button>
      </div>
    </div>

    <div v-if="targetHeight && upscaleMethod === 'ai'" class="row">
      <label>AI 模型</label>
      <div class="seg">
        <button class="seg-btn" :class="{ active: srModel === 'fast' }" @click="emit('update', { sr_model: 'fast' })">
          快速（約影片長度 3 倍時間）
        </button>
        <button
          class="seg-btn"
          :class="{ active: srModel === 'quality' }"
          @click="emit('update', { sr_model: 'quality' })"
        >
          高品質（細節多很多，非常慢）
        </button>
      </div>
      <div v-if="srModel === 'fast'" class="row detail-row">
        <label>
          細節保留 <span class="value">{{ Math.round(srDetail * 100) }}%</span>
        </label>
        <div class="detail-slider">
          <span class="hint">平滑</span>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            :value="srDetail"
            @change="emit('update', { sr_detail: Number($event.target.value) })"
          />
          <span class="hint">保留紋理</span>
        </div>
        <div class="hint">畫面被「抹平」像塗蠟時往右調；雜訊、壓縮方塊太明顯時往左調。</div>
      </div>
      <div v-if="aiEstimate" class="warn">{{ aiEstimate }}</div>
    </div>

    <div class="grid">
      <div v-for="s in sliders" :key="s.key" class="row">
        <label>
          {{ s.label }} <span class="value">{{ s.fmt(props[s.key]) }}</span>
          <span v-if="s.exportOnly" class="badge">僅匯出</span>
        </label>
        <input
          type="range"
          :min="s.min"
          :max="s.max"
          :step="s.step"
          :value="props[s.key]"
          @input="emit('update', { [s.key]: Number($event.target.value) })"
          @dblclick="emit('update', { [s.key]: NEUTRAL[s.key] })"
        />
      </div>
    </div>

    <div class="row">
      <div class="preview-row">
        <button class="btn btn-sm" :disabled="previewLoading" @click="loadPreview">
          {{ previewLoading ? "產生中…" : "預覽目前畫面（含放大、降噪）" }}
        </button>
        <span v-if="previewUrl" class="hint">處理：{{ previewSource }}</span>
        <a v-if="previewUrl" :href="previewUrl" target="_blank" rel="noopener" class="hint">開新分頁看原尺寸</a>
        <button v-if="previewUrl" class="btn btn-sm btn-ghost" @click="previewUrl = ''">關閉預覽</button>
        <span v-if="previewError" class="err">{{ previewError }}</span>
      </div>
      <img v-if="previewUrl" :src="previewUrl" class="preview-img" alt="畫質增強預覽" />
    </div>

    <div class="hint">
      亮度、對比、飽和度、銳利度會直接在播放器即時預覽（按播放列的「增強 / 原始」或 C 鍵比較）；放大與降噪只在匯出時套用，可用上面的「預覽目前畫面」看實際效果。雙擊滑桿可還原該項。
    </div>
  </div>
</template>

<style scoped>
.enhance-panel {
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin: 14px 0;
}
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px 20px;
}
.row {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
label {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--text-dim);
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 6px;
}
.value {
  color: var(--text-faint);
  font-weight: 400;
  font-variant-numeric: tabular-nums;
}
.badge {
  font-size: 10px;
  padding: 1px 5px;
  border: 1px solid var(--border);
  color: var(--text-faint);
}
.seg {
  display: inline-flex;
  flex-wrap: wrap;
  background: var(--bg-soft);
  border: 1px solid var(--border);
  padding: 2px;
  gap: 2px;
  width: fit-content;
}
.seg-btn {
  border: none;
  background: transparent;
  color: var(--text-dim);
  padding: 5px 12px;
  font-size: 12px;
  cursor: pointer;
}
.seg-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.seg-btn.active {
  background: var(--accent);
  color: var(--accent-ink);
  font-weight: 700;
}
input[type="range"] {
  width: 100%;
  accent-color: var(--accent);
}
.preview-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.preview-img {
  width: 100%;
  border: 1px solid var(--border);
  background: #000;
}
.btn-sm {
  padding: 4px 10px;
  font-size: 12px;
}
.hint {
  font-size: 11.5px;
  color: var(--text-faint);
}
.warn {
  font-size: 12px;
  color: #e8c46a;
}
.err {
  font-size: 12px;
  color: #ef9686;
}
.ok {
  font-size: 12px;
  color: var(--success);
}
.detail-row {
  margin-top: 4px;
}
.detail-slider {
  display: flex;
  align-items: center;
  gap: 10px;
}
.detail-slider input {
  flex: 1;
}
.server-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
@media (max-width: 640px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
