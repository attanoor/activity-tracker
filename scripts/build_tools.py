"""Helpers for build-downloads.ps1:  python build_tools.py icon <out.ico> | zip-extension <src> <out.zip> |
manifest <downloads dir> <key> <file> <version>"""

import hashlib
import json
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path


def icon(out: str) -> None:
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((8, 8, 248, 248), fill="#12b76a")
    d.rectangle((84, 68, 172, 100), fill="white")
    d.rectangle((112, 68, 144, 192), fill="white")
    img.save(out, sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])


def zip_extension(src: str, out: str) -> None:
    root = Path(src)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(root.rglob("*")):
            if p.is_file():
                z.write(p, Path("activity-tracker-extension") / p.relative_to(root))


def manifest(downloads: str, key: str, file: str, version: str) -> None:
    d = Path(downloads)
    path = d / file
    m_path = d / "manifest.json"
    try:
        m = json.loads(m_path.read_text())
    except (OSError, ValueError):
        m = {}
    m[key] = {"file": file, "version": version, "size": path.stat().st_size,
              "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "built_at": datetime.now(UTC).isoformat(timespec="seconds")}
    m_path.write_text(json.dumps(m, indent=2))


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    {"icon": icon, "zip-extension": zip_extension, "manifest": manifest}[cmd](*args)
