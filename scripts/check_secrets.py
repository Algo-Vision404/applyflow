"""Fail if the tree contains secrets, personal paths, or user data that must not be pushed."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "build",
    ".eggs",
    "node_modules",
}

SKIP_FILES = {"check_secrets.py"}

BLOCKED_NAMES = {
    ".env",
    "profile.json",
    "credentials.json",
    "secrets.json",
    "id_rsa",
    "id_ed25519",
    "applyflow.db",
}

BLOCKED_SUFFIXES = {
    ".pem",
    ".p12",
    ".pfx",
    ".sqlite",
    ".sqlite3",
}

# Split so this file does not contain the literals it is hunting for.
_PERSONAL = "".join(("louis", "baffoe"))
_HOME_WIN = "C:\\\\Users\\\\" + "kop\\\\"
_HOME_UNIX = "/Users/" + "kop/"

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("personal identifier", re.compile(re.escape(_PERSONAL), re.I)),
    ("home path", re.compile(_HOME_WIN, re.I)),
    ("home path", re.compile(_HOME_UNIX)),
    ("private key", re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}\b")),
    ("GitHub pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("personal gmail", re.compile(r"\b[A-Za-z0-9._%+-]+@gmail\.com\b", re.I)),
]

ALLOWED_GMAIL = {"you@gmail.com"}


def _iter_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS or part.endswith(".egg-info") for part in path.parts):
            continue
        if path.name in SKIP_FILES:
            continue
        files.append(path)
    return files


def scan(root: Path = ROOT) -> list[str]:
    problems: list[str] = []
    for path in _iter_files(root):
        rel = path.relative_to(root).as_posix()
        name = path.name.lower()
        if name in BLOCKED_NAMES or path.suffix.lower() in BLOCKED_SUFFIXES:
            problems.append(f"{rel}: blocked filename (user data or credentials)")
            continue
        if name.endswith(".pdf") or name.endswith(".docx"):
            problems.append(f"{rel}: resume/document file must not be committed")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        example = rel.endswith(".example") or rel.endswith(".md")
        for label, pattern in PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(0)
                if label == "personal gmail" and (value.lower() in ALLOWED_GMAIL or example):
                    continue
                if label == "personal gmail" and value.lower().endswith("@example.com"):
                    continue
                problems.append(f"{rel}: {label} ({value[:40]})")
    return problems


def main() -> int:
    problems = scan()
    if not problems:
        print("secret scan: clean")
        return 0
    print("secret scan: refusing to continue — remove these before git push:")
    for item in problems:
        print(f"  {item}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
