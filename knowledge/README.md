# 📚 外部知識庫 (knowledge/)

這裡放 7L 可以被檢索的「外部知識」純文字檔（`.md` / `.txt`），
與 `data/*.json` 的記憶一起被嵌入到 `data/rag/chroma` 向量庫。

## 建檔方式

```bash
python scripts/ingest_rag.py            # 全量重建（data/*.json + knowledge/**）
python scripts/ingest_rag.py --source knowledge   # 只索引本資料夾
```

## 適合放什麼

- 爸爸的偏好、直播規則、常用指令
- 遊戲攻略 / 角色資料 / 梗的出處
- 頻道設定、合作過的 VTuber 名單
- 任何希望 7L 「想得起來」的長篇資料

## 建議格式

- 一個主題一個檔案，檔名即主題（例：`minecraft_伺服器設定.md`）
- 內文用條列或短段落，單段 200~400 字最容易被正確召回
- 開頭放一行標題，方便檢索時辨識

> 機密（金鑰、密碼、個人隱私）請勿放入此資料夾。
