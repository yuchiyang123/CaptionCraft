<script setup>
const props = defineProps({
  fontSize: { type: Number, required: true },
  position: { type: String, required: true },
  color: { type: String, required: true },
  bgOpacity: { type: Number, required: true },
});

const emit = defineEmits(["update"]);

const positions = [
  { value: "top", label: "上方" },
  { value: "middle", label: "置中" },
  { value: "bottom", label: "下方" },
];

const presetColors = ["#ffffff", "#ffe066", "#ff6a2c", "#5fb8e0", "#8bb26a", "#e0665a"];
</script>

<template>
  <div class="style-panel card">
    <div class="row">
      <label>位置</label>
      <div class="seg">
        <button
          v-for="p in positions"
          :key="p.value"
          class="seg-btn"
          :class="{ active: position === p.value }"
          @click="emit('update', { position: p.value })"
        >
          {{ p.label }}
        </button>
      </div>
    </div>

    <div class="row">
      <label>字型大小 <span class="value">{{ fontSize }}px</span></label>
      <input
        type="range"
        min="16"
        max="72"
        step="2"
        :value="fontSize"
        @input="emit('update', { font_size: Number($event.target.value) })"
      />
    </div>

    <div class="row">
      <label>文字顏色</label>
      <div class="color-row">
        <button
          v-for="c in presetColors"
          :key="c"
          class="swatch"
          :class="{ active: color === c }"
          :style="{ background: c }"
          @click="emit('update', { color: c })"
        ></button>
        <input
          type="color"
          class="color-picker"
          :value="color"
          @input="emit('update', { color: $event.target.value })"
        />
      </div>
    </div>

    <div class="row">
      <label>背景透明度 <span class="value">{{ Math.round(bgOpacity * 100) }}%</span></label>
      <input
        type="range"
        min="0"
        max="1"
        step="0.05"
        :value="bgOpacity"
        @input="emit('update', { bg_opacity: Number($event.target.value) })"
      />
    </div>
  </div>
</template>

<style scoped>
.style-panel {
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
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
.seg {
  display: inline-flex;
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
  padding: 5px 14px;
  font-size: 12px;
  cursor: pointer;
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
.color-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.swatch {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: 2px solid transparent;
  cursor: pointer;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.15);
}
.swatch.active {
  border-color: var(--accent);
}
.color-picker {
  width: 26px;
  height: 26px;
  border: 1px solid var(--border);
  background: none;
  padding: 0;
  cursor: pointer;
  overflow: hidden;
}
</style>
