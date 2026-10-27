import fs from 'node:fs';
import crypto from 'node:crypto';

const ROOT = 'c:/Users/qiwai/world-execute-me-lyric-mv';
const timing = JSON.parse(fs.readFileSync(`${ROOT}/data/lyric_timing.json`, 'utf8'));
const currentTxt = fs.readFileSync(`${ROOT}/音頻&歌詞/lyrics.txt`, 'utf8');

const WORD = /[\p{L}\p{N}\p{M}]+/gu;
const h8 = (s) => crypto.createHash('sha256').update(s, 'utf8').digest('hex').slice(0, 8);

function wordsOf(body) {
  const ws = [...body.matchAll(WORD)].map((m) => ({ w: m[0].normalize('NFKC').toLowerCase(), a: m.index, b: m.index + m[0].length }));
  return ws.length ? ws : [{ w: '\u0001' + body, a: 0, b: body.length }];
}
const keyOf = (ws) => ws.map((x) => x.w).join(' ');

const rawLines = currentTxt.split(/\r?\n/).map(l => l.trim()).filter(Boolean);
console.log(`Current file has ${rawLines.length} lines. Expected ${timing.lines.length}.`);

let fileWordIdx = 0;
// Note fill_lyrics.mjs doesn't match line-by-line; it matches sequential words!
// But let's see how fill_lyrics does it.
