#!/usr/bin/env python3
"""Extract a CHM archive and create a browser-friendly HTML index."""

from __future__ import annotations

import argparse
import html
import os
import posixpath
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Optional
from urllib.parse import quote, unquote, urlsplit


HTML_SUFFIXES = {".htm", ".html", ".xhtml"}


class ChmToolError(RuntimeError):
    """An expected, user-facing error."""


@dataclass(frozen=True)
class Backend:
    name: str
    executable: str

    def command(self, source: Path, destination: Path) -> list[str]:
        if self.name == "extract_chmLib":
            return [self.executable, str(source), str(destination)]
        return [self.executable, "x", "-y", f"-o{destination}", str(source)]


@dataclass
class TocItem:
    """One entry from a CHM HTML Help Contents (.hhc) file."""

    label: str
    local: Optional[str] = None
    page: Optional[Path] = None
    url_suffix: str = ""
    children: list["TocItem"] = field(default_factory=list)


class _HhcParser(HTMLParser):
    """Parse the intentionally loose HTML emitted by CHM authoring tools."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[TocItem] = []
        self._list_stack: list[list[TocItem]] = []
        self._object_type: Optional[str] = None
        self._params: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        tag = tag.casefold()
        attributes = {
            key.casefold(): value or ""
            for key, value in attrs
            if key
        }
        if tag == "ul":
            if not self._list_stack:
                target = self.items
            elif self._list_stack[-1]:
                target = self._list_stack[-1][-1].children
            else:
                target = self._list_stack[-1]
            self._list_stack.append(target)
        elif tag == "object":
            self._object_type = attributes.get("type", "").casefold()
            self._params = {}
        elif tag == "param" and self._object_type is not None:
            name = attributes.get("name", "").strip().casefold()
            if name:
                self._params[name] = attributes.get("value", "").strip()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "object" and self._object_type is not None:
            if self._object_type == "text/sitemap":
                label = self._params.get("name", "").strip()
                local = self._params.get("local", "").strip() or None
                if label or local:
                    target = self._list_stack[-1] if self._list_stack else self.items
                    target.append(TocItem(label=label or local or "未命名页面", local=local))
            self._object_type = None
            self._params = {}
        elif tag == "ul" and self._list_stack:
            self._list_stack.pop()


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._inside_title = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag.casefold() == "title":
            self._inside_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "title":
            self._inside_title = False

    def handle_data(self, data: str) -> None:
        if self._inside_title:
            self._parts.append(data)

    @property
    def title(self) -> str:
        return " ".join("".join(self._parts).split())


def find_backend(requested: Optional[str] = None) -> Backend:
    """Find a supported CHM extraction command on PATH."""
    candidates = [requested] if requested else ["extract_chmLib", "7zz", "7z", "7za"]
    for candidate in candidates:
        if not candidate:
            continue
        executable = shutil.which(candidate)
        if executable:
            name = "extract_chmLib" if Path(candidate).name == "extract_chmLib" else "7zip"
            return Backend(name, executable)

    if requested:
        raise ChmToolError(f"找不到指定的解包程序：{requested}")
    raise ChmToolError(
        "找不到 CHM 解包程序。请安装 chmlib（extract_chmLib）或 7-Zip，"
        "也可以通过 --extractor 指定可执行文件。"
    )


def validate_source(source: Path) -> Path:
    source = source.expanduser().resolve()
    if not source.is_file():
        raise ChmToolError(f"CHM 文件不存在：{source}")
    try:
        with source.open("rb") as stream:
            signature = stream.read(4)
    except OSError as exc:
        raise ChmToolError(f"无法读取 CHM 文件：{exc}") from exc
    if signature != b"ITSF":
        raise ChmToolError(f"文件不是有效的 CHM（缺少 ITSF 文件头）：{source}")
    return source


def validate_destination(source: Path, destination: Path) -> Path:
    destination = destination.expanduser().resolve()
    if destination == Path(destination.anchor):
        raise ChmToolError("输出目录不能是文件系统根目录")
    try:
        source.relative_to(destination)
    except ValueError:
        pass
    else:
        raise ChmToolError("输出目录不能包含输入 CHM 文件")
    return destination


def run_extractor(backend: Backend, source: Path, destination: Path) -> None:
    result = subprocess.run(
        backend.command(source, destination),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        details = result.stdout.strip()
        suffix = f"\n{details}" if details else ""
        raise ChmToolError(f"CHM 解包失败（退出码 {result.returncode}）{suffix}")


def validate_extracted_tree(root: Path) -> None:
    """Reject links and paths that resolve outside the staging directory."""
    resolved_root = root.resolve()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ChmToolError(f"解包结果包含不安全的符号链接：{path.relative_to(root)}")
        try:
            path.resolve().relative_to(resolved_root)
        except ValueError as exc:
            raise ChmToolError(f"解包路径越界：{path}") from exc


def discover_html(root: Path, excluded: Optional[Path] = None) -> list[Path]:
    pages = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in HTML_SUFFIXES:
            continue
        relative = path.relative_to(root)
        if excluded is not None and relative == excluded:
            continue
        pages.append(relative)
    return sorted(pages, key=lambda item: item.as_posix().casefold())


def decode_project_file(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    for encoding in ("utf-8-sig", "gb18030", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def metadata_files(root: Path, suffix: str) -> list[Path]:
    return sorted(
        (path for path in root.rglob("*") if path.is_file() and path.suffix.casefold() == suffix),
        key=lambda path: path.relative_to(root).as_posix().casefold(),
    )


def normalized_archive_path(base: PurePosixPath, raw_path: str) -> Optional[str]:
    value = unquote(raw_path.strip().strip('"\'')).replace("\\", "/").lstrip("/")
    normalized = posixpath.normpath((base / value).as_posix())
    if normalized == ".." or normalized.startswith("../"):
        return None
    return normalized.removeprefix("./")


def find_configured_default_topic(root: Path, pages: list[Path]) -> Optional[Path]:
    page_by_name = {page.as_posix().casefold(): page for page in pages}
    for project in metadata_files(root, ".hhp"):
        try:
            content = decode_project_file(project.read_bytes())
        except OSError:
            continue
        for raw_line in content.splitlines():
            key, separator, value = raw_line.partition("=")
            if separator and key.strip().casefold() == "default topic":
                project_relative = PurePosixPath(project.parent.relative_to(root).as_posix())
                candidate = normalized_archive_path(project_relative, value)
                if candidate and candidate.casefold() in page_by_name:
                    return page_by_name[candidate.casefold()]
                candidate = normalized_archive_path(PurePosixPath(), value)
                if candidate and candidate.casefold() in page_by_name:
                    return page_by_name[candidate.casefold()]
    return None


def find_default_topic(root: Path, pages: list[Path]) -> Optional[Path]:
    configured = find_configured_default_topic(root, pages)
    if configured is not None:
        return configured
    return pages[0] if pages else None


def find_contents_file(root: Path) -> Optional[Path]:
    contents_files = metadata_files(root, ".hhc")
    if not contents_files:
        return None

    contents_by_name = {
        path.relative_to(root).as_posix().casefold(): path
        for path in contents_files
    }
    for project in metadata_files(root, ".hhp"):
        try:
            content = decode_project_file(project.read_bytes())
        except OSError:
            continue
        for raw_line in content.splitlines():
            key, separator, value = raw_line.partition("=")
            if not separator or key.strip().casefold() != "contents file":
                continue
            project_relative = PurePosixPath(project.parent.relative_to(root).as_posix())
            for base in (project_relative, PurePosixPath()):
                candidate = normalized_archive_path(base, value)
                if candidate and candidate.casefold() in contents_by_name:
                    return contents_by_name[candidate.casefold()]
    return contents_files[0]


def resolve_toc_pages(root: Path, contents_file: Path, items: list[TocItem], pages: list[Path]) -> set[Path]:
    page_by_name = {page.as_posix().casefold(): page for page in pages}
    contents_relative = PurePosixPath(contents_file.parent.relative_to(root).as_posix())
    referenced: set[Path] = set()

    def resolve(item: TocItem) -> None:
        if item.local:
            local = item.local.strip()
            # Some authoring tools store ms-its:/mk:@MSITStore: URLs in Local.
            if "::" in local:
                local = local.split("::", 1)[1]
            parsed = urlsplit(local.replace("\\", "/"))
            if not parsed.scheme or parsed.scheme.casefold() == "file":
                for base in (contents_relative, PurePosixPath()):
                    candidate = normalized_archive_path(base, parsed.path)
                    if candidate and candidate.casefold() in page_by_name:
                        item.page = page_by_name[candidate.casefold()]
                        suffix = f"?{parsed.query}" if parsed.query else ""
                        if parsed.fragment:
                            suffix += f"#{quote(unquote(parsed.fragment), safe='/:@-._~!$&()*+,;=')}"
                        item.url_suffix = suffix
                        referenced.add(item.page)
                        break
        for child in item.children:
            resolve(child)

    for item in items:
        resolve(item)
    return referenced


def load_contents(root: Path, pages: list[Path]) -> tuple[list[TocItem], set[Path]]:
    contents_file = find_contents_file(root)
    if contents_file is None:
        return [], set()
    try:
        content = decode_project_file(contents_file.read_bytes())
    except OSError:
        return [], set()
    parser = _HhcParser()
    try:
        parser.feed(content)
        parser.close()
    except (AssertionError, ValueError):
        return [], set()
    if not parser.items:
        return [], set()
    referenced = resolve_toc_pages(root, contents_file, parser.items, pages)
    return parser.items, referenced


def first_toc_page(items: list[TocItem]) -> Optional[Path]:
    for item in items:
        if item.page is not None:
            return item.page
        child_page = first_toc_page(item.children)
        if child_page is not None:
            return child_page
    return None


def page_label(root: Path, page: Path) -> str:
    try:
        content = decode_project_file((root / page).read_bytes())
    except OSError:
        return page.as_posix()
    parser = _TitleParser()
    try:
        parser.feed(content)
        parser.close()
    except (AssertionError, ValueError):
        return page.as_posix()
    return parser.title or page.as_posix()


def url_for(path: Path) -> str:
    return "/".join(quote(part) for part in path.parts)


def render_toc_items(items: list[TocItem], *, level: int = 0) -> str:
    rendered: list[str] = []
    indent = "        " + "  " * level
    for item in items:
        label = html.escape(item.label)
        if item.page is not None:
            href = html.escape(url_for(item.page) + item.url_suffix, quote=True)
            title = html.escape(item.page.as_posix(), quote=True)
            content = f'<a href="{href}" target="viewer" title="{title}">{label}</a>'
        else:
            content = f'<span class="toc-label">{label}</span>'
        if item.children:
            children = render_toc_items(item.children, level=level + 1)
            rendered.append(f"{indent}<li>{content}\n{indent}  <ul>\n{children}\n{indent}  </ul>\n{indent}</li>")
        else:
            rendered.append(f"{indent}<li>{content}</li>")
    return "\n".join(rendered)


def render_page_links(root: Path, pages: list[Path], *, level: int = 0) -> str:
    indent = "        " + "  " * level
    return "\n".join(
        '{indent}<li><a href="{url}" target="viewer" title="{title}">{label}</a></li>'.format(
            indent=indent,
            url=html.escape(url_for(page), quote=True),
            title=html.escape(page.as_posix(), quote=True),
            label=html.escape(page_label(root, page)),
        )
        for page in pages
    )


def create_index(root: Path, requested_name: str = "index.html") -> Path:
    # Generated links are root-relative, so the index must live at the root.
    index_path = Path(requested_name)
    if index_path.is_absolute() or len(index_path.parts) != 1 or index_path.parts[0] == "..":
        raise ChmToolError("索引文件名必须是输出目录根目录下的单个文件名")

    destination = root / index_path
    if destination.exists():
        index_path = Path("chmtool-index.html")
        destination = root / index_path
        counter = 2
        while destination.exists():
            index_path = Path(f"chmtool-index-{counter}.html")
            destination = root / index_path
            counter += 1

    pages = discover_html(root)
    if not pages:
        raise ChmToolError("CHM 已解包，但其中没有找到 HTML 文件")
    toc_items, referenced_pages = load_contents(root, pages)
    configured_topic = find_configured_default_topic(root, pages)
    default_topic = configured_topic or first_toc_page(toc_items) or pages[0]
    if toc_items:
        links = render_toc_items(toc_items)
        remaining_pages = [page for page in pages if page not in referenced_pages]
        if remaining_pages:
            links += (
                '\n        <li class="section-title">未在 CHM 目录中的页面</li>\n'
                + render_page_links(root, remaining_pages)
            )
    else:
        links = render_page_links(root, pages)
    initial_url = html.escape(url_for(default_topic), quote=True) if default_topic else "about:blank"
    title = html.escape(root.name)
    document = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} - CHM 内容</title>
  <style>
    :root {{ --sidebar-width: 28vw; --splitter-width: 9px; }}
    * {{ box-sizing: border-box; }}
    html, body {{ height: 100%; margin: 0; font-family: system-ui, sans-serif; color: #1f2937; }}
    body {{ display: grid; grid-template-columns: clamp(240px, var(--sidebar-width), calc(100vw - 360px)) var(--splitter-width) minmax(0, 1fr); overflow: hidden; }}
    body.is-resizing {{ cursor: col-resize; user-select: none; }}
    body.is-resizing iframe {{ pointer-events: none; }}
    nav {{ min-width: 0; padding: 16px; background: #f8fafc; overflow: auto; }}
    h1 {{ margin: 0 0 12px; font-size: 18px; }}
    input {{ width: 100%; padding: 8px 10px; border: 1px solid #9ca3af; border-radius: 6px; }}
    ul {{ margin: 0; padding-left: 18px; list-style: none; }}
    #pages {{ padding-left: 0; }}
    li {{ margin: 7px 0; overflow-wrap: anywhere; }}
    nav a {{ display: block; margin-left: -8px; padding: 5px 8px; border-radius: 6px; color: #374151; text-decoration: none; transition: color 120ms ease, background-color 120ms ease; }}
    nav a:hover {{ color: #0369a1; background: #f0f9ff; }}
    nav a:focus {{ color: #0369a1; background: #e0f2fe; outline: none; }}
    nav a:focus-visible {{ box-shadow: 0 0 0 2px #38bdf8; }}
    nav a.is-active {{ color: #075985; background: #dbeafe; font-weight: 600; }}
    .toc-label {{ color: #374151; font-weight: 600; }}
    .section-title {{ margin-top: 18px; padding-top: 12px; border-top: 1px solid #d1d5db; color: #6b7280; font-size: 13px; font-weight: 600; }}
    #splitter {{ position: relative; z-index: 2; width: var(--splitter-width); height: 100%; cursor: col-resize; touch-action: none; background: #e5e7eb; outline: none; }}
    #splitter::before {{ content: ""; position: absolute; inset: 0 3px; background: #cbd5e1; transition: inset 120ms ease, background-color 120ms ease; }}
    #splitter:hover::before, #splitter:focus-visible::before, body.is-resizing #splitter::before {{ inset: 0 2px; background: #0284c7; }}
    #splitter:focus-visible {{ box-shadow: inset 0 0 0 2px #7dd3fc; }}
    iframe {{ min-width: 0; width: 100%; height: 100%; border: 0; background: white; }}
    @media (max-width: 720px) {{
      body {{ grid-template-columns: 1fr; grid-template-rows: 42% 58%; }}
      nav {{ border-right: 0; border-bottom: 1px solid #d1d5db; }}
      #splitter {{ display: none; }}
    }}
  </style>
</head>
<body>
  <nav aria-label="CHM 页面导航">
    <h1>{title}</h1>
    <input id="filter" type="search" placeholder="筛选页面…" aria-label="筛选页面">
    <ul id="pages">
{links}
    </ul>
  </nav>
  <div id="splitter" role="separator" aria-label="调整导航栏宽度" aria-controls="viewer" aria-orientation="vertical" aria-valuemin="240" aria-valuenow="0" tabindex="0" title="拖动调整宽度；双击恢复默认"></div>
  <iframe id="viewer" name="viewer" src="{initial_url}" title="CHM 页面内容"></iframe>
  <script>
    const filter = document.querySelector('#filter');
    const splitter = document.querySelector('#splitter');
    const viewer = document.querySelector('#viewer');
    const navigationLinks = Array.from(document.querySelectorAll('#pages a'));
    const SIDEBAR_STORAGE_KEY = 'chmtool-sidebar-width';
    const DEFAULT_SIDEBAR_RATIO = 0.28;
    const MIN_SIDEBAR_WIDTH = 240;
    const MIN_CONTENT_WIDTH = 360;
    const KEYBOARD_STEP = 20;
    let sidebarWidth = 0;

    filter.addEventListener('input', () => {{
      const query = filter.value.trim().toLocaleLowerCase();
      document.querySelectorAll('#pages li').forEach((item) => {{
        item.hidden = !item.textContent.toLocaleLowerCase().includes(query);
      }});
    }});

    function setActiveLink(activeLink) {{
      navigationLinks.forEach((link) => {{
        const isActive = link === activeLink;
        link.classList.toggle('is-active', isActive);
        if (isActive) link.setAttribute('aria-current', 'page');
        else link.removeAttribute('aria-current');
      }});
    }}

    navigationLinks.forEach((link) => {{
      link.addEventListener('click', () => setActiveLink(link));
    }});
    const initialLink = navigationLinks.find(
      (link) => link.getAttribute('href') === viewer.getAttribute('src')
    );
    if (initialLink) setActiveLink(initialLink);

    function sidebarBounds() {{
      return {{
        min: MIN_SIDEBAR_WIDTH,
        max: Math.max(MIN_SIDEBAR_WIDTH, window.innerWidth - MIN_CONTENT_WIDTH - splitter.offsetWidth),
      }};
    }}

    function setSidebarWidth(width, persist = true) {{
      const bounds = sidebarBounds();
      sidebarWidth = Math.round(Math.min(bounds.max, Math.max(bounds.min, width)));
      document.documentElement.style.setProperty('--sidebar-width', `${{sidebarWidth}}px`);
      splitter.setAttribute('aria-valuemin', bounds.min);
      splitter.setAttribute('aria-valuemax', bounds.max);
      splitter.setAttribute('aria-valuenow', sidebarWidth);
      if (persist) {{
        try {{ localStorage.setItem(SIDEBAR_STORAGE_KEY, String(sidebarWidth)); }} catch (_) {{}}
      }}
    }}

    function resetSidebarWidth(persist = true) {{
      setSidebarWidth(window.innerWidth * DEFAULT_SIDEBAR_RATIO, persist);
    }}

    let savedWidth = NaN;
    try {{ savedWidth = Number(localStorage.getItem(SIDEBAR_STORAGE_KEY)); }} catch (_) {{}}
    if (Number.isFinite(savedWidth) && savedWidth > 0) {{
      setSidebarWidth(savedWidth, false);
    }} else {{
      resetSidebarWidth(false);
    }}

    splitter.addEventListener('pointerdown', (event) => {{
      if (event.button !== 0) return;
      event.preventDefault();
      splitter.setPointerCapture(event.pointerId);
      document.body.classList.add('is-resizing');
    }});
    splitter.addEventListener('pointermove', (event) => {{
      if (splitter.hasPointerCapture(event.pointerId)) setSidebarWidth(event.clientX);
    }});
    function stopResizing(event) {{
      if (splitter.hasPointerCapture(event.pointerId)) splitter.releasePointerCapture(event.pointerId);
      document.body.classList.remove('is-resizing');
    }}
    splitter.addEventListener('pointerup', stopResizing);
    splitter.addEventListener('pointercancel', stopResizing);
    splitter.addEventListener('dblclick', () => resetSidebarWidth());
    splitter.addEventListener('keydown', (event) => {{
      const bounds = sidebarBounds();
      let nextWidth = sidebarWidth;
      if (event.key === 'ArrowLeft') nextWidth -= KEYBOARD_STEP;
      else if (event.key === 'ArrowRight') nextWidth += KEYBOARD_STEP;
      else if (event.key === 'Home') nextWidth = bounds.min;
      else if (event.key === 'End') nextWidth = bounds.max;
      else return;
      event.preventDefault();
      setSidebarWidth(nextWidth);
    }});
    window.addEventListener('resize', () => setSidebarWidth(sidebarWidth, false));
  </script>
</body>
</html>
"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(document)
    return index_path


def extract_chm(
    source: Path,
    destination: Path,
    *,
    overwrite: bool = False,
    create_html_index: bool = True,
    index_name: str = "index.html",
    extractor: Optional[str] = None,
) -> tuple[Backend, Optional[Path], int]:
    source = validate_source(source)
    destination = validate_destination(source, destination)
    backend = find_backend(extractor)

    if destination.exists() and not overwrite:
        if not destination.is_dir():
            raise ChmToolError(f"输出路径已存在且不是目录：{destination}（如需替换，请使用 --overwrite）")
        if any(destination.iterdir()):
            raise ChmToolError(f"输出目录非空：{destination}（如需替换，请使用 --overwrite）")

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=destination.parent))
    try:
        run_extractor(backend, source, staging)
        validate_extracted_tree(staging)
        page_count = len(discover_html(staging))
        generated_index = create_index(staging, index_name) if create_html_index else None

        if destination.exists():
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        staging.replace(destination)
        return backend, generated_index, page_count
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="解包 CHM 文件，并生成一个可在浏览器中打开的 HTML 导航页。"
    )
    parser.add_argument("chm_file", type=Path, help="要处理的 .chm 文件")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="输出目录（默认：CHM 文件同目录下的 <文件名>_html）",
    )
    parser.add_argument("--overwrite", action="store_true", help="替换已有的非空输出目录")
    parser.add_argument("--no-index", action="store_true", help="只解包，不生成导航页")
    parser.add_argument("--index-name", default="index.html", help="导航页文件名，不能包含路径（默认：index.html）")
    parser.add_argument(
        "--extractor",
        help="指定解包程序名称或路径（extract_chmLib、7zz、7z 或 7za）",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    source = args.chm_file.expanduser()
    output = args.output or source.with_name(f"{source.stem}_html")
    try:
        backend, index_path, page_count = extract_chm(
            source,
            output,
            overwrite=args.overwrite,
            create_html_index=not args.no_index,
            index_name=args.index_name,
            extractor=args.extractor,
        )
    except ChmToolError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    output = output.expanduser().resolve()
    print(f"完成：使用 {backend.name} 解包了 {page_count} 个 HTML 页面")
    print(f"输出目录：{output}")
    if index_path:
        print(f"导航页面：{output / index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
