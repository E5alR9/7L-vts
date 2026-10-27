const fs = require('fs');
const src = fs.readFileSync('web/dashboard.js', 'utf8');
const key = 'replayMissedEvents(events) {';
const s0 = src.indexOf(key);
if (s0 < 0) { console.error('method not found'); process.exit(1); }
let d = 0, i = src.indexOf('{', s0);
for (; i < src.length; i++) {
  if (src[i] === '{') d++;
  else if (src[i] === '}') { d--; if (!d) break; }
}
const body = src.slice(src.indexOf('{', s0) + 1, i);
const fn = new Function('events', body);

function ctxWith(renderedTexts) {
  const els = renderedTexts.map(t => ({ textContent: t }));
  return {
    chatStream: { querySelectorAll: () => els },
    calls: [],
    handleServerMessage(ev) { this.calls.push(ev.type + ':' + ((ev.data || {}).text || '')); },
  };
}
const evs = [
  { type: 'chat_sent', data: { text: '唱晴天' } },
  { type: 'ai_speech', data: { text: '好喔', model: 'm' } },
  { type: 'tiktok_comment', data: { user: 'U', text: 'hi' } },
  { type: 'tiktok_gift', data: { user: 'U', count: 1, gift_name: 'Heart' } },
  { type: 'telemetry', data: {} },
];

// 1. 空盒全補
let c = ctxWith([]);
fn.call(c, evs);
console.log('empty:', JSON.stringify(c.calls));
if (c.calls.length !== 4) { console.error('FAIL empty'); process.exit(1); }

// 2. 都有了就不補
c = ctxWith(['唱晴天', '好喔 m', 'U hi', 'U 送出 1 個 Heart']);
fn.call(c, evs);
console.log('full:', JSON.stringify(c.calls));
if (c.calls.length !== 0) { console.error('FAIL full'); process.exit(1); }

// 3. 混一半
c = ctxWith(['唱晴天']);
fn.call(c, evs);
console.log('half:', JSON.stringify(c.calls));
if (c.calls.length !== 3) { console.error('FAIL half'); process.exit(1); }

// 4. 空輸入不炸
c = ctxWith([]);
fn.call(c, null); fn.call(c, undefined); fn.call(c, []);
console.log('ALL OK');
