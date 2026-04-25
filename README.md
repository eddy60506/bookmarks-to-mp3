# bookmarks-to-mp3

把 Chrome 匯出的書籤 HTML 裡**指定資料夾**內的 YouTube 影片批次下載成 MP3，檔案經完整性驗證後用書籤標題重新命名，適合拷進 USB 給車機播放。

一次性 pipeline，不是長期運行的應用。

## 這個工具解決什麼問題

- 爸媽/長輩在 Chrome 書籤存了一堆喜歡的 YouTube 歌曲，想在車上離線聽
- 車機只支援 USB + MP3，沒有 YouTube App
- 手動一首一首下載太痛苦

## 需求

- macOS 或 Linux
- Python 3.12+
- [uv](https://github.com/astral-sh/uv)（Python 套件管理）
- [ffmpeg / ffprobe](https://ffmpeg.org/)

macOS 一次裝好：

```bash
brew install uv ffmpeg
```

## 使用方式

### 1. 從 Chrome 匯出書籤

Chrome → 書籤 → 書籤管理員 → 右上角 → **匯出書籤** → 存成 HTML 放進專案根目錄。

### 2. 設定來源資料夾

打開 `parse_bookmarks.py`，改第 14 行的常數：

```python
TARGET_FOLDER = "錄音"   # 改成你書籤裡的資料夾名稱
```

只有這個資料夾內的 YouTube 連結會被下載，其他書籤不動。

### 3. 設定書籤檔名

打開 `parse_bookmarks.py` 最後面，確認路徑對應到你的書籤檔：

```python
main(root / "bookmarks_2026_4_25.html", root / "videos.tsv")
```

### 4. 依序執行四個階段

```bash
uv sync                              # 安裝依賴（第一次）
uv run python parse_bookmarks.py     # HTML → videos.tsv
uv run python download.py            # 下載並轉 MP3 (192kbps, 含 ID3 tag + 封面)
uv run python verify.py              # 整段解碼驗證檔案沒損毀
uv run python rename_to_bookmark.py  # 用書籤標題重新命名
```

執行結果放在 `mp3/` 目錄，複製到 USB 即可。

### 5. 失敗處理

下載階段若有影片下架/私人/年齡限制，清單會寫在 `failed.tsv`，不會中斷其他下載。

## 主要檔案

| 檔案 | 用途 |
|---|---|
| `parse_bookmarks.py` | 從書籤 HTML 抽出指定資料夾內的 YouTube 影片 |
| `download.py` | yt-dlp Python API 並行下載 + ffmpeg 轉 MP3 |
| `verify.py` | ffprobe + ffmpeg `-f null` 全解驗證 |
| `rename_to_bookmark.py` | 依書籤原標題重新命名（利用 ID3 purl tag 反查） |
| `CLAUDE.md` | 給 Claude Code 的專案說明 |

## 可調整項目

- **MP3 bitrate**：`download.py` 的 `preferredquality`（預設 `"192"`）
- **並行下載數**：`download.py` 的 `WORKERS`（預設 4）
- **檔名長度**：`download.py` outtmpl 裡的 `%(title).150B`（位元組數）

## 常見失敗模式

| 現象 | 說明 |
|---|---|
| `Video unavailable` | 影片被刪除或頻道關閉，無法取回 |
| `Private video` | 需要帳號授權 |
| `Sign in to confirm your age` | 年齡限制需要 cookies |

後兩者可設定 yt-dlp `--cookies-from-browser` 解決（本專案預設未啟用）。

## 授權與免責

本工具僅用於下載你**有權存取**的個人收藏。請遵守 YouTube 服務條款與當地著作權法律。
