# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案性質

這是一個**一次性資料處理 pipeline**，不是長期運行的應用：把 Chrome 匯出的書籤 HTML 裡指定資料夾的 YouTube 影片轉成 MP3，放到 USB 上給車機播放。

外部工具依賴：`ffmpeg`、`ffprobe`（透過 Homebrew 安裝，`/opt/homebrew/bin/`）。Python 依賴只有 `yt-dlp`，由 uv 管理。

## 常用指令

```bash
uv sync                              # 安裝依賴
uv run python parse_bookmarks.py     # ① HTML → videos.tsv
uv run python download.py            # ② videos.tsv → mp3/{id}__{title}.mp3
uv run python verify.py              # ③ 解碼驗證每支 MP3 完整性
uv run python rename_to_bookmark.py  # ④ 檔名改成書籤標題
```

這四支必須**照順序**執行。沒有 test suite、沒有 lint 設定。

## Pipeline 階段與資料流

```
bookmarks_*.html
   │ parse_bookmarks.py  (HTMLParser 追蹤資料夾堆疊，只抓 TARGET_FOLDER 下的連結)
   ▼
videos.tsv                (id \t url \t bookmark_title)
   │ download.py  (yt-dlp Python API, ThreadPoolExecutor 4 workers)
   ▼
mp3/{id}__{title}.mp3     (ID3 tag + 封面已嵌入; purl tag 存原始 YouTube URL)
   │ verify.py
   ▼
mp3/{id}__{title}.mp3     (ffprobe + ffmpeg -f null 全解檢查)
   │ rename_to_bookmark.py  (讀 ID3 purl → video id → videos.tsv 書籤標題)
   ▼
mp3/{bookmark_title}.mp3
```

## 非顯而易見的設計決策

這些設計不看原始碼會踩雷，修改前請先讀：

- **`parse_bookmarks.py` 的 `TARGET_FOLDER` 常數**控制抓哪個資料夾。Chrome 書籤 HTML 的資料夾階層必須用 `HTMLParser` 追蹤 `<H3>`/`<DL>` 配對（regex 做不到），parser 裡用 `_folder_stack` 在進入 `<DL>` 時 push、退出時 pop。

- **`download.py` 的檔名模板 `%(id)s__%(title).150B.%(ext)s`**：
  - `id` 前綴是 `scan_downloaded_ids()` 的快路徑（檔名 glob）；`rename_to_bookmark.py` 把前綴拿掉後，回退讀 ID3 `purl` tag 反查 video id。少了 fallback，重跑會把已重命名的檔當成沒下載再抓一次（曾經踩過這個坑）。
  - `.150B` 是位元組截斷，中文字（UTF-8 3 bytes）約 50 字上限，避免 macOS 檔名長度問題
  - 因此下載階段的檔名≠最終檔名，不要拿下載階段的 `mp3/` 內容去找「正確名字」

- **`rename_to_bookmark.py` 靠 ID3 `purl` tag 反查**：yt-dlp 下載時會把 `https://www.youtube.com/watch?v={id}` 寫進 ID3 `purl` 與 `comment`。重命名後檔名已丟掉 id prefix，就靠這個 tag 把檔案對回 `videos.tsv` 的書籤標題。如果 `verify.py` 或後續流程修掉這個 tag，rename_to_bookmark 會壞掉。

- **`rename_to_bookmark.py` 用兩階段重命名**（先全部 → `.__tmp_NNNN__.mp3`，再全部 → 目標名）。單階段 rename 遇到兩檔案互換名字時會中途覆蓋，兩階段是必要的。

- **「書籤標題」vs「YouTube 當前標題」會不同**：書籤是當時存的快照，YouTube 影片作者可能改過標題。yt-dlp 撈到的是 YouTube 當前標題；`videos.tsv` 存的是書籤標題。最終檔名要用書籤標題（使用者記憶中的名字），所以需要 `rename_to_bookmark.py`。

- **`verify.py` 用 `ffmpeg -f null` 整段解碼**，不只看 header。車機遇到尾部損毀會整首跳過，只驗 header 會漏掉這種壞檔。

- **`rename.py`（舊版）已被 `rename_to_bookmark.py` 取代**，保留但不再執行。如果整理專案可以刪掉。

## 典型失敗模式

- YouTube 影片下架 / 轉私人 / 帳號被停：`download.py` 會寫進 `failed.tsv`，這類無法自動恢復。年齡限制與私人影片需要 `--cookies-from-browser`（目前未設定）。
- 磁碟空間：每支歌平均 ~10–15 MB，下載中間 yt-dlp 會暫存 webm/m4a 再轉 mp3，短暫用量會高一些。
- 檔名含 `/`、`?`、`*` 等字元會被 `rename_to_bookmark.py` 的 `sanitize()` 替換成 `_`（Windows / 車機 FAT32 安全）。
