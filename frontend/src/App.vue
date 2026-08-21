<script setup>
import { RouterView, RouterLink } from "vue-router";
</script>

<template>
  <div class="app-shell">
    <div class="rule"></div>
    <header class="topbar">
      <RouterLink to="/" class="brand">
        <span class="brand-dot"></span>
        <span class="brand-text">CaptionCraft</span>
      </RouterLink>
      <div class="topbar-sub">字幕製作台</div>
    </header>
    <main class="app-main">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.app-shell {
  min-height: 100%;
  display: flex;
  flex-direction: column;
}

.rule {
  height: 3px;
  background: var(--accent);
  flex-shrink: 0;
}

.topbar {
  display: flex;
  align-items: baseline;
  gap: 14px;
  padding: 16px 32px;
  border-bottom: 1px solid var(--border);
  background: var(--bg);
  position: sticky;
  top: 0;
  z-index: 50;
}

.brand {
  display: flex;
  align-items: center;
  gap: 9px;
  text-decoration: none;
  color: var(--text);
}

.brand-dot {
  width: 8px;
  height: 8px;
  background: var(--accent);
  flex-shrink: 0;
}

.brand-text {
  font-family: var(--font-mono);
  font-weight: 600;
  font-size: 15px;
  letter-spacing: 0.01em;
}

.topbar-sub {
  color: var(--text-faint);
  font-size: 13px;
  padding-left: 14px;
  border-left: 1px solid var(--border);
}

.app-main {
  flex: 1;
  display: flex;
  flex-direction: column;
}
</style>
