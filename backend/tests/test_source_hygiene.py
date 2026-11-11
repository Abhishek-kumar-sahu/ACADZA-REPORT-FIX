"""Source files must not contain control or invisible characters.

Twice in this project a tooling step silently changed source text: escape sequences became literal
zero-width characters, and a regex `\\b` became a backspace (0x08), making a danger pattern match
nothing while every test still passed. Data lives in data/ (not scanned); code and docs must be clean.
"""
from backend.app.config import ROOT

FORBIDDEN = {i for i in range(32) if i not in (9, 10, 13)} | {0x7F, 0xA0, 0x200B, 0x200C, 0x200D,
                                                               0x2060, 0xFEFF}
SUFFIXES = {".py", ".md", ".json", ".toml", ".txt", ".yaml", ".yml", ".html", ".css", ".js", ".example"}
SKIP_DIRS = {".venv", "data", "__pycache__", ".pytest_cache", "node_modules", ".git"}


def test_no_control_or_invisible_characters():
    offenders = []
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.suffix not in SUFFIXES or SKIP_DIRS & set(p.relative_to(ROOT).parts):
            continue
        text = p.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            bad = sorted({hex(ord(c)) for c in line if ord(c) in FORBIDDEN})
            if bad:
                offenders.append(f"{p.relative_to(ROOT)}:{lineno} {bad}")
    assert offenders == []
