import pykakasi

kakasi = pykakasi.kakasi()

def natural_japanese_phonemes(text):
    """
    將日文轉為連貫的羅馬拼音音素，特別處理促音、長音與連讀助詞
    """
    # 助詞發音校正
    text = text.replace("は", " wa ").replace("へ", " e ").replace("を", " o ")
    
    result = kakasi.convert(text)
    words = []
    for item in result:
        hep = item['hepburn']
        words.append(hep)
    
    sentence = " ".join(words)
    # 連音與符號整理
    sentence = sentence.replace(" ,", ",").replace(" !", "!").replace(" ?", "?")
    return sentence

if __name__ == "__main__":
    t = "お兄ちゃん、おかえり！待ってたよ！今日も配信見に来てくれてありがとう！"
    # 調整語句，讓促音和尾音更符合口語自然拼讀
    # 例如: Oniichan, okaeri! Matte tayo! Kyou mo haishin mini kite kurete arigatou!
    print("口語自然化處理:")
    print(natural_japanese_phonemes(t))
