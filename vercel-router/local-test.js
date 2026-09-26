/**
 * 本地冒煙測試：不起 Vercel，直接用 http 伺服器包裝 handler，
 * 從 ai_vtuber/.env 讀金鑰，打一次真實 Groq 請求（含串流）。
 *
 *   node local-test.js            # 非串流
 *   node local-test.js stream     # 串流
 */
const http = require("http");
const fs = require("fs");
const path = require("path");

// 從主專案 .env 載入金鑰（只在本地測試這樣做；上雲端改用 vercel env）
const envPath = path.join(__dirname, "..", ".env");
if (fs.existsSync(envPath)) {
  for (const line of fs.readFileSync(envPath, "utf8").split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/i);
    if (m && !process.env[m[1]]) process.env[m[1]] = m[2].replace(/^["']|["']$/g, "");
  }
}
process.env.ROUTER_TOKEN = process.env.ROUTER_TOKEN || "local-test-token";

const handler = require("./api/chat.js");
const stream = process.argv.includes("stream");

const server = http.createServer((req, res) => {
  // 模擬 Vercel 的 body 解析
  const chunks = [];
  req.on("data", (c) => chunks.push(c));
  req.on("end", async () => {
    if (chunks.length) {
      const raw = Buffer.concat(chunks).toString("utf8");
      try {
        req.body = JSON.parse(raw);
      } catch {
        req.body = raw;
      }
    }
    try {
      await handler(req, res);
    } catch (e) {
      res.statusCode = 500;
      res.end(JSON.stringify({ error: String(e) }));
    }
  });
});

server.listen(8787, async () => {
  const t0 = Date.now();
  const r = await fetch("http://127.0.0.1:8787/", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${process.env.ROUTER_TOKEN}`,
    },
    body: JSON.stringify({
      model: "qwen/qwen3.8-27b",
      messages: [
        { role: "system", content: "你是虛擬主播 7L，回覆 15 字內中文。" },
        { role: "user", content: "打聲招呼" },
      ],
      max_tokens: 60,
      stream,
    }),
  });

  console.log(`HTTP ${r.status}  model=${r.headers.get("x-router-model")} key#${r.headers.get("x-router-key-index")}/${r.headers.get("x-router-key-count")}`);

  if (stream) {
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let first = null;
    let text = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      const s = dec.decode(value, { stream: true });
      if (first === null && s.trim()) first = Date.now() - t0;
      text += s;
      process.stdout.write(s);
    }
    console.log(`\n首塊延遲 ${first}ms  總耗時 ${Date.now() - t0}ms`);
  } else {
    const j = await r.json();
    console.log(`回覆: ${(j.choices?.[0]?.message?.content || JSON.stringify(j)).slice(0, 120)}`);
    console.log(`耗時 ${Date.now() - t0}ms  usage=${JSON.stringify(j.usage || {})}`);
  }
  server.close();
  // Node 24/Windows: process.exit() 會撞 UV_HANDLE_CLOSING 斷言，改用自然結束
  setTimeout(() => process.exit(0), 100);
});
