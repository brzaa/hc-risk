from __future__ import annotations

import argparse
import html
import re
import textwrap
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import mistune


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSS = """
@namespace epub "http://www.idpf.org/2007/ops";

body {
  font-family: serif;
  line-height: 1.6;
  margin: 5%;
  color: #1f1a17;
}

h1, h2, h3, h4 {
  font-family: sans-serif;
  line-height: 1.25;
  page-break-after: avoid;
}

h1 {
  font-size: 1.9em;
  margin: 0 0 0.4em;
}

h2 {
  font-size: 1.5em;
  margin-top: 1.8em;
  padding-bottom: 0.25em;
  border-bottom: 1px solid #d8d1c7;
}

h3 {
  font-size: 1.2em;
  margin-top: 1.4em;
}

h4 {
  font-size: 1.05em;
  margin-top: 1.1em;
}

p, li {
  orphans: 2;
  widows: 2;
}

ul, ol {
  padding-left: 1.2em;
}

pre {
  white-space: pre-wrap;
  word-break: break-word;
  overflow-wrap: anywhere;
  background: #f6f1eb;
  border: 1px solid #ddd4c8;
  border-radius: 0.35em;
  padding: 0.9em;
  font-size: 0.88em;
}

code {
  font-family: monospace;
  font-size: 0.92em;
}

p code, li code, td code, th code {
  background: #f3eee7;
  padding: 0.08em 0.28em;
  border-radius: 0.25em;
}

.math-inline {
  font-family: monospace;
  background: #f3eee7;
  padding: 0.08em 0.28em;
  border-radius: 0.25em;
}

table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  margin: 1em 0;
  font-size: 0.9em;
}

th, td {
  border: 1px solid #ddd4c8;
  padding: 0.42em 0.5em;
  text-align: left;
  vertical-align: top;
  overflow-wrap: anywhere;
}

thead th {
  background: #f2ece3;
}

hr {
  border: 0;
  border-top: 1px solid #ddd4c8;
  margin: 1.5em 0;
}

blockquote {
  margin: 1em 0;
  padding-left: 0.8em;
  border-left: 3px solid #ddd4c8;
  color: #4c433a;
}

.title-page {
  text-align: center;
  margin-top: 25%;
}

.title-page p {
  color: #5c5349;
}

.toc ol {
  padding-left: 1.2em;
}
"""


@dataclass
class Chapter:
    title: str
    filename: str
    xhtml: str


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "chapter"


def _derive_title(markdown_path: Path, text: str) -> str:
    heading_match = re.search(r"(?m)^##\s+(.+?)\s*$", text)
    if heading_match:
        heading = heading_match.group(1).strip()
        cleaned = re.sub(r"^\d+(?:\.\d+)?\s+", "", heading)
        if cleaned:
            return cleaned
    return markdown_path.stem.replace("-", " ").title()


def _clean_math(expr: str) -> str:
    cleaned = expr.strip()
    replacements = {
        r"\times": "×",
        r"\approx": "≈",
        r"\div": "÷",
        r"\ln": "ln",
        r"\max": "max",
        r"\sum": "sum",
        r"\left": "",
        r"\right": "",
        r"\%": "%",
        r"\>": ">",
    }
    for source, target in replacements.items():
        cleaned = cleaned.replace(source, target)
    fraction_pattern = re.compile(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}")
    while True:
        updated = fraction_pattern.sub(r"(\1)/(\2)", cleaned)
        if updated == cleaned:
            break
        cleaned = updated
    cleaned = re.sub(r"_\{([^{}]+)\}", r"_\1", cleaned)
    cleaned = re.sub(r"\^\{([^{}]+)\}", r"^\1", cleaned)
    cleaned = cleaned.replace("{", "").replace("}", "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return html.escape(cleaned).replace("|", "&#124;")


def _normalize_markdown(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = re.sub(
        r"(?m)^([A-Z]\.\d+\s+.+)$",
        r"### \1",
        text,
    )

    def replace_display(match: re.Match[str]) -> str:
        return f'<span class="math-inline">{_clean_math(match.group(1))}</span>'

    text = re.sub(r"\$\$(.+?)\$\$", replace_display, text, flags=re.DOTALL)

    inline_pattern = re.compile(r"(?<!\$)\$([^\n$]+?)\$(?!\$)")

    def replace_inline(match: re.Match[str]) -> str:
        inner = match.group(1)
        if any(token in inner for token in ("\\", "_", "^", "{", "}")):
            return f'<span class="math-inline">{_clean_math(inner)}</span>'
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_\\^{}]*", inner.strip()):
            return f'<span class="math-inline">{_clean_math(inner)}</span>'
        return match.group(0)

    text = inline_pattern.sub(replace_inline, text)

    lines = text.splitlines()
    normalized_lines: list[str] = []
    for line in lines:
        if line.startswith("|") and normalized_lines:
            previous = normalized_lines[-1]
            if previous.strip() and not previous.lstrip().startswith("|"):
                normalized_lines.append("")
        normalized_lines.append(line)
    return "\n".join(normalized_lines)


def _split_chapters(text: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", text))
    if not matches:
        return [("Document", text.strip())]

    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        title = match.group(1).strip()
        sections.append((title, chunk))
    return sections


def _wrap_xhtml(title: str, body_html: str, book_title: str) -> str:
    return textwrap.dedent(
        f"""\
        <?xml version="1.0" encoding="utf-8"?>
        <html xmlns="http://www.w3.org/1999/xhtml" lang="en" xml:lang="en">
          <head>
            <title>{html.escape(title)}</title>
            <link rel="stylesheet" type="text/css" href="styles.css"/>
          </head>
          <body>
        {body_html}
          </body>
        </html>
        """
    ).lstrip()


def _render_chapters(text: str, title: str) -> list[Chapter]:
    renderer = mistune.create_markdown(plugins=["table"], escape=False)
    chapters: list[Chapter] = []
    used_filenames: set[str] = set()

    for index, (chapter_title, chunk) in enumerate(_split_chapters(text), start=1):
        stem = f"chapter-{index:02d}-{_slugify(chapter_title)}"
        filename = f"{stem}.xhtml"
        while filename in used_filenames:
            stem = f"{stem}-{index}"
            filename = f"{stem}.xhtml"
        used_filenames.add(filename)
        body_html = renderer(chunk)
        body_html = body_html.replace("<br>", "<br />")
        chapters.append(Chapter(chapter_title, filename, _wrap_xhtml(chapter_title, body_html, title)))
    return chapters


def _title_page_xhtml(title: str, source_name: str) -> str:
    body = textwrap.dedent(
        f"""\
        <section class="title-page">
          <h1>{html.escape(title)}</h1>
          <p>EPUB export generated from {html.escape(source_name)}</p>
        </section>
        """
    )
    return _wrap_xhtml(title, body, title)


def _nav_xhtml(title: str, chapters: list[Chapter]) -> str:
    items = "\n".join(
        f'          <li><a href="{html.escape(chapter.filename)}">{html.escape(chapter.title)}</a></li>'
        for chapter in chapters
    )
    body = textwrap.dedent(
        f"""\
        <section class="toc">
          <h1>Contents</h1>
          <nav xmlns:epub="http://www.idpf.org/2007/ops" epub:type="toc" id="toc">
            <ol>
        {items}
            </ol>
          </nav>
        </section>
        """
    )
    return _wrap_xhtml("Contents", body, title)


def _content_opf(book_id: str, title: str, chapters: list[Chapter]) -> str:
    modified = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = [
        '    <item id="toc" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        '    <item id="titlepage" href="title.xhtml" media-type="application/xhtml+xml"/>',
        '    <item id="css" href="styles.css" media-type="text/css"/>',
    ]
    spine = [
        '    <itemref idref="titlepage"/>',
        '    <itemref idref="toc"/>',
    ]
    for index, chapter in enumerate(chapters, start=1):
        item_id = f"chapter{index}"
        manifest.append(
            f'    <item id="{item_id}" href="{html.escape(chapter.filename)}" media-type="application/xhtml+xml"/>'
        )
        spine.append(f'    <itemref idref="{item_id}"/>')

    return textwrap.dedent(
        f"""\
        <?xml version="1.0" encoding="utf-8"?>
        <package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
          <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
            <dc:identifier id="bookid">urn:uuid:{book_id}</dc:identifier>
            <dc:title>{html.escape(title)}</dc:title>
            <dc:language>en</dc:language>
            <meta property="dcterms:modified">{modified}</meta>
          </metadata>
          <manifest>
        {"\n".join(manifest)}
          </manifest>
          <spine toc="ncx">
        {"\n".join(spine)}
          </spine>
        </package>
        """
    ).lstrip()


def _toc_ncx(book_id: str, title: str, chapters: list[Chapter]) -> str:
    nav_points = [
        textwrap.dedent(
            f"""\
              <navPoint id="navPoint-{index}" playOrder="{index}">
                <navLabel><text>{html.escape(chapter.title)}</text></navLabel>
                <content src="{html.escape(chapter.filename)}"/>
              </navPoint>
            """
        ).strip()
        for index, chapter in enumerate(chapters, start=1)
    ]
    return textwrap.dedent(
        f"""\
        <?xml version="1.0" encoding="utf-8"?>
        <ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
          <head>
            <meta name="dtb:uid" content="urn:uuid:{book_id}"/>
            <meta name="dtb:depth" content="1"/>
            <meta name="dtb:totalPageCount" content="0"/>
            <meta name="dtb:maxPageNumber" content="0"/>
          </head>
          <docTitle><text>{html.escape(title)}</text></docTitle>
          <navMap>
        {"\n".join(nav_points)}
          </navMap>
        </ncx>
        """
    ).lstrip()


def build_epub(markdown_path: Path, output_path: Path, title: str | None = None) -> Path:
    source_text = markdown_path.read_text(encoding="utf-8")
    book_title = title or _derive_title(markdown_path, source_text)
    normalized = _normalize_markdown(source_text)
    chapters = _render_chapters(normalized, book_title)
    book_id = str(uuid.uuid4())

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        epub.writestr(
            "META-INF/container.xml",
            textwrap.dedent(
                """\
                <?xml version="1.0" encoding="utf-8"?>
                <container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
                  <rootfiles>
                    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
                  </rootfiles>
                </container>
                """
            ).lstrip(),
        )
        epub.writestr("OEBPS/styles.css", DEFAULT_CSS)
        epub.writestr("OEBPS/title.xhtml", _title_page_xhtml(book_title, markdown_path.name))
        epub.writestr("OEBPS/nav.xhtml", _nav_xhtml(book_title, chapters))
        epub.writestr("OEBPS/content.opf", _content_opf(book_id, book_title, chapters))
        epub.writestr("OEBPS/toc.ncx", _toc_ncx(book_id, book_title, chapters))
        for chapter in chapters:
            epub.writestr(f"OEBPS/{chapter.filename}", chapter.xhtml)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert Markdown to a reader-friendly EPUB.")
    parser.add_argument("markdown", type=Path, help="Path to the source Markdown file.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output EPUB path. Defaults to the Markdown filename with an .epub extension.",
    )
    parser.add_argument("--title", type=str, help="Book title to use in EPUB metadata.")
    args = parser.parse_args()

    markdown_path = args.markdown.resolve()
    output_path = (args.output or markdown_path.with_suffix(".epub")).resolve()
    if not markdown_path.exists():
        raise SystemExit(f"Markdown file not found: {markdown_path}")

    build_epub(markdown_path, output_path, args.title)
    print(output_path)


if __name__ == "__main__":
    main()
