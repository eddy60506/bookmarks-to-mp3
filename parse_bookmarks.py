"""從 Chrome 匯出的書籤 HTML 抽取指定資料夾內的 YouTube 影片 ID。

Chrome 書籤 HTML 結構（NETSCAPE-Bookmark-file-1）：
    <DT><H3>資料夾名</H3>
    <DL><p>
        <DT><A HREF="...">連結</A>
        ...
    </DL><p>

用 HTMLParser 追蹤當前資料夾堆疊，只擷取 TARGET_FOLDER 底下的連結。
"""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

TARGET_FOLDER = "錄音"


class BookmarkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.entries: list[tuple[str, str]] = []
        self._folder_stack: list[str] = []

        # DL 開啟 = 進入新資料夾。Chrome 把最近的 H3 當成這個 DL 的名稱。
        # 為了對齊 H3 與 DL，維護「下一個 DL 要用的資料夾名」。
        self._pending_folder: str | None = None
        self._in_h3: bool = False
        self._h3_buffer: list[str] = []

        self._current_href: str | None = None
        self._a_buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t == "h3":
            self._in_h3 = True
            self._h3_buffer = []
        elif t == "dl":
            # 進入一層新資料夾，用最近看到的 H3 當名稱（頂層沒 H3，會是 None）
            self._folder_stack.append(self._pending_folder or "")
            self._pending_folder = None
        elif t == "a":
            for name, value in attrs:
                if name.lower() == "href" and value:
                    self._current_href = value
                    self._a_buffer = []
                    return

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "h3" and self._in_h3:
            self._pending_folder = "".join(self._h3_buffer).strip()
            self._in_h3 = False
        elif t == "dl":
            if self._folder_stack:
                self._folder_stack.pop()
        elif t == "a" and self._current_href is not None:
            title = "".join(self._a_buffer).strip()
            if TARGET_FOLDER in self._folder_stack:
                self.entries.append((self._current_href, title))
            self._current_href = None
            self._a_buffer = []

    def handle_data(self, data: str) -> None:
        if self._in_h3:
            self._h3_buffer.append(data)
        elif self._current_href is not None:
            self._a_buffer.append(data)


def extract_video_id(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if "youtu.be" in host:
        vid = parsed.path.lstrip("/").split("/")[0]
        return vid or None
    if "youtube.com" not in host:
        return None
    if parsed.path == "/watch":
        q = parse_qs(parsed.query)
        if "v" in q and q["v"]:
            return q["v"][0]
    m = re.match(r"^/(shorts|embed|v)/([^/?#]+)", parsed.path)
    if m:
        return m.group(2)
    return None


def main(html_path: Path, out_path: Path) -> None:
    parser = BookmarkParser()
    parser.feed(html_path.read_text(encoding="utf-8"))

    seen: dict[str, tuple[str, str]] = {}
    for href, title in parser.entries:
        vid = extract_video_id(href)
        if vid is None:
            continue
        if vid in seen:
            continue
        clean = re.sub(r"^\(\d+\)\s*", "", title)
        clean = re.sub(r"\s*-\s*YouTube\s*$", "", clean)
        seen[vid] = (f"https://www.youtube.com/watch?v={vid}", clean)

    lines = [f"{vid}\t{url}\t{title}" for vid, (url, title) in seen.items()]
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"「{TARGET_FOLDER}」資料夾內抽出 {len(seen)} 支獨立影片", file=sys.stderr)


if __name__ == "__main__":
    root = Path(__file__).parent
    main(root / "bookmarks_2026_4_24.html", root / "videos.tsv")
