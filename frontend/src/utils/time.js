export function formatTime(totalSeconds) {
  if (totalSeconds == null || Number.isNaN(totalSeconds)) totalSeconds = 0;
  const sign = totalSeconds < 0 ? "-" : "";
  totalSeconds = Math.abs(totalSeconds);
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = Math.floor(totalSeconds % 60);
  const ms = Math.round((totalSeconds - Math.floor(totalSeconds)) * 1000);
  const parts = [];
  if (h > 0) parts.push(String(h).padStart(2, "0"));
  parts.push(String(m).padStart(2, "0"));
  parts.push(String(s).padStart(2, "0"));
  return `${sign}${parts.join(":")}.${String(ms).padStart(3, "0")}`;
}

export function parseTime(text) {
  if (typeof text === "number") return text;
  const str = text.trim();
  const match = str.match(/^(\d+):(\d{1,2}):(\d{1,2})(?:[.,](\d{1,3}))?$/);
  if (match) {
    const [, h, m, s, ms] = match;
    return (
      Number(h) * 3600 + Number(m) * 60 + Number(s) + Number((ms || "0").padEnd(3, "0")) / 1000
    );
  }
  const match2 = str.match(/^(\d+):(\d{1,2})(?:[.,](\d{1,3}))?$/);
  if (match2) {
    const [, m, s, ms] = match2;
    return Number(m) * 60 + Number(s) + Number((ms || "0").padEnd(3, "0")) / 1000;
  }
  const num = parseFloat(str);
  return Number.isNaN(num) ? 0 : num;
}
