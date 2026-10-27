const fs = require('fs');
const src = fs.readFileSync('web/dashboard.js', 'utf8');

function extractMethod(name, params) {
  const key = `${name}(${params}) {`;
  const s0 = src.indexOf(key);
  if (s0 < 0) throw new Error('missing ' + name);
  let d = 0, i = src.indexOf('{', s0);
  for (; i < src.length; i++) {
    if (src[i] === '{') d++;
    else if (src[i] === '}') { d--; if (!d) break; }
  }
  return src.slice(src.indexOf('{', s0) + 1, i);
}

// 最小 DOM stub
function makeEl(text) {
  return { textContent: text, children: [], appendChild(c) { this.children.push(c); return c; } };
}
function makeContainer(texts) {
  const els = texts.map(t => ({ textContent: t }));
  return {
    children: [],
    querySelectorAll: () => els,
    appendChild(c) {
      if (c && Array.isArray(c.children) && c !== this) this.children.push(...c.children);
      else this.children.push(c);
      return c;
    },
    set innerHTML(v) { this.children = []; },
    get innerHTML() { return ''; },
    scrollTop: 0, scrollHeight: 0,
  };
}
function makeCtx(renderedTexts) {
  const document = { createDocumentFragment: () => makeContainer([]) };
  return {
    document,
    chatStream: makeContainer(renderedTexts),
    loadedMemoryIds: new Set(),
    appendChatBubble(role, a, b, c, d, frag) {
      const t = role === 'tiktok' ? b : a;
      (frag || this.chatStream).children.push(`${role}:${t}`);
    },
    renderVisionHistory() {},
  };
}

const loadBody = extractMethod('loadConversationHistory', 'memories, merge = false');
const loadFnRaw = new Function('document', 'memories', 'merge', loadBody);
const stubDoc = { createDocumentFragment: () => makeContainer([]) };
function callLoad(ctx, mem, merge) { return loadFnRaw.call(ctx, stubDoc, mem, merge); }
const mem = [
  { role: 'user', speaker: '老爸', content: '唱晴天', time: 1 },
  { role: 'system', speaker: '系統', content: '鋼琴準備線上搜尋演奏《晴天》', time: 2 },
];

// 1. 非 merge 照舊整盒重建
let c = makeCtx([]);
callLoad(c, mem, false);
console.log('full:', JSON.stringify(c.chatStream.children));
if (c.chatStream.children.length !== 2) { console.error('FAIL full'); process.exit(1); }

// 2. merge：已渲染的不重複，只補系統那句
c = makeCtx(['唱晴天']);
c.loadedMemoryIds.add('user_老爸_唱晴天_1');
callLoad(c, mem, true);
console.log('merge:', JSON.stringify(c.chatStream.children));
if (c.chatStream.children.length !== 1 || !c.chatStream.children[0].includes('鋼琴準備')) {
  console.error('FAIL merge'); process.exit(1);
}

// 3. merge 空記憶不炸不清空
c = makeCtx(['a']);
callLoad(c, [], true);
if (c.chatStream.children.length !== 0) { console.error('FAIL empty'); process.exit(1); }
console.log('ALL OK');
