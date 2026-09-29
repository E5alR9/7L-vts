# -*- coding: utf-8 -*-
"""請 Gemini 親耳驗收：同段落（原曲 vs 我方渲染）＋渲染代碼，求診斷。
用法：python scripts/ask_gemini_mix.py
"""
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def load_gemini_keys():
    t = open(os.path.join(BASE, ".env"), encoding="utf-8-sig").read()
    out = []
    for key in ("GEMINI_API_KEYS", "GEMINI_API_KEY"):
        m = re.search(r"^" + key + r"=(.*)$", t, re.M)
        if m:
            v = m.group(1).strip()
            # 多行值：吃到下一個 KEY= 為止
            lines = t[m.start():].splitlines()[1:]
            for ln in lines:
                if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", ln):
                    break
                v += " " + ln.strip()
            out += [k.strip() for k in re.split(r"[\s,;]+", v) if k.strip()]
    return out


def excerpt(src, dst, start=60.0, dur=30.0, sr=16000):
    import librosa
    import soundfile as sf
    y, _ = librosa.load(src, sr=sr, mono=True, offset=start, duration=dur)
    sf.write(dst, y, sr)
    return dst


PROMPT = """你是資深混音師＋MIDI 渲染工程師。聽這兩段同曲同段落（30 秒）：
A = 原曲官方混音（參考標準）；B = 我的程式渲染（SoundFont FluidR3 真採樣＋自寫 numpy 混音）。

已知渲染鏈：mido 讀譜 → 自寫 SF2 解析（keyRange/sampleID/tune/atten/loop，不支援 modulator/LFO/濾波）
→ 線性插值重採樣 → 各軌直接疊加 → tanh 總線 → 正規化。人聲是原音疊頂。

請回答（繁中，具體可執行）：
1. B 最刺耳的 3 個問題是什麼（逐條指出時間點＋現象，如渾濁/rclick/相位/鼓糊/貝斯轟）？
2. 每個問題最可能的技術成因（對照我的渲染鏈）？
3. 給修法（參數級：attack/release/增益/循環策略/包絡，程式碼級改哪個函式）？
4. 有沒有哪個問題是「換音源也救不了、必須改渲染器」的？
篇幅精簡，條列，不要客套話。
"""


def main():
    import asyncio
    from google import genai
    from google.genai import types

    keys = load_gemini_keys()
    print("keys:", len(keys))
    a = excerpt(os.path.join(BASE, "data", "score_in", "anthem.m4a"),
                os.path.join(BASE, "data", "clip_A_orig.wav"))
    b = excerpt(os.path.join(BASE, "songs_ai", "sun_burn_out_final.wav"),
                os.path.join(BASE, "data", "clip_B_render.wav"))
    code = open(os.path.join(BASE, "services", "soundfont.py"), encoding="utf-8").read()[:12000]
    last = ""
    for model in ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.5-flash"):
        for k in keys[:12]:
            try:
                client = genai.Client(api_key=k)
                up_a = client.files.upload(file=a)
                up_b = client.files.upload(file=b)
                resp = asyncio.run(asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=model,
                        contents=[types.Content(role="user", parts=[
                            types.Part.from_text(text=PROMPT),
                            types.Part.from_text(text="A=原曲，B=我方渲染"),
                            types.Part.from_uri(file_uri=up_a.uri, mime_type="audio/wav"),
                            types.Part.from_uri(file_uri=up_b.uri, mime_type="audio/wav"),
                            types.Part.from_text(text="渲染器代碼：\n" + code),
                        ])],
                    ), timeout=180.0))
                print(f"MODEL: {model}")
                print(resp.text)
                with open(os.path.join(BASE, "data", "gemini_mix_verdict.txt"), "w", encoding="utf-8") as f:
                    f.write(f"MODEL: {model}\n\n" + (resp.text or ""))
                return
            except Exception as e:
                last = str(e)[:120]
                print(f"{model} key fail:", last)
                continue
    print("ALL FAILED:", last)


if __name__ == "__main__":
    main()
