/**
 * lib/auth.js — 帳號、密碼、session、權限
 *
 * 身分（按權限高到低）：
 *   1. ADMIN_TOKEN（env）：最高後門（建第一個 admin、緊急管理）
 *   2. user token role=admin：管理後台全部權限
 *   3. session token：登入後發的瀏覽器憑證（綁定對應 user 的權限）
 *   4. user token role=user：聊天 + 查自己用量，受點數限制
 *   5. ROUTER_TOKEN（舊共用入口）：相容保留，不扣點
 *
 * 密碼：SHA-256(salt + password)，salt 存在 user 物件裡。
 */
const { getUsers } = require("./store");

const crypto = require("crypto");

function adminToken() {
  return process.env.ADMIN_TOKEN || "";
}

function bearer(req) {
  const h = req.headers.authorization || "";
  return h.startsWith("Bearer ") ? h.slice(7) : "";
}

function hashPassword(password, salt) {
  return crypto.createHash("sha256").update(salt + "::" + password).digest("hex");
}

function newSalt() {
  return crypto.randomBytes(16).toString("hex");
}

/**
 * 鑑權。回傳 {ok, kind: 'admin'|'user'|'legacy'|'none', user?}
 */
async function auth(req) {
  const tok = bearer(req);
  if (!tok) return { ok: false, kind: "none" };
  if (adminToken() && tok === adminToken()) return { ok: true, kind: "admin" };
  // session token（gr:sessions:{sid} → user token）
  if (tok.startsWith("ses_")) {
    const users = await getUsers();
    if (users) {
      const entry = Object.entries(users).find(([, u]) => u.session === tok && !u.disabled);
      if (entry) {
        const [userToken, u] = entry;
        return { ok: true, kind: u.role === "admin" ? "admin" : "user",
          user: { token: userToken, ...u }, session: true };
      }
    }
    return { ok: false, kind: "none", reason: "session 已失效" };
  }
  const users = await getUsers();
  if (users && users[tok]) {
    const u = users[tok];
    if (u.disabled) return { ok: false, kind: "none", reason: "帳號已停用" };
    return { ok: true, kind: u.role === "admin" ? "admin" : "user", user: { token: tok, ...u } };
  }
  const legacy = process.env.ROUTER_TOKEN;
  if (legacy && tok === legacy) return { ok: true, kind: "legacy" };
  return { ok: false, kind: "none" };
}

function requireAdmin(a) {
  return a.ok && a.kind === "admin";
}

function randomToken(prefix = "gr") {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789";
  let s = "";
  const buf = crypto.randomBytes(32);
  for (const b of buf) s += chars[b % chars.length];
  return `${prefix}_${s}`;
}

module.exports = { adminToken, bearer, auth, requireAdmin, randomToken, hashPassword, newSalt };
