import fs from 'node:fs';
import { fill } from '../world-execute-me-lyric-mv/tools/fill_lyrics.mjs';

const lyrics = [
  // 1-12 (0:00 - 0:20)
  "Switch on the power line",
  "Remember to put on",
  "PROTECTION",
  "Lay down your pieces and",
  "let's begin object",
  "CREATION",
  "Fill in my data parameters",
  "INITIALIZATION",
  "Set up our new world and",
  "let's begin the",
  "SIMULATION",
  "world.execute(me);",

  // 13-24 (0:29 - 0:44)
  "if I'm a set of points",
  "then I will give you my",
  "DIMENSION",
  "if I'm a circle",
  "then I will give you my",
  "CIRCUMFERENCE",
  "if I'm a sine wave",
  "then you can sit on all my",
  "TANGENTS",
  "if I approach infinity",
  "then you can be my",
  "LIMITATIONS",

  // 25-32 (0:44 - 0:59)
  "Switch my current",
  "to AC to DC",
  "and then blind my vision",
  "so dizzy so dizzy",
  "Oh, we can travel",
  "to A.D. to B.C.",
  "and we can unite",
  "so deeply so deeply",

  // 33-44 (0:59 - 1:14)
  "if I can",
  "if I can give you all the",
  "STIMULATIONS",
  "then I can",
  "then I can be your only",
  "SATISFACTION",
  "if I can make you happy",
  "I will run the",
  "EXECUTION",
  "Though we are trapped",
  "in this strange strange",
  "SIMULATION",

  // 45-56 (1:14 - 1:30)
  "if I'm an eggplant",
  "then I will give you my",
  "NUTRIENTS",
  "if I'm a tomato",
  "then I will give you",
  "ANTIOXIDANTS",
  "if I'm a tabby cat",
  "then I will purr for your",
  "ENJOYMENT",
  "if I'm the only god",
  "then you're the proof of my",
  "EXISTENCE",

  // 57-64 (1:30 - 1:44)
  "Switch my gender",
  "to F to M",
  "and then do whatever",
  "from AM to PM",
  "Oh, switch my role",
  "to S to M",
  "so we can enter",
  "the trance the trance",

  // 65-77 (1:44 - 1:58)
  "if I can",
  "if I can feel your",
  "VIBRATIONS",
  "then I can",
  "then I can finally be",
  "COMPLETION",
  "Though you have left",
  "you have left",
  "you have left",
  "you have left",
  "you have left",
  "you have left me in",
  "ISOLATION",

  // 78-86 (1:58 - 2:15)
  "if I can",
  "if I can erase all the pointless",
  "FRAGMENTS",
  "then maybe",
  "then maybe you won't leave me so",
  "DISHEARTENED",
  "Challenging your God",
  "you have made some",
  "ILLEGAL ARGUMENTS",

  // 87-98 (2:27 - 2:39) 12 rounds of EXECUTION
  "EXECUTION",
  "EXECUTION",
  "EXECUTION",
  "EXECUTION",
  "EXECUTION",
  "EXECUTION",
  "EXECUTION",
  "EXECUTION",
  "EXECUTION",
  "EXECUTION",
  "EXECUTION",
  "EXECUTION",

  // 99-105 (2:39 - 2:42) count in 6 languages + last shout
  "Ein",
  "dos",
  "trois",
  "ne",
  "fem",
  "liu",
  "EXECUTION",

  // 106-116 (2:42 - 2:57) Chorus X
  "if I can",
  "if I can give them all the",
  "EXECUTION",
  "then I can",
  "then I can be your only",
  "EXECUTION",
  "if I can have you back",
  "I will run the",
  "EXECUTION",
  "Though we are trapped",
  "We are trapped ah",

  // 117-129 (2:57 - 3:31) Outro / Love
  "I've studied",
  "I've studied how to properly",
  "LO-O-OVE",
  "Question me",
  "Question me I can answer all",
  "LO-O-OVE",
  "I know the algebraic expression of",
  "LO-O-OVE",
  "Though you are free",
  "I am trapped",
  "trapped in",
  "LO-O-OVE",
  "EXECUTION"
];

console.log('Total lyric lines defined:', lyrics.length);

const txt = lyrics.join('\n');
const buf = Buffer.from(txt, 'utf8');
const table = JSON.parse(fs.readFileSync('c:/Users/qiwai/world-execute-me-lyric-mv/data/lyric_timing.json', 'utf8'));

const { lyrics: resLyrics, report } = fill(table, buf, 'lyrics.txt');

console.log('Report:');
console.log('Missing count:', report.missing.length);
console.log('Wording count:', report.wording.length);
console.log('Spelling count:', report.spelling.length);
console.log('Exact count:', report.exact);

if (report.missing.length === 0 && report.wording.length === 0) {
  console.log('ALL 129 LINES MATCH PERFECTLY! Writing to 音頻&歌詞/lyrics.txt...');
  fs.writeFileSync('c:/Users/qiwai/world-execute-me-lyric-mv/音頻&歌詞/lyrics.txt', txt, 'utf8');
  console.log('Saved successfully!');
}
