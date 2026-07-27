"""Render an application HTML file to a print-ready A4 PDF.

Why this exists: Node/npx is broken on this machine, so the toolchain is Python +
headless Chrome. Chrome is the renderer because it is the only engine here that
does real CSS paged media, and it embeds fonts into the PDF so the file looks the
same on the recruiter's machine as it does here.

Two things it handles that a bare Chrome call does not:
  1. Images referenced with src="..." are inlined as base64 data URIs, so the PDF
     is self-contained and never silently loses the photo.
  2. Chrome is launched against a throwaway --user-data-dir. Without that it
     refuses to start whenever the user already has Chrome open, and exits 0
     having written nothing.

Usage:
    py build_pdf.py <input.html> [output.pdf]
"""

import base64
import mimetypes
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


def find_chrome() -> str:
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    raise SystemExit("No Chrome/Edge binary found - cannot render PDF.")


def inline_images(html: str, base_dir: Path) -> str:
    """Replace local image src="..." with base64 data URIs."""

    def repl(match: re.Match) -> str:
        quote, src = match.group(1), match.group(2)
        if src.startswith(("data:", "http://", "https://")):
            return match.group(0)
        path = (base_dir / src).resolve()
        if not path.exists():
            print(f"  ! image not found, left as-is: {src}")
            return match.group(0)
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        payload = base64.b64encode(path.read_bytes()).decode("ascii")
        print(f"  + inlined {src} ({path.stat().st_size // 1024} KB)")
        return f"src={quote}data:{mime};base64,{payload}{quote}"

    return re.sub(r'src=(["\'])(.*?)\1', repl, html)


def render(src_html: Path, out_pdf: Path) -> None:
    html = src_html.read_text(encoding="utf-8")
    html = inline_images(html, src_html.parent)

    tmp_dir = Path(tempfile.mkdtemp(prefix="pdfbuild_"))
    try:
        resolved = tmp_dir / "resolved.html"
        resolved.write_text(html, encoding="utf-8")

        subprocess.run(
            [
                find_chrome(),
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                f"--user-data-dir={tmp_dir / 'profile'}",
                "--no-pdf-header-footer",
                "--print-to-pdf-no-header",
                f"--print-to-pdf={out_pdf}",
                resolved.as_uri(),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )

        if not out_pdf.exists():
            raise SystemExit(f"Chrome exited cleanly but wrote no PDF: {out_pdf}")
        print(f"  -> {out_pdf.name} ({out_pdf.stat().st_size // 1024} KB)")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    src = Path(sys.argv[1]).resolve()
    if not src.exists():
        raise SystemExit(f"No such file: {src}")
    out = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else src.with_suffix(".pdf")
    print(f"Rendering {src.name}")
    render(src, out)


if __name__ == "__main__":
    main()
