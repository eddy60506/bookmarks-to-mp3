"""驗證 mp3/ 下每個檔案都是合法可播放的 MP3。

策略：
1. ffprobe 檢查 format + 至少一條 audio stream，time-length > 1s
2. 用 ffmpeg null output 解碼整段一次，確認沒有資料損毀（decode errors）
   這比單純看 header 嚴謹很多 — 車機碰到壞尾會整首跳過。
"""

from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).parent
MP3_DIR = ROOT / "mp3"


def probe(path: Path) -> tuple[Path, str | None, dict | None]:
    """ffprobe JSON 輸出；回傳 (path, error or None, info)."""
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error", "-print_format", "json",
                "-show_format", "-show_streams", str(path),
            ],
            capture_output=True, text=True, check=True, timeout=30,
        )
    except subprocess.CalledProcessError as exc:
        return path, f"ffprobe failed: {exc.stderr.strip()[:200]}", None
    except subprocess.TimeoutExpired:
        return path, "ffprobe timeout", None

    info = json.loads(out.stdout)
    fmt = info.get("format", {})
    streams = info.get("streams", [])
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

    if not audio_streams:
        return path, "no audio stream", info
    if "mp3" not in fmt.get("format_name", ""):
        return path, f"format is {fmt.get('format_name')}, not mp3", info
    try:
        duration = float(fmt.get("duration", 0))
    except (TypeError, ValueError):
        return path, "no duration", info
    if duration < 1.0:
        return path, f"too short: {duration:.2f}s", info
    return path, None, info


def decode_check(path: Path) -> str | None:
    """用 ffmpeg -f null 解碼一遍，抓 decode error。回傳錯誤訊息或 None。"""
    try:
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"],
            capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        return "decode timeout"
    if result.returncode != 0:
        return f"ffmpeg exit {result.returncode}: {result.stderr.strip()[:200]}"
    stderr = result.stderr.strip()
    if stderr:
        # ffmpeg 有時會印警告但 returncode=0；當成錯誤處理（fail-fast）
        return f"decode warnings: {stderr[:200]}"
    return None


def check_one(path: Path) -> tuple[Path, str | None, float]:
    path, probe_err, info = probe(path)
    if probe_err:
        return path, probe_err, 0.0
    decode_err = decode_check(path)
    duration = float(info["format"].get("duration", 0)) if info else 0.0
    return path, decode_err, duration


def main() -> int:
    files = sorted(MP3_DIR.glob("*.mp3"))
    total = len(files)
    print(f"驗證 {total} 個 MP3 檔案...", file=sys.stderr)

    bad: list[tuple[Path, str]] = []
    total_duration = 0.0

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(check_one, p): p for p in files}
        done = 0
        for fut in as_completed(futures):
            path, err, dur = fut.result()
            done += 1
            if err:
                bad.append((path, err))
                print(f"[{done}/{total}] BAD  {path.name}: {err}", flush=True)
            else:
                total_duration += dur
                if done % 25 == 0 or done == total:
                    print(f"[{done}/{total}] ...", flush=True)

    hours = total_duration / 3600
    print(f"\n總時長: {hours:.2f} 小時 ({total_duration:.0f} 秒)", file=sys.stderr)
    print(f"OK: {total - len(bad)}  BAD: {len(bad)}", file=sys.stderr)
    if bad:
        for p, err in bad:
            print(f"  - {p.name}: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
