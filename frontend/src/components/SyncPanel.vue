<script setup>
import { computed, ref } from "vue";
import { formatTime, parseTime } from "../utils/time";

const props = defineProps({
  offset: { type: Number, required: true },
  status: { type: String, required: true },
  progress: { type: Number, default: 0 },
  error: { type: String, default: null },
  detectedOffset: { type: Number, default: null },
  confidence: { type: String, default: null },
  windows: { type: String, default: null },
  followSubtitles: { type: Boolean, default: true },
  preview: { type: Boolean, default: false },
  currentTime: { type: Number, default: 0 },
  duration: { type: Number, default: 0 },
});

const emit = defineEmits(["analyze", "update", "preview", "follow", "shift-subtitles"]);

const confidenceLabels = { high: "高", medium: "中", low: "低" };
const FRAME = 1 / 30;

function describeShift(v) {
  if (!v) return "不調整";
  return v < 0 ? `聲音提前 ${Math.abs(v).toFixed(3)} 秒` : `聲音延後 ${v.toFixed(3)} 秒`;
}

const detectedText = computed(() => {
  const d = props.detectedOffset;
  if (d === null || d === undefined) return "";
  if (Math.abs(d) < 0.02) return "偵測結果：聲音與畫面已經同步";
  // a negative correction means the audio is currently late
  return d < 0
    ? `偵測結果：聲音比畫面慢 ${Math.abs(d).toFixed(3)} 秒`
    : `偵測結果：聲音比畫面快 ${d.toFixed(3)} 秒`;
});

const details = computed(() => {
  try {
    return props.windows ? JSON.parse(props.windows) : null;
  } catch {
    return null;
  }
});

const percent = computed(() => Math.round(props.progress * 100));

function nudge(delta) {
  emit("update", Math.max(-10, Math.min(10, Math.round((props.offset + delta) * 1000) / 1000)));
}

function onNumber(e) {
  const v = Number(e.target.value);
  if (!Number.isNaN(v)) emit("update", Math.max(-10, Math.min(10, v)));
}

// detection range: whole video, or a custom start/end (e.g. only the part where someone talks to camera)
const rangeMode = ref("all");
const rangeStart = ref("00:00.000");
const rangeEnd = ref("");

const rangeError = computed(() => {
  if (rangeMode.value !== "custom") return "";
  const s = parseTime(rangeStart.value);
  const e = rangeEnd.value ? parseTime(rangeEnd.value) : props.duration;
  if (e - s < 5) return "檢測範圍至少要 5 秒";
  if (props.duration && s >= props.duration) return "開始時間超過影片長度";
  return "";
});

function setRangeFromPlayer(which) {
  const t = formatTime(props.currentTime);
  if (which === "start") rangeStart.value = t;
  else rangeEnd.value = t;
}

function analyze() {
  if (rangeMode.value === "custom") {
    if (rangeError.value) return;
    emit("analyze", {
      start: parseTime(rangeStart.value),
      end: rangeEnd.value ? parseTime(rangeEnd.value) : null,
    });
  } else {
    emit("analyze", null);
  }
}

const subShift = ref(0);
function applySubShift() {
  if (subShift.value) emit("shift-subtitles", Number(subShift.value));
  subShift.value = 0;
}
</script>

<template>
  <div class="sync-panel card">
    <div class="row">
      <label>自動偵測（比對嘴型與人聲）</label>
      <div class="range-row">
        <div class="seg">
          <button class="seg-btn" :class="{ active: rangeMode === 'all' }" @click="rangeMode = 'all'">整部影片</button>
          <button class="seg-btn" :class="{ active: rangeMode === 'custom' }" @click="rangeMode = 'custom'">
            指定範圍
          </button>
        </div>
        <template v-if="rangeMode === 'custom'">
          <input class="time-input" v-model="rangeStart" placeholder="00:00.000" aria-label="開始時間" />
          <button class="btn btn-sm btn-ghost" @click="setRangeFromPlayer('start')" title="用播放器目前的時間">
            目前時間
          </button>
          <span class="hint">到</span>
          <input
            class="time-input"
            v-model="rangeEnd"
            :placeholder="formatTime(duration)"
            aria-label="結束時間"
          />
          <button class="btn btn-sm btn-ghost" @click="setRangeFromPlayer('end')" title="用播放器目前的時間">
            目前時間
          </button>
        </template>
      </div>
      <div v-if="rangeError" class="err">{{ rangeError }}</div>
      <div class="detect-row">
        <button class="btn" :disabled="status === 'analyzing' || !!rangeError" @click="analyze">
          <span v-if="status === 'analyzing'" class="btn-spinner"></span>
          {{ status === "analyzing" ? `分析中… ${percent}%` : status === "ready" ? "重新偵測" : "開始偵測" }}
        </button>
        <span v-if="status === 'ready' && detectedText" class="detected">
          {{ detectedText }}
          <span class="conf" :class="`conf-${confidence}`">信心度 {{ confidenceLabels[confidence] || "—" }}</span>
        </span>
      </div>
      <div v-if="status === 'ready' && detectedOffset !== null" class="apply-row">
        <button
          class="btn btn-primary"
          :disabled="Math.abs(offset - detectedOffset) < 0.001"
          @click="emit('update', detectedOffset)"
        >
          套用偵測結果（{{ describeShift(detectedOffset) }}）
        </button>
      </div>
      <div v-if="status === 'ready' && details?.drift" class="warn">
        各段偵測到的時間差不一致，影片可能越播越不同步（漂移）。目前套用的是整體平均值，建議到不同段落預覽確認。
      </div>
      <details v-if="status === 'ready' && details?.windows?.length" class="windows">
        <summary>
          分段偵測結果（{{ details.windows.length }} 段{{
            details.range ? `，範圍 ${formatTime(details.range[0])} – ${details.range[1] != null ? formatTime(details.range[1]) : "結尾"}` : ""
          }}）
        </summary>
        <table>
          <tr v-for="w in details.windows" :key="w.start">
            <td>{{ formatTime(w.start) }} – {{ formatTime(w.end) }}</td>
            <td class="num-cell">{{ w.offset > 0 ? "+" : "" }}{{ w.offset.toFixed(3) }} 秒</td>
            <td><span class="conf" :class="`conf-${w.confidence}`">{{ confidenceLabels[w.confidence] }}</span></td>
          </tr>
        </table>
      </details>
      <div v-if="status === 'error'" class="err">{{ error }}</div>
      <div class="hint">
        需要畫面中有人正面說話。建議指定「有人正面說話」的片段，會比整部影片更準；範圍內會平均取幾段分析（最多約 3 分鐘）。
      </div>
    </div>

    <div class="row">
      <label>音軌位移 <span class="value">{{ describeShift(offset) }}</span></label>
      <div class="offset-row">
        <input
          type="range"
          min="-2"
          max="2"
          step="0.005"
          :value="offset"
          @input="emit('update', Number($event.target.value))"
        />
        <input type="number" class="num" min="-10" max="10" step="0.005" :value="offset" @change="onNumber" />
      </div>
      <div class="nudge-row">
        <button class="btn btn-sm" @click="nudge(-FRAME)" title="聲音提前 1 幀（約 33 毫秒）">« 1 幀</button>
        <button class="btn btn-sm" @click="nudge(-0.01)" title="聲音提前 10 毫秒">‹ 10ms</button>
        <button class="btn btn-sm" @click="nudge(0.01)" title="聲音延後 10 毫秒">10ms ›</button>
        <button class="btn btn-sm" @click="nudge(FRAME)" title="聲音延後 1 幀（約 33 毫秒）">1 幀 »</button>
        <button class="btn btn-sm btn-ghost" :disabled="!offset" @click="emit('update', 0)">歸零</button>
      </div>
    </div>

    <div class="row">
      <label class="check">
        <input type="checkbox" :checked="followSubtitles" @change="emit('follow', $event.target.checked)" />
        字幕跟著聲音一起位移
      </label>
      <label class="check">
        <input type="checkbox" :checked="preview" @change="emit('preview', $event.target.checked)" />
        在播放器預覽同步效果
      </label>
      <div class="hint">
        字幕是依原本的聲音產生的，所以預設會跟著音軌一起移動（預覽與匯出都套用）。位移會套用到匯出的影片；SRT / VTT 匯出仍是原始時間。
      </div>
    </div>

    <div class="row">
      <label>字幕整體位移（直接修改所有字幕時間）</label>
      <div class="offset-row">
        <input type="number" class="num" step="0.05" v-model.number="subShift" />
        <span class="hint">秒（正數 = 延後，負數 = 提前）</span>
        <button class="btn btn-sm" :disabled="!subShift" @click="applySubShift">套用到所有字幕</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sync-panel {
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin: 14px 0;
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
.range-row,
.detect-row,
.offset-row,
.apply-row,
.nudge-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.detected {
  font-size: 13px;
  color: var(--text);
  display: flex;
  align-items: center;
  gap: 8px;
}
.conf {
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 2px 6px;
  border: 1px solid var(--border);
  color: var(--text-dim);
}
.conf-high {
  color: var(--success);
  border-color: currentColor;
}
.conf-low {
  color: #ef9686;
  border-color: currentColor;
}
.err,
.warn {
  color: #ef9686;
  font-size: 12.5px;
}
.warn {
  color: #e8c46a;
}
.windows {
  font-size: 12px;
  color: var(--text-dim);
}
.windows summary {
  cursor: pointer;
  font-family: var(--font-mono);
  font-size: 11.5px;
}
.windows table {
  margin-top: 6px;
  border-collapse: collapse;
}
.windows td {
  padding: 3px 12px 3px 0;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}
.num-cell {
  text-align: right;
}
.hint {
  font-size: 11.5px;
  color: var(--text-faint);
}
input[type="range"] {
  flex: 1;
  min-width: 140px;
  accent-color: var(--accent);
}
.num {
  width: 80px;
  background: var(--bg-soft);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 4px 6px;
  font-family: var(--font-mono);
  font-size: 12px;
}
.seg {
  display: inline-flex;
  background: var(--bg-soft);
  border: 1px solid var(--border);
  padding: 2px;
  gap: 2px;
}
.seg-btn {
  border: none;
  background: transparent;
  color: var(--text-dim);
  padding: 5px 12px;
  font-size: 12px;
  cursor: pointer;
}
.seg-btn.active {
  background: var(--accent);
  color: var(--accent-ink);
  font-weight: 700;
}
.time-input {
  width: 96px;
  background: var(--bg-soft);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 4px 6px;
  font-family: var(--font-mono);
  font-size: 12px;
}
.btn-sm {
  padding: 4px 10px;
  font-size: 12px;
}
.check {
  cursor: pointer;
}
.check input {
  accent-color: var(--accent);
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
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
