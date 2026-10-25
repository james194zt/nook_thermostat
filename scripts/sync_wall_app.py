"""Copy the wall app's web files into the integration so HACS ships them.

The integration serves them at /nook/static/wall/ (the Nook panel's
Wall panels preview loads them from there). Run after changing
nspanel-thermostat/, then commit both; tests/test_wall_app_bundle.py fails
if they drift.

    python scripts/sync_wall_app.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "nspanel-thermostat"
DEST = ROOT / "custom_components" / "nook" / "www" / "wall"

# Runtime files only: no APK/Capacitor build bits, and never config.json
# (a panel's local settings, untracked).
FILES = ["index.html", "setup.html", "version.json", "devices.json"]
DIRS = ["css", "js", "assets"]


def wall_app_files() -> list[Path]:
    """Relative paths of every file the bundle should contain."""
    rel = [Path(f) for f in FILES]
    for d in DIRS:
        rel += sorted(p.relative_to(SRC) for p in (SRC / d).rglob("*") if p.is_file())
    return rel


def main() -> None:
    if DEST.exists():
        shutil.rmtree(DEST)
    for rel in wall_app_files():
        out = DEST / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SRC / rel, out)
    print(f"Copied {len(wall_app_files())} files to {DEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
