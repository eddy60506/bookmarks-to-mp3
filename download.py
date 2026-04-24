"""批次把 videos.tsv 內的 YouTube 影片下載成 MP3。

設計重點：
- yt-dlp Python API（而非 subprocess）：更可靠、進度可控
- ThreadPoolExecutor 並行 4 個 worker
- 跳過已完成檔案（以 video id 在檔名前綴）
- 嵌入 ID3 metadata 讓車載系統顯示曲名
- 失敗列進 failed.tsv 供下一輪重試

Fail-fast：如果 yt-dlp 回報錯誤，紀錄後繼續下一支，不偷偷吞錯。
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

ROOT = Path(__file__).parent
OUT_DIR = ROOT / "mp3"
LOG_DIR = ROOT / "logs"
WORKERS = 4


def make_ydl_opts(out_dir: Path, log_file: Path) -> dict:
    """回傳 yt-dlp 設定。檔名前綴 video id 以利之後跳過已下載。"""
    return {
        "format": "bestaudio/best",
        "outtmpl": str(out_dir / "%(id)s__%(title).150B.%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            },
            {"key": "FFmpegMetadata"},  # 寫入 ID3 tag
            {"key": "EmbedThumbnail"},  # 封面圖（車機有的會顯示）
        ],
        "writethumbnail": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ignoreerrors": False,
        "retries": 3,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 4,
        "logtostderr": False,
    }


def already_downloaded(video_id: str, out_dir: Path) -> Path | None:
    matches = list(out_dir.glob(f"{video_id}__*.mp3"))
    return matches[0] if matches else None


def download_one(video_id: str, url: str, title: str) -> tuple[str, str, str, str | None]:
    """下載單支影片。回傳 (video_id, url, title, error or None)。"""
    existing = already_downloaded(video_id, OUT_DIR)
    if existing is not None:
        return video_id, url, title, None

    log_file = LOG_DIR / f"{video_id}.log"
    opts = make_ydl_opts(OUT_DIR, log_file)
    try:
        with YoutubeDL(opts) as ydl:
            ydl.download([url])
        return video_id, url, title, None
    except DownloadError as exc:
        return video_id, url, title, str(exc)
    except Exception as exc:  # noqa: BLE001 — 要能繼續處理下一支
        return video_id, url, title, f"{type(exc).__name__}: {exc}"


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)

    videos_file = ROOT / "videos.tsv"
    entries: list[tuple[str, str, str]] = []
    for line in videos_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        vid, url, title = line.split("\t", 2)
        entries.append((vid, url, title))

    total = len(entries)
    print(f"共 {total} 支影片，{WORKERS} 個 worker 並行下載", file=sys.stderr)

    failures: list[tuple[str, str, str, str]] = []
    completed = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(download_one, v, u, t): (v, u, t) for v, u, t in entries}
        for fut in as_completed(futures):
            vid, url, title, err = fut.result()
            completed += 1
            if err is None:
                print(f"[{completed}/{total}] OK   {vid}  {title[:60]}", flush=True)
            else:
                first_line = err.split("\n", 1)[0][:200]
                print(f"[{completed}/{total}] FAIL {vid}  {first_line}", flush=True)
                failures.append((vid, url, title, err))

    if failures:
        failed_tsv = ROOT / "failed.tsv"
        with failed_tsv.open("w", encoding="utf-8") as f:
            for vid, url, title, err in failures:
                err_short = err.replace("\t", " ").replace("\n", " ")[:500]
                f.write(f"{vid}\t{url}\t{title}\t{err_short}\n")
        print(f"\n失敗 {len(failures)} 支，詳情見 {failed_tsv}", file=sys.stderr)
        return 1

    print("\n全部下載完成", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
