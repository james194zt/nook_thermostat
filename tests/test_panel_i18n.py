"""The sidebar panel's labels all come from www/i18n/en.json (plain Python, no HA needed).

Checks: every label the panel asks for exists, nothing in the file is unused, and no
English is left written straight into the panel code (so a translation is just another
JSON file).
"""

import json
import re
from pathlib import Path

WWW = Path(__file__).resolve().parent.parent / "custom_components" / "nook" / "www"
JS = (WWW / "nook-panel.js").read_text(encoding="utf-8")
EN = json.loads((WWW / "i18n" / "en.json").read_text(encoding="utf-8"))
KEY = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")

# Text that isn't a label: brand/product names, units, CSS/HTML bits, ids, HA terms.
ALLOWED_TEXT = {
    "Nook",  # HA's device-name prefix stripped from entity names (_entityName)
    "notify.",  # start of an HA service id: <code>notify.mobile_app_…</code>
    "hallway",  # example device ID in the wall panel dialog's placeholder
}


def code() -> str:
    """The panel JS without its stylesheet and comments."""
    start = JS.index("const STYLES = `")
    end = JS.index("\n`;", start)
    text = JS[:start] + JS[end + 3 :]
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"(?m)^\s*//.*$", "", text)
    return re.sub(r"(?m)\s//\s.*$", "", text)


CODE = code()


def strip_interpolations(text: str) -> str:
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"\$\{[^{}`]*\}", "", text)
    return text


def literal_keys() -> set[str]:
    # Key-shaped quoted strings (no spaces, so quotes can't pair up across HTML attributes).
    return set(re.findall(r"\"([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+)\"", CODE))


def dynamic_prefixes() -> set[str]:
    return set(re.findall(r"\bt\(`([a-z0-9_.]+)\$\{", CODE))


def test_language_file_is_flat_strings():
    assert EN, "en.json is empty"
    for key, value in EN.items():
        assert KEY.match(key), f"odd key {key!r}"
        assert isinstance(value, str), f"{key} is not a string"


def test_every_label_used_exists():
    namespaces = {k.split(".")[0] for k in EN}
    missing = []
    for key in literal_keys():
        if key.split(".")[0] not in namespaces or key in EN:
            continue
        if f"{key}.one" in EN and f"{key}.other" in EN:  # tn()
            continue
        missing.append(key)
    assert not missing, f"used but not in en.json: {sorted(missing)}"


def test_plural_labels_have_both_forms():
    for base in re.findall(r"\btn\(\"([^\"]+)\"", CODE):
        assert f"{base}.one" in EN and f"{base}.other" in EN, f"{base} needs .one and .other"


def test_dynamic_labels_exist():
    """Labels built from ids (t(`nav.${id}`) etc.) exist for every id the panel uses."""
    expected = {
        "nav.": ["overview", "energy", "schedule", "wall_panels", "settings"],
        "day.": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
        "day_short.": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
        "month.": ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"],
        "month_short.": ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"],
        "wall.shape.": ["square", "tall", "landscape", "wide", "nspanel_pro"],
        "preset.": ["none", "eco", "boost", "away"],
        "room.pill.trv_": ["open", "off", "idle"],
        "room_dlg.hold_ends.": ["house_change", "block_change", "manual"],
        "schedule.axis.": ["1a", "3a", "5a", "7a", "9a", "11a", "noon", "1p", "3p", "5p", "7p", "9p", "11p"],
        "helper.toast.": ["hide.on", "hide.off", "cpu.on", "cpu.off", "wifi.on", "wifi.off"],
    }
    for prefix, ids in expected.items():
        for item in ids:
            assert f"{prefix}{item}" in EN, f"missing {prefix}{item}"
    for shape in expected["wall.shape."]:
        assert f"wall.shape.{shape}.hint" in EN
    for field in re.findall(r"\{ key: \"([a-z_]+)\", kind:", CODE):
        assert f"kiosk.field.{field}" in EN and f"kiosk.field.{field}.desc" in EN, field


def test_no_unused_labels():
    used = literal_keys()
    plural_bases = set(re.findall(r"\btn\(\"([^\"]+)\"", CODE))
    prefixes = dynamic_prefixes() | {"kiosk.field.", "wall.shape."}
    unused = [
        key
        for key in EN
        if key not in used
        and not any(key.startswith(p) for p in prefixes)
        and not any(key in (f"{b}.one", f"{b}.other") for b in plural_bases)
    ]
    assert not unused, f"in en.json but never used: {sorted(unused)}"


def leftovers() -> list[str]:
    found = []
    # Text between tags in the HTML templates.
    for raw in re.findall(r">([^<>\n]+)<", CODE):
        text = strip_interpolations(raw).strip()
        if re.search(r"[;{}=`]|=>", text):  # JavaScript ("a => b", "x < y"), not markup
            continue
        if re.search(r"[A-Za-z]{2,}", text):
            found.append(text)
    # Tooltips, aria labels and placeholders written in as text.
    for attr in re.findall(r"(?:title|aria-label|placeholder)=\"([^\"$]*[A-Za-z]{2,}[^\"$]*)\"", CODE):
        found.append(attr)
    # Quoted phrases: two or more words starting with a capital (e.g. "Room order saved").
    for phrase in re.findall(r"[\"`']([A-Z][a-z']+ [a-z][^\"`'\n$]*)[\"`']", CODE):
        found.append(phrase)
    return [f for f in found if f not in ALLOWED_TEXT]


def test_no_english_left_in_the_panel_code():
    assert not leftovers(), f"English still in the panel code: {leftovers()}"
