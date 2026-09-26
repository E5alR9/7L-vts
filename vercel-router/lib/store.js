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

/** 邀請碼：gr:invites JSON {code: {credits, maxUses, used, createdBy, createdAt, disabled}} */
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

/** 計費表：gr:pricing JSON {model: multiplier}；沒有就回預設
 *
 *  倍率 = Groq 官方 input 價 ÷ 基準（gpt-oss-20b $0.075/1M）：
 *    20b  $0.075 → 1x ｜ 120b $0.15 → 2x ｜ qwen3.8 $0.80 → 10x ｜ allam 未定價 → 0.5x
 *  （output 約貴 4~5 倍，但中轉站按 total_tokens 單一倍率簡化計費）
 */
const DEFAULT_PRICING = {
  "qwen/qwen3.8-27b": 10,
  "openai/gpt-oss-20b": 1,
  "openai/gpt-oss-120b": 2,
  "allam-2-7b": 0.5,
};

async function getPricing() {
  const k = kv();
  if (!k) return { ...DEFAULT_PRICING };
  try {
    const raw = await k.get("gr:pricing");
    const p = raw ? (typeof raw === "string" ? JSON.parse(raw) : raw) : {};
    return { ...DEFAULT_PRICING, ...p };
  } catch {
    return { ...DEFAULT_PRICING };
  }
}

async function setPricing(p) {
  const k = kv();
  if (!k) throw new Error("NO_KV");
  await k.set("gr:pricing", JSON.stringify(p));
}

function priceFor(pricing, model) {
  const m = Number(pricing[model]);
  return Number.isFinite(m) && m > 0 ? m : 1;
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

/** 訂閱制：當月首次使用自動補點
 *  user.plan: 'free'（無）| 方案名；user.monthlyQuota: 每月額度；user.quotaReset: 'YYYY-MM'
 *  回傳 true 表示本月已重置（補過點） */
async function ensureMonthlyQuota(users, token) {
  const u = users[token];
  if (!u || !u.monthlyQuota || Number(u.monthlyQuota) <= 0) return false;
  const t = new Date();
  const ym = `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}`;
  if (u.quotaReset === ym) return false;
  u.quotaReset = ym;
  if (u.credits !== -1) u.credits = Number(u.monthlyQuota);
  return true;
}

/** 用量記錄：gr:usage:{yyyymmdd} JSON {token: {tokens, reqs, models:{m:n}}} + user.usedTokens 累加 */
function dayKey(d) {
  const t = d || new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${t.getFullYear()}${p(t.getMonth() + 1)}${p(t.getDate())}`;
}

async function recordUsage(userToken, model, tokens) {
  const k = kv();
  if (!k) return;
  const dk = `gr:usage:${dayKey()}`;
  try {
    let day = {};
    try {
      const raw = await k.get(dk);
      day = raw ? (typeof raw === "string" ? JSON.parse(raw) : raw) : {};
    } catch { day = {}; }
    const e = day[userToken] || { tokens: 0, reqs: 0, models: {} };
    e.tokens += tokens;
    e.reqs += 1;
    e.models[model] = (e.models[model] || 0) + 1;
    day[userToken] = e;
    await k.set(dk, JSON.stringify(day), { ex: 90 * 86400 });  // 留 90 天
  } catch { /* 用量記錄失敗不影響回應 */ }
}

/** 讀用量：days 天內每日彙總（只回該 token 自己的，除非 admin 看全部） */
async function getUsage(days) {
  const k = kv();
  if (!k) return null;
  const n = Math.max(1, Math.min(90, Number(days) || 7));
  const out = [];
  const now = new Date();
  for (let i = 0; i < n; i++) {
    const d = new Date(now.getTime() - i * 86400000);
    const dk = `gr:usage:${dayKey(d)}`;
    try {
      const raw = await k.get(dk);
      out.push({ day: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`,
        data: raw ? (typeof raw === "string" ? JSON.parse(raw) : raw) : {} });
    } catch { out.push({ day: "", data: {} }); }
  }
  return out;
}

module.exports = { kv, hasKV, envKeys, mask, getManagedKeys, setManagedKeys, allKeys, getUsers, setUsers, isSeeded, markSeeded, recordUsage, getUsage, getInvites, setInvites, newInviteCode, getPricing, setPricing, priceFor, DEFAULT_PRICING, logRequest, getLogs, ensureMonthlyQuota };
