<script setup>
import { watch, nextTick } from "vue";
import { formatTime, parseTime } from "../utils/time";

const props = defineProps({
  subtitles: { type: Array, required: true },
  activeId: { type: String, default: null },
});

const emit = defineEmits(["select", "change", "delete", "split", "seek"]);

const cardRefs = new Map();

function setCardRef(id, el) {
  if (el) cardRefs.set(id, el);
  else cardRefs.delete(id);
}

watch(
  () => props.activeId,
  (id) => {
    if (!id) return;
    nextTick(() => {
      cardRefs.get(id)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
  }
);

function onTimeInput(sub, field, e) {
  const value = parseTime(e.target.value);
  emit("change", { id: sub.id, [field]: value });
}

function onTextInput(sub, e) {
  emit("change", { id: sub.id, text: e.target.value });
}

function autoGrow(e) {
  e.target.style.height = "auto";
  e.target.style.height = e.target.scrollHeight + "px";
}
</script>

<template>
  <div class="sub-list">
    <div
      v-for="(sub, idx) in subtitles"
      :key="sub.id"
      :ref="(el) => setCardRef(sub.id, el)"
      class="sub-card"
      :class="{ active: sub.id === activeId }"
      @click="emit('select', sub.id)"
    >
      <div class="sub-index">{{ idx + 1 }}</div>
      <div class="sub-body">
        <div class="time-row">
          <button class="time-btn" @click.stop="emit('seek', sub.start)" title="跳到此時間">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
          </button>
          <input
            type="text"
            class="time-input"
            :value="formatTime(sub.start)"
            @change="onTimeInput(sub, 'start', $event)"
            @click.stop
          />
          <span class="arrow">→</span>
          <input
            type="text"
            class="time-input"
            :value="formatTime(sub.end)"
            @change="onTimeInput(sub, 'end', $event)"
            @click.stop
          />
          <div class="spacer"></div>
          <button class="icon-btn" title="拆分字幕" @click.stop="emit('split', sub.id)">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M12 3v6m0 6v6M4 12h16" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
          </button>
          <button class="icon-btn danger" title="刪除" @click.stop="emit('delete', sub.id)">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M4 7h16M9 7V4h6v3m-8 0l1 13a2 2 0 002 2h4a2 2 0 002-2l1-13" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
        </div>
        <textarea
          class="sub-text"
          rows="1"
          :value="sub.text"
          placeholder="輸入字幕文字…"
          @input="autoGrow($event); onTextInput(sub, $event)"
          @click.stop
        ></textarea>
      </div>
    </div>
    <div v-if="!subtitles.length" class="empty">尚無字幕，點擊「新增字幕」開始編輯，或先執行 AI 辨識。</div>
  </div>
</template>

<style scoped>
.sub-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sub-card {
  display: flex;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-left: 2px solid transparent;
  background: var(--bg-soft);
  cursor: pointer;
  transition: border-color 0.12s ease, background 0.12s ease;
}
.sub-card:hover {
  border-color: var(--border-strong);
}
.sub-card.active {
  border-color: var(--accent-border);
  border-left-color: var(--accent);
  background: var(--accent-soft);
}

.sub-index {
  width: 22px;
  flex-shrink: 0;
  color: var(--text-faint);
  font-family: var(--font-mono);
  font-size: 11px;
  padding-top: 7px;
  text-align: center;
}

.sub-body {
  flex: 1;
  min-width: 0;
}

.time-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.time-btn {
  border: 1px solid var(--border);
  background: var(--panel-2);
  color: var(--accent);
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
}
.time-input {
  width: 92px;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  padding: 4px 6px;
  font-size: 11.5px;
}
.arrow {
  color: var(--text-faint);
  font-size: 12px;
}
.spacer {
  flex: 1;
}
.icon-btn {
  border: none;
  background: transparent;
  color: var(--text-faint);
  width: 24px;
  height: 24px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}
.icon-btn:hover {
  background: var(--panel-2);
  color: var(--text);
}
.icon-btn.danger:hover {
  color: var(--danger);
}

.sub-text {
  width: 100%;
  resize: none;
  min-height: 34px;
  line-height: 1.5;
  font-size: 13.5px;
}

.empty {
  text-align: center;
  color: var(--text-faint);
  padding: 40px 0;
  font-size: 13px;
}
</style>
