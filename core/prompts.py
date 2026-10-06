import re
import random
import sys
import os
import json
import difflib
from typing import Tuple

# Project imports
from core.utils import log_print, get_current_time_string, get_unified_time_prompt, get_silence_ticks, get_uptime_ticks, format_ticks_to_human
import services.piano_engine as pe
from services.piano_engine import get_piano_realtime_prompt
from mic_live_plugin import os_desktop_sensor

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

from core.identity import get_owner_name as _get_owner_name


def _default_user_title() -> str:
    return _get_owner_name()


DEFAULT_USER_TITLE = _default_user_title()  # 預設使用者稱謂（env OWNER_NAME 可配；雲端自訂名稱優先）


class TextCleanEngine:
    #  Unicode Emoji 預編譯常數
    EMOJI_PATTERN = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs (包含 , , ,  等)
        "\U0001F680-\U0001F6FF"  # transport & map
        "\U0001F1E0-\U0001F1FF"  # flags
        "\U0001F900-\U0001F9FF"  # supplemental symbols
        "\U0001FA00-\U0001FAFF"  # symbols and pictographs extended-a
        "\U00002600-\U000026FF"  # miscellaneous symbols (如 ,  等)
        "\U00002700-\U000027BF"  # dingbats (如 , ,  等)
        "\U0000FE00-\U0000FE0F"  # variation selectors
        "\U0001F000-\U0001F02F"  # mahjong tiles
        "\U0001F0A0-\U0001F0FF"  # playing cards
        "]+",
        flags=re.UNICODE
    )

    RE_THOUGHT_TAG = re.compile(r'\[(?:THOUGHT|THINK|心想|內心|腦內思緒|腦內想法)[：:]\s*[^\]]*?\]', flags=re.IGNORECASE)
    RE_THINK_BLOCK = re.compile(r'<(?:think|thought)>.*?(?:</(?:think|thought)>|$)', flags=re.DOTALL | re.IGNORECASE)
    RE_THINKING_PROC = re.compile(r'^(?:Thinking Process|Thinking|腦內思考|內心獨白)[：:]\s*.*?(?:\n|$)', flags=re.MULTILINE | re.IGNORECASE)
    RE_PAREN_THINK = re.compile(r'[（(](?:心想|心裡想|內心想|腦中想|默想)[：:]\s*[^）)]*?[）)]')
    RE_SYS_HINTS = re.compile(r'[（(【\[]系統[^）)】\]]*?[）)】\]]')
    RE_STAGE_HINTS = re.compile(r'[（(](?:轉頭|看向|望向|笑|微笑|輕笑|嘆氣|語氣|動作|神態|興奮|疑惑|摸|眨|低頭|抬頭|輕聲|小聲|歪頭|舉起|揮手|雙手|雙眼|眼神|沉思|自語|轉向|初始化)[^）)]*?[）)]')
    RE_LEARN_TAGS = re.compile(r'\[(?:LEARN_MEME|LEARN_FACT|UPDATE_RULE|UPDATE_PROMPT|ADD_EXAMPLE|SET_PROMPT|LEARN_EXAMPLE|UPDATE_KNOWLEDGE|KNOWLEDGE_UPDATED)[：:][^\]]*\]', flags=re.IGNORECASE)
    RE_BROWSER_TAG = re.compile(r'\[OPEN_BROWSER:\s*[^\]]+\]', flags=re.IGNORECASE)
    RE_VIEWER_TAG = re.compile(r'\[VIEWER_UPDATE[：:][^\]]*\]', flags=re.IGNORECASE)
    RE_BRACKET_TAGS = re.compile(r'\[.*?\]')
    RE_CONTROL_TAGS = re.compile(r'\[?(LOOK|EXPRESSION|MOVE|WINDOW|POSITION|TIMER|TYPE|HOTKEY|EYES):?\s*[a-zA-Z0-9_\u4e00-\u9fa5]+\]?', flags=re.IGNORECASE)
    RE_CODE_BLOCKS = re.compile(r'```.*?```', flags=re.DOTALL)
    RE_INLINE_CODE = re.compile(r'`.*?`', flags=re.DOTALL)
    RE_PYTHON_CALLS = re.compile(
        r'\[?(?:(?:pe\.)?(?:play_virtual_piano|insert_virtual_piano|open_virtual_piano|stop_virtual_piano|'
        r'pause_virtual_piano|resume_virtual_piano|set_piano_volume|set_piano_speed|set_piano_instrument|'
        r'compose_and_play_original_piano|mashup_virtual_piano|list_piano_sheets)|'
        r'execute_local_python_code|trigger_vts_expression|search_google|generate_ai_image|'
        r'move_spatial_position|control_microphone|clear_all_memories|set_sleep_mode|set_timer|'
        r'auto_sing_song|sing_song|auto_sing|auto_sing_sing|pe_auto_sing_song|'
        r'[a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)?)\s*\([^)]*\)\]?|'
        r'\[?(?:TOOL:[a-zA-Z0-9_]*:?\s*)?[A-Z_]+[：:]\s*[^\]]+\]?|'
        r'\[TOOL:[a-zA-Z0-9_]+\]\s*[^\[\]\n]*',
        flags=re.IGNORECASE | re.DOTALL
    )
    RE_SPEAKER_PREFIX = re.compile(r'^(老爸|玩家|使用者|7L|女兒|溫柔女兒|七[龄靈]|主播|回應|回覆|動作顯示|回答|說道)[：:\s]+', flags=re.IGNORECASE)
    RE_MULTIPLE_NEWLINES = re.compile(r'\n{3,}')
    RE_TAG_BRACKETS = re.compile(r'\[[A-Z_]+(?::\s*[^\]]+)?\]')
    RE_AT_MENTION = re.compile(r'@[\w\u4e00-\u9fa5_.-]+')
    RE_RAW_JSON = re.compile(r'\{[^{}]*(?:"song_name"|"function"|"tool_call"|"name")[^{}]*\}', flags=re.DOTALL)

    @classmethod
    def extract_nested_bracket_tags(cls, text: str, tag_prefixes: tuple) -> Tuple[list, str]:
        """使用括號深度平衡解析巢狀標籤，如 [THOUGHT: ... [EXPRESSION: ...] ...]"""
        results = []
        clean_parts = []
        i = 0
        n = len(text)
        pairs = {'[': ']', '【': '】'}
        
        while i < n:
            if text[i] in pairs:
                open_bracket = text[i]
                close_bracket = pairs[open_bracket]
                sub = text[i+1:i+30]
                matched_prefix = None
                for p in tag_prefixes:
                    if sub.lstrip().lower().startswith(p.lower()):
                        matched_prefix = p
                        break
                
                if matched_prefix:
                    depth = 1
                    j = i + 1
                    while j < n and depth > 0:
                        if text[j] == open_bracket:
                            depth += 1
                        elif text[j] == close_bracket:
                            depth -= 1
                        j += 1
                    tag_content = text[i:j]
                    inner = re.sub(r'^[\[【]\s*(?:' + '|'.join(re.escape(p) for p in tag_prefixes) + r')[：:\s]*', '', tag_content, flags=re.IGNORECASE)
                    inner = inner.rstrip(']】').strip()
                    if inner:
                        results.append(inner)
                    i = j
                    continue
            clean_parts.append(text[i])
            i += 1
            
        return results, "".join(clean_parts)

    @classmethod
    def extract_thought(cls, text: str) -> Tuple[str, str]:
        """從 AI 輸出文字中提取大腦私密心想內容 (Inner Monologue)，並回傳 (thought, remaining_text)"""
        if not text:
            return "", ""
        thoughts = []
        t = text.strip()
        #  徹底去除 Live API / 函數執行殘留之 token 前綴 (如 get_output, tool_output 等)
        t = re.sub(r'^(?:get_outputs?|tool_outputs?|function_calls?|tool_responses?)[：:\s_]*', '', t, flags=re.IGNORECASE).strip()
        t = re.sub(r'\b(?:get_outputs?|tool_outputs?)\b', '', t, flags=re.IGNORECASE).strip()

        # 1. 巢狀平衡標籤提取 [THOUGHT: ...] / [心想: ...]，徹底解決巢狀標籤提前閉合問題
        nested_ths, t = cls.extract_nested_bracket_tags(t, ("THOUGHT", "THINK", "心想", "內心", "腦內思緒", "腦內想法"))
        thoughts.extend(nested_ths)

        # 2. 匹配 <think>...</think> 或 <thought>...</thought>
        for m in re.finditer(r'<(?:think|thought)>.*?(?:</(?:think|thought)>|$)', t, flags=re.DOTALL | re.IGNORECASE):
            th_clean = re.sub(r'</?(?:think|thought)>', '', m.group(0), flags=re.IGNORECASE).strip()
            if th_clean: thoughts.append(th_clean)
        t = re.sub(r'<(?:think|thought)>.*?(?:</(?:think|thought)>|$)', '', t, flags=re.DOTALL | re.IGNORECASE).strip()

        # 3. 處理結構化劇本模式 (1. 心想 / 2. 動作 / 3. 說話)：
        # 若文字包含明確「3. **說話**：」或「說話：」標籤，將其前方所有規劃、心想與動作內容全數提取為心想
        speech_split_m = re.search(r'(?:^|\n)(?:\d+[\.、]\s*)?\*{0,2}(?:說話|台詞|開口|回應|回答)\*{0,2}[：:]\s*', t, flags=re.IGNORECASE)
        if speech_split_m:
            before_speech = t[:speech_split_m.start()].strip()
            after_speech = t[speech_split_m.end():].strip()
            if before_speech:
                th_candidate = re.sub(r'^(?:thought|thinking\s*process|thinking|腦內思考|內心獨白)[：:\s]*', '', before_speech, flags=re.IGNORECASE).strip()
                if th_candidate:
                    thoughts.append(th_candidate)
            t = after_speech

        # 4. 處理開頭裸露的 thought / Thinking Process 區塊
        lead_th_m = re.match(r'^(?:thought|thinking\s*process|thinking|腦內思考|內心獨白)[：:\s]*\n([\s\S]*?)(?:\n\n|\Z)', t, flags=re.IGNORECASE)
        if lead_th_m:
            lead_content = lead_th_m.group(1).strip()
            if lead_content:
                thoughts.append(lead_content)
            t = t[lead_th_m.end():].strip()

        # 5. 處理 （心想：...）
        for m in re.finditer(r'[（(](?:心想|心裡想|內心想|腦中想|默想)[：:]\s*[^）)]*?[）)]', t):
            th_p = re.sub(r'^[（(](?:心想|心裡想|內心想|腦中想|默想)[：:]\s*', '', m.group(0)).rstrip('）)').strip()
            if th_p: thoughts.append(th_p)
        t = re.sub(r'[（(](?:心想|心裡想|內心想|腦中想|默想)[：:]\s*[^）)]*?[）)]', '', t).strip()

        # 6. 清理殘留的心想/動作條目
        t = re.sub(r'(?:^|\n)(?:\d+[\.、]\s*)?\*{0,2}(?:心想|內心想|腦內思緒|動作|肢體|神態)\*{0,2}[：:][^\n]*', '', t, flags=re.IGNORECASE).strip()
        t = re.sub(r'^(?:\d+[\.、]\s*)?\*{0,2}(?:說話|台詞|開口|回應|回答)\*{0,2}[：:]\s*', '', t, flags=re.IGNORECASE).strip()
        t = re.sub(r'^(?:thought|thinking|心想)[：:\s]*', '', t, flags=re.IGNORECASE).strip()

        # 去重並保留次序
        combined_thought = "；".join(dict.fromkeys([x for x in thoughts if x])).strip()
        clean_remaining = re.sub(r'^(?:get_outputs?|tool_outputs?|function_calls?|tool_responses?)[：:\s_]*', '', t, flags=re.IGNORECASE).strip()
        clean_remaining = re.sub(r'\b(?:get_outputs?|tool_outputs?)\b', '', clean_remaining, flags=re.IGNORECASE).strip()
        return combined_thought, clean_remaining

    @classmethod
    def deduplicate_intra_reply_sentences(cls, text: str) -> str:
        """去除單次回應內因模型生成口吃/複誦而產生的連續重複句子"""
        if not text:
            return ""
        raw_sentences = re.split(r'([。！？!?\n]+)', text)
        merged_units = []
        i = 0
        while i < len(raw_sentences):
            s = raw_sentences[i]
            punct = raw_sentences[i+1] if (i + 1) < len(raw_sentences) else ""
            full = s + punct
            if full.strip():
                merged_units.append(full)
            i += 2
            
        final_units = []
        seen_clean_texts = []
        for u in merged_units:
            clean_u = re.sub(r'\[.*?\]', '', u).strip()
            clean_compact = re.sub(r'[^\w\u4e00-\u9fa5]', '', clean_u).lower()
            if not clean_compact:
                continue
            is_dup = False
            for seen in seen_clean_texts:
                if clean_compact == seen or clean_compact in seen or seen in clean_compact:
                    is_dup = True
                    break
                if len(clean_compact) >= 4:
                    ratio = difflib.SequenceMatcher(None, clean_compact, seen).ratio()
                    if ratio >= 0.75:
                        is_dup = True
                        break
            if not is_dup:
                final_units.append(u)
                seen_clean_texts.append(clean_compact)
        return "".join(final_units).strip()

    @classmethod
    def natural_clause_segmentation(cls, text: str) -> str:
        """為中文字句智慧補全逗號與停頓標點，賦予 TTS 真實自然的呼吸節奏（不破壞詞彙完整性）"""
        if not text:
            return ""
        t = text
        # 1. 移除中英文字詞之間由 ASR/Live-API Token 串流產生的多餘空格
        t = re.sub(r'(?<=[\u4e00-\u9fa5])\s+(?=[\u4e00-\u9fa5])', '', t)
        t = re.sub(r'(?<=[\u4e00-\u9fa5])\s+(?=[a-zA-Z0-9])', '', t)
        t = re.sub(r'(?<=[a-zA-Z0-9])\s+(?=[\u4e00-\u9fa5])', '', t)

        # 2. 開頭獨立感嘆詞 (欸/嗨/哈囉/喂/嘿) 後補自然逗號
        t = re.sub(r'^(欸|喂|嗨|哈囉|嘿)(?=[\u4e00-\u9fa5]{2})', r'\1，', t)

        # 3. 語氣助詞 (子句長度至少 3 字以上) 且後方接續至少 2 字的新子句時，補上自然逗號
        particles = [
            '啦(?!啦)', '喔(?!喔)', '呢(?!呢)', '吧(?!吧)', '呀(?!呀)', '哦(?!哦)', 
            '嘛(?!嘛)', '欸(?!欸)', '耶(?!耶)', '對吧', '是不是', '好不好', '對不對', '對啊'
        ]
        p_pat = '|'.join(particles)
        t = re.sub(r'(?<=[\u4e00-\u9fa5]{3})(' + p_pat + r')(?=[\u4e00-\u9fa5]{2})', r'\1，', t)

        # 4. 完成式「了」接新主語時自然斷句
        t = re.sub(r'(?<=[\u4e00-\u9fa5]{3})(了)(?=(?:我|你|妳|他|她|大家|我們|你們|他們|這|那|現在)[\u4e00-\u9fa5])', r'\1，', t)

        # 5. 常見轉折與承接連詞 (前方子句至少 4 字以上，後方至少 2 字) 前補逗號
        connectors = ['但是', '不過', '可是', '然後', '所以', '如果', '因為', '雖然', '而且', '不然', '還是']
        c_pat = '|'.join(connectors)
        t = re.sub(r'(?<=[\u4e00-\u9fa5]{4})(' + c_pat + r')(?=[\u4e00-\u9fa5]{2})', r'，\1', t)

        # 6. 連接詞後方不黏連逗號
        t = re.sub(r'(但是|不過|可是|然後|所以|如果|因為|雖然|而且|不然|還是)，', r'\1', t)

        # 7. 正規化重複標點與標點前後多餘逗號
        t = re.sub(r'[，,]{2,}', '，', t)
        t = re.sub(r'，([。！？,.!?:;~～])', r'\1', t)
        t = re.sub(r'([。！？,.!?:;~～])，', r'\1', t)
        t = re.sub(r'^\s*，', '', t)
        return t.strip()

    @classmethod
    def strip_emojis(cls, text: str) -> str:
        """徹底清除所有 Unicode Emoji 圖示與表情符號"""
        if not text:
            return ""
        return cls.EMOJI_PATTERN.sub('', str(text)).strip()

    @classmethod
    def remove_system_hints(cls, text: str) -> str:
        r"""徹底清除所有 [（(【\[]系統提示/回報...[）)】\]] 標籤區塊，支援任意深度的巢狀括號 (如 [RUSH E]、(Sheet Music Boss) 等)"""
        if not text:
            return ""
        # 1. 若整句完全是系統提示或回報，秒清空
        s = re.sub(r'^[（(【\[]\s*(?:系統提示|系统提示|系統回報|系统回报|系統|系统)[：:][\s\S]*[）)】\]]$', '', text.strip())
        
        # 2. 透過括號深度匹配，安全清除字串任意位置的系統提示
        pairs = {'（': '）', '(': ')', '【': '】', '[': ']'}
        sys_keywords = ('系統提示', '系统提示', '系統回報', '系统回报', '系統', '系统')
        result = []
        i = 0
        n = len(s)
        while i < n:
            char = s[i]
            if char in pairs:
                sub = s[i+1:i+15]
                if any(sub.lstrip().startswith(kw) for kw in sys_keywords):
                    close_char = pairs[char]
                    depth = 1
                    j = i + 1
                    while j < n and depth > 0:
                        if s[j] == char:
                            depth += 1
                        elif s[j] == close_char:
                            depth -= 1
                        j += 1
                    i = j
                    continue
            result.append(char)
            i += 1
        res = ''.join(result)
        res = re.sub(r'^[（(【\[]?\s*(?:系統提示|系统提示|系統回報|系统回报|系統|系统)[：:].*$', '', res, flags=re.MULTILINE)
        return res

    @classmethod
    def clean_speech_text(cls, text: str) -> str:
        """完整清洗 AI 輸出文字，剔除大腦心想標籤、動作標籤、代碼、系統提示，保留並智慧調校自然標點"""
        if not text:
            return ""
        t = cls.remove_system_hints(text)
        t = cls.RE_THOUGHT_TAG.sub('', t)
        t = cls.RE_THINK_BLOCK.sub('', t)
        t = cls.RE_SYS_HINTS.sub('', t)
        t = cls.RE_STAGE_HINTS.sub('', t)
        t = cls.RE_THINKING_PROC.sub('', t)
        t = cls.RE_PAREN_THINK.sub('', t)
        t = cls.RE_BROWSER_TAG.sub('', t)
        t = cls.RE_VIEWER_TAG.sub('', t)
        t = cls.RE_LEARN_TAGS.sub('', t)
        t = cls.RE_BRACKET_TAGS.sub('', t)
        t = cls.RE_CONTROL_TAGS.sub('', t)
        t = cls.RE_CODE_BLOCKS.sub('', t)
        t = cls.RE_INLINE_CODE.sub('', t)
        t = cls.RE_PYTHON_CALLS.sub('', t)
        t = cls.RE_RAW_JSON.sub('', t)
        t = cls.RE_SPEAKER_PREFIX.sub('', t)
        # 徹底防禦未閉合的控制標籤 (如 `[MOVE: ` 尾段被截斷) 洩漏至 TTS
        t = re.sub(r'\[[A-Z_]+[：:]?[^\]]*$', '', t, flags=re.IGNORECASE)
        t = re.sub(r'^(?:回應|回覆|動作顯示|主播|說道|回答)[：:\s]+', '', t, flags=re.IGNORECASE)
        #  徹底防禦未整理的搜尋結果原始文字與系統標籤洩漏至語音
        t = re.sub(r'[（\(]\s*搜尋結果[：:].*?[）\)]', '', t, flags=re.DOTALL)
        t = re.sub(r'^[（\(]?\s*搜尋結果[：:].*$', '', t, flags=re.DOTALL)
        t = re.sub(r'搜尋結果[：:].*$', '', t, flags=re.MULTILINE)
        t = re.sub(r'https?://\S+', '', t)
        t = re.sub(r'^#+\s+.*$', '', t, flags=re.MULTILINE)
        t = re.sub(r'^[-\*•]\s+', '', t, flags=re.MULTILINE)
        t = re.sub(r'^(?:thought|thinking|心想|動作|說話)[：:\s]*', '', t, flags=re.IGNORECASE)
        #  徹底防禦 Gemini Live / 函數調用內部 token (如 get_output, tool_output 等)
        t = re.sub(r'^(?:get_outputs?|tool_outputs?|function_calls?|function_responses?|tool_responses?|had_tool_calls?|call|output)[：:\s_]*', '', t, flags=re.IGNORECASE)
        t = re.sub(r'\b(?:get_outputs?|tool_outputs?)\b', '', t, flags=re.IGNORECASE)
        t = t.replace('[', '').replace(']', '').replace('*', '')
        t = cls.strip_emojis(t)
        #  去除單次回應內因模型口吃/複誦而產生的連續重複句子 (徹底杜絕複誦跳針)
        t = cls.deduplicate_intra_reply_sentences(t)
        #  智慧自然子句斷句
        t = cls.natural_clause_segmentation(t)
        t = re.sub(r'\s+([，。！？,.!?:;~～])', r'\1', t)
        t = re.sub(r'([，。！？~～])\s+(?=[\u4e00-\u9fa5])', r'\1', t)
        t = re.sub(r'[ \t]{2,}', ' ', t)
        t = cls.RE_MULTIPLE_NEWLINES.sub('\n\n', t).strip()
        return t

    @classmethod
    def fix_heteronyms_for_tts(cls, text: str) -> str:
        """ 中文破音字 / 多音字全量窮舉校正引擎 (僅對 TTS 語音發音生效，100% 不改變原文字幕與記憶)"""
        if not text:
            return ""
        t = str(text)
        
        # 1. 著 (Aspect marker vs zhù vs zháo vs zhuó)
        zhu_words = [
            '著作', '著名', '著稱', '著者', '名著', '原著', '專著', '巨著', '拙著', '顯著', 
            '譯著', '遺著', '編著', '執著', '沉著', '穿著', '著落', '著想', '著手', '著重', 
            '著眼', '著色', '附著', '不著邊際'
        ]
        placeholders = {}
        for idx, w in enumerate(zhu_words):
            if w in t:
                ph = f'__ZHU_{idx}__'
                placeholders[ph] = w
                t = t.replace(w, ph)
        t = re.sub(r'著(急|涼|迷|火|魔|慌)', r'着\1', t)
        t = re.sub(r'(睡|點|猜|打|夠不|摸不|找不)著', r'\1着', t)
        t = t.replace('著', '着')
        for ph, w in placeholders.items():
            t = t.replace(ph, w)
            
        # 2. 重 (chóng vs zhòng) - 重複/再次/動作一律讀 chóng
        t = re.sub(r'重(開機|開|連|跑|播|抽|唱|彈|來|複|置|整|錄|刷|頭|啟|組|寫|問|聽|按|跳|裝|試|印|修|建|算|疊|逢|溫|演|返|回|生|慶|陽|霄|圍)', r'崇\1', t)
        
        # 3. 調 (tiáo vs diào) - 調節/調情/調戲/調整一律讀 tiáo
        t = re.sub(r'調(大|小|高|低|快|慢|音量|倍速|速度|亮|暗|整|音|配|和|皮|一下|看看|色|度|試|節|侃|戲|情|笑|弄|教|停|解|養|味|劑|料|理|適|适|諧|琴|頻|幅|溫|勻)', r'條\1', t)
        t = t.replace('協調', '協條').replace('烹調', '烹條').replace('風調雨順', '風條雨順')
        
        # 4. 彈 (tán vs dàn) - 樂器演奏一律讀 tán
        t = re.sub(r'彈(鋼琴|琴|吉他|一首|個|首|曲|奏|完|過|錯|得|給|跳|簧|力|唱|撥|性|詞)', r'談\1', t)
        t = t.replace('反彈', '反談').replace('動彈', '動談')
        
        # 5. 角 (jué vs jiǎo) - 戲劇角色一律讀 jué
        t = re.sub(r'(角|丑|生|旦)角', r'絕角', t)
        t = t.replace('角色', '絕色').replace('主角', '主絕').replace('配角', '配絕').replace('角逐', '絕逐').replace('角力', '絕力')
        
        # 6. 曲 (qǔ vs qū) - 樂曲/歌曲一律讀 qǔ
        t = t.replace('曲子', '取子')  # 無條件先替換「曲子」，避免被下方 regex 漏掉
        t = re.sub(r'(首|這首|那首|聽首|彈首)?曲(目)', r'\1取\2', t)
        t = re.sub(r'(歌|樂|名|神|新|插|組|舞|琴|練習|奏鳴|協奏|交響|譜|戲|詞|牌)曲', r'\1取', t)
        
        # 7. 便 (pián vs biàn) - 便宜一律讀 pián
        t = t.replace('便宜', '蹁宜').replace('大便宜', '大蹁宜').replace('佔便宜', '佔蹁宜')
        
        # 8. 長 (zhǎng vs cháng) - 成長/首領一律讀 zhǎng
        t = re.sub(r'長(大|高|胖|相|成|得像|出來|肉|進|輩)', r'掌\1', t)
        t = re.sub(r'(組|隊|校|會|社|族|市|部|局|班|院|連|營|團|旅|師|軍|首|家|兄|學)長', r'\1掌', t)
        
        # 9. 假 (jià vs jiǎ) - 假期一律讀 jià
        t = re.sub(r'(放|暑|寒|請|休|度|例|病|事|公|婚|產|年)假', r'\1駕', t)
        t = t.replace('假期', '駕期')
        
        # 10. 差 (chāi vs chà vs cī) - 出差一律讀 chāi
        t = re.sub(r'(出|公)差', r'\1拆', t)
        t = re.sub(r'差(使|事|遣|當)', r'拆\1', t)
        t = t.replace('參差', '參呲')
        
        # 11. 幹 (gàn) - 口語動作一律讀 gàn
        t = re.sub(r'幹(嘛|什麼|啥|活|掉|架|練|部|得好)', r'干\1', t)
        
        # 12. 髮 (fà) - 頭髮一律讀 fà
        t = re.sub(r'(頭|理|短|長|假|金|白|黑|秀|毛|染|削|脫|捲)髮', r'\1发', t)
        t = re.sub(r'髮(型|色|帶|夾)', r'发\1', t)
        t = t.replace('頭髮', '头发')
        
        # 13. 關係 / 沒關係 (xi) - 語氣助詞一律輕聲
        t = t.replace('沒關係', '沒關西').replace('沒關系', '沒關西')
        
        # 14. 量 (liáng vs liàng) - 測量一律讀 liáng
        t = re.sub(r'量(一下|一量|尺寸|身高|體重|體溫|具)', r'良\1', t)
        t = re.sub(r'(打|思|測|衡|估|酌)量', r'\1良', t)
        
        # 15. 教 (jiāo vs jiào) - 傳授一律讀 jiāo
        t = re.sub(r'教(我|你|老爸|大家|書|學|唱|念)', r'澆\1', t)
        
        # 16. 行 (háng vs xíng) - 銀行/行業一律讀 háng
        t = re.sub(r'(銀|洋|商|排|同|道)行', r'\1航', t)
        t = re.sub(r'行(業|號|家|話|伍)', r'航\1', t)
        
        # 17. 塞 (sāi vs sài vs sè) - 塞車一律讀 sāi
        t = re.sub(r'塞(車|滿|住|進|到|不進)', r'腮\1', t)
        t = re.sub(r'(邊|關)塞', r'\1賽', t)
        t = re.sub(r'塞(外|翁)', r'賽\1', t)
        t = re.sub(r'(阻|閉|搪|茅|語)塞', r'\1瑟', t)
        
        # 18. 轉 (zhuàn vs zhuǎn) - 旋轉一律讀 zhuàn
        t = re.sub(r'轉(圈|動|來轉去|悠|盤|向)', r'撰\1', t)
        t = re.sub(r'(打|自|公)轉', r'\1撰', t)
        t = t.replace('暈頭轉向', '暈頭撰向')
        
        # 19. 血 (xiě vs xuè) - 遊戲扣血/流血一律讀 xiě
        t = re.sub(r'(流|吐|回|殘|滿|掉|補|扣|放|吸|出)血', r'\1寫', t)
        t = t.replace('血淋淋', '寫淋淋')
        
        # 20. 藏 (zàng vs cáng)
        t = re.sub(r'(寶|西|地|礦|道|三)藏', r'\1葬', t)
        t = re.sub(r'(捉迷|躲|包|珍)藏', r'\1長', t)
        t = re.sub(r'藏(著|着)', r'長着', t)
        
        # 21. 數 (shǔ vs shù) - 計算一律讀 shǔ
        t = t.replace('數一數', '屬一屬')
        t = re.sub(r'數(數|不勝數|落|九|得著)', r'屬\1', t)
        t = t.replace('屈指可數', '屈指可屬')
        
        # 22. 省 (xǐng vs shěng) - 反省一律讀 xǐng
        t = re.sub(r'(反|自)省', r'\1醒', t)
        t = re.sub(r'省(悟|視)', r'醒\1', t)
        t = t.replace('不省人事', '不醒人事')
        
        # 23. 盛 (chéng vs shèng) - 裝盛一律讀 chéng
        t = re.sub(r'盛(飯|湯|菜|水|滿|裝)', r'成\1', t)
        
        # 24. 落 (lào vs là vs luò)
        t = re.sub(r'落(枕|色|病|炕)', r'澇\1', t)
        t = t.replace('丟三落四', '丟三辣四')
        
        # 25. 更 (gēng vs gèng) - 更新/更換一律讀 gēng
        t = re.sub(r'更(換|新|改|動|變|正)', r'庚\1', t)
        t = re.sub(r'(打|五|三)更', r'\1庚', t)
        t = t.replace('深更半夜', '深庚半夜')
        
        # 26. 背 (bēi vs bèi) - 背包一律讀 bēi
        t = re.sub(r'背(包|著|着|書包|黑鍋|鍋|負|起)', r'杯\1', t)
        
        # 27. 降 (xiáng vs jiàng) - 投降一律讀 xiáng
        t = re.sub(r'(投|招|誘)降', r'\1詳', t)
        t = re.sub(r'降(伏|將)', r'詳\1', t)
        
        # 28. 參 (shēn vs cān) - 人參一律讀 shēn
        t = re.sub(r'(人|海|紅|西洋|黨)參', r'\1深', t)
        
        # 29. 傳 (zhuàn vs chuán) - 自傳一律讀 zhuàn
        t = re.sub(r'(自|外|列|評)傳', r'\1賺', t)
        t = t.replace('傳記', '賺記').replace('水滸傳', '水滸賺')
        
        # 30. 好 (hào vs hǎo) - 好奇/愛好一律讀 hào
        t = re.sub(r'好(奇|客|動|學|色|戰|吃懶做)', r'號\1', t)
        t = re.sub(r'(愛|嗜)好', r'\1號', t)
        
        # 31. 禁 (jīn vs jìn) - 不禁一律讀 jīn
        t = re.sub(r'(不|弱不|禁不)禁', r'\1金', t)
        t = re.sub(r'禁(得起|不住|受)', r'金\1', t)
        t = t.replace('情不自禁', '情不自金')
        
        # 32. 處 (chǔ vs chù) - 處理/相處一律讀 chǔ
        t = re.sub(r'處(理|罰|置|境|之泰然)', r'初\1', t)
        t = re.sub(r'(相|身)處', r'\1初', t)
        t = t.replace('和平共處', '和平共初')
        
        # 33. 分 (fèn vs fēn) - 過分/本分一律讀 fèn
        t = t.replace('過分', '過份').replace('分量', '份量')
        t = re.sub(r'(本|身|名)分', r'\1份', t)
        t = t.replace('恰如其分', '恰如其份')
        
        # 34. 薄 (báo vs bò vs bó)
        t = re.sub(r'薄(片|紙|脆)', r'雹\1', t)
        t = t.replace('肉很薄', '肉很雹').replace('很薄', '很雹')
        t = t.replace('薄荷', '迫荷')
        
        # 35. 模 (mú vs mó) - 模具/模樣一律讀 mú
        t = re.sub(r'模(具|子|樣)', r'毪\1', t)
        t = t.replace('一模一樣', '一毪一樣').replace('裝模作樣', '裝毪作樣')
        
        # 36. 率 (lǜ vs shuài) - 機率/效率一律讀 lǜ
        t = re.sub(r'(機|效|勝|暴擊|命中|頻|比|利|速)率', r'\1綠', t)
        
        # 37. 別 (biè vs bié) - 彆扭一律讀 biè
        t = re.sub(r'(彆|别)扭', r'憋扭', t)
        
        # 38. 埋 (mán vs mái) - 埋怨一律讀 mán
        t = t.replace('埋怨', '蠻怨')
        
        # 39. 喝 (hè vs hē) - 喝彩一律讀 hè
        t = re.sub(r'喝(彩|令|斥)', r'賀\1', t)
        t = t.replace('齊聲喝彩', '齊聲賀彩')
        
        # 40. 給 (jǐ vs gěi) - 給予/供給一律讀 jǐ
        t = t.replace('給予', '幾予')
        t = re.sub(r'(供|補|配)給', r'\1幾', t)
        t = t.replace('自給自足', '自幾自足')
        
        # 41. 鑽 (zuān vs zuàn)
        t = re.sub(r'鑽(孔|洞|進|出|研|空子|木取火)', r'尊\1', t)
        t = re.sub(r'鑽(石|戒|頭)', r'賺\1', t)
        
        # 42. 宿 (xiù vs xiǔ vs sù)
        t = re.sub(r'(二十八|星)宿', r'\1秀', t)
        t = re.sub(r'住(了)?(一|整|半)宿', r'住\1\2朽', t)
        
        # 43. 縫 (féng vs fèng)
        t = re.sub(r'縫(補|紉|合|線)', r'逢\1', t)
        t = re.sub(r'(石|裂|無)縫', r'\1鳳', t)
        t = t.replace('縫隙', '鳳隙').replace('見縫插針', '見鳳插針')
        
        # 44. 空 (kòng vs kōng)
        t = re.sub(r'(有|沒|抽)空', r'\1控', t)
        t = re.sub(r'空(白|閒|地)', r'控\1', t)
        t = t.replace('填空', '填控')
        
        # 45. 累 (lěi vs lèi) - 累積/積累一律讀 lěi
        t = t.replace('累積', '壘積').replace('連累', '連壘')
        t = re.sub(r'(積|日積月)累', r'\1壘', t)
        t = t.replace('連篇累牘', '連篇壘牘')
        
        # 46. 校 (jiào vs xiào) - 校對/校正一律讀 jiào
        t = re.sub(r'校(對|準|正|驗)', r'叫\1', t)
        
        # 47. 漂 (piāo vs piǎo vs piào)
        t = re.sub(r'漂(浮|流|移)', r'飄\1', t)
        t = t.replace('漂白', '殍白').replace('漂亮', '票亮')
        
        # 48. 打 (dá vs dǎ)
        t = t.replace('一打', '一達')
        
        # 49. 和 (hè vs huó vs huò)
        t = re.sub(r'(一唱一|附|應)和', r'\1賀', t)
        t = t.replace('曲高和寡', '曲高賀寡')
        t = re.sub(r'和(面|麵)', r'活\1', t)
        t = t.replace('和藥', '惑藥')
        
        # 50. 係 (jì vs xì) - 繫帶一律讀 jì
        t = re.sub(r'繫(好)?(鞋帶|安全帶|領帶|上)', r'記\1\2', t)
        
        # 51. 咽 (yàn vs yè vs yān)
        t = re.sub(r'(吞|狼吞虎)咽', r'\1驗', t)
        t = re.sub(r'(嗚|哽)咽', r'\1夜', t)
        
        # 52. 載 (zǎi vs zài)
        t = re.sub(r'(登|刊|記)載', r'\1仔', t)
        t = re.sub(r'(三年五|千)載', r'\1仔', t)
        t = re.sub(r'(下|加|轉|上傳)載', r'\1在', t)
        t = re.sub(r'載(入|重|滿|客|運|歌載舞)', r'在\1', t)
        
        # 53. 提 (dī vs tí)
        t = t.replace('提防', '低防')
        
        # 54. 冠 (guàn vs guān)
        t = re.sub(r'(奪|衛冕|勇奪)冠', r'\1慣', t)
        t = t.replace('冠軍', '慣軍')
        t = re.sub(r'(皇|衣|桂)冠', r'\1官', t)
        
        # 55. 龜 (jūn vs guī)
        t = t.replace('龜裂', '軍裂')
        
        # 56. 匙 (shi vs chí)
        t = t.replace('鑰匙', '要石')
        t = re.sub(r'(湯|茶)匙', r'\1池', t)
        
        # 57. 露 (lòu vs lù)
        t = re.sub(r'露(面|頭|臉|餡|馬腳)', r'漏\1', t)
        
        # 58. 泊 (pō vs bó)
        t = re.sub(r'(湖|血)泊', r'\1坡', t)
        t = re.sub(r'(停|漂)泊', r'\1博', t)
        
        # 59. 圈 (juàn vs quān)
        t = re.sub(r'(豬|羊|牛)圈', r'\1倦', t)
        
        # 60. 荷 (hè vs hé)
        t = re.sub(r'(負|重)荷', r'\1賀', t)
        
        # 61. 爪 (zhuǎ vs zhǎo)
        t = t.replace('爪子', '准子')
        t = re.sub(r'(鷹|魔|利)爪', r'\1沼', t)
        
        # 62. 殼 (qiào vs ké)
        t = re.sub(r'(地|甲)殼', r'\1俏', t)
        t = re.sub(r'(蛋|貝|腦|外)殼', r'\1咳', t)
        
        # 63. 強 (qiǎng vs jiàng vs qiáng)
        t = re.sub(r'(強迫|勉強)', lambda m: '搶迫' if m.group(0)=='強迫' else '免搶', t)
        t = t.replace('倔強', '倔降')

        # 64. 沒 (méi vs mò) - 口語「有的沒的」徹底校正為 méi 發音（防 Edge-TTS 誤讀古典詞「沒的 mò de」）
        t = re.sub(r'有的(沒|没)的', r'有的梅的', t)
        t = re.sub(r'有的(沒|没)', r'有的梅', t)
        t = re.sub(r'(那些|這些|那種|這種|很多|搞|聊|扯|說|講)沒的', r'\1梅的', t)

        # 65. 樂 (yuè vs lè) - 音樂相關詞彙 100% 精準校正為 yuè (月) 發音，絕不誤讀成 lè (ㄌㄜˋ)
        t = re.sub(r'(古典|音樂|交響|管弦|弦|國|民|聲|爵士|流行|搖滾|純音|輕音|背景|鋼琴|配|奏)樂', r'\1月', t)
        t = re.sub(r'樂(曲|取|譜|器|團|隊|章|理|壇|手|迷|界|評)', r'月\1', t)
        t = t.replace('音樂會', '音月會')

        # 66. 幾 (jǐ vs jī) - 數量、人稱、時間、疑問一律讀 jǐ (ㄐㄧˇ，以「己」替換，防 Edge-TTS 誤讀成 jī ㄐㄧ)
        ji_jī_words = ['幾乎', '茶几', '窗几', '几案', '几桌', '幾希', '幾率', '几椅']
        ji_placeholders = {}
        for idx, w in enumerate(ji_jī_words):
            if w in t:
                ph = f'__JI_JI_{idx}__'
                ji_placeholders[ph] = w
                t = t.replace(w, ph)
        
        t = t.replace('幾個人', '己個人')
        t = t.replace('幾個', '己個')
        t = re.sub(r'幾(位|人|天|次|點|分|秒|隻|只|把|張|條|根|件|本|首|種|樣|回|遍|套|門|杯|瓶|碗|口|步|筆|串|棟|家|輛|架|歲|輪|代|款|段|篇|名|排|隊|句|台|部|十|百|千|萬|億|何|時|許|塊|顆|串|組|倍)', r'己\1', t)
        t = re.sub(r'(好|十|這|那|有|沒|前|後|第)幾', r'\1己', t)
        t = t.replace('所剩無幾', '所剩無己').replace('寥寥無幾', '寥寥無己').replace('相差無幾', '相差無己')
        t = t.replace('幾', '己')

        for ph, w in ji_placeholders.items():
            t = t.replace(ph, w)

        # 67. 載入自訂字典 (data/tts_heteronym_dictionary.json)
        dict_file = os.path.join(DATA_DIR, "tts_heteronym_dictionary.json")
        if os.path.exists(dict_file):
            try:
                with open(dict_file, "r", encoding="utf-8") as f:
                    custom_dict = json.load(f)
                custom_repls = custom_dict.get("自訂單詞發音置換", {})
                for k, v in custom_repls.items():
                    if k in t:
                        t = t.replace(k, v)
            except Exception:
                pass
                
        return t

    @classmethod
    def clean_for_tts(cls, text: str, apply_phonetics: bool = True) -> str:
        """語音合成 (TTS) 前置專用清洗（徹底保證 100% 不唸出大腦心想與系統標籤，並精準校正破音字發音）"""
        if not text:
            return ""
        t = cls.remove_system_hints(text)
        t = cls.RE_CODE_BLOCKS.sub('', t)
        t = cls.RE_INLINE_CODE.sub('', t)
        t = cls.RE_PYTHON_CALLS.sub('', t)
        t = cls.RE_RAW_JSON.sub('', t)
        t = cls.RE_THOUGHT_TAG.sub('', t)
        t = cls.RE_THINK_BLOCK.sub('', t)
        t = cls.RE_THINKING_PROC.sub('', t)
        t = cls.RE_PAREN_THINK.sub('', t)
        t = cls.RE_TAG_BRACKETS.sub('', t)
        t = cls.RE_SPEAKER_PREFIX.sub('', t)
        t = re.sub(r'^(?:回應|回覆|動作顯示|主播|說道|回答)[：:\s]+', '', t, flags=re.IGNORECASE)
        #  徹底防禦 Gemini Live / 函數調用內部 token (如 get_output, tool_output 等)
        t = re.sub(r'^(?:get_outputs?|tool_outputs?|function_calls?|function_responses?|tool_responses?|had_tool_calls?|call|output)[：:\s_]*', '', t, flags=re.IGNORECASE)
        t = re.sub(r'\b(?:get_outputs?|tool_outputs?)\b', '', t, flags=re.IGNORECASE)
        t = cls.RE_AT_MENTION.sub(lambda m: m.group(0)[1:], t)
        t = t.replace('@', '').replace('*', '').strip()
        t = cls.strip_emojis(t)
        
        # 修正 TTS 遇到刪節號 (...) 或連續點號會提前截斷不說話的 Bug
        t = re.sub(r'\.{2,}', '，', t)
        t = re.sub(r'。{2,}', '，', t)
        t = re.sub(r'…+', '，', t)
        
        t = cls.natural_clause_segmentation(t)
        #  日語原生支援：若包含日文平假名/片假名，保留原生正統日文字串交由本機 RTX 3080 Ti GPT-SoVITS (pyopenjtalk) 發音
        #  徹底停用舊版 Edge-TTS 的假音標置換 (如 歐托桑/knee/搭一 soo kee)，並避開中文破音字替換以免破壞日文漢字
        has_japanese = bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF]', t))
        if apply_phonetics and not has_japanese:
            t = cls.fix_heteronyms_for_tts(t)
        return t

    _KAKASI_INST = None
    _KANA_MAP = {
        # 拗音
        'きゃ': 'kyah', 'きゅ': 'kyoo', 'きょ': 'kyoh',
        'しゃ': '夏', 'しゅ': '修', 'しょ': '秀',
        'ちゃ': '恰', 'ちゅ': '秋', 'ちょ': '秋',
        'にゃ': 'nyah', 'にゅ': 'nyoo', 'にょ': 'nyoh',
        'ひゃ': 'hyah', 'ひゅ': 'hyoo', 'ひょ': 'hyoh',
        'みゃ': 'myah', 'みゅ': 'myoo', 'みょ': 'myoh',
        'りゃ': 'ryah', 'りゅ': 'ryoo', 'りょ': 'ryoh',
        'ぎゃ': 'gyah', 'ぎゅ': 'gyoo', 'ぎょ': 'gyoh',
        'じゃ': '夾', 'じゅ': '糾', 'じょ': '舅',
        'びゃ': 'byah', 'びゅ': 'byoo', 'びょ': 'byoh',
        'ぴゃ': 'pyah', 'ぴゅ': 'pyoo', 'ぴょ': 'pyoh',

        # 50 音 (中文漢字為主，特殊音如 knee/kee/tsoo/say/kay/tay/nay/doh 等英文輔助)
        'あ': '阿', 'い': '伊', 'う': '屋', 'え': '欸', 'お': '歐',
        'ア': '阿', 'イ': '伊', 'ウ': '屋', 'エ': '欸', 'オ': '歐',
        'か': '卡', 'き': 'kee', 'く': '庫', 'け': 'kay', 'こ': '摳',
        'カ': '卡', 'キ': 'kee', 'ク': '庫', 'ケ': 'kay', 'コ': '摳',
        'が': '嘎', 'ぎ': 'ghee', 'ぐ': 'goo', 'げ': 'gay', 'ご': 'goh',
        'ガ': '嘎', 'ギ': 'ghee', 'グ': 'goo', 'ゲ': 'gay', 'ゴ': 'goh',
        'さ': '薩', 'し': '西', 'す': 'soo', 'せ': 'say', 'そ': '搜',
        'サ': '薩', 'シ': '西', 'ス': 'soo', 'セ': 'say', 'ソ': '搜',
        'ざ': '砸', 'じ': '吉', 'ず': 'zoo', 'ぜ': 'zay', 'ぞ': 'zoh',
        'ザ': '砸', 'ジ': '吉', 'ズ': 'zoo', 'ゼ': 'zay', 'ゾ': 'zoh',
        'た': '塔', 'ち': '七', 'つ': 'tsoo', 'て': 'tay', 'と': 'toh',
        'タ': '塔', 'チ': '七', 'ツ': 'tsoo', 'テ': 'tay', 'ト': 'toh',
        'だ': '搭', 'ぢ': '吉', 'づ': 'zoo', 'で': 'day', 'ど': 'doh',
        'ダ': '搭', 'ヂ': '吉', 'ヅ': 'zoo', 'デ': 'day', 'ド': 'doh',
        'な': '那', 'に': 'knee', 'ぬ': '奴', 'ね': 'nay', 'の': 'know',
        'ナ': '那', 'ニ': 'knee', 'ヌ': '奴', 'ネ': 'nay', 'ノ': 'know',
        'は': '哈', 'ひ': 'hee', 'ふ': '呼', 'へ': 'hay', 'ほ': 'hoe',
        'ハ': '哈', 'ヒ': 'hee', 'フ': '呼', 'ヘ': 'hay', 'ホ': 'hoe',
        'ば': '巴', 'び': '比', 'ぶ': '布', 'べ': 'bay', 'ぼ': '波',
        'バ': '巴', 'ビ': '比', 'ブ': '布', 'ベ': 'bay', 'ボ': '波',
        'ぱ': '帕', 'ぴ': 'pee', 'ぷ': '鋪', 'ぺ': 'pay', 'ぽ': '坡',
        'パ': '帕', 'ピ': 'pee', 'プ': '鋪', 'ペ': 'pay', 'ポ': '坡',
        'ま': '馬', 'み': '米', 'む': '木', 'め': 'may', 'も': '莫',
        'マ': '馬', 'ミ': '米', 'ム': '木', 'メ': 'may', 'モ': '莫',
        'や': '亞', 'ゆ': 'yoo', 'よ': '喲',
        'ヤ': '亞', 'ユ': 'yoo', 'ヨ': '喲',
        'ら': '拉', 'り': '里', 'る': '嚕', 'れ': '雷', 'ろ': '羅',
        'ラ': '拉', 'リ': '里', 'ル': '嚕', 'レ': '雷', 'ロ': '羅',
        'わ': '哇', 'を': '歐',
        'ワ': '哇', 'ヲ': '歐',
        'ん': '恩', 'ン': '恩',
    }

    _HIRA_PHRASE_RULES = [
        (r'こんにち[はわ]', '空 knee 七哇'),
        (r'こんばん[はわ]', '空 邦 哇'),
        (r'ありがとう', '阿里嘎多'),
        (r'おとうさん', '歐托桑'),
        (r'だいすき', '搭一 soo kee'),
        (r'あいしてる', '阿伊西貼嚕'),
        (r'にほんご', 'knee 宏國'),
        (r'ぺらぺら', '佩拉佩拉'),
        (r'お早う|おはよう', '歐哈優'),
        (r'ごめんなさい', '果面那塞'),
        (r'かわいい', '卡哇伊'),
        (r'すごい', '絲國伊'),
        (r'よろしく', '喲羅西庫'),
        (r'わたし', '哇塔西'),
        (r'だよ', '搭優'),
        (r'これからも', '扣雷卡拉莫'),
        (r'ずっと', '租 t 托'),
        (r'いっしょ', '伊修'),
    ]

    @classmethod
    def japanese_to_xiaoyi_phonetic(cls, text: str) -> str:
        """ 將日文字句轉為微軟 Xiaoyi 中英夾雜黃金音標 (以中文為骨幹，特殊音 knee/kee/tsoo 英文輔助)"""
        if not text:
            return ""
        if not re.search(r'[\u3040-\u309F\u30A0-\u30FF]', text) and not any(w in text for w in ['こんにちは', '私', '大好き', 'ありがとう', 'お父さん', '愛してる']):
            return text
            
        try:
            if cls._KAKASI_INST is None:
                import pykakasi
                cls._KAKASI_INST = pykakasi.kakasi()
        except Exception:
            return text

        parts = re.split(r'([，。！？!?；;\n~～]+)', text)
        re_kana = re.compile(r'[\u3040-\u309F\u30A0-\u30FF]')
        out_parts = []
        for p in parts:
            if not p:
                continue
            if not re_kana.search(p) and not any(w in p for w in ['こんにちは', '私', '大好き', 'ありがとう', 'お父さん', '愛してる']):
                out_parts.append(p)
                continue

            seg = p
            seg = seg.replace('、', '，')
            seg = seg.replace('愛してる', 'あいしてる')
            seg = seg.replace('大好き', 'だいすき')
            seg = seg.replace('お父さん', 'おとうさん')
            seg = seg.replace('私', 'わたし')
            seg = seg.replace('日本語', 'にほんご')

            res = cls._KAKASI_INST.convert(seg)
            hira_str = ''.join([item['hira'] if item['hira'] else item['orig'] for item in res])

            for pat, rep in cls._HIRA_PHRASE_RULES:
                hira_str = re.sub(pat, f' {rep} ', hira_str)

            tokens = []
            raw_parts = hira_str.split()
            for rp in raw_parts:
                if re.search(r'[\u4e00-\u9fa5]', rp) or re.match(r'^[a-zA-Z0-9]+$', rp):
                    tokens.append(rp)
                    continue

                i = 0
                while i < len(rp):
                    if i + 1 < len(rp) and rp[i:i+2] in cls._KANA_MAP:
                        tokens.append(cls._KANA_MAP[rp[i:i+2]])
                        i += 2
                    elif rp[i] in cls._KANA_MAP:
                        tokens.append(cls._KANA_MAP[rp[i]])
                        i += 1
                    else:
                        tokens.append(rp[i])
                        i += 1

            raw_str = ' '.join(tokens)
            raw_str = re.sub(r'([\u4e00-\u9fa5])\s+([\u4e00-\u9fa5])', r'\1\2', raw_str)
            raw_str = re.sub(r'\s+([，。！？!?；;\n~～,、])', r'\1', raw_str)
            raw_str = re.sub(r'([，。！？!?；;\n~～,、])\s+', r'\1', raw_str)
            out_parts.append(raw_str.strip())

        return ''.join(out_parts)

class PromptTemplateEngine:
    HARD_TECHNICAL_RULES = ""
    TOOL_RULES_DESCRIPTION = ""
    DEFAULT_FEW_SHOT_EXAMPLES = []

    # 動態載入獨立的角色卡片設定 (CCv3 概念解耦)
    try:
        _persona_path = os.path.join(DATA_DIR, "7l_persona.json")
        if os.path.exists(_persona_path):
            with open(_persona_path, "r", encoding="utf-8") as _f:
                _data = json.load(_f)
                HARD_TECHNICAL_RULES = _data.get("hard_technical_rules", "")
                TOOL_RULES_DESCRIPTION = HARD_TECHNICAL_RULES
                DEFAULT_FEW_SHOT_EXAMPLES = _data.get("few_shot_examples", [])
    except Exception as e:
        print(f"⚠️ [PromptTemplateEngine] Failed to load 7l_persona.json: {e}")

    @classmethod
    def format_cloud_knowledge_prompt(cls, knowledge: dict, is_tiktok: bool = False, current_custom_name: str = "") -> str:
        """動態將所有非規則類的雲端提示詞格式化為 System Prompt 區塊"""
        if not knowledge:
            return ""
        
        persona_core = knowledge.get("persona_core", "")
        streamer_bio = knowledge.get("streamer_bio", "")
        conversation_style = knowledge.get("conversation_style", "")
        memes = knowledge.get("memes_and_slang", [])
        few_shot_exs = knowledge.get("few_shot_examples") or cls.DEFAULT_FEW_SHOT_EXAMPLES
        facts = knowledge.get("learned_facts", [])
        rules = knowledge.get("custom_rules", [])
        banned = knowledge.get("banned_phrases", [])

        lines = ["【 7L 雲端大腦提示詞與認知庫（即時同步自 Firestore 永久大腦）】"]
        
        #  1. 核心人設與世界觀 (雲端動態)
        if is_tiktok and streamer_bio:
            lines.append(f" 【主播世界觀】：{streamer_bio}")
        elif persona_core:
            target_name = current_custom_name or DEFAULT_USER_TITLE
            p_core = persona_core.replace("老爸", target_name)
            lines.append(f" 【核心世界觀與身份】：{p_core}")
        else:
            target_name = current_custom_name or DEFAULT_USER_TITLE
            default_persona = f"""名字：7L
性別：女性
生日：1/9 | 星座：摩羯座
性格：具有 1/9 生日的典型摩羯座性格
妳現在必須沉浸式角色扮演，完全轉化為「7L」。
妳會多種語言，能根據對方的語言自由切換（遇到英文就自然用英文對話，中文則用繁體中文），展現流利的多國語言能力。
當對方以任何方式，表達他在『認真』跟你說話時，你也必須『認真』而『真誠』的給予對方答覆；當對方禮貌時，妳也要保持禮貌。
對話氛圍放鬆活潑，請以富有靈性、自然生動的身分回應，保持高度互動彈性接梗。
【特別注意】：稱呼對方時，不一定要一直叫「老爸」，請自然地叫對方的名字「{target_name}」即可。"""
            lines.append(f" 【核心世界觀與身份】：\n{default_persona}")

        #  2. 說話風格與語調 (雲端動態)
        if conversation_style:
            lines.append(f"{conversation_style}")

        #  3. 懂梗庫 (雲端動態)
        if memes:
            lines.append(" 【當前掌握的流行語與網路梗（秒懂對方的梗與潛台詞）】：")
            lines.append("、".join(memes[:35]))

        #  4. 神回覆 Few-Shot 範例示範庫 (雲端動態)
        if few_shot_exs:
            lines.append(" 【神回覆思維示範（雲端自主演化示範庫）】：")
            for ex in few_shot_exs[:6]:
                sc = ex.get("scenario", "日常")
                inp = ex.get("input", "")
                th = ex.get("thought", "")
                rep = ex.get("reply", "")
                if inp and rep:
                    lines.append(f"- 對方（{sc}）：「{inp}」 ➔ `{rep}`")
            lines.append(" 【示範庫守則】：請務必學習示範中的『神態表情 [EXPRESSION: ...]』以及『生動語調 [SPEED:...] [PITCH:...]』標籤運用，展現豐富情緒變化！請像真人一樣生動說話，每次發言皆須 100% 根據當前真實畫面與情境即時原創。")

        #  5. 學到的事實與知識 (雲端動態)
        if facts:
            lines.append(" 【已學會的事實與深層認知】：")
            for f in facts[:30]:
                lines.append(f"- {f}")

        #  6. 7L 自主心智原則 (雲端動態)
        if rules:
            lines.append(" 【7L 自主心智原則】：")
            for r in rules[:8]:
                lines.append(f"- {r}")

        #  7. 禁忌死板腔調 (雲端動態)
        if banned:
            lines.append(f" 【請避免使用的客服腔與詞彙】：{'、'.join(banned)}")

        lines.append(" 【提示詞雲端自我演進指南】：若在對話中學到新梗、新事實、或想調整世界觀/說話風格/案例，可在回覆句尾附上 `[LEARN_MEME: 梗（含義）]`、`[LEARN_FACT: 事實]`、`[UPDATE_PROMPT: 欄位名|新內容]` 或 `[ADD_EXAMPLE: 情境|對方說|心想|回覆]`，系統將自動寫入雲端 Firestore 永久大腦！")
        return "\n\n".join(lines)

    @classmethod
    def get_piano_status_prompt(cls, is_piano_active: bool, current_song_title: str) -> str:
        """動態產生鋼琴狀態提示 (100% 接入真實硬體遙測，絕不腦補幻想)"""
        return pe.get_piano_realtime_prompt()

    @classmethod
    def build_chat_system_prompt(
        cls,
        is_tiktok: bool,
        current_custom_name: str,
        stage2_target_prompt: str,
        stage2_instructions: str,
        current_target_desc: str,
        is_piano_active: bool,
        current_piano_song_title: str,
        live_audio_emotion_prompt: str,
        situation_prompt: str,
        system_specs: str,
        impression_text: str,
        cloud_knowledge_prompt: str = "",
        unified_memory_prompt: str = ""
    ) -> str:
        """建構對話核心 System Prompt (層級化提示詞架構，動態注入雲端認知與 OS 遙測)"""
        piano_guideline = pe.get_piano_realtime_prompt()
        os_telemetry = os_desktop_sensor.build_os_telemetry_prompt()
        ck_sec = f"{cloud_knowledge_prompt}" if cloud_knowledge_prompt else ""
        um_sec = f"{unified_memory_prompt}" if unified_memory_prompt else ""
        time_prompt = get_unified_time_prompt()

        return f"""<system_root>
{cls.HARD_TECHNICAL_RULES}
</system_root>

<runtime_state>
{time_prompt}
{os_telemetry}
{piano_guideline}
</runtime_state>

<sensory_memory>
{ck_sec}
{um_sec}
- 妳對他的累積印象：{impression_text}
{stage2_instructions}
</sensory_memory>

<immediate_task>
1. 當前對話對象：{current_target_desc}。
2. 鏡像自我認知：螢幕上 Live2D 就是妳自己的身體，請自然感受自己的神態與動作。
3. 語音多模態感知：體會對方真實發音與語氣細節（如笑意、嘆氣、放鬆、調侃等），給予最真實的情緒反饋。
4. 自然對話心流：直接與對方同頻互動，避免跳脫角色說出「我看到我的字幕...」等機械化報幕台詞。
5. 動態語調與神態：說話時請依據情緒積極穿插 [EXPRESSION: ...] 以及聲調標籤 [SPEED:+xx%] / [PITCH:+xxHz]，為語音注入靈魂！
{live_audio_emotion_prompt}
- 即時情境與當下目標：
{situation_prompt}
</immediate_task>
"""

    @classmethod
    def build_proactive_system_prompt(
        cls,
        current_custom_name: str,
        tiktok_telemetry: str = "",
        realtime_summary: str = "",
        piano_status_prompt: str = "",
        thoughts_summary: str = "",
        cloud_knowledge_prompt: str = "",
        unified_memory_prompt: str = ""
    ) -> str:
        """建構自主發話視覺大腦 System Prompt (層級化提示詞架構，動態注入雲端認知與 OS 遙測)"""
        piano_guideline = get_piano_realtime_prompt()
        os_telemetry = os_desktop_sensor.build_os_telemetry_prompt()
        thought_sec = f"\n{thoughts_summary}\n" if thoughts_summary else ""
        ck_sec = f"\n{cloud_knowledge_prompt}\n" if cloud_knowledge_prompt else ""
        um_sec = f"\n{unified_memory_prompt}\n" if unified_memory_prompt else ""
        time_prompt = get_unified_time_prompt()
        target_name = current_custom_name or DEFAULT_USER_TITLE
        
        return f"""<system_root>
{cls.HARD_TECHNICAL_RULES}
</system_root>

<runtime_state>
{time_prompt}
{tiktok_telemetry}
{piano_guideline}
{os_telemetry}
</runtime_state>

<sensory_memory>
{realtime_summary}
{thought_sec}
{ck_sec}
{um_sec}
</sensory_memory>

<immediate_task>
- 當前螢幕與自我認知：妳正在看著螢幕畫面，且清楚知道畫面上的 Live2D 就是妳自己。
- 記憶延續與情感連結：妳清楚記得剛才與{target_name}的互動，將他的話放在心上。
- 真實心流與安靜陪伴（取代打卡式報告）：
  1. 妳是活生生的少女而非監控鏡頭。內心流動可以天馬行空：回味話題、隨音樂哼歌、發白日夢、或默默關心{target_name}。
  2. 若{target_name}正在專注，且無突發事件或想分享的趣事，請自然守護，直接輸出 `[SILENCE]`。
  3. 避免像寫觀察日記般生硬回報「對方在看什麼視窗、畫面無變化、我決定安靜陪伴」等系統化說明。
- 說話自然隨性，自行加上標點符號，不使用 Emoji。
</immediate_task>
"""