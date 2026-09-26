/**
 * GET /v1/models — 轉發 Groq 的模型清單（讓 OpenAI 相容客戶端的「列出模型」功能可用）
 */
const MODELS_URL = "https://api.groq.com/openai/v1/models";

const store = require("../lib/store");
const libAuth = require("../lib/auth");

module.exports = async (req, res) => {
  if (req.method !== "GET") {
    res.statusCode = 405;
    return res.end(JSON.stringify({ error: "GET only" }));
  }

  const a = await libAuth.auth(req);
  if (!a.ok) {
    res.statusCode = 401;
    res.setHeader("Content-Type", "application/json");
    return res.end(JSON.stringify({ error: { message: "unauthorized" } }));
  }

  const keys = (await store.allKeys()).map((k) => k.key);
  if (!keys.length) {
    res.statusCode = 500;
    res.setHeader("Content-Type", "application/json");
    return res.end(JSON.stringify({ error: { message: "未設定 GROQ_KEYS" } }));
  }

  const upstream = await fetch(MODELS_URL, { headers: { Authorization: `Bearer ${keys[0]}` } });
  const text = await upstream.text();
  res.statusCode = upstream.status;
  res.setHeader("Content-Type", upstream.headers.get("content-type") || "application/json");
  res.end(text);
};
