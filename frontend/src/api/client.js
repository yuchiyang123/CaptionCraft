import axios from "axios";

const api = axios.create({
  baseURL: "/api",
});

export default api;

export function mediaStreamUrl(videoId) {
  return `/api/videos/${videoId}/stream`;
}

export function exportUrl(videoId, fmt) {
  return `/api/videos/${videoId}/export?fmt=${fmt}`;
}
