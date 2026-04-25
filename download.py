"""批次把 videos.tsv 內的 YouTube 影片下載成 MP3。

設計重點：
- yt-dlp Python API（而非 subprocess）：更可靠、進度可控
- ThreadPoolExecutor 並行 4 個 worker
- 跳過已完成檔案（檔名 `id__` 前綴；被重命名過的檔回退讀 ID3 purl tag）
- 嵌入 ID3 metadata 讓車載系統顯示曲名
- 失敗列進 failed.tsv 供下一輪重試

Fail-fast：如果 yt-dlp 回報錯誤，紀錄後繼續下一支，不偷偷吞錯。
"""

from __future__ import annotations

import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

ROOT = Path(__file__).parent
OUT_DIR = ROOT / "mp3"
LOG_DIR = ROOT / "logs"
WORKERS = 4

ID_PREFIX_RE = re.compile(r"^([A-Za-z0-9_-]{11})__")


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


def read_purl_video_id(path: Path) -> str | None:
    """讀 mp3 的 ID3 purl tag 反查 YouTube video id。失敗回 None。"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format_tags=purl",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True, timeout=10,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None
    purl = result.stdout.strip()
    if not purl:
        return None
    parsed = urlparse(purl)
    if parsed.path == "/watch":
        q = parse_qs(parsed.query)
        if q.get("v"):
            return q["v"][0]
    if "youtu.be" in parsed.netloc:
        return parsed.path.lstrip("/").split("/")[0] or None
    return None


def scan_downloaded_ids(out_dir: Path) -> set[str]:
    """掃描 out_dir，回傳已下載的 video id 集合。

    優先看檔名 `{id}__` 前綴；前綴被 rename_to_bookmark.py 拿掉的，回退讀 ID3 purl tag。
    缺了 fallback 的話，rename 過的檔案會被當成「沒下載」重抓一次。
    """
    ids: set[str] = set()
    for f in out_dir.glob("*.mp3"):
        m = ID_PREFIX_RE.match(f.name)
        if m:
            ids.add(m.group(1))
            continue
        vid = read_purl_video_id(f)
        if vid:
            ids.add(vid)
    return ids


def download_one(video_id: str, url: str, title: str) -> tuple[str, str, str, str | None]:
    """下載單支影片。回傳 (video_id, url, title, error or None)。"""
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

    existing_ids = scan_downloaded_ids(OUT_DIR)
    todo = [e for e in entries if e[0] not in existing_ids]
    total = len(todo)
    print(
        f"videos.tsv {len(entries)} 支，已下載 {len(entries) - total} 支，"
        f"待下載 {total} 支（{WORKERS} 個 worker）",
        file=sys.stderr,
    )

    if not todo:
        print("沒有要下載的", file=sys.stderr)
        return 0

    failures: list[tuple[str, str, str, str]] = []
    completed = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(download_one, v, u, t): (v, u, t) for v, u, t in todo}
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
