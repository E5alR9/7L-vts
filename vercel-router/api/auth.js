/**
 * 帳號 API（中轉站：註冊 / 登入 / 登出 / 我的用量）
 *
 *   POST /api/auth {action:"register", name, password}  → 建 user（初始 0 點，等管理員充值）
 *   POST /api/auth {action:"login", name, password}     → 回 session token（ses_）
 *   POST /api/auth {action:"logout"}                    → 登出（需 session）
 *   GET  /api/auth?action=me                            → 我的帳號+點數（需 user/admin）
 *   GET  /api/auth?action=usage&days=7                  → 我的用量（需 user/admin；admin 可帶 token= 看別人）
 *
 * 規則：
 *   - name 唯一（不分大小寫比對）、2~24 字、限英文數字底線中文
 *   - password 最少 6 字；只存 SHA-256(salt+password)
 *   - 註冊要驗證碼嗎？目前不用（要擋濫註冊時加 INVITE_CODE env 再說）
 */
const store = require("../lib/store");
const { auth, randomToken, hashPassword, newSalt } = require("../lib/auth");

function sendJson(res, status, obj) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(JSON.stringify(obj));
}

function parseBody(req) {
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
      try { resolve(JSON.parse(raw || "{}")); } catch { resolve({}); }
    });
    req.on("error", () => resolve({}));
  });
}

function cleanUser(token, u) {
  return { name: u.name, role: u.role, credits: u.credits,
    usedTokens: u.usedTokens || 0, disabled: !!u.disabled, createdAt: u.createdAt || "" };
}

module.exports = async (req, res) => {
  const url = new URL(req.url, "http://x");
  const body = req.method === "POST" ? await parseBody(req) : {};
  const action = (req.method === "GET" ? url.searchParams.get("action") : body.action) || "me";

  if (!store.hasKV()) {
    return sendJson(res, 503, { ok: false, error: { message: "帳號系統尚未啟用（缺 Redis）" } });
  }

  try {
    // ── 註冊 ──
    if (action === "register") {
      const name = String(body.name || "").trim();
      const password = String(body.password || "");
      if (!/^[\w\u4e00-\u9fff]{2,24}$/.test(name)) {
        return sendJson(res, 400, { ok: false, error: { message: "名稱需 2~24 字（英文數字底線中文）" } });
      }
      if (password.length < 6) {
        return sendJson(res, 400, { ok: false, error: { message: "密碼最少 6 字" } });
      }
      const users = (await store.getUsers()) || {};
      const dup = Object.values(users).some((u) => String(u.name || "").toLowerCase() === name.toLowerCase());
      if (dup) return sendJson(res, 409, { ok: false, error: { message: "這名稱已被註冊" } });
      const token = randomToken("usr");
      const salt = newSalt();
      const session = randomToken("ses");
      users[token] = { name, role: "user", credits: 0,
        passwordHash: hashPassword(password, salt), salt,
        session, usedTokens: 0, createdAt: new Date().toISOString(), disabled: false };
      await store.setUsers(users);
      return sendJson(res, 200, { ok: true, session, user: cleanUser(token, users[token]),
        token, note: "API token 請妥善保存（只顯示這一次）；初始 0 點，請聯繫管理員充值" });
    }

    // ── 登入 ──
    if (action === "login") {
      const name = String(body.name || "").trim().toLowerCase();
      const password = String(body.password || "");
      const users = (await store.getUsers()) || {};
      const found = Object.entries(users).find(([t, u]) => String(u.name || "").toLowerCase() === name);
      if (!found) return sendJson(res, 401, { ok: false, error: { message: "帳號或密碼錯誤" } });
      const [token, u] = found;
      if (u.disabled) return sendJson(res, 403, { ok: false, error: { message: "帳號已停用" } });
      if (!u.passwordHash || hashPassword(password, u.salt || "") !== u.passwordHash) {
        return sendJson(res, 401, { ok: false, error: { message: "帳號或密碼錯誤" } });
      }
      u.session = randomToken("ses");          // 每次登入換新 session
      await store.setUsers(users);
      return sendJson(res, 200, { ok: true, session: u.session, user: cleanUser(token, u) });
    }

    // 以下需登入
    const a = await auth(req);
    if (!a.ok) return sendJson(res, 401, { ok: false, error: { message: "請先登入" } });

    // ── 登出 ──
    if (action === "logout") {
      if (a.session && a.user) {
        const users = (await store.getUsers()) || {};
        if (users[a.user.token]) {
          users[a.user.token].session = "";
          await store.setUsers(users);
        }
      }
      return sendJson(res, 200, { ok: true });
    }

    // ── 每日簽到（加額度；每天一次，寫死一天一次防刷）──
    if (action === "checkin") {
      if (a.kind === "legacy") {
        return sendJson(res, 400, { ok: false, error: { message: "共用入口不支援簽到，請用帳號登入" } });
      }
      if (a.kind === "admin" && !a.user) {
        return sendJson(res, 400, { ok: false, error: { message: "ADMIN_TOKEN 不用簽到" } });
      }
      const today = (() => {
        const t = new Date();
        const p = (n) => String(n).padStart(2, "0");
        return `${t.getFullYear()}-${p(t.getMonth() + 1)}-${p(t.getDate())}`;
      })();
      const users = (await store.getUsers()) || {};
      const u = users[a.user.token];
      if (!u || u.disabled) return sendJson(res, 403, { ok: false, error: { message: "帳號已停用" } });
      if (u.lastCheckin === today) {
        return sendJson(res, 200, { ok: true, checked: false, credits: u.credits,
          message: "今天已簽到過，明天再來" });
      }
      const award = Math.max(1, Number(process.env.CHECKIN_CREDITS) || 100);
      u.lastCheckin = today;
      if (u.credits !== -1) u.credits = (Number(u.credits) || 0) + award;
      await store.setUsers(users);
      return sendJson(res, 200, { ok: true, checked: true, award, credits: u.credits,
        message: `簽到成功 +${award} 點` });
    }

    // ── 我的帳號 ──
    if (action === "me") {
      if (a.kind === "legacy") return sendJson(res, 200, { ok: true, kind: "legacy", note: "共用入口，不扣點" });
      if (a.kind === "admin" && !a.user) {
        return sendJson(res, 200, { ok: true, kind: "admin", name: "ADMIN_TOKEN", note: "最高權限後門" });
      }
      return sendJson(res, 200, { ok: true, kind: a.kind, user: cleanUser(a.user.token, a.user) });
    }

    // ── 用量 ──
    if (action === "usage") {
      const days = url.searchParams.get("days") || body.days;
      const all = await store.getUsage(days);
      const qToken = url.searchParams.get("token") || body.token;
      if (a.kind === "admin" && qToken) {
        // admin 看指定帳號
        const mine = (all || []).map((d) => ({ day: d.day, ...(d.data[qToken] ? d.data[qToken] : { tokens: 0, reqs: 0, models: {} }) }));
        return sendJson(res, 200, { ok: true, usage: mine });
      }
      if (a.kind === "admin" && !qToken) {
        // admin 看全站：按天彙總
        const agg = (all || []).map((d) => {
          let tokens = 0, reqs = 0;
          const users = Object.keys(d.data || {});
          const models = {};
          for (const tk of users) {
            const e = d.data[tk] || {};
            tokens += e.tokens || 0;
            reqs += e.reqs || 0;
            for (const [m, n] of Object.entries(e.models || {})) models[m] = (models[m] || 0) + n;
          }
          return { day: d.day, tokens, reqs, users: users.length, models };
        });
        return sendJson(res, 200, { ok: true, usage: agg });
      }
      if (!a.user) return sendJson(res, 200, { ok: true, usage: [] });
      const mine = (all || []).map((d) => ({ day: d.day, ...(d.data[a.user.token] ? d.data[a.user.token] : { tokens: 0, reqs: 0, models: {} }) }));
      return sendJson(res, 200, { ok: true, usage: mine });
    }

    // ── 兌換邀請碼（加額度；需登入 user）──
    if (action === "invites.redeem") {
      if (a.kind === "legacy" || (a.kind === "admin" && !a.user)) {
        return sendJson(res, 400, { ok: false, error: { message: "此身分不需兌換" } });
      }
      const code = String(body.code || "").trim().toUpperCase();
      if (!code) return sendJson(res, 400, { ok: false, error: { message: "請輸入邀請碼" } });
      const inv = await store.getInvites();
      const v = inv[code];
      if (!v || v.disabled) return sendJson(res, 404, { ok: false, error: { message: "邀請碼無效" } });
      if ((v.used || 0) >= v.maxUses) {
        return sendJson(res, 400, { ok: false, error: { message: "邀請碼已用完" } });
      }
      const users = (await store.getUsers()) || {};
      const u = users[a.user.token];
      if (!u || u.disabled) return sendJson(res, 403, { ok: false, error: { message: "帳號已停用" } });
      v.used = (v.used || 0) + 1;
      if (u.credits !== -1) u.credits = (Number(u.credits) || 0) + v.credits;
      await store.setInvites(inv);
      await store.setUsers(users);
      return sendJson(res, 200, { ok: true, added: v.credits, credits: u.credits,
        message: `兌換成功 +${v.credits} 點` });
    }

    return sendJson(res, 400, { ok: false, error: { message: "未知 action: " + action } });
  } catch (e) {
    return sendJson(res, 500, { ok: false, error: { message: String((e && e.message) || e) } });
  }
};
