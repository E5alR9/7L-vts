/**
 * GET /api/health — 冒煙測試用。只回統計數字，不回任何金鑰內容。
 */
const store = require("../lib/store");

module.exports = async (req, res) => {
  const keys = await store.allKeys();
  const kv = store.hasKV();
  let users = 0;
  if (kv) {
    try {
      const u = (await store.getUsers()) || {};
      users = Object.keys(u).length;
    } catch { /* 忽略 */ }
  }
  res.statusCode = 200;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(
    JSON.stringify({
      ok: true,
      hasRouterToken: Boolean(process.env.ROUTER_TOKEN),
      hasAdminToken: Boolean(process.env.ADMIN_TOKEN),
      kv: kv,
      keyCount: keys.length,
      users: users,
      keyPrefixes: [...new Set(keys.map((k) => (k.key || "").slice(0, 4)))],
      ladder: (process.env.MODEL_LADDER || "qwen/qwen3.8-27b,openai/gpt-oss-120b,openai/gpt-oss-20b,allam-2-7b")
        .split(/[\s,;]+/)
        .filter(Boolean),
      time: new Date().toISOString(),
    })
  );
};
