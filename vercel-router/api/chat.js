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
const NV_URL = "https://integrate.api.nvidia.com/v1/chat/completions";   // NVIDIA 直連（nvapi key 存服務端，只寫不讀）

const store = require("../lib/store");
const libAuth = require("../lib/auth");
const crypto = require("crypto");

// 上下文壓縮：用便宜模型把舊訊息濃縮成摘要（分段 map-reduce）
// 多模型容錯：不同模型 = 不同的 TPM 桶；20b 被挤爆就换跑道（摘要小，花费可忽略）
// safeguard-20b 同價、131k 上下文、幾乎沒人用——桶最空，放第二顺位
const SUMMARY_MODELS = ["openai/gpt-oss-20b", "openai/gpt-oss-safeguard-20b", "openai/gpt-oss-120b", "allam-2-7b"];
const SUMMARY_MEM = new Map();   // warm 實例內快取（hash→摘要），上限 50 條

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
const STATE = { cursor: 0, cooldownUntil: new Map(), itpm: new Map() };   // itpm: key→該key背後org已知的輸入上限

function loadLadder() {
  const raw = (process.env.MODEL_LADDER || "").trim();
  const list = raw ? raw.split(/[\s,;]+/).filter(Boolean) : [];
  return list.length ? list : DEFAULT_LADDER;
}

/** 未指定輸出上限 → 補上「模型真上限 與 上下文剩餘視窗 的較小值」：
 *  1) 呼叫端有設 → 尊重
 *  2) Groq /v1/models 權威值 max_completion_tokens + context_window（ensureLimits 抓一次）
 *  3) MODEL_SPECS 靜態表兜底
 *  ⚠ 還會夾在剩餘視窗內：否則 prompt+max_tokens>ctx 被上游400 "reduce the length" */
let LIMITS = null;   // {modelId: {max, ctx}} — warm instance 抓一次
async function ensureLimits() {
  if (LIMITS) return;
  try {
    // ① KV 快取（6h）：別每次冷實例都跨海抓上游
    try {
      const kv0 = store.kv();
      if (kv0) {
        const raw = await kv0.get("gr:modellimits");
        const c = raw ? (typeof raw === "string" ? JSON.parse(raw) : raw) : null;
        if (c && c.map && Date.now() - (c.at || 0) < 6 * 3600 * 1000) { LIMITS = c.map; return; }
      }
    } catch { /* 快取沒命中 → 抓上游 */ }
    const keys = (await store.allKeys()).map((k) => k.key);
    if (!keys.length) return;
    const ac = new AbortController();
    const tm = setTimeout(() => ac.abort(), 8000);   // 8s保險：上游挂住時不讓整發請求悶到120秒才死
    const r = await fetch(MODELS_URL, { headers: { Authorization: `Bearer ${keys[0]}` }, signal: ac.signal });
    clearTimeout(tm);
    const j = await r.json();
    const map = {};
    for (const m of (j.data || [])) {
      const mx = m.max_completion_tokens || m.max_output_length;
      const cx = m.context_window || m.context_length;
      if (mx || cx) map[m.id] = { max: mx || 0, ctx: cx || 0 };
    }
    if (Object.keys(map).length) {
      LIMITS = map;
      try { const kv1 = store.kv(); if (kv1) await kv1.set("gr:modellimits", JSON.stringify({ at: Date.now(), map }), { ex: 6 * 3600 }); } catch {}
    }
  } catch { /* 抓失敗 → 走 MODEL_SPECS 兜底，下次請求再試 */ }
}

/** 輸入 token 粗估（中英混合同步：中文字≈1token/1.05、其他/3）——用於上下文夾限與提早預檢 */
function estPromptPts(b) {
  const s = JSON.stringify(b.messages || b.input || "");
  let cjk = 0;
  for (const ch of s) {
    const c = ch.codePointAt(0);
    if ((c >= 0x2E80 && c <= 0x9FFF) || (c >= 0x3400 && c <= 0x4DBF) ||
        (c >= 0xF900 && c <= 0xFAFF) || (c >= 0xFF00 && c <= 0xFFEF)) cjk++;
  }
  return Math.max(1, Math.ceil(cjk / 1.05) + Math.ceil((s.length - cjk) / 3));
}

/** ITPM 瘦身：丟最舊訊息直到輸入估算 ≤ maxTok；只剩2則還超 → 砍最舊那則的前段（不再放棄）
 *  觸發條件＝Groq 免費層 org 級 ITPM 上限（如 qwen7000/分），單發輸入超標必400 */
function trimToLimit(b, maxTok) {
  const msgs = Array.isArray(b.messages) ? b.messages : null;
  if (!msgs || msgs.length < 1) return null;
  let m = msgs.map((x) => ({ ...x }));
  let dropped = 0;
  while (m.length >= 1 && estPromptPts({ messages: m }) > maxTok && dropped < 50) {
    if (m.length > 2) { m.shift(); dropped++; continue; }
    const over = estPromptPts({ messages: m }) - maxTok;
    const cut = Math.min(m[0].content.length - 1, Math.ceil(over * 1.05) + 64);
    if (m.length === 1 && cut < 16) break;              // 單則且砍無剩 → 放棄
    if (cut < 16) { m.shift(); dropped++; continue; }
    m[0] = { role: m[0].role, content: m[0].content.slice(cut) };
    dropped++;
  }
  if (!m.length || estPromptPts({ messages: m }) > maxTok) return null;
  return { body: { ...b, messages: m }, dropped };
}

/** 摘要快取（同一批舊訊息只壓一次）：記憶體 + KV 7 天 */
function sumHash(s) {
  return crypto.createHash("sha256").update(s).digest("hex").slice(0, 24);
}
async function sumCacheGet(h) {
  if (SUMMARY_MEM.has(h)) return SUMMARY_MEM.get(h);
  try {
    const k = store.kv();
    if (!k) return null;
    const raw = await k.get("gr:sum:" + h);
    const t = raw ? (typeof raw === "string" ? raw : JSON.stringify(raw)) : null;
    if (t) {
      if (SUMMARY_MEM.size > 50) SUMMARY_MEM.clear();
      SUMMARY_MEM.set(h, t);
      return t;
    }
  } catch { /* 快取沒命中就現壓 */ }
  return null;
}
async function sumCacheSet(h, text) {
  try {
    if (SUMMARY_MEM.size > 50) SUMMARY_MEM.clear();
    SUMMARY_MEM.set(h, text);
    const k = store.kv();
    if (k) await k.set("gr:sum:" + h, text, { ex: 7 * 86400 });
  } catch { /* 記失敗不擋路 */ }
}

/** 單塊摘要：直接打 Groq（不走本路由遞迴），小塊一定過 ITPM */
async function summarizeOne(chunkText, gkey, model, maxTok) {
  const ac = new AbortController();
  const tm = setTimeout(() => ac.abort(), 45000);
  try {
    const r = await fetch(GROQ_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${gkey}` },
      signal: ac.signal,
      body: JSON.stringify({
        model: model || SUMMARY_MODELS[0],
        temperature: 0.2,
        max_tokens: maxTok || 800,
        messages: [
          { role: "system", content: "你是對話上下文壓縮器。把【歷史對話】壓成一段精煉摘要（繁體中文，200~600字）：保留人名/地名/關鍵事件/結論/待辦與未解問題、數字與專有名詞；刪寒暄與重複。只輸出摘要本文，不要前言。" },
          { role: "user", content: chunkText },
        ],
      }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error((j.error && j.error.message) || ("HTTP " + r.status));
    const text = (j.choices && j.choices[0] && j.choices[0].message && j.choices[0].message.content || "").trim();
    if (!text) throw new Error("empty summary");
    const u = j.usage || {};
    return { text, pt: Number(u.prompt_tokens) || 0, ct: Number(u.completion_tokens) || 0, model: model || SUMMARY_MODELS[0] };
  } finally {
    clearTimeout(tm);
  }
}

/** 單塊摘要（帶跨 key 容錯）：首選「沒被 ITPM 拒過、未冷卻」的 key，
 *  絕不用剛 413 的那把（它背後 org 的分鐘桶是滿的，小請求一樣被拒） */
async function summarizeWithModels(chunkText, roundKeys, badKey, models, maxTok) {
  const now = Date.now();
  const fresh = (roundKeys || []).filter((k) => k !== badKey && (STATE.cooldownUntil.get("k:" + k) || 0) <= now);
  const keyCands = [...fresh.slice(0, 3), badKey].filter(Boolean);
  let lastErr = null;
  // 模型 × key 矩陣容錯：20b 桶满就换 safeguard/120b/allam（不同模型的 TPM 桶互相独立）
  for (const m of (models && models.length ? models : SUMMARY_MODELS)) {
    for (const k of keyCands.slice(0, 2)) {
      try {
        return await summarizeOne(chunkText, k, m, maxTok);
      } catch (e) { lastErr = e; }
    }
  }
  throw lastErr || new Error("summarize failed");
}

/** 舊名相容（預設跑全模型表） */
async function summarizeChunkResilient(chunkText, roundKeys, badKey) {
  return summarizeWithModels(chunkText, roundKeys, badKey, SUMMARY_MODELS);
}

/** 向量 RAG（NVIDIA nemotron-3-embed-1b，dim 2048）：從被折疊的舊訊息裡撿回跟本問最相關的原文片段
 *  embeddings 走你自己的 NVIDIA key＋免費額度（站內不扣點）；向量快取 30 天 */
const EMBED_MODEL = "nvidia/nemotron-3-embed-1b";
const EMBED_MEM = new Map();
async function getNvidiaKey() {
  if (process.env.NVIDIA_API_KEY) return process.env.NVIDIA_API_KEY;
  try {
    const cfg = await store.getConfig();
    return (cfg && cfg.nvidiaKey) || "";
  } catch { return ""; }
}
function cosSim(a, b) {
  let s = 0, na = 0, nb = 0;
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) { s += a[i] * b[i]; na += a[i] * a[i]; nb += b[i] * b[i]; }
  return (na > 0 && nb > 0) ? s / (Math.sqrt(na) * Math.sqrt(nb)) : 0;
}
async function embCacheGet(h) {
  if (EMBED_MEM.has(h)) return EMBED_MEM.get(h);
  try {
    const k = store.kv();
    if (!k) return null;
    const raw = await k.get("gr:emb:" + h);
    if (!raw) return null;
    const v = typeof raw === "string" ? JSON.parse(raw) : raw;
    if (Array.isArray(v) && v.length > 100) {
      if (EMBED_MEM.size > 200) EMBED_MEM.clear();
      EMBED_MEM.set(h, v);
      return v;
    }
  } catch {}
  return null;
}
async function embCacheSet(h, vec) {
  try {
    if (EMBED_MEM.size > 200) EMBED_MEM.clear();
    EMBED_MEM.set(h, vec);
    const k = store.kv();
    if (k) await k.set("gr:emb:" + h, JSON.stringify(vec), { ex: 30 * 86400 });
  } catch {}
}
async function nvidiaEmbed(texts, apiKey, inputType) {
  const ac = new AbortController();
  const tm = setTimeout(() => ac.abort(), 30000);
  try {
    const r = await fetch("https://integrate.api.nvidia.com/v1/embeddings", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
      signal: ac.signal,
      body: JSON.stringify({ model: EMBED_MODEL, input: texts, ...(inputType ? { input_type: inputType } : {}), encoding_format: "float", truncate: "END" }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(((j && j.detail) || (j.error && j.error.message)) || ("HTTP " + r.status));
    const out = (j.data || []).map((d) => d.embedding).filter((v) => Array.isArray(v));
    if (!out.length) throw new Error("empty embedding");
    const u = j.usage || {};
    const tokens = Number(u.prompt_tokens ?? u.total_tokens) || 0;   // embedding 實耗（計費依據；快取命中不算）
    return { vecs: out, tokens };
  } finally { clearTimeout(tm); }
}
/** 從 older 裡按向量相似度撿 top-k（塞得進 budgetEst 才拿）；回 {msgs:[system塊], count} */
async function retrieveRelevant(older, query, budgetEst, apiKey) {
  const docs = older
    .map((m, i) => ({ i, text: `${m.role === "user" ? "user" : "assistant"}: ${String(m.content ?? "")}`.slice(0, 2000) }))
    .filter((d) => d.text.replace(/^(user|assistant):\s*/, "").trim().length > 0);
  if (!docs.length || !String(query || "").trim()) return { msgs: [], count: 0, embTokens: 0 };
  const vecs = new Array(docs.length).fill(null);
  const missed = [], missedIdx = [];
  for (let i = 0; i < docs.length; i++) {
    const c = await embCacheGet(sumHash("emb2:" + docs[i].text));
    if (c) vecs[i] = c;
    else { missed.push(docs[i].text); missedIdx.push(i); }
  }
  const qText = String(query).slice(0, 2000);
  const qh = sumHash("emb2:q:" + qText);
  let qv = await embCacheGet(qh);
  let embTokens = 0;
  // query 走 query 模式、文件走 passage 模式（官方：混用大掉準確率），分兩批各 1 個 request；前綴換 emb2 避免吃到舊混算快取
  if (!qv) {
    const gq = await nvidiaEmbed([qText], apiKey, "query");
    embTokens += gq.tokens || 0;
    qv = gq.vecs[0];
    await embCacheSet(qh, qv);
  }
  if (missed.length) {
    const gd = await nvidiaEmbed(missed, apiKey, "passage");
    embTokens += gd.tokens || 0;
    missedIdx.forEach((i, k) => { vecs[i] = gd.vecs[k]; });
    for (const i of missedIdx) if (vecs[i]) await embCacheSet(sumHash("emb2:" + docs[i].text), vecs[i]);
  }
  if (!qv) return { msgs: [], count: 0, embTokens };
  const scored = docs.map((d, i) => ({ ...d, s: vecs[i] ? cosSim(qv, vecs[i]) : -1 }))
    .sort((a, b) => b.s - a.s);
  // 實測 query/passage 分數整體偏低（相關 ~0.23、無關 ~0.1）：0.15 門檻＋只拿與最佳接近的，雜訊不燒 token
  const best = scored.length ? scored[0].s : 0;
  const rel = scored.filter((d) => d.s > 0.15 && d.s >= best * 0.6);
  if (!rel.length) return { msgs: [], count: 0, embTokens };
  const picked = [];
  let used = 0;
  for (const d of rel) {   // 貪心塞 budget，最多 4 段
    if (picked.length >= 4) break;
    const e = estPromptPts({ messages: [{ role: "system", content: d.text }] });
    if (used + e > budgetEst) continue;
    used += e;
    picked.push(d);
  }
  if (!picked.length) return { msgs: [], count: 0, embTokens };
  picked.sort((a, b) => a.i - b.i);   // 按時間序排回來，模型好讀
  const block = "[相關歷史原文（與你本問最相關，按時間序；session 完整保留）]\n" +
    picked.map((d, n) => `〈片段${n + 1}〉${d.text}`).join("\n");
  return { msgs: [{ role: "system", content: block }], count: picked.length, embTokens };
}

/** 把舊訊息分段壓成摘要：system 留首、最近 2 則原文、其餘濃縮；單一超長訊息則砍其前段 */
async function compressMessages(msgs, targetEst, gkey, roundKeys) {
  const sys = msgs.filter((m) => m.role === "system");
  const rest = msgs.filter((m) => m.role !== "system");
  const recent = rest.slice(-2);
  const older = rest.slice(0, -2);
  // 只有 0~2 則還超 → 退回截斷最舊前段（跟 trim 同行為）
  if (!older.length) {
    const tr = trimToLimit({ messages: msgs }, targetEst);
    if (!tr) return null;
    return { messages: tr.body.messages, folded: 0, dropped: tr.dropped, summary: "", sumCost: 0, fromCache: false };
  }
  const h = sumHash(JSON.stringify({ o: older, t: targetEst, v: 1 }));
  const hit = await sumCacheGet(h);
  let summary, sumCost = 0, fromCache = false;
  if (hit) {
    summary = hit;
    fromCache = true;
  } else {
    // 兩輪嘗試：先用標準模型＋大塊（快、品質好）；桶满才退到 allam＋小塊（ctx 只有 4096）
    const STD_MODELS = ["openai/gpt-oss-20b", "openai/gpt-oss-safeguard-20b", "openai/gpt-oss-120b"];
    const runPass = async (budget, models, maxTok, mergeCap) => {
      const chunks = [];
      let cur = [];
      for (const m of older) {
        cur.push(m);
        if (estPromptPts({ messages: cur }) > budget) {
          const last = cur.pop();
          if (cur.length) chunks.push(cur);
          cur = [last];
        }
      }
      if (cur.length) chunks.push(cur);
      while (chunks.length > (mergeCap || 6)) {   // 塊太多 → 兩兩合併再壓（省輪次，一塊都不丟）
        const a = chunks.shift(), b = chunks.shift();
        chunks.unshift([...a, ...b]);
      }
      const parts = [];
      let cost = 0;
      const pricing = await store.getPricing().catch(() => ({}));
      for (const ch of chunks) {
        const txt = ch.map((m) => `${m.role === "user" ? "user" : "assistant"}: ${String(m.content ?? "")}`).join("\n").slice(0, 20000);
        const s = await summarizeWithModels(txt, roundKeys, gkey, models, maxTok);
        parts.push(s.text);
        cost += store.costFor(s.model || models[0], s.pt, s.ct, pricing);
      }
      let sum = parts.join("\n");
      if (estPromptPts({ messages: [{ role: "system", content: sum }] }) > 1500) {
        const s2 = await summarizeWithModels(sum.slice(0, 20000), roundKeys, gkey, models, maxTok);   // 合併再壓一輪
        sum = s2.text;
        const pricing2 = await store.getPricing().catch(() => ({}));
        cost += store.costFor(s2.model || models[0], s2.pt, s2.ct, pricing2);
      }
      return { summary: sum, sumCost: cost };
    };
    try {
      const r1 = await runPass(5000, STD_MODELS, 800, 6);
      summary = r1.summary; sumCost = r1.sumCost;
    } catch (e1) {
      const m1 = String((e1 && e1.message) || e1).slice(0, 100);
      try {
        const r2 = await runPass(1000, ["allam-2-7b"], 400, 12);   // allam ctx 4096＋中文分词差 → 小塊＋短輸出
        summary = r2.summary; sumCost = r2.sumCost;
      } catch (e2) {
        throw new Error(`std[${m1}] allam[${String((e2 && e2.message) || e2).slice(0, 100)}]`);
      }
    }
    await sumCacheSet(h, summary);
  }
  const note = `[前文壓縮摘要（${older.length}則舊訊息濃縮，原文 session 完整保留）]\n${summary}`;
  let out = [...sys, { role: "system", content: note }, ...recent];
  let rag = 0, embCost = 0, embTokens = 0;
  // RAG 補中間缺失：剩餘預算夠＋有本問＋有 key → 向量撿回最相關的原文片段（失敗就跳過，不擋路）
  try {
    const remain = targetEst - estPromptPts({ messages: out }) - 150;
    const lastU = [...msgs].reverse().find((m) => m.role === "user");
    const nvKey = remain > 900 && lastU ? await getNvidiaKey() : "";
    if (nvKey) {
      const rr = await retrieveRelevant(older, lastU.content, remain, nvKey);
      embTokens = rr.embTokens || 0;
      if (rr.count > 0) {
        const out2 = [...sys, { role: "system", content: note }, ...rr.msgs, ...recent];
        if (estPromptPts({ messages: out2 }) <= targetEst) { out = out2; rag = rr.count; }
      }
    }
  } catch { /* RAG 失敗 → 只有摘要，一樣能過 */ }
  if (estPromptPts({ messages: out }) > targetEst) return null;   // 壓完還超 → 交給 trim 收尾
  if (embTokens > 0) {
    try {
      const ep = await store.getPricing().catch(() => ({}));
      embCost = store.costFor(EMBED_MODEL, embTokens, 0, ep);   // embedding 按站內價計入本次帳單
    } catch { embCost = 0; }
  }
  return { messages: out, folded: older.length, dropped: 0, summary, sumCost, fromCache, rag, embCost };
}

/** ITPM 收斂器：先壓縮（保語義），壓不動才截斷；回 {body, folded, dropped, sumCost} 或 null */
async function shrinkForItpm(b, targetEst, gkey, roundKeys) {
  try {
    const c = await compressMessages(b.messages, targetEst, gkey, roundKeys);
    if (c && estPromptPts({ messages: c.messages }) <= targetEst) return { ...c, dropped: c.dropped || 0 };
  } catch { /* 壓縮失敗 → 掉到截斷 */ }
  const tr = trimToLimit(b, targetEst);
  if (!tr) return null;
  return { body: tr.body, folded: 0, dropped: tr.dropped, summary: "", sumCost: 0, fromCache: false };
}
function withMax(b, model) {
  if (b.max_tokens !== undefined) return { ...b, model };
  const raw = LIMITS && LIMITS[model];
  const lim = typeof raw === "number" ? { max: raw, ctx: 0 } : raw;   // 相容舊warm快取的純數字格式
  const sp = store.MODEL_SPECS[model];
  const cap = (lim && lim.max) || (sp && sp.maxOut) || 0;
  const ctx = (lim && lim.ctx) || (sp && sp.ctx) || 0;
  if (!cap) return { ...b, model };
  const pt = estPromptPts(b);                                  // 輸入粗估（中英混合）
  const room = (ctx || 131072) - pt - 4096;                    // 上下文剩餘視窗（留緩衝）
  return { ...b, model, max_tokens: Math.max(64, Math.min(cap, room)) };   // 模型上限 與 剩餘視窗 取小
}

function isCooling(i) {
  const until = STATE.cooldownUntil.get(i);
  return until !== undefined && Date.now() < until;
}

function coolKey(key, status) {
  const ms = COOLDOWN_MS[status];
  if (ms > 0) STATE.cooldownUntil.set("k:" + key, Date.now() + ms);
}

/** 取下一把可用金鑰（round-robin，跳過冷卻中的）；全冷卻時回傳最久之後解凍的 */
function nextKeyIdx(keyArr) {
  const now = Date.now();
  let best = -1;
  let bestUntil = Infinity;
  for (let n = 0; n < keyArr.length; n++) {
    const i = (STATE.cursor + n) % keyArr.length;
    const until = STATE.cooldownUntil.get("k:" + keyArr[i]);
    if (until === undefined || now >= until) {
      STATE.cursor = (i + 1) % keyArr.length;
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

/** header 值必須 ASCII（Node 對非 ASCII setHeader 直接拋錯）：中文一律轉數字型 */
function ascii(s) {
  return String(s == null ? "" : s).replace(/[^\x20-\x7E]/g, "?").slice(0, 200);
}

function checkAuth(req, res) {
  // 舊共用入口（相容保留，不扣點）。新用戶請用 /api/admin 發的 user token。
  const want = process.env.ROUTER_TOKEN;
  const got = req.headers.authorization || "";
  if (want && got === `Bearer ${want}`) return { kind: "legacy" };
  return null;
}

/** 解析回應 usage → {pt, ct}（真實 input/output tokens）；拿不到回 null */
function parseUsage(text) {
  try {
    const j = JSON.parse(text);
    const u = j.usage || {};
    const pt = Number(u.prompt_tokens), ct = Number(u.completion_tokens);
    if (Number.isFinite(pt) && Number.isFinite(ct)) return { pt, ct };
  } catch { /* 非 JSON */ }
  return null;
}

/** 串流沒有 usage → 依輸入字數估 input，輸出粗估（VTuber 對話短，誤差可接受） */
function estimateTokens(body) {
  const input = JSON.stringify(body.messages || body.input || "").length;
  const pt = Math.max(1, Math.ceil(input / 4));
  return { pt, ct: Math.max(100, Math.ceil(pt / 2)) };
}

module.exports = async (req, res) => {
  const T0 = Date.now();   // 量測前置耗時（→ Server-Timing，診斷「第一個token慢」）
  if (req.method !== "POST") return sendJson(res, 405, { error: { message: "POST only" } });

  // 鑑權：admin / user token / 舊共用入口
  let caller = checkAuth(req, res);
  if (!caller) {
    const a = await libAuth.auth(req);
    if (!a.ok) return sendJson(res, 401, { error: { message: "unauthorized" } });
    // admin 也能直接聊天（不扣點）
    caller = { kind: a.kind, user: a.user, sub: a.sub };   // sub = 子金鑰資訊（有申請多把金鑰時）
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
  // 方案先算（窗口 + 是否吃到飽），再做餘額預檢
  let PLAN_CAPS = null;   // 扣點時用它的 disc（API方案折扣）與 fee（>0=吃到飽）
  if (caller.kind === "user" && caller.user) {
    try {
      const users0 = (await store.getUsers()) || {};
      const u0 = users0[caller.user.token];
      if (u0) {
        const [plans, evRaw] = await Promise.all([store.getPlans(), store.getEvent()]);   // 並行省一輪跨海
        try { if (store.maybeRenew(u0, plans)) await store.setUsers(users0); } catch {}   // 到期自動續約（未取消才扣費）
        const ev = store.activeEvent(evRaw);
        const caps = store.planCapsFor(plans, store.activePlanOf(u0, plans), ev);
        PLAN_CAPS = caps;
        const used5 = store.hourlySpend(u0, 5), usedW = store.hourlySpend(u0, 168);
        const act = ev ? `（活動×${ev.mult}）` : "";
        if (caps.h5 > 0 && used5 >= caps.h5) {
          return sendJson(res, 429, { error: { message:
            `方案 ${caps.label} 的5小時用量已滿（${used5.toFixed(4)} / ${caps.h5} 點${act}），稍後再試或升級方案`, code: "plan_5h_limit" } });
        }
        if (caps.wk > 0 && usedW >= caps.wk) {
          return sendJson(res, 429, { error: { message:
            `方案 ${caps.label} 的每週用量已滿（${usedW.toFixed(4)} / ${caps.wk} 點${act}），下週再試或升級方案`, code: "plan_week_limit" } });
        }
      }
    } catch { /* 配額檢查失敗不擋路 */ }
  }

  // 付費方案生效 = 吃到飽（API不扣點）→ 餘額0也放行；Free 才做402預檢
  const planFed = !!(PLAN_CAPS && PLAN_CAPS.fee > 0);
  if (!planFed && caller.kind === "user" && caller.user.credits !== -1 && (Number(caller.user.credits) || 0) <= 0) {
    return sendJson(res, 402, { error: { message: "點數不足，請聯繫管理員充值", code: "insufficient_credits" } });
  }

  const keyObjs = await store.allKeys();
  const keys = keyObjs.map((k) => k.key);
  if (!keys.length) return sendJson(res, 500, { error: { message: "未設定 GROQ_KEYS" } });

  // 方案優先權（排隊不擋路）：RPM 吃緊（冷卻金鑰占比高）→ 先跑高方案，Free 只是慢、永不拒絕
  // 延遲階梯：≥50%冷卻 Free+3s ｜ ≥75% Free+6s·Plus+2s ｜ ≥90% Free+10s·Plus+5s·Pro+2s ｜ Max/Ultra 永遠即時
  if (caller.kind === "user" && PLAN_CAPS) {
    const now2 = Date.now();
    let cooling = 0;
    for (const gk of keys) if ((STATE.cooldownUntil.get("k:" + gk) || 0) > now2) cooling++;
    const pressure = keys.length ? cooling / keys.length : 0;
    const tmap = { free: 0, plus: 1, pro: 2, max: 3, ultra: 4 };
    const tier = tmap[PLAN_CAPS.id] !== undefined ? tmap[PLAN_CAPS.id] : 0;
    let wait = 0;
    if (pressure >= 0.9)       wait = tier === 0 ? 10000 : tier === 1 ? 5000 : tier === 2 ? 2000 : 0;
    else if (pressure >= 0.75) wait = tier === 0 ? 6000  : tier === 1 ? 2000 : 0;
    else if (pressure >= 0.5)  wait = tier === 0 ? 3000  : 0;
    if (wait > 0) {
      try { res.setHeader("x-priority-wait", String(wait)); } catch {}
      await new Promise((r) => setTimeout(r, wait));   // 讓高方案先跑；free只是慢，不擋
    }
  }

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

  // 本發帳本：壓縮摘要花的點數（併入實扣，1:1 如實轉嫁）與展示字串
  let summaryCostTotal = 0, summaryNote = "", summaryFolded = 0, summaryRag = 0, embCostTotal = 0;
  const pickSummaryKey = (arr) => {
    const now = Date.now();
    return arr.find((k) => (STATE.cooldownUntil.get("k:" + k) || 0) <= now) || arr[0];
  };

  // 預先壓縮：輸入明顯超過免費層 ITPM（est > 已知上限+300）→ 先濃縮再打，省掉一輪 413 來回
  // 上限取「已知最大」（將來掛 Dev Tier key 會自然墊高）；沒有紀錄時默認 7000
  {
    const caps = [...STATE.itpm.values()].filter((v) => Number.isFinite(v) && v > 0);
    const limHint = caps.length ? Math.max(...caps) : 7000;
    if (Array.isArray(body.messages) && body.messages.length > 2 && estPromptPts(body) > limHint + 300) {
      try {
        const sk = pickSummaryKey(keys);
        const c = await compressMessages(body.messages, limHint - 400, sk, keys);
        if (c && estPromptPts({ messages: c.messages }) <= limHint - 400) {
          body = { ...body, messages: c.messages };
          summaryCostTotal += c.sumCost || 0;
          embCostTotal += c.embCost || 0;
          summaryFolded += c.folded || 0;
          summaryRag += c.rag || 0;
          if (c.folded > 0) summaryNote = `${c.folded}則舊訊息→摘要${c.fromCache ? "（快取）" : ""}${c.rag > 0 ? `＋RAG撿回${c.rag}段原文` : ""}`;
        }
      } catch { /* 預壓失敗 → 走正常流程，413 時再收斂 */ }
    }
  }

  let lastError = { status: 502, payload: { error: { message: "all keys/models exhausted" } } };
  let reqError = null;   // 優先回報「呼叫端指定模型」的真錯誤（別被梯隊最後的allam遮掉）

  if (!LIMITS) ensureLimits().catch(() => {});   // 非阻塞：這一發先用靜態表上車，抓好後的請求就有真值

  // 上下文快滿 → 友善提早擋（比上游400 "reduce the length" 好讀）
  if (body.messages || body.input) {
    const ptE = estPromptPts(body);
    const rr = LIMITS && LIMITS[ladder[0]];
    const rctx = (rr && (typeof rr === "object" ? rr.ctx : 0)) || (store.MODEL_SPECS[ladder[0]] || {}).ctx || 131042;
    if (ptE > rctx - 1024) {   // 只擋「真的滿到連1k都塞不下」——上下文用到模型支援的最大值
      return sendJson(res, 400, { error: { message:
        `上下文已達模型上限（輸入≈${ptE} / ${rctx} tokens）：按🧹開新對話，或 ✏️編輯/刪除幾則舊訊息再送`, code: "context_full" } });
    }
  }

  for (const model of ladder) {
    let modelDead = false;
    let itpmFails = 0;   // 每模型最多自我校準收斂 3 次（防死循環）
    let compressedThisModel = false;   // 本模型已壓過 → 之後只截斷（摘要的摘要沒意義）

    // 渠道路由：有啟用且支援此模型的渠道 → 按權重選一個，用它的 keys；
    // 沒有渠道（或 KV 未開）→ 用全池（env + 管理的 keys）
    let roundKeys = keys;
    let channelName = "";
    let channelZdr = false;
    try {
      const chs = await store.getChannels();
      const picked = chs ? store.pickChannel(chs, model) : null;
      if (picked && (picked.keys || []).length) {
        roundKeys = picked.keys;
        channelName = picked.name || picked.id;
        channelZdr = !!picked.zdr;
      }
    } catch { /* 渠道讀取失敗就用全池 */ }

    // NVIDIA 直連模型：走 nvapi 單 key（存服務端 KV，只寫不讀），不吃 Groq 輪替池；
    // 失敗就記錯並跳下一階（Groq 梯隊兜底）
    const nvSpec = store.NV_CHAT_MODELS[model];
    if (nvSpec) {
      let nk = "";
      try { nk = await getNvidiaKey(); } catch {}
      if (!nk) {
        lastError = { status: 500, payload: { error: { message: "未設定 NVIDIA 金鑰（管理頁 config.set nvidiaKey）" } } };
        if (model === ladder[0] && !reqError) reqError = lastError;
        continue;   // 下一階
      }
      roundKeys = [nk];   // 單 key 跑完這圈
    }

    // 大輸入（近/超 ITPM）→ 優先挑「沒被 org ITPM 拒過、或上限吃得下」的 key：
    // 將來掛一把 Dev Tier 的 key 就會自然被選中跑長上下文（免費 key 全被牆擋也照跑）
    const inputEst = estPromptPts(body);
    if (inputEst > 6500) {
      const elig = roundKeys.filter((k) => { const cap = STATE.itpm.get("k:" + k); return cap === undefined || cap >= inputEst; });
      if (elig.length) roundKeys = elig;
    }

    for (let tries = 0; tries < roundKeys.length && !modelDead; tries++) {
      const idx = nextKeyIdx(roundKeys);
      if (idx < 0) break;
      const gkey = roundKeys[idx];
      const t0 = Date.now();   // 速度量測起點（這把 key 的上游耗時）

      const init = {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${gkey}`,
        },
        body: JSON.stringify(withMax(body, model)),
      };

      let upstream;
      try {
        // 100s 上限（< Vercel 120s）：上游排隊太久就換下一把/下一階，不讓整發陪葬；
        // 只包 fetch 本身，串流 body 不受影響
        const ac = new AbortController();
        const tm = setTimeout(() => ac.abort(), 100000);
        try {
          upstream = await fetch(nvSpec ? NV_URL : GROQ_URL, { ...init, signal: ac.signal });
        } finally { clearTimeout(tm); }
      } catch (e) {
        coolKey(gkey, 503);
        try { await store.recordKeyStat(gkey, { err: true }); } catch {}
        lastError = { status: 502, payload: { error: { message: `network: ${e.message}` } } };
        continue;
      }

      if (upstream.ok) {
        res.setHeader("x-router-model", model);
        res.setHeader("x-router-upstream", nvSpec ? "nvidia" : "groq");
        res.setHeader("x-router-key-index", String(idx));
        res.setHeader("x-router-key-count", String(roundKeys.length));
        if (channelName) res.setHeader("x-router-channel", channelName);
        if (summaryNote) { try { res.setHeader("x-context-summary", `folded=${summaryFolded}+rag=${summaryRag}`); } catch {} }
        if (summaryCostTotal > 0) { try { res.setHeader("x-summary-cost", String(summaryCostTotal)); } catch {} }
        if (embCostTotal > 0) { try { res.setHeader("x-emb-cost", String(embCostTotal)); } catch {} }
        // ZDR（Zero Data Retention）：本中轉全程不存訊息內容，只記 token 流量
        if (channelZdr || process.env.ZDR === "1") res.setHeader("x-router-zdr", "1");

        // user 帳號扣點（admin/legacy 不扣；-1 無限不扣）——見下方各分支內聯實作
        // （扣點必須在 res.end() 之前完成，否則 x-credits-left 發不出去）

        if (wantStream) {
          const est = estimateTokens(body);   // 基底估算（上游沒給 usage 才當 fallback）
          res.statusCode = 200;
          res.setHeader("Content-Type", upstream.headers.get("content-type") || "text/event-stream");
          res.setHeader("Cache-Control", "no-cache");
          res.setHeader("Connection", "keep-alive");
          try { res.setHeader("Server-Timing", `prep;dur=${Date.now() - T0}`); } catch {}   // 前置耗時可視
          res.flushHeaders?.();
          let realUsage = null, hold = "";
          try {
            for await (const chunk of upstream.body) {
              // 邊轉邊掃 SSE：抓上游真實 usage（單行 data: 事件）
              hold += Buffer.from(chunk).toString("utf8");
              const evts = hold.split(/\r?\n\r?\n/);
              hold = evts.pop();
              for (const evt of evts) {
                const line = evt.split(/\r?\n/).find((l) => l.startsWith("data:"));
                if (!line) continue;
                const payload = line.slice(5).trim();
                if (payload === "[DONE]") continue;
                try {
                  const jj = JSON.parse(payload);
                  if (jj.usage && Number.isFinite(jj.usage.prompt_tokens)) realUsage = jj.usage;
                } catch {}
              }
              res.write(chunk);
            }
          } catch {
            // 上游中斷就直接收尾，客戶端會看到不完整的 SSE
          }
          // 流結束 → 用真實 usage 結算（上游有給就實測，否則才用估算）
          const u2 = (realUsage && Number.isFinite(realUsage.completion_tokens))
            ? { pt: realUsage.prompt_tokens, ct: realUsage.completion_tokens } : est;
          const total = u2.pt + u2.ct;
          const baseCost = store.costFor(model, u2.pt, u2.ct, await store.getPricing());
          const cost = Math.max(0.000001, Math.round((baseCost + summaryCostTotal + embCostTotal) * 1e6) / 1e6);
          let billedLeft = null, planFedFlag = false;
          let win5 = null, winWk = null, cap5 = 0, capWk = 0;   // 方案用量%（給前端顯示）
          if (caller.kind === "user" && caller.user.credits !== -1) {
            try {
              const users = (await store.getUsers()) || {};
              const u = users[caller.user.token];
              if (u && u.credits !== -1) {
                planFedFlag = !!(PLAN_CAPS && PLAN_CAPS.fee > 0);   // 吃到飽不扣點
                if (!planFedFlag) u.credits = Math.max(0, (Number(u.credits) || 0) - cost);
                u.usedTokens = (Number(u.usedTokens) || 0) + total;
                if (caller.sub) { const kk = (u.keys || []).find((x) => x.id === caller.sub.id); if (kk) kk.lastUsed = Date.now(); }
                await store.addHourlySpend(u, cost);   // 計入5h/週配額桶（吃到飽也計）
                if (PLAN_CAPS && PLAN_CAPS.h5 > 0) {   // 付費方案才有額度可報
                  win5 = store.hourlySpend(u, 5);
                  winWk = store.hourlySpend(u, 168);
                  cap5 = PLAN_CAPS.h5; capWk = PLAN_CAPS.wk;
                }
                await store.setUsers(users);
                billedLeft = u.credits;
                await store.recordUsage(caller.user.token, model, total, cost);
                await store.logRequest({ user: caller.user.name || caller.user.token.slice(0, 12),
                  key: caller.sub ? caller.sub.name : undefined,
                  model, tokens: total, cost });
                await store.logUserReq(caller.user.token, { model, tokens: total, cost,
                  key: caller.sub ? caller.sub.name : "" });
              }
            } catch { /* 扣點失敗不擋回應 */ }
          }
          try { await store.recordKeyStat(gkey, { tokens: total }); } catch {}
          // 最終 chunk：最終 usage +（有扣點才帶）扣點/餘額 → 前端顯示
          try {
            const inject = { choices: [], usage: {
              prompt_tokens: u2.pt, completion_tokens: u2.ct, total_tokens: total,
              estimated: !realUsage } };
            if (billedLeft !== null) {
              inject.x_cost = planFedFlag ? 0 : cost;   // 實扣（方案吃到飽=0）
              inject.x_value = cost;                    // 市價（ROI/展示用）
              inject.x_left = billedLeft;
              inject.x_plan = planFedFlag ? 1 : 0;
              if (summaryCostTotal > 0) inject.x_sumcost = Math.round(summaryCostTotal * 1e6) / 1e6;
              if (embCostTotal > 0) inject.x_embcost = Math.round(embCostTotal * 1e6) / 1e6;
              if (summaryNote) inject.x_summary = summaryNote;
              if (summaryRag > 0) inject.x_rag = summaryRag;
              if (win5 !== null) inject.x_win = { u5: win5, c5: cap5, uw: winWk, cw: capWk };   // 方案用量%
            }
            res.write(`data: ${JSON.stringify(inject)}\n\n`);
            res.write("data: [DONE]\n\n");
          } catch { /* 客戶端已斷線就跳過 */ }
          res.end();
          // 實測速度：完成 tokens ÷ 上游耗時（串流含客戶端讀取，僅供參考）
          try { await store.recordSpeed({ model, tokens: total,
            tps: total / Math.max(0.05, (Date.now() - t0) / 1000),
            u: caller.user ? caller.user.token : caller.kind }); } catch {}
          return;
        }

        const text = await upstream.text();
        const usage = parseUsage(text) || estimateTokens(body);
        const realTokens = usage.pt + usage.ct;
        // 計費：直接按官方價（訂閱期間此值只進窗口/ROI，不動餘額；Free 則照扣）＋壓縮摘要成本
        const baseCost = store.costFor(model, usage.pt, usage.ct, await store.getPricing());
        const cost = Math.max(0.000001, Math.round((baseCost + summaryCostTotal + embCostTotal) * 1e6) / 1e6);
        try { await store.recordKeyStat(gkey, { tokens: realTokens }); } catch {}
        try { await store.recordSpeed({ model, tokens: realTokens,
          tps: realTokens / Math.max(0.05, (Date.now() - t0) / 1000),
          u: caller.user ? caller.user.token : caller.kind }); } catch {}
        // 先扣點再 end（header 必須在 end 之前設，否則發不出去）
        if (caller.kind === "user" && caller.user.credits !== -1) {
          try {
            const users = (await store.getUsers()) || {};
            const u = users[caller.user.token];
            if (u && u.credits !== -1) {
              const fed = !!(PLAN_CAPS && PLAN_CAPS.fee > 0);   // 付費方案=吃到飽不扣點
              if (!fed) u.credits = Math.max(0, (Number(u.credits) || 0) - cost);
              u.usedTokens = (Number(u.usedTokens) || 0) + realTokens;
              if (caller.sub) { const kk = (u.keys || []).find((x) => x.id === caller.sub.id); if (kk) kk.lastUsed = Date.now(); }
              await store.addHourlySpend(u, cost);   // 計入5h/週配額桶（吃到飽也計，窗口才會滾動攔）
              await store.setUsers(users);
              res.setHeader("x-credits-left", String(u.credits));
              if (fed) res.setHeader("x-plan-usage", "1");   // 本發方案內行使、免扣
              await store.recordUsage(caller.user.token, model, realTokens, cost);
              await store.logRequest({ user: caller.user.name || caller.user.token.slice(0, 12),
                key: caller.sub ? caller.sub.name : undefined,
                model, tokens: realTokens, cost });
              await store.logUserReq(caller.user.token, { model, tokens: realTokens, cost,
                key: caller.sub ? caller.sub.name : "" });
            }
          } catch { /* 扣點失敗不影響已生成的回應 */ }
        }
        res.statusCode = 200;
        res.setHeader("Content-Type", "application/json; charset=utf-8");
        try { res.setHeader("Server-Timing", `prep;dur=${Date.now() - T0}`); } catch {}
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
      coolKey(gkey, status);
      // Groq 免費層 ITPM（單發輸入/分鐘，org層）超標 → 自動裁最舊、同輪立刻瘦身重打
      // 分key沒用：限制掛在 org 上；session 不動，只瘦身這次請求
      const mLimit = (status === 400 || status === 413 || status === 429) ? String(msg).match(/Limit\s+(\d+)/) : null;   // Groq用413(Payload Too Large)回ITPM超標
      if (mLimit && /input tokens per minute|ITPM/i.test(msg)) {
        const lim = Number(mLimit[1]) || 7000;
        STATE.itpm.set("k:" + gkey, lim);                       // 記住這把 key 背後 org 的上限（供大請求挑 key）
        store.setItpmCap(store.mask(gkey), { limit: lim,
          org: (String(msg).match(/org_[a-z0-9]+/) || [""])[0] }).catch(() => {});
        if (itpmFails < 3) {
          itpmFails++;
          // 自我校準「盡可能大」：錯誤訊息帶真實輸入量 Requested R → 算出 r=真實/估算
          // 目標=貼近上限（lim−300）的最大可過上下文 → 只砍到剛好能過為止
          const mReq = String(msg).match(/Requested\s+(\d+)/);
          const estSent = estPromptPts(body);
          const r = (mReq && estSent > 0) ? (Number(mReq[1]) / estSent) : 0.7;
          const targetEst = Math.floor((lim - 300) / Math.max(0.3, r));
          let sh = null, shErr = "";
          if (!compressedThisModel) {
            // 第一輪：壓縮（保語義，摘要走別把 key）；壓完還超或壓不動 → 同輪內接著截斷
            try {
              const c = await compressMessages(body.messages, targetEst, gkey, roundKeys);
              if (c && estPromptPts({ messages: c.messages }) <= targetEst) {
                sh = { ...c, dropped: c.dropped || 0 };
              } else {
                shErr = c ? `fit-fail(outEst=${estPromptPts({ messages: c.messages })} tgt=${targetEst})` : "compress-null";
              }
            } catch (e) { shErr = String((e && e.message) || e).slice(0, 140); }
            if (!sh) {
              const tr = trimToLimit(body, targetEst);
              if (tr) sh = { body: tr.body, folded: 0, dropped: tr.dropped, sumCost: 0 };
              else if (!shErr) shErr = "trim-null";
            }
            compressedThisModel = true;
            if (!sh || sh.folded === 0) { try { res.setHeader("x-context-debug", ascii("shrink:" + shErr) || "shrinkTrim"); } catch {} }
          } else {
            const tr = trimToLimit(body, targetEst);
            if (tr) sh = { body: tr.body, folded: 0, dropped: tr.dropped, sumCost: 0 };
          }
          if (sh) {
            body = sh.body;
            summaryCostTotal += sh.sumCost || 0;
            embCostTotal += sh.embCost || 0;
            summaryFolded += sh.folded || 0;
            summaryRag += sh.rag || 0;
            if (sh.folded > 0) summaryNote = `${summaryFolded}則舊訊息→摘要${sh.rag > 0 ? `＋RAG撿回${sh.rag}段原文` : ""}`;
            tries--;                                       // 同一發預算內立刻重打
            try {
              res.setHeader("x-context-trimmed", String(sh.dropped || 0));
              if (sh.folded > 0) res.setHeader("x-context-summary", `folded=${sh.folded}+rag=${sh.rag || 0}`);
            } catch {}
            continue;
          }
        }
      }
      try { await store.recordKeyStat(gkey, { err: true }); } catch {}
      lastError = { status: status === 404 ? 502 : status, payload: payload || { error: { message: `HTTP ${status}` } } };
      if (model === ladder[0] && !reqError) reqError = lastError;   // 記住指定模型的真錯誤

      // 模型不存在 / 模型名錯誤 → 換下一階模型（跟金鑰無關，繼續敲同一把也沒用）
      if (status === 404 || /model.*not.*found|does not exist|decommissioned/i.test(msg)) {
        modelDead = true;
      }
      // 401/403/429 → 該把已冷卻，換下一把
    }

    if (modelDead) continue; // 換下一階模型
    // 不是 modelDead（例如全部金鑰都被 429 擋住）→ 等下一次請求再試同一階
  }

  return (function () {
    const fin = reqError || lastError;
    return sendJson(res, fin.status, fin.payload);
  })();
};
