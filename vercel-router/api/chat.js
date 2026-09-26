/**
 * Groq 小型轉發器 — Vercel Serverless Function
 *
 * 🎯 目的：
 *    把 28 把 Groq 金鑰收在 Vercel 環境變數裡，對外只暴露一個入口 token。
 *    多台機器 / 多支 bot 共用同一批金鑰，金鑰本體不外流。
 *
 * ⚙️ 行為（與本機 core/groq_router.py 同邏輯的精簡版）：
 *    1. 金鑰 round-robin 輪替
 *    2. 逐金鑰冷卻：429 → 60s、401/403 → 10min、5xx → 30s
 *    3. 模型梯隊：主模型 404 / model_not_found 時自動降到下一階
 *    4. 串流（stream:true）原樣轉發，不在這裡 buffer
 *
 * 端點（OpenAI 相容，見 vercel.json 的 rewrite）：
 *    POST /v1/chat/completions
 *    GET  /v1/models
 *    GET  /api/health
 */

const GROQ_URL = "https://api.groq.com/openai/v1/chat/completions";
const MODELS_URL = "https://api.groq.com/openai/v1/models";

const store = require("../lib/store");
const libAuth = require("../lib/auth");

// 與本機 router 同步的模型梯隊（本帳號實際存在的 4 個聊天模型）
const DEFAULT_LADDER = [
  "qwen/qwen3.8-27b",
  "openai/gpt-oss-120b",
  "openai/gpt-oss-20b",
  "allam-2-7b",
];

// 逐金鑰冷卻（毫秒）
const COOLDOWN_MS = { 401: 600_000, 403: 600_000, 429: 60_000, 400: 0, 500: 30_000, 502: 30_000, 503: 30_000 };

// 模組層狀態：同一個 warm instance 之間保留（cold start 會清空，無妨）
const STATE = { cursor: 0, cooldownUntil: new Map() };

function loadLadder() {
  const raw = (process.env.MODEL_LADDER || "").trim();
  const list = raw ? raw.split(/[\s,;]+/).filter(Boolean) : [];
  return list.length ? list : DEFAULT_LADDER;
}

function isCooling(i) {
  const until = STATE.cooldownUntil.get(i);
  return until !== undefined && Date.now() < until;
}

function cool(i, status) {
  const ms = COOLDOWN_MS[status];
  if (ms > 0) STATE.cooldownUntil.set(i, Date.now() + ms);
}

/** 取下一把可用金鑰的索引（round-robin，跳過冷卻中的）；全冷卻時回傳最久之後解凍的 */
function nextKey(total) {
  const now = Date.now();
  let best = -1;
  let bestUntil = Infinity;
  for (let n = 0; n < total; n++) {
    const i = (STATE.cursor + n) % total;
    const until = STATE.cooldownUntil.get(i);
    if (until === undefined || now >= until) {
      STATE.cursor = (i + 1) % total;
      return i;
    }
    if (until < bestUntil) {
      bestUntil = until;
      best = i;
    }
  }
  return best; // 全部冷卻中 → 用最接近解凍的那把硬試
}

function sendJson(res, status, obj) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(JSON.stringify(obj));
}

function checkAuth(req, res) {
  // 舊共用入口（相容保留，不扣點）。新用戶請用 /api/admin 發的 user token。
  const want = process.env.ROUTER_TOKEN;
  const got = req.headers.authorization || "";
  if (want && got === `Bearer ${want}`) return { kind: "legacy" };
  return null;
}

/** 從回應 usage 估點數（total_tokens；拿不到時按字數粗估） */
function estimateCost(body, text) {
  try {
    const j = JSON.parse(text);
    const u = j.usage || {};
    if (Number.isFinite(u.total_tokens) && u.total_tokens > 0) return u.total_tokens;
  } catch { /* 非 JSON */ }
  const input = JSON.stringify(body.messages || body.input || "").length;
  return Math.max(1, Math.ceil(input / 4) + 50);
}

module.exports = async (req, res) => {
  if (req.method !== "POST") return sendJson(res, 405, { error: { message: "POST only" } });

  // 鑑權：admin / user token / 舊共用入口
  let caller = checkAuth(req, res);
  if (!caller) {
    const a = await libAuth.auth(req);
    if (!a.ok) return sendJson(res, 401, { error: { message: "unauthorized" } });
    // admin 也能直接聊天（不扣點）
    caller = { kind: a.kind, user: a.user };
  }
  // user 帳號：訂閱月補（當月首次自動補點）→ 點數預檢（-1 = 無限）
  if (caller.kind === "user" && caller.user) {
    try {
      const users = (await store.getUsers()) || {};
      if (users[caller.user.token] && await store.ensureMonthlyQuota(users, caller.user.token)) {
        await store.setUsers(users);
        caller.user.credits = users[caller.user.token].credits;
      }
    } catch { /* 月補失敗不擋路 */ }
  }
  if (caller.kind === "user" && caller.user.credits !== -1 && (Number(caller.user.credits) || 0) <= 0) {
    return sendJson(res, 402, { error: { message: "點數不足，請聯繫管理員充值", code: "insufficient_credits" } });
  }

  const keyObjs = await store.allKeys();
  const keys = keyObjs.map((k) => k.key);
  if (!keys.length) return sendJson(res, 500, { error: { message: "未設定 GROQ_KEYS" } });

  let body = req.body;
  if (typeof body === "string") {
    try {
      body = JSON.parse(body);
    } catch {
      return sendJson(res, 400, { error: { message: "invalid JSON body" } });
    }
  }
  body = body || {};

  // 梯隊：呼叫端指定的模型優先，失敗再依序降級
  const requested = typeof body.model === "string" && body.model.trim() ? body.model.trim() : "";
  const ladder = requested ? [requested, ...loadLadder().filter((m) => m !== requested)] : loadLadder();
  const wantStream = body.stream === true;

  let lastError = { status: 502, payload: { error: { message: "all keys/models exhausted" } } };

  for (const model of ladder) {
    let modelDead = false;

    for (let tries = 0; tries < keys.length && !modelDead; tries++) {
      const idx = nextKey(keys.length);
      if (idx < 0) break;

      const init = {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${keys[idx]}`,
        },
        body: JSON.stringify({ ...body, model }),
      };

      let upstream;
      try {
        upstream = await fetch(GROQ_URL, init);
      } catch (e) {
        cool(idx, 503);
        lastError = { status: 502, payload: { error: { message: `network: ${e.message}` } } };
        continue;
      }

      if (upstream.ok) {
        res.setHeader("x-router-model", model);
        res.setHeader("x-router-key-index", String(idx));
        res.setHeader("x-router-key-count", String(keys.length));

        // user 帳號扣點（admin/legacy 不扣；-1 無限不扣）——見下方各分支內聯實作
        // （扣點必須在 res.end() 之前完成，否則 x-credits-left 發不出去）

        if (wantStream) {
          // 串流按請求字數預估先扣（header 要在 end 前設）
          if (caller.kind === "user" && caller.user.credits !== -1) {
            try {
              const users = (await store.getUsers()) || {};
              const u = users[caller.user.token];
              if (u && u.credits !== -1) {
                const cost = Math.ceil(estimateCost(body, "") * store.priceFor(await store.getPricing(), model));
                u.credits = Math.max(0, (Number(u.credits) || 0) - cost);
                u.usedTokens = (Number(u.usedTokens) || 0) + cost;
                await store.setUsers(users);
                res.setHeader("x-credits-left", String(u.credits));
                await store.recordUsage(caller.user.token, model, cost);
                await store.logRequest({ user: caller.user.name || caller.user.token.slice(0, 12),
                  model, tokens: cost, cost });
              }
            } catch { /* 忽略 */ }
          }
          res.statusCode = 200;
          res.setHeader("Content-Type", upstream.headers.get("content-type") || "text/event-stream");
          res.setHeader("Cache-Control", "no-cache");
          res.setHeader("Connection", "keep-alive");
          res.flushHeaders?.();
          try {
            for await (const chunk of upstream.body) res.write(Buffer.from(chunk));
          } catch {
            // 上游中斷就直接收尾，客戶端會看到不完整的 SSE
          }
          res.end();
          return;
        }

        const text = await upstream.text();
        const cost = Math.ceil(estimateCost(body, text) * store.priceFor(await store.getPricing(), model));
        // 先扣點再 end（header 必須在 end 之前設，否則發不出去）
        if (caller.kind === "user" && caller.user.credits !== -1) {
          try {
            const users = (await store.getUsers()) || {};
            const u = users[caller.user.token];
            if (u && u.credits !== -1) {
              u.credits = Math.max(0, (Number(u.credits) || 0) - cost);
              u.usedTokens = (Number(u.usedTokens) || 0) + cost;
              await store.setUsers(users);
              res.setHeader("x-credits-left", String(u.credits));
              await store.recordUsage(caller.user.token, model, cost);
              await store.logRequest({ user: caller.user.name || caller.user.token.slice(0, 12),
                model, tokens: cost, cost });
            }
          } catch { /* 扣點失敗不影響已生成的回應 */ }
        }
        res.statusCode = 200;
        res.setHeader("Content-Type", "application/json; charset=utf-8");
        res.end(text);
        return;
      }

      // 非 2xx：判斷是「這把金鑰的問題」還是「這個模型的問題」
      const status = upstream.status;
      let payload = {};
      try {
        payload = await upstream.json();
      } catch {
        /* 非 JSON */
      }
      const msg = (payload && payload.error && payload.error.message) || "";
      cool(idx, status);
      lastError = { status: status === 404 ? 502 : status, payload: payload || { error: { message: `HTTP ${status}` } } };

      // 模型不存在 / 模型名錯誤 → 換下一階模型（跟金鑰無關，繼續敲同一把也沒用）
      if (status === 404 || /model.*not.*found|does not exist|decommissioned/i.test(msg)) {
        modelDead = true;
      }
      // 401/403/429 → 該把已冷卻，換下一把
    }

    if (modelDead) continue; // 換下一階模型
    // 不是 modelDead（例如全部金鑰都被 429 擋住）→ 等下一次請求再試同一階
  }

  return sendJson(res, lastError.status, lastError.payload);
};
