# -*- coding: utf-8 -*-
"""直播聊天室監聽器純函式測試（Twitch IRC 解析 / YouTube InnerTube 解析）"""
from conftest import ROOT  # noqa: F401
from services.twitch_listener import parse_irc_line, parse_channels, build_queue_item as tw_item
from services.youtube_live_listener import (
    normalize_video_id, normalize_channel, extract_continuation, extract_live_from_html,
    parse_live_chat_response, build_queue_item as yt_item,
)

# ⚠️ 必須與 vts_7L_test.py 軌道2 的正則一致（那邊負責拆出暱稱/ID/內容）
TRACK2_RE = __import__("re").compile(
    r"【\w+ (?:直播觀眾|官方提問箱|直播動態)\s*([^\】]*?)\s*(?:留言|送禮|動態|提問)?】[：:]\s*(.*)"
)


# ── Twitch IRC ────────────────────────────────────────────────────────────
def test_twitch_parse_privmsg_with_tags():
    line = ("@badge-info=;badges=;color=#FF0000;display-name=小夏子;mod=0; "
            ":xiaoxiazi!xiaoxiazi@xiaoxiazi.tmi.twitch.tv PRIVMSG #mychan :7L 早安！")
    m = parse_irc_line(line)
    assert m["user"] == "xiaoxiazi"
    assert m["display"] == "小夏子"
    assert m["channel"] == "mychan"
    assert m["message"] == "7L 早安！"


def test_twitch_parse_privmsg_without_tags():
    m = parse_irc_line(":someuser!someuser@someuser.tmi.twitch.tv PRIVMSG #ch :hi there")
    assert m["user"] == "someuser"
    assert m["display"] == "someuser"          # 沒 tags 時用帳號名
    assert m["message"] == "hi there"


def test_twitch_parse_ping_and_noise():
    assert parse_irc_line("PING :tmi.twitch.tv") == {"ping": True}
    assert parse_irc_line(":tmi.twitch.tv 001 justinfan1 :Welcome") is None
    assert parse_irc_line(":u!u@u JOIN #ch") is None
    assert parse_irc_line("") is None
    assert parse_irc_line(None) is None


def test_twitch_parse_channels():
    assert parse_channels("Foo, bar ;Baz") == ["foo", "bar", "baz"]
    assert parse_channels("#MainChan") == ["mainchan"]
    assert parse_channels("") == []
    assert parse_channels(None) == []


def test_twitch_queue_item_matches_track2_regex():
    item = tw_item("someuser", "小夏子", "彈一首卡農！")
    m = TRACK2_RE.search(item["text"])
    assert m, f"軌道2 正則解析失敗: {item['text']}"
    assert m.group(1).strip() == "小夏子 (@someuser)"
    assert m.group(2) == "彈一首卡農！"
    assert item["source"] == "twitch" and item["audio_base64"] is None


# ── YouTube InnerTube ────────────────────────────────────────────────────
def test_normalize_video_id():
    assert normalize_video_id("abc123def45") == "abc123def45"
    assert normalize_video_id("https://www.youtube.com/watch?v=xyzABC12345&t=10") == "xyzABC12345"
    assert normalize_video_id("https://youtu.be/xyzABC12345") == "xyzABC12345"
    assert normalize_video_id("") == ""
    # 頻道輸入不再當成直播 ID（交給 normalize_channel）
    assert normalize_video_id("@LofiGirl") == ""
    assert normalize_video_id("UCc5afI6TobiZjRke2sYBDPA") == ""
    assert normalize_video_id("https://www.youtube.com/@LofiGirl") == ""
    assert normalize_video_id("https://www.youtube.com/channel/UCc5afI6TobiZjRke2sYBDPA") == ""


def test_normalize_channel():
    assert normalize_channel("@LofiGirl") == "@LofiGirl"
    assert normalize_channel("@LofiGirl/live") == "@LofiGirl"
    assert normalize_channel("UCc5afI6TobiZjRke2sYBDPA") == "channel/UCc5afI6TobiZjRke2sYBDPA"
    assert normalize_channel("https://www.youtube.com/@LofiGirl") == "@LofiGirl"
    assert normalize_channel("https://www.youtube.com/channel/UCc5afI6TobiZjRke2sYBDPA") == "channel/UCc5afI6TobiZjRke2sYBDPA"
    assert normalize_channel("https://www.youtube.com/c/SomeName") == "c/SomeName"
    assert normalize_channel("") == ""
    # 非頻道輸入回空
    assert normalize_channel("abc123def45") == ""
    assert normalize_channel("https://www.youtube.com/watch?v=abc123def45") == ""


def _fake_live_page(video_id="3PFJ9SETS4M", is_live=True, ok=True, title="lofi radio"):
    status = "OK" if ok else "LIVE_STREAM_OFFLINE"
    pr = ('{"videoDetails":{"videoId":"VID","isLiveContent":LIVE,"title":"TITLE"},'
          '"playabilityStatus":{"status":"STAT"}}').replace("VID", video_id).replace("LIVE", "true" if is_live else "false")
    pr = pr.replace("TITLE", title).replace("STAT", status)
    # 夾一個 '};' 誘餌：括號配對必須跳過它
    return ('<html><link rel="canonical" href="https://www.youtube.com/watch?v=%s">'
            "<script>var ytInitialPlayerResponse = %s;</script>"
            "<script>var dummy = {a:1};</script></html>") % (video_id, pr)


def test_extract_live_from_html_live_and_offline():
    vid, is_live, title, ok = extract_live_from_html(_fake_live_page())
    assert (vid, is_live, ok) == ("3PFJ9SETS4M", True, True)
    assert title == "lofi radio"
    vid, is_live, title, ok = extract_live_from_html(_fake_live_page(is_live=False, ok=False, title="some trailer"))
    assert (vid, is_live, ok) == ("3PFJ9SETS4M", False, True)
    # 空頁 / 無 canonical / 無 playerResponse
    assert extract_live_from_html("") == (None, False, "", False)
    assert extract_live_from_html("<html>no data</html>") == (None, False, "", False)
    only_canon = '<link rel="canonical" href="https://www.youtube.com/watch?v=abc123def45">'
    assert extract_live_from_html(only_canon) == ("abc123def45", False, "", False)


def test_extract_continuation_patterns():
    html1 = '{"liveChatRenderer":{"continuation":"CONT_TOKEN_111"}}'
    assert extract_continuation(html1) == "CONT_TOKEN_111"
    html2 = 'junk {"continuation":"ABCDEFG1234567890_-"} more'
    assert extract_continuation(html2) == "ABCDEFG1234567890_-"
    assert extract_continuation("<html>沒有 token</html>") is None
    assert extract_continuation("") is None


def _sample_response(with_author=True, with_timeout=True):
    renderer = {"message": {"runs": [{"text": "7L 唱一首！"}]}}
    if with_author:
        renderer["authorName"] = {"simpleText": "路人甲"}
    data = {
        "continuationContents": {
            "liveChatContinuation": {
                "actions": [
                    {"addLiveChatTextAction": {"item": {"liveChatTextActionRenderer": renderer}}},
                    {"addLiveChatTickerItemAction": {"item": {"liveChatTickerRenderer": {}}}},  # 應被忽略
                    {"addLiveChatMembershipItemAction": {"item": {}}},                          # 應被忽略
                ],
                "continuation": "NEXT_CONT_TOKEN",
                **({"timeoutMs": 5000} if with_timeout else {}),
            }
        }
    }
    return data


def test_parse_live_chat_response_basic():
    msgs, cont, wait = parse_live_chat_response(_sample_response())
    assert msgs == [{"user": "路人甲", "message": "7L 唱一首！"}]
    assert cont == "NEXT_CONT_TOKEN"
    assert wait == 5.0


def test_parse_live_chat_response_nextgen_continuation_shapes():
    """真實 InnerTube 形狀：continuations[0].invalidationContinuationData.continuation"""
    data = {"continuationContents": {"liveChatContinuation": {
        "actions": [], "timeoutMs": 9000,
        "continuations": [{"invalidationContinuationData": {
            "continuation": "INVD_" + "X" * 40, "invalidationId": {}}}]}}}
    msgs, cont, wait = parse_live_chat_response(data)
    assert msgs == [] and cont == "INVD_" + "X" * 40 and wait == 9.0

    # timedContinuationData 變體
    data2 = {"liveChatContinuation": {
        "continuations": [{"timedContinuationData": {"continuation": "TIMED_" + "Y" * 40}}]}}
    assert parse_live_chat_response(data2)[1] == "TIMED_" + "Y" * 40

    # 三處都沒有 → 回 None（呼叫端重抓）
    assert parse_live_chat_response({"actions": []}) == ([], None, 8.0)


def test_parse_live_chat_response_author_fallback_and_no_timeout():
    msgs, cont, wait = parse_live_chat_response(_sample_response(with_author=False, with_timeout=False))
    assert msgs[0]["user"] == "觀眾"          # 沒 authorName → 兜底
    assert cont == "NEXT_CONT_TOKEN"
    assert 5.0 <= wait <= 15.0                # timeoutMs 缺 → 預設 8s，且被夾在5~15


def test_parse_live_chat_response_empty_and_flat_shape():
    # 空回應
    assert parse_live_chat_response({}) == ([], None, 8.0)
    assert parse_live_chat_response(None) == ([], None, 8.0)
    # 扁平形狀（無 continuationContents 包裝）
    flat = {"actions": [{"addLiveChatTextAction": {"item": {
        "liveChatTextActionRenderer": {"message": {"runs": [{"text": "哈囉"}]}}}}}],
        "continuation": "FLAT_CONT", "timeoutMs": 12000}
    msgs, cont, wait = parse_live_chat_response(flat)
    assert msgs[0]["message"] == "哈囉" and cont == "FLAT_CONT" and wait == 12.0


def test_youtube_queue_item_matches_track2_regex():
    item = yt_item("路人甲", "早啊")
    m = TRACK2_RE.search(item["text"])
    assert m, f"軌道2 正則解析失敗: {item['text']}"
    assert m.group(1).strip() == "路人甲"      # 無 (@id) → 主程式會用暱稱當 id
    assert m.group(2) == "早啊"
    assert item["source"] == "youtube"
