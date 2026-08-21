<script setup>
import { ref, onMounted, onUnmounted } from "vue";
import { useRouter } from "vue-router";
import api from "../api/client";

const router = useRouter();
const videos = ref([]);
const uploading = ref(false);
const uploadProgress = ref(0);
const dragOver = ref(false);
const fileInput = ref(null);
const errorMsg = ref("");

let pollTimer = null;

const statusLabel = {
  uploaded: "尚未產生字幕",
  transcribing: "字幕產生中",
  ready: "已完成",
  error: "發生錯誤",
};

async function loadVideos() {
  const { data } = await api.get("/videos");
  videos.value = data;
}

function formatDuration(sec) {
  if (!sec) return "--:--";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

async function handleFiles(files) {
  if (!files || !files.length) return;
  const file = files[0];
  errorMsg.value = "";
  uploading.value = true;
  uploadProgress.value = 0;
  try {
    const form = new FormData();
    form.append("file", file);
    const { data } = await api.post("/videos/upload", form, {
      headers: { "Content-Type": "multipart/form-data" },
      onUploadProgress: (evt) => {
        uploadProgress.value = Math.round((evt.loaded / evt.total) * 100);
      },
    });
    await loadVideos();
    router.push({ name: "editor", params: { id: data.id } });
  } catch (e) {
    errorMsg.value = e?.response?.data?.detail || "上傳失敗，請確認檔案格式";
  } finally {
    uploading.value = false;
  }
}

function onDrop(e) {
  dragOver.value = false;
  handleFiles(e.dataTransfer.files);
}

function onPick(e) {
  handleFiles(e.target.files);
  e.target.value = "";
}

async function removeVideo(id) {
  if (!confirm("確定要刪除這部影片與其字幕嗎？")) return;
  await api.delete(`/videos/${id}`);
  await loadVideos();
}

onMounted(() => {
  loadVideos();
  pollTimer = setInterval(loadVideos, 4000);
});
onUnmounted(() => clearInterval(pollTimer));
</script>

<template>
  <div
    class="library"
    :class="{ over: dragOver }"
    @dragover.prevent="dragOver = true"
    @dragleave.prevent="dragOver = false"
    @drop.prevent="onDrop"
  >
    <header class="page-head">
      <div class="page-head-index">影片庫</div>
      <h1>你的字幕工作區</h1>
      <p>上傳影片、交給語音辨識產字幕，再手動校對文字與時間軸。</p>
    </header>

    <div class="toolbar">
      <input ref="fileInput" type="file" accept="video/*" hidden @change="onPick" />
      <button class="btn btn-primary" :disabled="uploading" @click="fileInput.click()">
        + 上傳影片
      </button>
      <span class="toolbar-hint">或將檔案拖曳到此頁面任意處　·　支援 MP4 / MOV / MKV / WEBM / AVI</span>
    </div>

    <div v-if="uploading" class="upload-status">
      <span class="mono">上傳中 {{ uploadProgress }}%</span>
      <div class="progress-track"><div class="progress-fill" :style="{ width: uploadProgress + '%' }"></div></div>
    </div>
    <p v-if="errorMsg" class="error-msg">{{ errorMsg }}</p>

    <div v-if="dragOver" class="drop-indicator">放開以上傳影片</div>

    <section class="video-grid" v-if="videos.length">
      <div v-for="(v, i) in videos" :key="v.id" class="video-card" @click="router.push({ name: 'editor', params: { id: v.id } })">
        <div class="thumb">
          <img v-if="v.has_thumbnail" :src="`/api/videos/${v.id}/thumbnail`" loading="lazy" alt="" />
          <div v-else class="thumb-fallback">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none"><path d="M8 5v14l11-7z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>
          </div>
          <span class="index-tag mono">{{ String(i + 1).padStart(2, "0") }}</span>
          <span class="duration-tag mono">{{ formatDuration(v.duration) }}</span>
          <button class="delete-btn" @click.stop="removeVideo(v.id)" title="刪除">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none"><path d="M4 7h16M9 7V4h6v3m-8 0l1 13a2 2 0 002 2h4a2 2 0 002-2l1-13" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
        </div>
        <div class="video-info">
          <div class="video-name" :title="v.original_name">{{ v.original_name }}</div>
          <div class="tag" :class="`tag-${v.status}`">
            <span class="tag-dot"></span>{{ statusLabel[v.status] || v.status }}
          </div>
        </div>
      </div>
    </section>

    <section v-else class="empty-state">
      <p>目前還沒有任何影片，點上面「上傳影片」開始吧。</p>
    </section>
  </div>
</template>

<style scoped>
.library {
  max-width: 1120px;
  margin: 0 auto;
  padding: 56px 32px 80px;
  width: 100%;
  min-height: 100%;
  outline: 2px dashed transparent;
  outline-offset: -8px;
  transition: outline-color 0.15s ease;
}
.library.over {
  outline-color: var(--accent);
}

.page-head {
  margin-bottom: 40px;
  padding-bottom: 28px;
  border-bottom: 1px solid var(--border);
}
.page-head-index {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--accent);
  letter-spacing: 0.08em;
  margin-bottom: 10px;
}
.page-head h1 {
  font-family: var(--font-display);
  font-size: 36px;
  font-weight: 600;
  letter-spacing: -0.01em;
  margin: 0 0 10px;
  color: var(--text);
}
.page-head p {
  color: var(--text-dim);
  font-size: 14px;
  margin: 0;
  max-width: 46ch;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.toolbar-hint {
  color: var(--text-faint);
  font-size: 12.5px;
}

.upload-status {
  margin-top: 18px;
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
  color: var(--text-dim);
}
.progress-track {
  flex: 1;
  max-width: 320px;
  height: 3px;
  background: var(--panel-2);
}
.progress-fill {
  height: 100%;
  background: var(--accent);
  transition: width 0.2s ease;
}
.error-msg {
  color: var(--danger);
  margin-top: 14px;
  font-size: 13px;
}
.drop-indicator {
  margin-top: 24px;
  padding: 20px;
  text-align: center;
  border: 1px dashed var(--accent);
  color: var(--accent);
  font-size: 13px;
  font-family: var(--font-mono);
}

.video-grid {
  margin-top: 36px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: 22px 20px;
}
.video-card {
  cursor: pointer;
}
.thumb {
  position: relative;
  aspect-ratio: 16/9;
  background: #050504;
  border: 1px solid var(--border);
  overflow: hidden;
  transition: border-color 0.12s ease, transform 0.12s ease, box-shadow 0.12s ease;
}
.video-card:hover .thumb {
  border-color: var(--text);
  transform: translate(-2px, -2px);
  box-shadow: var(--shadow-hard);
}
.thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.thumb-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-faint);
  background: var(--bg-soft);
}
.index-tag {
  position: absolute;
  top: 0;
  left: 0;
  background: var(--bg);
  color: var(--text-faint);
  font-size: 10px;
  padding: 3px 6px;
  border-right: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
}
.duration-tag {
  position: absolute;
  bottom: 6px;
  right: 6px;
  background: rgba(0, 0, 0, 0.75);
  color: var(--text);
  font-size: 11px;
  padding: 2px 6px;
}
.delete-btn {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 24px;
  height: 24px;
  border: 1px solid var(--border);
  background: rgba(17, 17, 16, 0.85);
  color: var(--text-dim);
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  cursor: pointer;
  transition: opacity 0.12s ease;
}
.video-card:hover .delete-btn {
  opacity: 1;
}
.delete-btn:hover {
  color: var(--danger);
  border-color: var(--danger);
}

.video-info {
  padding: 10px 1px 0;
}
.video-name {
  font-size: 13.5px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-bottom: 8px;
}

.empty-state {
  text-align: center;
  color: var(--text-faint);
  padding: 70px 0;
  font-size: 13.5px;
  border: 1px dashed var(--border);
  margin-top: 36px;
}
</style>
