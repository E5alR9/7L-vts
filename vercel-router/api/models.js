/**
 * GET /v1/models — 全模型中轉：直通 Groq 完整目錄（6h 快取 + 靜態兜底）
 * 任何登入身分可用；音訊模型（whisper/tts）也照轉，聊天端點用到才會上游報錯。
 */
const MODELS_URL = "https://api.groq.com/openai/v1/models";

const store = require("../lib/store");
const libAuth = require("../lib/auth");

// warm instance 記憶體快取（cold start 重新抓）
let CACHE = { at: 0, text: "" };
const TTL = 6 * 3600 * 1000;

function staticFallback() {
  // 上游掛了的最後手段：本側已知價目當目錄
  return JSON.stringify({
    object: "list",
    data: Object.keys(store.MODEL_PRICES).map((id) => ({ id, object: "model",
      owned_by: store.NV_CHAT_MODELS[id] ? "nvidia" : "groq" })),
  });
}

function reply(res, status, text) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(text);
}

module.exports = async (req, res) => {
  if (req.method !== "GET") return reply(res, 405, JSON.stringify({ error: "GET only" }));

  const a = await libAuth.auth(req);
  if (!a.ok) return reply(res, 401, JSON.stringify({ error: { message: "unauthorized" } }));

  // 快取有效 → 直接回
  if (CACHE.text && Date.now() - CACHE.at < TTL) return reply(res, 200, CACHE.text);

  const keys = (await store.allKeys()).map((k) => k.key);
  if (!keys.length) return reply(res, 500, JSON.stringify({ error: { message: "未設定 GROQ_KEYS" } }));

  try {
    const upstream = await fetch(MODELS_URL, { headers: { Authorization: `Bearer ${keys[0]}` } });
    let text = await upstream.text();
    if (upstream.ok) {
      // 併入 NVIDIA 直連模型（靜態清單，不打上游）
      try {
        const j = JSON.parse(text);
        if (j && Array.isArray(j.data)) {
          const have = new Set(j.data.map((m) => m.id));
          for (const id of Object.keys(store.NV_CHAT_MODELS)) {
            if (!have.has(id)) j.data.push({ id, object: "model", owned_by: "nvidia" });
          }
          text = JSON.stringify(j);
        }
      } catch { /* 解析失敗就原樣回傳 */ }
      CACHE = { at: Date.now(), text };
      return reply(res, 200, text);
    }
    // 上游非 2xx：有舊快取就給舊的（比直接炸掉好），否則照轉錯誤
    if (CACHE.text) return reply(res, 200, CACHE.text);
    return reply(res, upstream.status, text);
  } catch {
    // 網路炸 → 快取 or 靜態目錄
    if (CACHE.text) return reply(res, 200, CACHE.text);
    return reply(res, 200, staticFallback());
  }
};
