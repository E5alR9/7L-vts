/**
 * 本地測試 admin API（無 Redis 模式：status 可讀、寫入類應回 503）
 *   node local-test-admin.js serve   # 只起 server（另開視窗用 curl 測）
 *   node local-test-admin.js         # 起 server + 順序驗證
 */
const http = require("http");
const path = require("path");
const fs = require("fs");

const envPath = path.join(__dirname, "..", ".env");
if (fs.existsSync(envPath)) {
  for (const line of fs.readFileSync(envPath, "utf8").split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/i);
    if (m && !process.env[m[1]]) process.env[m[1]] = m[2].replace(/^["']|["']$/g, "");
  }
}
process.env.ADMIN_TOKEN = process.env.ADMIN_TOKEN || "local-admin-token";
delete process.env.UPSTASH_REDIS_REST_URL;
delete process.env.KV_REST_API_URL;

const admin = require("./api/admin.js");
const health = require("./api/health.js");
const PORT = 8788;

const server = http.createServer((req, res) => {
  const chunks = [];
  req.on("data", (c) => chunks.push(c));
  req.on("end", async () => {
    if (chunks.length) {
      try { req.body = JSON.parse(Buffer.concat(chunks).toString("utf8")); } catch { /* 非 JSON */ }
    }
    const handler = req.url.startsWith("/api/admin") ? admin : health;
    try {
      await handler(req, res);
    } catch (e) {
      res.statusCode = 500;
      res.end(JSON.stringify({ error: String(e) }));
    }
  });
});

function req(method, urlPath, body, token) {
  return new Promise((resolve) => {
    const q = http.request({ host: "127.0.0.1", port: PORT, path: urlPath, method,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` } },
      (resp) => {
        let b = "";
        resp.on("data", (c) => { b += c; });
        resp.on("end", () => {
          let j = {};
          try { j = JSON.parse(b); } catch { /* 非 JSON */ }
          resolve({ status: resp.statusCode, json: j });
        });
      });
    q.on("error", (e) => resolve({ status: "ERR", json: { error: e.message } }));
    q.setTimeout(15000, () => resolve({ status: "TIMEOUT", json: {} }));
    if (body) q.write(JSON.stringify(body));
    q.end();
  });
}

server.on("error", (e) => { console.error("listen 失敗:", e.message); process.exit(1); });
server.listen(PORT, "127.0.0.1", async () => {
  console.log(`測試伺服器已啟動 http://127.0.0.1:${PORT}`);
  if (process.argv.includes("serve")) {
    console.log("serve 模式：保持運行");
    return;
  }
  const A = process.env.ADMIN_TOKEN;
  const t = [];
  let r = await req("GET", "/api/admin?action=status", null, A);
  t.push(["status", r.status === 200 && r.json.kv === false ? "OK" : `FAIL ${r.status}`, `envKeys=${r.json.envKeys}`]);
  r = await req("POST", "/api/admin", { action: "keys.add", key: "gsk_test123" }, A);
  t.push(["keys.add 無KV→503", r.status === 503 ? "OK" : `FAIL ${r.status}`, ""]);
  r = await req("POST", "/api/admin", { action: "users.create", name: "x" }, A);
  t.push(["users.create 無KV→503", r.status === 503 ? "OK" : `FAIL ${r.status}`, ""]);
  r = await req("GET", "/api/health", null, A);
  t.push(["health", r.status === 200 ? "OK" : `FAIL ${r.status}`, `keyCount=${r.json.keyCount}`]);
  r = await req("GET", "/api/admin?action=status", null, "wrong");
  t.push(["未授權→401", r.status === 401 ? "OK" : `FAIL ${r.status}`, ""]);
  let fail = 0;
  for (const [name, info] of t.map(([n, s, i]) => [n, s, i])) {
    if (String(info).startsWith("FAIL")) fail++;
    console.log(`  ${name}: ${info}`);
  }
  console.log(fail ? `❌ ${fail} 項失敗` : "✅ 全部通過");
  server.close();
  setTimeout(() => process.exit(fail ? 1 : 0), 100);
});
