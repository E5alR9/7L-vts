import fs from 'node:fs';
import { fill } from '../world-execute-me-lyric-mv/tools/fill_lyrics.mjs';

const lyricsPath = 'c:/Users/qiwai/world-execute-me-lyric-mv/音頻&歌詞/lyrics.txt';
const buf = fs.readFileSync(lyricsPath);
const table = JSON.parse(fs.readFileSync('c:/Users/qiwai/world-execute-me-lyric-mv/data/lyric_timing.json', 'utf8'));
const { lyrics, report } = fill(table, buf, 'lyrics.txt');

for (const i of report.wording) {
  console.log(`Line ${i + 1} (${table.lines[i].start}s): got "${lyrics.lines[i].text}", expected words=${table.lines[i].words}, letters=${table.lines[i].letters}, h=${table.lines[i].h}`);
}
