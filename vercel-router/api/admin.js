/**
 * 管理 API（全部需 admin：ADMIN_TOKEN 或 role=admin 的 user token）
 *
 *   GET  /api/admin?action=status   KV 狀態、keys 數、users 數、點數總覽
 *   POST /api/admin {action:"seed", name?}            建第一個 admin 帳號（限一次，force 可重建）
 *   GET  /api/admin?action=keys     keys 清單（遮蔽顯示）
 *   POST /api/admin {action:"keys.add", key, label?}
 *   POST /api/admin {action:"keys.remove", id}
 *   POST /api/admin {action:"keys.toggle", id, disabled}
 *   GET  /api/admin?action=users    帳號清單
 *   POST /api/admin {action:"users.create", name, role?, credits?}  → 回 token（只顯示一次）
 *   POST /api/admin {action:"users.add-credits", token, delta}
 *   POST /api/admin {action:"users.set", token, fields:{name?,role?,credits?,disabled?}}
 *
 * 無 KV（沒開通 Vercel KV）時：status 回 kv:false，其他寫入類回 503。
 */
const store = require("../lib/store");
const { auth, requireAdmin, randomToken, adminToken } = require("../lib/auth");

function sendJson(res, status, obj) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(JSON.stringify(obj));
}

function parseBody(req) {
  // Vercel 會自動解析 JSON；本地測試 server 也會先塞 req.body
  if (req.body !== undefined) {
    if (typeof req.body === "string") {
      try { return Promise.resolve(JSON.parse(req.body)); } catch { return Promise.resolve({}); }
    }
    return Promise.resolve(req.body || {});
  }
  return new Promise((resolve) => {
    let raw = "";
    req.on("data", (c) => { raw += c; });
    req.on("end", () => {
      if (!raw) return resolve({});
      try { resolve(JSON.parse(raw)); } catch { resolve({ _raw: raw }); }
    });
    req.on("error", () => resolve({}));
  });
}

function keyId(key) {
  const h = require("crypto").createHash("sha256").update(key).digest("hex");
  return "k_" + h.slice(0, 12);
}

module.exports = async (req, res) => {
  const url = new URL(req.url, "http://x");
  const body = req.method === "POST" ? await parseBody(req) : {};
  const action = (req.method === "GET" ? url.searchParams.get("action") : body.action) || "status";
  if (process.env.ADMIN_TEST_LOG) console.log("ADMIN action=", action, "method=", req.method);

  // seed 允許用 ADMIN_TOKEN（還沒有任何 admin 時）
  const a = await auth(req);
  if (!requireAdmin(a)) {
    return sendJson(res, 401, { ok: false, error: { message: "需要管理員權限（ADMIN_TOKEN 或 admin 帳號）" } });
  }

  const needKV = action !== "status";
  if (needKV && !store.hasKV()) {
    return sendJson(res, 503, { ok: false, error: { message: "未接 Redis：到 Vercel Dashboard → Storage → Create → Redis（Marketplace），把 UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN 設進環境變數後重部署" } });
  }

  try {
    // ── 狀態 ──
    if (action === "status") {
      const kv = store.hasKV();
      const users = kv ? await store.getUsers() : null;
      const managed = kv ? await store.getManagedKeys() : null;
      const list = users ? Object.values(users) : [];
      return sendJson(res, 200, { ok: true, kv,
        envKeys: store.envKeys().length,
        managedKeys: managed ? managed.filter((k) => !k.disabled).length : 0,
        users: list.length,
        creditsTotal: list.reduce((s, u) => s + (Number(u.credits) || 0), 0),
        hasAdminToken: Boolean(adminToken()),
      });
    }

    // ── 建第一個 admin ──
    if (action === "seed") {
      const users = (await store.getUsers()) || {};
      const hasAdmin = Object.values(users).some((u) => u.role === "admin" && !u.disabled);
      if (hasAdmin && !body.force) {
        return sendJson(res, 409, { ok: false, error: { message: "已存在 admin 帳號（要重建請帶 force:true）" } });
      }
      const token = randomToken("adm");
      users[token] = { name: String(body.name || "admin"), role: "admin",
        credits: -1, createdAt: new Date().toISOString(), disabled: false };
      await store.setUsers(users);
      await store.markSeeded();
      return sendJson(res, 200, { ok: true, name: users[token].name, role: "admin",
        token, note: "token 只顯示這一次，請妥善保存" });
    }

    // ── keys ──
    if (action === "keys") {
      const managed = (await store.getManagedKeys()) || [];
      return sendJson(res, 200, { ok: true,
        env: store.envKeys().map((k) => ({ id: "env:" + k.slice(-6), prefix: store.mask(k), label: "env", managed: false })),
        managed: managed.map((k) => ({ id: k.id, prefix: k.prefix || store.mask(k.key), label: k.label || "", disabled: !!k.disabled, addedAt: k.addedAt || "" })),
      });
    }
    if (action === "keys.add") {
      const key = String(body.key || "").trim();
      if (!key || !key.startsWith("gsk_")) {
        return sendJson(res, 400, { ok: false, error: { message: "key 格式不對（應為 gsk_ 開頭）" } });
      }
      const managed = (await store.getManagedKeys()) || [];
      if (managed.some((k) => k.key === key) || store.envKeys().includes(key)) {
        return sendJson(res, 409, { ok: false, error: { message: "這把 key 已存在" } });
      }
      managed.push({ id: keyId(key), prefix: store.mask(key), key,
        label: String(body.label || ""), addedAt: new Date().toISOString(), disabled: false });
      await store.setManagedKeys(managed);
      return sendJson(res, 200, { ok: true, count: managed.length });
    }
    if (action === "keys.remove") {
      const managed = ((await store.getManagedKeys()) || []).filter((k) => k.id !== body.id);
      await store.setManagedKeys(managed);
      return sendJson(res, 200, { ok: true, count: managed.length });
    }
    if (action === "keys.toggle") {
      const managed = (await store.getManagedKeys()) || [];
      const k = managed.find((x) => x.id === body.id);
      if (!k) return sendJson(res, 404, { ok: false, error: { message: "找不到這把 key" } });
      k.disabled = body.disabled !== false;
      await store.setManagedKeys(managed);
      return sendJson(res, 200, { ok: true, disabled: k.disabled });
    }

    // ── users ──
    if (action === "users") {
      const users = (await store.getUsers()) || {};
      const list = Object.entries(users).map(([token, u]) => ({
        token, name: u.name, role: u.role, credits: u.credits,
        plan: u.plan || "free", monthlyQuota: u.monthlyQuota || 0,
        disabled: !!u.disabled, createdAt: u.createdAt || "",
      }));
      return sendJson(res, 200, { ok: true, users: list });
    }
    if (action === "users.create") {
      const name = String(body.name || "").trim();
      if (!name) return sendJson(res, 400, { ok: false, error: { message: "name 不可為空" } });
      const role = body.role === "admin" ? "admin" : "user";
      const credits = body.credits === undefined ? 10000 : Number(body.credits);
      if (!Number.isFinite(credits) || (credits < 0 && credits !== -1)) {
        return sendJson(res, 400, { ok: false, error: { message: "credits 需為 >=0 的數字（-1 = 無限）" } });
      }
      const token = randomToken(role === "admin" ? "adm" : "usr");
      const users = (await store.getUsers()) || {};
      users[token] = { name, role, credits, createdAt: new Date().toISOString(), disabled: false };
      await store.setUsers(users);
      return sendJson(res, 200, { ok: true, name, role, credits, token, note: "token 只顯示這一次" });
    }
    if (action === "users.add-credits") {
      const users = (await store.getUsers()) || {};
      const u = users[body.token];
      if (!u) return sendJson(res, 404, { ok: false, error: { message: "找不到帳號" } });
      const delta = Number(body.delta);
      if (!Number.isFinite(delta)) return sendJson(res, 400, { ok: false, error: { message: "delta 需為數字" } });
      if (u.credits === -1) return sendJson(res, 200, { ok: true, credits: -1, note: "無限點數帳號" });
      u.credits = Math.max(0, (Number(u.credits) || 0) + delta);
      await store.setUsers(users);
      return sendJson(res, 200, { ok: true, credits: u.credits });
    }
    if (action === "users.set") {
      const users = (await store.getUsers()) || {};
      const u = users[body.token];
      if (!u) return sendJson(res, 404, { ok: false, error: { message: "找不到帳號" } });
      const f = body.fields || {};
      if (f.name !== undefined) u.name = String(f.name);
      if (f.role === "admin" || f.role === "user") u.role = f.role;
      if (f.credits !== undefined) {
        const c = Number(f.credits);
        if (!Number.isFinite(c) || (c < 0 && c !== -1)) {
          return sendJson(res, 400, { ok: false, error: { message: "credits 需為 >=0（-1 = 無限）" } });
        }
        u.credits = c;
      }
      if (f.disabled !== undefined) u.disabled = !!f.disabled;
      if (f.plan !== undefined) u.plan = String(f.plan || "free");       // 方案名（free/月費方案名）
      if (f.monthlyQuota !== undefined) {
        const q = Number(f.monthlyQuota);
        if (!Number.isFinite(q) || q < 0) {
          return sendJson(res, 400, { ok: false, error: { message: "monthlyQuota 需為 >=0（0=無月補）" } });
        }
        u.monthlyQuota = q;
      }
      await store.setUsers(users);
      return sendJson(res, 200, { ok: true, user: { name: u.name, role: u.role, credits: u.credits,
        disabled: !!u.disabled, plan: u.plan || "free", monthlyQuota: u.monthlyQuota || 0 } });
    }
    if (action === "users.delete") {
      // 真刪（KV 移除）。admin 帳號至少要留一個。
      const users = (await store.getUsers()) || {};
      const u = users[body.token];
      if (!u) return sendJson(res, 404, { ok: false, error: { message: "找不到帳號" } });
      if (u.role === "admin" && !u.disabled) {
        const admins = Object.values(users).filter((x) => x.role === "admin" && !x.disabled);
        if (admins.length <= 1) {
          return sendJson(res, 400, { ok: false, error: { message: "不能刪除最後一個啟用中的 admin" } });
        }
      }
      delete users[body.token];
      await store.setUsers(users);
      return sendJson(res, 200, { ok: true });
    }
    if (action === "users.set-password") {
      // 幫帳號設/重設密碼（含 admin 自己的 E5alR9）
      const { hashPassword, newSalt } = require("../lib/auth");
      const users = (await store.getUsers()) || {};
      const u = users[body.token];
      if (!u) return sendJson(res, 404, { ok: false, error: { message: "找不到帳號" } });
      const pw = String(body.password || "");
      if (pw.length < 6) return sendJson(res, 400, { ok: false, error: { message: "密碼最少 6 字" } });
      const salt = newSalt();
      u.salt = salt;
      u.passwordHash = hashPassword(pw, salt);
      u.session = "";                    // 換密碼即登出所有 session
      await store.setUsers(users);
      return sendJson(res, 200, { ok: true });
    }

    // ── 邀請碼（加額度用，不是擋註冊）──
    if (action === "invites") {
      const inv = await store.getInvites();
      const list = Object.entries(inv).map(([code, v]) => ({
        code, credits: v.credits, maxUses: v.maxUses, used: v.used || 0,
        disabled: !!v.disabled, createdAt: v.createdAt || "",
      }));
      return sendJson(res, 200, { ok: true, invites: list });
    }
    if (action === "invites.create") {
      const credits = Number(body.credits);
      const maxUses = body.maxUses === undefined ? 1 : Number(body.maxUses);
      if (!Number.isFinite(credits) || credits <= 0) {
        return sendJson(res, 400, { ok: false, error: { message: "credits 需為正數" } });
      }
      if (!Number.isFinite(maxUses) || maxUses < 1 || maxUses > 10000) {
        return sendJson(res, 400, { ok: false, error: { message: "maxUses 需為 1~10000" } });
      }
      const inv = await store.getInvites();
      let code = store.newInviteCode();
      while (inv[code]) code = store.newInviteCode();
      inv[code] = { credits, maxUses, used: 0,
        createdBy: (a.user && a.user.name) || "ADMIN_TOKEN",
        createdAt: new Date().toISOString(), disabled: false };
      await store.setInvites(inv);
      return sendJson(res, 200, { ok: true, code, credits, maxUses });
    }
    if (action === "invites.toggle") {
      const inv = await store.getInvites();
      const v = inv[body.code];
      if (!v) return sendJson(res, 404, { ok: false, error: { message: "找不到邀請碼" } });
      v.disabled = body.disabled !== false;
      await store.setInvites(inv);
      return sendJson(res, 200, { ok: true, disabled: v.disabled });
    }
    if (action === "invites.delete") {
      const inv = await store.getInvites();
      if (!inv[body.code]) return sendJson(res, 404, { ok: false, error: { message: "找不到邀請碼" } });
      delete inv[body.code];
      await store.setInvites(inv);
      return sendJson(res, 200, { ok: true });
    }

    // ── 請求日誌（最新 100 筆）──
    if (action === "logs") {
      const logs = await store.getLogs();
      return sendJson(res, 200, { ok: true, logs });
    }

    // ── 計費表（模型倍率；扣點 = tokens × 倍率）──
    if (action === "pricing") {
      const pricing = await store.getPricing();
      return sendJson(res, 200, { ok: true, pricing, defaults: store.DEFAULT_PRICING });
    }
    if (action === "pricing.set") {
      const p = body.pricing || {};
      const clean = {};
      for (const [m, mult] of Object.entries(p)) {
        const v = Number(mult);
        if (typeof m !== "string" || !m || !Number.isFinite(v) || v <= 0 || v > 100) {
          return sendJson(res, 400, { ok: false, error: { message: `倍率不合法: ${m}=${mult}（需 0~100）` } });
        }
        clean[m] = v;
      }
      const cur = await store.getPricing();
      await store.setPricing({ ...cur, ...clean });
      return sendJson(res, 200, { ok: true, pricing: await store.getPricing() });
    }
    if (action === "pricing.reset") {
      await store.setPricing({ ...store.DEFAULT_PRICING });
      return sendJson(res, 200, { ok: true, pricing: await store.getPricing() });
    }

    return sendJson(res, 400, { ok: false, error: { message: "未知 action: " + action } });
  } catch (e) {
    return sendJson(res, 500, { ok: false, error: { message: String((e && e.message) || e) } });
  }
};
