<script setup>
import { ref, computed, watch, onBeforeUnmount } from "vue";

const props = defineProps({
  subtitles: { type: Array, required: true },
  duration: { type: Number, default: 0 },
  currentTime: { type: Number, default: 0 },
  activeId: { type: String, default: null },
  pxPerSecond: { type: Number, default: 70 },
});

const emit = defineEmits(["seek", "update", "select"]);

const trackRef = ref(null);
const dragState = ref(null);

const totalWidth = computed(() => Math.max(props.duration * props.pxPerSecond, 400));

const ticks = computed(() => {
  const dur = props.duration || 60;
  let step = 5;
  if (dur > 600) step = 60;
  else if (dur > 240) step = 30;
  else if (dur > 90) step = 10;
  else if (dur < 20) step = 1;
  const arr = [];
  for (let t = 0; t <= dur; t += step) arr.push(t);
  return arr;
});

function fmtTick(t) {
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

watch(
  () => props.currentTime,
  (t) => {
    if (dragState.value || !trackRef.value) return;
    const x = t * props.pxPerSecond;
    const el = trackRef.value;
    const margin = 60;
    if (x < el.scrollLeft + margin) {
      el.scrollLeft = Math.max(0, x - margin);
    } else if (x > el.scrollLeft + el.clientWidth - margin) {
      el.scrollLeft = x - el.clientWidth + margin;
    }
  }
);

function xToTime(clientX) {
  const rect = trackRef.value.getBoundingClientRect();
  const x = clientX - rect.left + trackRef.value.scrollLeft;
  return Math.max(0, x / props.pxPerSecond);
}

function onRulerClick(e) {
  if (dragState.value) return;
  emit("seek", xToTime(e.clientX));
}

function startDrag(e, sub, mode) {
  e.stopPropagation();
  emit("select", sub.id);
  dragState.value = {
    id: sub.id,
    mode, // 'move' | 'left' | 'right'
    startX: e.clientX,
    origStart: sub.start,
    origEnd: sub.end,
  };
  window.addEventListener("mousemove", onDragMove);
  window.addEventListener("mouseup", onDragEnd);
}

function onDragMove(e) {
  if (!dragState.value) return;
  const dt = (e.clientX - dragState.value.startX) / props.pxPerSecond;
  const { mode, origStart, origEnd, id } = dragState.value;
  let start = origStart;
  let end = origEnd;
  if (mode === "move") {
    start = Math.max(0, origStart + dt);
    end = start + (origEnd - origStart);
  } else if (mode === "left") {
    start = Math.min(Math.max(0, origStart + dt), origEnd - 0.1);
  } else if (mode === "right") {
    end = Math.max(origEnd + dt, origStart + 0.1);
  }
  emit("update", { id, start: round2(start), end: round2(end) });
}

function round2(n) {
  return Math.round(n * 100) / 100;
}

function onDragEnd() {
  dragState.value = null;
  window.removeEventListener("mousemove", onDragMove);
  window.removeEventListener("mouseup", onDragEnd);
}

onBeforeUnmount(() => {
  window.removeEventListener("mousemove", onDragMove);
  window.removeEventListener("mouseup", onDragEnd);
});
</script>

<template>
  <div class="timeline card">
    <div class="timeline-scroll" ref="trackRef" @mousedown="onRulerClick">
      <div class="timeline-inner" :style="{ width: totalWidth + 'px' }">
        <div class="ruler">
          <div v-for="t in ticks" :key="t" class="tick" :style="{ left: t * pxPerSecond + 'px' }">
            <span>{{ fmtTick(t) }}</span>
          </div>
        </div>
        <div class="lane">
          <div
            v-for="sub in subtitles"
            :key="sub.id"
            class="block"
            :class="{ active: sub.id === activeId }"
            :style="{ left: sub.start * pxPerSecond + 'px', width: Math.max((sub.end - sub.start) * pxPerSecond, 6) + 'px' }"
            @mousedown="startDrag($event, sub, 'move')"
          >
            <div class="handle left" @mousedown="startDrag($event, sub, 'left')"></div>
            <span class="block-text">{{ sub.text || "（空白）" }}</span>
            <div class="handle right" @mousedown="startDrag($event, sub, 'right')"></div>
          </div>
        </div>
        <div class="playhead" :style="{ left: currentTime * pxPerSecond + 'px' }"></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.timeline {
  padding: 0;
  overflow: hidden;
}
.timeline-scroll {
  overflow-x: auto;
  overflow-y: hidden;
  padding: 10px 0;
  cursor: text;
}
.timeline-inner {
  position: relative;
  height: 78px;
  min-width: 100%;
}
.ruler {
  position: relative;
  height: 20px;
  border-bottom: 1px solid var(--border);
}
.tick {
  position: absolute;
  top: 0;
  bottom: 0;
  border-left: 1px solid var(--border);
  padding-left: 4px;
}
.tick span {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-faint);
}
.lane {
  position: relative;
  height: 44px;
  margin-top: 8px;
}
.block {
  position: absolute;
  top: 0;
  height: 40px;
  background: var(--accent-soft);
  border: 1px solid var(--accent-border);
  border-left: 3px solid var(--accent);
  display: flex;
  align-items: center;
  padding: 0 10px;
  cursor: grab;
  overflow: hidden;
  user-select: none;
  transition: background 0.1s ease;
}
.block:hover {
  background: rgba(255, 106, 44, 0.22);
}
.block.active {
  background: rgba(255, 106, 44, 0.32);
  border-color: var(--accent);
}
.block-text {
  font-size: 11px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--text);
  pointer-events: none;
}
.handle {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 6px;
  cursor: ew-resize;
}
.handle.left {
  left: 0;
}
.handle.right {
  right: 0;
}
.playhead {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--text);
  pointer-events: none;
  z-index: 5;
}
.playhead::before {
  content: "";
  position: absolute;
  top: -1px;
  left: -3.5px;
  width: 8px;
  height: 8px;
  background: var(--text);
}
</style>
