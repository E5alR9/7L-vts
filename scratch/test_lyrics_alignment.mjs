import fs from 'node:fs';
import path from 'node:path';
import { fill } from '../world-execute-me-lyric-mv/tools/fill_lyrics.mjs';

const lyricsPath = 'c:/Users/qiwai/world-execute-me-lyric-mv/音頻&歌詞/lyrics.txt';
const buf = fs.readFileSync(lyricsPath);
const table = JSON.parse(fs.readFileSync('c:/Users/qiwai/world-execute-me-lyric-mv/data/lyric_timing.json', 'utf8'));
const { lyrics, report } = fill(table, buf, 'lyrics.txt');

console.log('Report:');
console.log('Missing count:', report.missing.length);
if (report.missing.length) {
  console.log('Missing line indices (0-based):', report.missing);
  for (const idx of report.missing) {
    console.log(`Line ${idx + 1} (${table.lines[idx].start}s): words=${table.lines[idx].words}, letters=${table.lines[idx].letters}, h=${table.lines[idx].h}`);
  }
}
console.log('Wording count:', report.wording.length);
if (report.wording.length) {
  console.log('Wording line indices:', report.wording);
}
console.log('Spelling count:', report.spelling.length);
console.log('Exact count:', report.exact);
