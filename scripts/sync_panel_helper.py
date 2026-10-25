#!/usr/bin/env python3
"""Copy a built Nook Panel Helper APK into the integration, so Nook can update panels.

Usage: python3 scripts/sync_panel_helper.py <path to app-release.apk> <output-metadata.json>
Writes custom_components/nook/www/panel-helper/{neat-panel-helper.apk,version.json}.
"""

import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "custom_components" / "nook" / "www" / "panel-helper"


def main() -> None:
    apk, meta_path = Path(sys.argv[1]), Path(sys.argv[2])
    meta = json.loads(meta_path.read_text())
    element = meta["elements"][0]
    DEST.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(apk, DEST / "neat-panel-helper.apk")
    info = {
        "version": element["versionName"],
        "version_code": int(element["versionCode"]),
        "sha256": hashlib.sha256((DEST / "neat-panel-helper.apk").read_bytes()).hexdigest(),
    }
    (DEST / "version.json").write_text(json.dumps(info, indent=2) + "\n")
    print(f"panel helper {info['version']} ({info['version_code']}) -> {DEST}")


if __name__ == "__main__":
    main()
