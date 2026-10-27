import crypto from 'node:crypto';
import fs from 'node:fs';

const h8 = (s) => crypto.createHash('sha256').update(s, 'utf8').digest('hex').slice(0, 8);
const WORD = /[\p{L}\p{N}\p{M}]+/gu;

const target_h = 'eaf68fce';
console.log('Searching for target_h =', target_h);

// What is sung between 174.98 and 177.25?
// Song: "Though we are trapped, [lyric]..."
// In lyrics sites: "Though we are trapped in the strange, strange simulation" or "trapped, trapped, trapped..."
// Let's test English dictionary words or words from Mili's song.

const vocab = [
  'trapped', 'in', 'the', 'a', 'ah', 'oh', 'so', 'we', 'are', 'me', 'you', 'be', 'to', 'of',
  'strange', 'world', 'here', 'now', 'all', 'love', 'held', 'loop', 'cell', 'cage', 'room',
  'dark', 'cold', 'lost', 'gone', 'stay', 'dead', 'shut', 'away', 'down', 'deep', 'hard',
  'like', 'just', 'still', 'again', 'ever', 'never', 'life', 'mind', 'soul', 'heart',
  'ha', 'la', 'fa', 'da', 'ba', 'na', 'ya', 'eh', 'uh', 'mm'
];

for (const w1 of vocab) {
  for (const w2 of vocab) {
    for (const w3 of vocab) {
      for (const w4 of vocab) {
        if (w1.length + w2.length + w3.length + w4.length === 14) {
          const key = `${w1} ${w2} ${w3} ${w4}`;
          if (h8(key) === target_h) {
            console.log('FOUND MATCH!', key);
          }
        }
      }
    }
  }
}
console.log('Search finished.');
