/**
 * lib/store.js — 持久層抽象（Vercel KV 可選；沒有 KV 時退回 env 唯讀模式）
 *
 * 資料模型（KV hash/key）：
 *   gr:keys              JSON array [{id, prefix, key, label, addedAt, disabled}]
 *   gr:users             JSON object {token: {name, role, credits, createdAt}}
 *   gr:meta              JSON {seeded: true}
 *
 * 有 KV：完整 CRUD + 點數扣減。
 * 無 KV：keys 只讀 env（管理 API 回 503 + 提示開通 KV），users 不可用。
 */
let _kv = null;
let _kvTried = false;

function kv() {
  if (_kvTried) return _kv;
  _kvTried = true;
  try {
    // Upstash Redis（Vercel Marketplace → Storage → Redis，自動注入環境變數）。
    // 沒配時拋錯 → 走 env 唯讀模式。
    const { Redis } = require("@upstash/redis");
    const url = process.env.UPSTASH_REDIS_REST_URL || process.env.KV_REST_API_URL;
    const token = process.env.UPSTASH_REDIS_REST_TOKEN || process.env.KV_REST_API_TOKEN;
    if (!url || !token) return null;
    _kv = new Redis({ url, token });
  } catch {
    _kv = null;
  }
  return _kv;
}

function hasKV() {
  return Boolean(kv());
}

/** env 來的 Groq keys（唯讀基底；KV 有額外 keys 時合併） */
function envKeys() {
  const set = new Set();
  const raw = process.env.GROQ_KEYS || process.env.GROQ_KEY || process.env.GROQ_API_KEYS || "";
  for (const k of raw.split(/[\s,;]+/)) if (k.trim()) set.add(k.trim());
  for (let i = 1; i <= 64; i++) {
    const v = process.env[`GROQ_KEY_${i}`];
    if (v && v.trim()) set.add(v.trim());
  }
  return [...set];
}

function mask(key) {
  if (!key || key.length < 10) return "***";
  return key.slice(0, 7) + "…" + key.slice(-4);
}

async function getManagedKeys() {
  const k = kv();
  if (!k) return null;
  try {
    const raw = await k.get("gr:keys");
    if (!raw) return [];
    return typeof raw === "string" ? JSON.parse(raw) : raw;
  } catch {
    return [];
  }
}

async function setManagedKeys(list) {
  const k = kv();
  if (!k) throw new Error("NO_KV");
  await k.set("gr:keys", JSON.stringify(list));
}

/** 全部可用 keys = env 基底 + KV 管理的（disabled 跳過，去重） */
async function allKeys() {
  const base = envKeys().map((key) => ({ id: "env:" + key.slice(-6), prefix: mask(key), key, label: "env", managed: false }));
  const managed = (await getManagedKeys()) || [];
  const seen = new Set(base.map((k) => k.key));
  const extra = managed.filter((k) => !k.disabled && k.key && !seen.has(k.key)).map((k) => ({ ...k, managed: true }));
  return [...base, ...extra];
}

async function getUsers() {
  const k = kv();
  if (!k) return null;
  try {
    const raw = await k.get("gr:users");
    if (!raw) return {};
    return typeof raw === "string" ? JSON.parse(raw) : raw;
  } catch {
    return {};
  }
}

async function setUsers(users) {
  const k = kv();
  if (!k) throw new Error("NO_KV");
  await k.set("gr:users", JSON.stringify(users));
}

async function isSeeded() {
  const k = kv();
  if (!k) return false;
  try {
    const raw = await k.get("gr:meta");
    const meta = typeof raw === "string" ? JSON.parse(raw) : raw;
    return Boolean(meta && meta.seeded);
  } catch {
    return false;
  }
}

async function markSeeded() {
  const k = kv();
  if (!k) throw new Error("NO_KV");
  await k.set("gr:meta", JSON.stringify({ seeded: true, at: new Date().toISOString() }));
}

/** 渠道：gr:channels JSON {id: {name, keys:[完整key], weight, models, disabled, createdAt}}
 *  聊天路由：按 weight 選渠道 → 渠道內輪 key。預設渠道 default（env 來的 keys）。 */
async function getChannels() {
  const k = kv();
  if (!k) return null;
  try {
    const raw = await k.get("gr:channels");
    return raw ? (typeof raw === "string" ? JSON.parse(raw) : raw) : {};
  } catch {
    return {};
  }
}

async function setChannels(ch) {
  const k = kv();
  if (!k) throw new Error("NO_KV");
  await k.set("gr:channels", JSON.stringify(ch));
}

function newChannelId() {
  return "ch_" + require("crypto").randomBytes(6).toString("hex");
}

/** 選渠道：啟用的、支援該模型的，按 weight 加權隨機 */
function pickChannel(channels, model) {
  const list = Object.entries(channels || {})
    .filter(([, c]) => !c.disabled && (c.keys || []).length > 0)
    .filter(([, c]) => !(c.models || []).length || (c.models || []).includes(model));
  if (!list.length) return null;
  const total = list.reduce((s, [, c]) => s + Math.max(1, Number(c.weight) || 1), 0);
  let r = Math.random() * total;
  for (const [id, c] of list) {
    r -= Math.max(1, Number(c.weight) || 1);
    if (r <= 0) return { id, ...c };
  }
  const [id, c] = list[list.length - 1];
  return { id, ...c };
}
async function getInvites() {
  const k = kv();
  if (!k) throw new Error("NO_KV");
  try {
    const raw = await k.get("gr:invites");
    return raw ? (typeof raw === "string" ? JSON.parse(raw) : raw) : {};
  } catch {
    return {};
  }
}

async function setInvites(inv) {
  const k = kv();
  if (!k) throw new Error("NO_KV");
  await k.set("gr:invites", JSON.stringify(inv));
}

function newInviteCode() {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const b = require("crypto").randomBytes(6);
  let s = "";
  for (const x of b) s += chars[x % chars.length];
  return s.slice(0, 4) + "-" + s.slice(4);
}

/** 點數匯率：1 點 = US$1（1:1 · 使用者指定；env POINTS_PER_USD 可覆寫）
 *  計費 = 實際美元價直接扣（保留6位小數，不再進位到整數）——
 *  一發小對話 ≈ $0.00007 = 0.00007 點，餘額不會被整數進位打爆 */
const POINTS_PER_USD = Number(process.env.POINTS_PER_USD) || 1;

/** 計費表 = 促銷係數（1 = 官方價直轉；<1 折扣、>1 加價）
 *  版本標記 __v：不符即作廢回預設 ×1（v3 = 對齊 docs 現行11模型；涵蓋舊10/2/1倍率表） */
const DEFAULT_PRICING = {
  "qwen/qwen3.8-27b": 1,
  "openai/gpt-oss-120b": 1,
  "openai/gpt-oss-20b": 1,
  "allam-2-7b": 1,
  "deepseek-ai/deepseek-v4.1-flash": 1,
  "z-ai/glm-5.3-flash": 1,
  "openai/gpt-oss-safeguard-20b": 1,
  "meta-llama/llama-prompt-guard-2-22m": 1,
  "meta-llama/llama-prompt-guard-2-86m": 1,
  "whisper-large-v3": 1,
  "whisper-large-v3-turbo": 1,
  "canopylabs/orpheus-v1-english": 1,
  "canopylabs/orpheus-arabic-saudi": 1,
  "nvidia/nemotron-3-embed-1b": 1,
};
const PRICING_VERSION = 3;

async function getPricing() {
  const k = kv();
  if (!k) return { ...DEFAULT_PRICING };
  try {
    const raw = await k.get("gr:pricing");
    const p = raw ? (typeof raw === "string" ? JSON.parse(raw) : raw) : null;
    if (!p || p.__v !== PRICING_VERSION) return { ...DEFAULT_PRICING };   // 舊版倍率表作廢
    const out = { ...p };
    delete out.__v;
    return { ...DEFAULT_PRICING, ...out };
  } catch {
    return { ...DEFAULT_PRICING };
  }
}

async function setPricing(p) {
  const k = kv();
  if (!k) throw new Error("NO_KV");
  await k.set("gr:pricing", JSON.stringify({ ...p, __v: PRICING_VERSION }));
}

function priceFor(pricing, model) {
  const m = Number(pricing[model]);
  return Number.isFinite(m) && m > 0 ? m : 1;
}

/** 直接按官方價算扣點：
 *  usd = (pt × input + ct × output) / 1e6 × 促銷係數；轉點後至少 1 點（$0 模型 = 免費0點） */
function costFor(model, pt, ct, pricing) {
  const mp = MODEL_PRICES[model];
  const mult = priceFor(pricing || {}, model);
  let usd;
  if (mp) usd = (Math.max(0, pt) * mp.input + Math.max(0, ct) * mp.output) / 1e6;
  else usd = ((Math.max(0, pt) + Math.max(0, ct)) * 0.075) / 1e6;   // 未列模型 → 按基準價
  usd *= mult;
  if (usd <= 0) return 0;
  const pts = usd * POINTS_PER_USD;                       // 1:1 → pts = usd
  return Math.max(0.000001, Math.round(pts * 1e6) / 1e6); // 小數6位精準扣，最小單位 $0.000001
}

/** 請求日誌：gr:logs JSON array（最新在前，只留 100 筆）
 *  entry = {t, user, model, tokens, cost} */
async function logRequest(entry) {
  const k = kv();
  if (!k) return;
  try {
    let logs = [];
    try {
      const raw = await k.get("gr:logs");
      logs = raw ? (typeof raw === "string" ? JSON.parse(raw) : raw) : [];
      if (!Array.isArray(logs)) logs = [];
    } catch { logs = []; }
    logs.unshift({ t: Date.now(), ...entry });
    await k.set("gr:logs", JSON.stringify(logs.slice(0, 100)));
  } catch { /* 日誌失敗不影響 */ }
}

async function getLogs() {
  const k = kv();
  if (!k) return [];
  try {
    const raw = await k.get("gr:logs");
    const logs = raw ? (typeof raw === "string" ? JSON.parse(raw) : raw) : [];
    return Array.isArray(logs) ? logs : [];
  } catch {
    return [];
  }
}

/** 逐筆請求明細（個人）：gr:ureq:{usr_token} array（最新在前，留200筆/365天）
 *  entry = {t, model, tokens, cost, key} */
async function logUserReq(userToken, entry) {
  const k = kv();
  if (!k) return;
  try {
    let arr = [];
    try {
      const raw = await k.get("gr:ureq:" + userToken);
      arr = raw ? (typeof raw === "string" ? JSON.parse(raw) : raw) : [];
      if (!Array.isArray(arr)) arr = [];
    } catch { arr = []; }
    arr.unshift({ t: Date.now(), ...entry });
    await k.set("gr:ureq:" + userToken, JSON.stringify(arr.slice(0, 200)), { ex: 365 * 86400 });
  } catch { /* 失敗不影響回應 */ }
}

async function getUserReqs(userToken) {
  const k = kv();
  if (!k) return [];
  try {
    const raw = await k.get("gr:ureq:" + userToken);
    const arr = raw ? (typeof raw === "string" ? JSON.parse(raw) : raw) : [];
    return Array.isArray(arr) ? arr : [];
  } catch { return []; }
}

/** 訂閱制：當月首次使用自動補點
 *  user.plan: 'free'（無）| 方案名；user.monthlyQuota: 每月額度；user.quotaReset: 'YYYY-MM'
 *  回傳 true 表示本月已重置（補過點） */
async function ensureMonthlyQuota(users, token) {
  const u = users[token];
  if (!u) return false;
  // 有效方案=free（到期已取消/續不起）→ 不月補；不在這裡降級（續約交給 maybeRenew / plan.info）
  try {
    const plans = await getPlans();
    if (activePlanOf(u, plans) === "free") return false;
  } catch { /* 讀方案失敗→照舊邏輯 */ }
  if (!u.monthlyQuota || Number(u.monthlyQuota) <= 0) return false;
  const t = new Date();
  const ym = `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}`;
  if (u.quotaReset === ym) return false;
  u.quotaReset = ym;
  // 補發 = 加點（不可覆寫：覆寫會把用戶自儲餘額洗掉，訂閱變倒虧）
  if (u.credits !== -1) u.credits = Math.round(((Number(u.credits) || 0) + Number(u.monthlyQuota)) * 1e6) / 1e6;
  return true;
}

/** 用量記錄：gr:usage:{yyyymmdd} JSON {token: {tokens(真實), points(扣點), reqs, models}} + user.usedTokens 累加 */
/** 連續簽到天數（台北日）：log 為 YYYY-MM-DD 陣列；有今天算到今天、沒有算到昨天 */
function streakDays(logArr) {
  const set = new Set(Array.isArray(logArr) ? logArr : []);
  const fmt = (ms) => {
    const d = new Date(ms + 8 * 3600000);
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}`;
  };
  let cur = Date.now();
  if (!set.has(fmt(cur))) cur -= 86400000;
  let n = 0;
  while (set.has(fmt(cur))) { n++; cur -= 86400000; }
  return n;
}
/** 連簽加成：7天×1.5 · 14天×2 · 30天×3（與活動/方案倍率相乘） */
function streakMult(n) { return n >= 30 ? 3 : n >= 14 ? 2 : n >= 7 ? 1.5 : 1; }

/** 到期處理（規則：錢不夠就不續約，乾淨結案）：
 *  · 未到期 → null（不用動）
 *  · 到期 + 未取消 + 餘額足 → **自動續約**：扣月費、期限=當下+30天，回 "renewed"（呼叫端寫回）
 *  · 到期 + 已取消 → 結案：清 plan 欄位回 Free，回 "dropped"
 *  · 到期 + 錢不夠 → **不續約**：清 plan 欄位回 Free（餘額不動、之後補款也不會回頭補續），回 "dropped"
 */
function maybeRenew(u, plans) {
  if (!u || !u.plan || u.plan === "free" || !u.subUntil) return null;
  const exp = Date.parse(u.subUntil);
  if (!Number.isFinite(exp) || Date.now() <= exp) return null;
  const p = plans[u.plan];
  const fee = p ? (Number(p.fee) || 0) : 0;
  const canPay = !u.subCancel && p && (u.credits === -1 || (Number(u.credits) || 0) >= fee);
  if (!canPay) {                                   // 取消 / 錢不夠 → 結案降Free，不留殘帳
    u.plan = "free";
    u.monthlyQuota = 0;
    return "dropped";
  }
  if (fee > 0 && u.credits !== -1) u.credits = Math.round(((Number(u.credits) || 0) - fee) * 1e6) / 1e6;
  u.subUntil = new Date(Date.now() + 30 * 86400000).toISOString();
  u.subCancel = false;
  return "renewed";
}

/** 用量日 key（站務時區 UTC+8＝台北：日界線以台北午夜為準，與前端日曆一致） */
function dayKey(d) {
  const t = new Date((d ? d.getTime() : Date.now()) + 8 * 3600000);
  const p = (n) => String(n).padStart(2, "0");
  return `${t.getUTCFullYear()}${p(t.getUTCMonth() + 1)}${p(t.getUTCDate())}`;
}

async function recordUsage(userToken, model, tokens, points) {
  const k = kv();
  if (!k) return;
  const dk = `gr:usage:${dayKey()}`;
  try {
    let day = {};
    try {
      const raw = await k.get(dk);
      day = raw ? (typeof raw === "string" ? JSON.parse(raw) : raw) : {};
    } catch { day = {}; }
    const e = day[userToken] || { tokens: 0, points: 0, reqs: 0, models: {} };
    e.tokens += Math.max(0, Number(tokens) || 0);
    e.points = (Number(e.points) || 0) + Math.max(0, Number(points) || 0);
    e.reqs += 1;
    // 每模型明細：新格式 {r:請求, tk:tokens}；舊資料是純數字(請求數) → 兼容升級
    const tkAdd = Math.max(0, Number(tokens) || 0);
    const prev = e.models[model];
    if (prev === undefined) e.models[model] = { r: 1, tk: tkAdd };
    else if (typeof prev === "number") e.models[model] = { r: prev + 1, tk: tkAdd };
    else { prev.r = (prev.r || 0) + 1; prev.tk = (prev.tk || 0) + tkAdd; }
    day[userToken] = e;
    await k.set(dk, JSON.stringify(day), { ex: 365 * 86400 });  // 留 365 天（~1KB/天，零壓力）
  } catch { /* 用量記錄失敗不影響回應 */ }
}

/** 讀用量：days 天內每日彙總（只回該 token 自己的，除非 admin 看全部）— pipeline 一次HTTP撈全部 */
async function getUsage(days) {
  const k = kv();
  if (!k) return null;
  const n = Math.max(1, Math.min(365, Number(days) || 7));   // 最多回看365天
  const now = new Date();
  const list = [];
  for (let i = 0; i < n; i++) list.push(new Date(now.getTime() - i * 86400000));
  const isoOf = (d) => {
    const tw = new Date(d.getTime() + 8 * 3600000);   // 標籤與 key 同用 UTC+8，避免錯位一天
    return `${tw.getUTCFullYear()}-${String(tw.getUTCMonth() + 1).padStart(2, "0")}-${String(tw.getUTCDate()).padStart(2, "0")}`;
  };
  try {
    const pl = k.pipeline();
    for (const d of list) pl.get(`gr:usage:${dayKey(d)}`);
    const res = await pl.exec();                      // ← 單次HTTP（原本31次逐筆=慢數秒元凶）
    return list.map((d, i) => {
      const raw = res ? res[i] : null;
      let data = {};
      try { data = raw ? (typeof raw === "string" ? JSON.parse(raw) : raw) : {}; } catch {}
      return { day: isoOf(d), data };
    });
  } catch {
    const out = [];                                   // 退路：pipeline不可用時逐筆
    for (const d of list) {
      try {
        const raw = await k.get(`gr:usage:${dayKey(d)}`);
        let data = {};
        try { data = raw ? (typeof raw === "string" ? JSON.parse(raw) : raw) : {}; } catch {}
        out.push({ day: isoOf(d), data });
      } catch { out.push({ day: "", data: {} }); }
    }
    return out;
  }
}

/* ── 方案（plus/pro/max/ultra 預留）：gr:plans {id:{label,monthlyQuota,rewardMult}} ── */
/** 方案（分級容量）：fee=30天訂閱費 · h5/wk=額度(0=不限制,Free全0純付費;v6週=月費/2→月含額≈2×費)
 *  無月補（回饋靠每日簽到×倍率＋推薦碼） · rewardMult=簽到/推薦倍率 · __v 版本遷移 */
const DEFAULT_PLANS = {
  free:  { label: "Free",  monthlyQuota: 0, rewardMult: 1,   fee: 0,    h5: 0,     wk: 0,     disc: 1 },
  plus:  { label: "Plus",  monthlyQuota: 0, rewardMult: 1.5, fee: 20,   h5: 2,     wk: 10,    disc: 0.95 },
  pro:   { label: "Pro",   monthlyQuota: 0, rewardMult: 2,   fee: 100,  h5: 10,    wk: 50,    disc: 0.9 },
  max:   { label: "Max",   monthlyQuota: 0, rewardMult: 3,   fee: 500,  h5: 50,    wk: 250,   disc: 0.85 },
  ultra: { label: "Ultra", monthlyQuota: 0, rewardMult: 5,   fee: 2000, h5: 200,   wk: 1000,  disc: 0.8 },
};
const PLANS_VERSION = 7;   // v7: 拔月補（簽到/推薦已是回饋主力，月補多餘）

async function getPlans() {
  const k = kv();
  if (!k) return JSON.parse(JSON.stringify(DEFAULT_PLANS));
  try {
    const raw = await k.get("gr:plans");
    const p = raw ? (typeof raw === "string" ? JSON.parse(raw) : raw) : null;
    if (!p || p.__v !== PLANS_VERSION) return JSON.parse(JSON.stringify(DEFAULT_PLANS));  // 舊表作廢
    const out = { ...p };
    delete out.__v;
    return { ...JSON.parse(JSON.stringify(DEFAULT_PLANS)), ...out };
  } catch { return JSON.parse(JSON.stringify(DEFAULT_PLANS)); }
}

async function setPlans(p) {
  const k = kv();
  if (!k) throw new Error("NO_KV");
  await k.set("gr:plans", JSON.stringify({ ...p, __v: PLANS_VERSION }));
}

/** 取生效方案id：非free且逾期 → 視為free（寫回由 ensureMonthlyQuota 慰懶處理） */
function activePlanOf(u, plans) {
  const id = (u && u.plan) || "free";
  if (id !== "free" && u.subUntil && Date.now() > Date.parse(u.subUntil)) return "free";
  return plans[id] ? id : "free";
}

/** 方案配額（含活動倍率）：h5/wk 上限、月費、獎勵倍率 */
function planCapsFor(plans, planId, ev) {
  const p = plans[planId] || plans.free || {};
  const m = ev ? (Number(ev.mult) || 1) : 1;
  const d = Number(p.disc);
  return { id: plans[planId] ? planId : "free",
    h5: (Number(p.h5) || 0) * m, wk: (Number(p.wk) || 0) * m,
    disc: (d > 0 && d <= 1) ? d : 1,
    fee: Number(p.fee) || 0, rewardMult: Number(p.rewardMult) || 1,
    monthlyQuota: Number(p.monthlyQuota) || 0, label: p.label || planId };
}

/** 每小時用量桶：u.uh = {"YYYYMMDDHH": 點數}，只留168小時（7天）· 時區=UTC+8 */
const UH_KEEP = 168;
function hourKey(d) {
  const t = new Date((d ? d.getTime() : Date.now()) + 8 * 3600000);
  const p = (n) => String(n).padStart(2, "0");
  return `${t.getUTCFullYear()}${p(t.getUTCMonth() + 1)}${p(t.getUTCDate())}${p(t.getUTCHours())}`;
}
async function addHourlySpend(u, pts) {
  const k = hourKey();
  if (!u.uh || typeof u.uh !== "object") u.uh = {};
  u.uh[k] = (Number(u.uh[k]) || 0) + (Number(pts) || 0);
  const cut = hourKey(new Date(Date.now() - UH_KEEP * 3600000));
  for (const key of Object.keys(u.uh)) if (key < cut) delete u.uh[key];
}
function hourlySpend(u, hours) {
  if (!u || !u.uh) return 0;
  const cut = hourKey(new Date(Date.now() - hours * 3600000));
  let s = 0;
  for (const [k, v] of Object.entries(u.uh)) if (k > cut) s += Number(v) || 0;
  return s;
}

/* ── 活動：gr:event {enabled,label,mult,until}；activeEvent() 回目前有效的，否則 null ── */
async function getEvent() {
  const k = kv();
  if (!k) return { enabled: false, label: "", mult: 1, until: "" };
  try {
    const raw = await k.get("gr:event");
    const e = raw ? (typeof raw === "string" ? JSON.parse(raw) : raw) : {};
    return { enabled: false, label: "", mult: 1, until: "", ...e };
  } catch { return { enabled: false, label: "", mult: 1, until: "" }; }
}

async function setEvent(e) {
  const k = kv();
  if (!k) throw new Error("NO_KV");
  await k.set("gr:event", JSON.stringify(e));
}

function activeEvent(ev) {
  if (!ev || !ev.enabled) return null;
  const t = new Date(Date.now() + 8 * 3600000);   // 站務時區 UTC+8：活動到期=台北午夜
  const p = (n) => String(n).padStart(2, "0");
  const today = `${t.getUTCFullYear()}-${p(t.getUTCMonth() + 1)}-${p(t.getUTCDate())}`;
  if (ev.until && today > String(ev.until)) return null;
  return ev;
}

/* ── KEY 壓力統計（只記流量數字，零內容）：gr:keystat {day, keys:{hash:{prefix,reqs,tokens,errs,ts[]}}} ── */
function keyStatHash(key) {
  return "h_" + require("crypto").createHash("sha256").update(key).digest("hex").slice(0, 12);
}

async function recordKeyStat(key, opts) {
  const k = kv();
  if (!k) return;
  const o = opts || {};
  try {
    let s = null;
    try {
      const raw = await k.get("gr:keystat");
      s = raw ? (typeof raw === "string" ? JSON.parse(raw) : raw) : null;
    } catch { s = null; }
    const t = new Date();
    const p = (n) => String(n).padStart(2, "0");
    const day = `${t.getFullYear()}-${p(t.getMonth() + 1)}-${p(t.getDate())}`;
    if (!s || s.day !== day || !s.keys) s = { day, keys: {} };
    const h = keyStatHash(key);
    const e = s.keys[h] || { prefix: mask(key), reqs: 0, tokens: 0, errs: 0, ts: [] };
    e.reqs += 1;
    e.tokens += Math.max(0, Number(o.tokens) || 0);
    if (o.err) e.errs += 1;
    const now = Date.now();
    e.ts = [...(e.ts || []), now].filter((x) => now - x < 60000).slice(-120);
    s.keys[h] = e;
    await k.set("gr:keystat", JSON.stringify(s), { ex: 2 * 86400 });
  } catch { /* 統計失敗不影響回應 */ }
}

async function getKeyStat() {
  const k = kv();
  if (!k) return { day: "", keys: {} };
  try {
    const raw = await k.get("gr:keystat");
    const s = raw ? (typeof raw === "string" ? JSON.parse(raw) : raw) : null;
    return s && s.keys ? s : { day: "", keys: {} };
  } catch { return { day: "", keys: {} }; }
}

/** NVIDIA 直連聊天模型（走你的 nvapi key；上游免費額度，站內按下方站內價計點，管理頁可改）
 *  只有「此帳號實測 200 過的」才會列進來；404 無權的不加。 */
const NV_CHAT_MODELS = {
  "deepseek-ai/deepseek-v4.1-flash": { label: "DeepSeek V4.1 Flash（推理）" },
  "z-ai/glm-5.3-flash":              { label: "GLM 5.3 Flash（快速）" },
};
/** 模型官方參考價（$/1M tokens，input/output；以 Groq 公告為準）
 *  扣點規則：站內實付 = total_tokens × 倍率（倍率見 DEFAULT_PRICING）
 *  註：nv/ 開頭為 NVIDIA 站內價（上游免費額度 $0，費率由站長定，計費表可改） */
/** 模型官方價（對齊 console.groq.com/docs/models 現行目錄 = 你的帳號11模型，一模一樣、無未列）
 *  非 token 計價模型（STT/TTS）用 unit 顯示、input/output=0（聊天端點打不到它們） */
const MODEL_PRICES = {
  // 對話（4）
  "qwen/qwen3.8-27b":    { input: 0.80,  output: 4.0,  note: "主力對話" },
  "openai/gpt-oss-120b": { input: 0.15,  output: 0.60, note: "推理較強" },
  "openai/gpt-oss-20b":  { input: 0.075, output: 0.30, note: "計費基準" },
  "allam-2-7b":          { input: 0,     output: 0,    note: "免費（$0 計價）" },
  // NVIDIA 站內價（上游免費額度 $0；對標同級 Groq 價，計費表可改）
  "deepseek-ai/deepseek-v4.1-flash": { input: 0.15,  output: 0.60, note: "NV · 站內價（推理，對標120b級）" },
  "z-ai/glm-5.3-flash":              { input: 0.075, output: 0.30, note: "NV · 站內價（快速，對標20b級）" },
  // 安全模型（3）
  "openai/gpt-oss-safeguard-20b": { input: 0.075, output: 0.30, note: "安全模型" },
  "meta-llama/llama-prompt-guard-2-22m": { input: 0.03, output: 0.03, note: "安全審查" },
  "meta-llama/llama-prompt-guard-2-86m": { input: 0.04, output: 0.04, note: "安全審查" },
  // STT（2 · 按小時）
  "whisper-large-v3":       { input: 0, output: 0, unit: "$0.111 / 時", note: "語音轉文字" },
  "whisper-large-v3-turbo": { input: 0, output: 0, unit: "$0.04 / 時",  note: "語音轉文字 · 快" },
  // TTS（2 · 按字元）
  "canopylabs/orpheus-v1-english":   { input: 0, output: 0, unit: "$22 / 1M 字元", note: "文字轉語音" },
  "canopylabs/orpheus-arabic-saudi": { input: 0, output: 0, unit: "$40 / 1M 字元", note: "文字轉語音" },
  // 向量檢索（只收 input；上游免費額度，站內價計入突破 7K 的請求帳單）
  "nvidia/nemotron-3-embed-1b": { input: 0.02, output: 0, note: "NV · 對標市場地板（OpenAI small / Voyage-lite / Jina v3 同級 $0.02）；上游免費額度" },
};

/** 模型規格表（Groq 官方 console 資料：速度 T/s、開發層限流、上下文、最長輸出、檔案上限）
 *  tps=null 官方未公布；rpm/tpm = 官方開發層「單把、單模型」限流（每個模型分開算、互不共用） */
const MODEL_SPECS = {
  "qwen/qwen3.8-27b":    { tps: 450,  rpm: 1000, tpm: 250000, limits: "250K TPM · 1K RPM", ctx: 131042, maxOut: 16384,  file: "20 MB", note: "主力對話" },
  "openai/gpt-oss-120b": { tps: 500,  rpm: 1000, tpm: 250000, limits: "250K TPM · 1K RPM", ctx: 131072, maxOut: 65536,  file: "-", note: "推理較強" },
  "openai/gpt-oss-20b":  { tps: 1000, rpm: 1000, tpm: 250000, limits: "250K TPM · 1K RPM", ctx: 131072, maxOut: 65536,  file: "-", note: "最快 · 計費基準" },
  "allam-2-7b":          { tps: null, rpm: null, tpm: null,   limits: "—",                ctx: null,   maxOut: null,   file: "-", note: "免費 · 官方未公布規格" },
  "openai/gpt-oss-safeguard-20b": { tps: 1000, rpm: 1000, tpm: 150000, limits: "150K TPM · 1K RPM", ctx: 131072, maxOut: 65536, file: "-", note: "安全模型" },
  "meta-llama/llama-prompt-guard-2-22m": { tps: null, rpm: 100, tpm: 30000, limits: "30K TPM · 100 RPM", ctx: 512, maxOut: 512, file: "-", note: "安全審查 · $0.03" },
  "meta-llama/llama-prompt-guard-2-86m": { tps: null, rpm: 100, tpm: 30000, limits: "30K TPM · 100 RPM", ctx: 512, maxOut: 512, file: "-", note: "安全審查 · $0.04" },
  "whisper-large-v3":        { tps: null, rpm: 300, tpm: null, limits: "200K ASH · 300 RPM", ctx: null, maxOut: null, file: "100 MB", note: "STT · $0.111/時" },
  "whisper-large-v3-turbo":  { tps: null, rpm: 400, tpm: null, limits: "400K ASH · 400 RPM", ctx: null, maxOut: null, file: "100 MB", note: "STT · $0.04/時" },
  "canopylabs/orpheus-v1-english":      { tps: null, rpm: 250, tpm: 50000, limits: "50K TPM · 250 RPM", ctx: 4000, maxOut: 50000, file: "-", note: "TTS · $22/1M字元" },
  "canopylabs/orpheus-arabic-saudi":    { tps: null, rpm: 250, tpm: 50000, limits: "50K TPM · 250 RPM", ctx: 4000, maxOut: 50000, file: "-", note: "TTS · $40/1M字元" },
};

/** 實測速度環：gr:speed JSON array（最多5,000筆、滾動保留365天，有流量就一直累積）· {t, model, tokens, tps, u} */
async function recordSpeed(e) {
  const k = kv();
  if (!k) return;
  try {
    let arr = [];
    try {
      const raw = await k.get("gr:speed");
      arr = raw ? (typeof raw === "string" ? JSON.parse(raw) : raw) : [];
      if (!Array.isArray(arr)) arr = [];
    } catch { arr = []; }
    arr.push({ t: Date.now(), model: e.model, tokens: e.tokens,
      tps: Math.round((Number(e.tps) || 0) * 10) / 10, u: e.u || "" });
    await k.set("gr:speed", JSON.stringify(arr.slice(-5000)), { ex: 365 * 86400 });   // 留365天·5000筆上限
  } catch { /* 速度記錄失敗不影響回應 */ }
}

async function getSpeed() {
  const k = kv();
  if (!k) return [];
  try {
    const raw = await k.get("gr:speed");
    const arr = raw ? (typeof raw === "string" ? JSON.parse(raw) : raw) : [];
    return Array.isArray(arr) ? arr : [];
  } catch { return []; }
}

/** Playground 對話 sessions：gr:chats:{usr_token} array（最新在前，30則/365天，一直保留） */
async function getChats(userToken) {
  const k = kv();
  if (!k) return [];
  try {
    const raw = await k.get("gr:chats:" + userToken);
    const arr = raw ? (typeof raw === "string" ? JSON.parse(raw) : raw) : [];
    return Array.isArray(arr) ? arr : [];
  } catch { return []; }
}
async function setChats(userToken, all) {
  const k = kv();
  if (!k) throw new Error("NO_KV");
  // 全域預算 ~900KB（gr:chats 單值）：新的完整保留 → 舊的先壓成4則×2000字 → 再塞不下就捨棄更舊的
  const list = (all || []).slice(0, 30);
  const squash = (c) => ({ ...c, messages: (c.messages || []).slice(-4)
    .map((m) => ({ role: m.role, content: String(m.content).slice(0, 2000) })) });
  let out = [];
  for (let i = 0; i < list.length; i++) {
    let cand = [...out, list[i]];
    if (JSON.stringify(cand).length <= 900000) { out = cand; continue; }
    cand = [...out, squash(list[i])];
    if (JSON.stringify(cand).length <= 900000) { out = cand; continue; }
    break;
  }
  await k.set("gr:chats:" + userToken, JSON.stringify(out), { ex: 365 * 86400 });
}

/** Playground 對話 Session（一直保留；自動標題=首句；清單30則×每則80則×單則2萬字）── */
/** 已知的 ITPM 上限（每把key被org拒時記下）：gr:itpmcap {prefix: {limit, org}}
 *  用途：KEY壓力頁顯示 + 大輸入請求挑「沒被org擋過的key」 */
async function getItpmCaps() {
  const k = kv();
  if (!k) return {};
  try {
    const raw = await k.get("gr:itpmcap");
    const o = raw ? (typeof raw === "string" ? JSON.parse(raw) : raw) : {};
    return o && typeof o === "object" ? o : {};
  } catch { return {}; }
}
async function setItpmCap(prefix, info) {
  const k = kv();
  if (!k) return;
  try {
    const cur = await getItpmCaps();
    cur[prefix] = info;
    await k.set("gr:itpmcap", JSON.stringify(cur), { ex: 90 * 86400 });
  } catch { /* 記失敗不擋路 */ }
}

/** 站務設定 gr:config（放第三方金鑰等敏感值；只經 TLS，不進代碼/git/前端） */
async function getConfig() {
  const k = kv();
  if (!k) return {};
  try {
    const raw = await k.get("gr:config");
    const o = raw ? (typeof raw === "string" ? JSON.parse(raw) : raw) : {};
    return o && typeof o === "object" ? o : {};
  } catch { return {}; }
}
async function setConfig(cfg) {
  const k = kv();
  if (!k) throw new Error("NO_KV");
  await k.set("gr:config", JSON.stringify(cfg || {}));
}

module.exports = { kv, hasKV, envKeys, mask, getManagedKeys, setManagedKeys, allKeys, getUsers, setUsers, isSeeded, markSeeded, recordUsage, getUsage, dayKey, getInvites, setInvites, newInviteCode, getPricing, setPricing, priceFor, DEFAULT_PRICING, MODEL_PRICES, MODEL_SPECS, POINTS_PER_USD, costFor, logRequest, getLogs, logUserReq, getUserReqs, ensureMonthlyQuota, getChannels, setChannels, newChannelId, pickChannel, getPlans, setPlans, DEFAULT_PLANS, activePlanOf, planCapsFor, maybeRenew, addHourlySpend, hourlySpend, streakDays, streakMult, getEvent, setEvent, activeEvent, keyStatHash, recordKeyStat, getKeyStat, recordSpeed, getSpeed, getChats, setChats, getConfig, setConfig, setItpmCap, getItpmCaps, NV_CHAT_MODELS };
