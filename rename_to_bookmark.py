"""用書籤標題（videos.tsv）重新命名 mp3/ 內的檔案。

映射方式：讀每個 MP3 的 ID3 `purl` tag → video id → 對應書籤標題。
撞名時加 " (2)", " (3)" 等後綴。
Fail-fast：任何找不到 purl 或 id 對不上 videos.tsv 就拋錯。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).parent
MP3_DIR = ROOT / "mp3"

# Windows / USB / 車機友善：移除或替換檔名中的不安全字元
INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize(name: str) -> str:
    name = INVALID_CHARS.sub("_", name)
    name = name.strip().rstrip(".")
    return name or "untitled"


def read_purl(path: Path) -> str | None:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format_tags=purl",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    purl = result.stdout.strip()
    return purl or None


def extract_video_id(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.path == "/watch":
        q = parse_qs(parsed.query)
        if "v" in q and q["v"]:
            return q["v"][0]
    if "youtu.be" in parsed.netloc:
        return parsed.path.lstrip("/").split("/")[0] or None
    return None


def load_bookmark_titles() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for line in (ROOT / "videos.tsv").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        vid, _url, title = line.split("\t", 2)
        mapping[vid] = title
    return mapping


def main() -> int:
    titles = load_bookmark_titles()
    files = sorted(MP3_DIR.glob("*.mp3"))

    # 第一輪：收集重命名計畫（不動檔），撞名時編號
    plan: list[tuple[Path, Path]] = []
    used: set[str] = set()
    for src in files:
        purl = read_purl(src)
        if not purl:
            print(f"❌ 沒 purl tag: {src.name}", file=sys.stderr)
            return 1
        vid = extract_video_id(purl)
        if vid not in titles:
            print(f"❌ video id 不在 videos.tsv: {vid}  ({src.name})", file=sys.stderr)
            return 1

        base = sanitize(titles[vid])
        candidate = f"{base}.mp3"
        counter = 2
        while candidate in used:
            candidate = f"{base} ({counter}).mp3"
            counter += 1
        used.add(candidate)
        plan.append((src, MP3_DIR / candidate))

    # 第二輪：先全改成暫名，再改回目標名，避免中途撞到自己
    temps: list[tuple[Path, Path]] = []
    for i, (src, dst) in enumerate(plan):
        temp = MP3_DIR / f".__tmp_{i:04d}__.mp3"
        src.rename(temp)
        temps.append((temp, dst))

    for temp, dst in temps:
        temp.rename(dst)

    print(f"重新命名 {len(plan)} 個檔案")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
