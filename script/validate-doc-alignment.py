#!/usr/bin/env python3
"""
validate-doc-alignment.py

Validates that integration-critical identifiers defined in Rust contract source
files are documented in the corresponding Markdown documentation files.

Checks three categories:
  1. Public entrypoints  (pub fn <name>) in contracts/streaming/src/lib.rs
     -> must appear in docs/streaming.md
  2. Event symbols       (Symbol::short/new) in contracts/core/src/events.rs
     -> must appear in docs/events.md
  3. Error enum variants in contracts/core/src/error.rs
     -> must appear in docs/error.md

Exit codes:
  0 -- all identifiers are documented
  1 -- one or more identifiers are missing from documentation
"""

import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent

CONTRACT_SRC = REPO_ROOT / "contracts" / "streaming" / "src" / "lib.rs"
EVENTS_SRC = REPO_ROOT / "contracts" / "core" / "src" / "events.rs"
ERROR_SRC = REPO_ROOT / "contracts" / "core" / "src" / "error.rs"

DOC_STREAMING = REPO_ROOT / "docs" / "streaming.md"
DOC_EVENTS = REPO_ROOT / "docs" / "events.md"
DOC_ERROR = REPO_ROOT / "docs" / "error.md"

# pub fn names that are internal helpers, not ABI entry-points.
ENTRYPOINT_ALLOWLIST = frozenset({"save_stream"})

# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

# Matches:  pub fn foo(  or      pub fn foo<T>(
_RE_ENTRYPOINT = re.compile(
    r"^\s*pub\s+fn\s+([a-zA-Z0-9_]+)\s*[\(<]",
    re.MULTILINE,
)

# Matches:  Symbol::short(&env, "topic")  or  Symbol::new(&env, "topic")
_RE_EVENT_SYMBOL = re.compile(
    r'Symbol::(?:short|new)\s*\(\s*&\w+\s*,\s*"([^"]+)"\s*\)',
    re.MULTILINE,
)

# Matches enum variants of the form:   Variant = 42,
_RE_ERROR_VARIANT = re.compile(
    r"^\s{4}([A-Z][A-Za-z0-9]+)\s*=\s*\d+\s*,",
    re.MULTILINE,
)


def extract_entrypoints(source: str) -> set:
    """Return all pub fn names that are contract ABI entry-points."""
    names = set(_RE_ENTRYPOINT.findall(source))
    return names - ENTRYPOINT_ALLOWLIST


def extract_event_symbols(source: str) -> set:
    """Return all Symbol::short/new string literals (event topics)."""
    return set(_RE_EVENT_SYMBOL.findall(source))


def extract_error_variants(source: str) -> set:
    """Return all error enum variant names (Variant = N pattern)."""
    return set(_RE_ERROR_VARIANT.findall(source))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def check_missing(identifiers: set, doc_text: str) -> set:
    """Return identifiers not found anywhere in doc_text."""
    return {ident for ident in identifiers if ident not in doc_text}


def validate(
    contract_path: Path,
    events_path: Path,
    error_path: Path,
    streaming_doc: Path,
    events_doc: Path,
    error_doc: Path,
) -> int:
    """
    Run all alignment checks. Returns 0 on success, 1 on any drift.
    """
    source = contract_path.read_text(encoding="utf-8")
    events_source = events_path.read_text(encoding="utf-8")
    error_source = error_path.read_text(encoding="utf-8")
    streaming_text = streaming_doc.read_text(encoding="utf-8")
    events_text = events_doc.read_text(encoding="utf-8")
    error_text = error_doc.read_text(encoding="utf-8")

    checks = [
        (extract_entrypoints(source), streaming_text, streaming_doc, "entrypoint"),
        (extract_event_symbols(events_source), events_text, events_doc, "event symbol"),
        (extract_error_variants(error_source), error_text, error_doc, "error variant"),
    ]

    drift_found = False

    for identifiers, doc_text, doc_path, kind in checks:
        for ident in sorted(check_missing(identifiers, doc_text)):
            try:
                display = doc_path.relative_to(REPO_ROOT)
            except ValueError:
                display = doc_path
            print(
                f"MISSING DOC: '{ident}' ({kind}) found in code "
                f"but not in '{display}'"
            )
            drift_found = True

    if not drift_found:
        print("OK: all contract identifiers are present in documentation.")

    return 1 if drift_found else 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    required = [
        CONTRACT_SRC, EVENTS_SRC, ERROR_SRC,
        DOC_STREAMING, DOC_EVENTS, DOC_ERROR,
    ]
    for path in required:
        if not path.exists():
            print(f"ERROR: required file not found: {path}")
            return 1

    return validate(
        CONTRACT_SRC, EVENTS_SRC, ERROR_SRC,
        DOC_STREAMING, DOC_EVENTS, DOC_ERROR,
    )


if __name__ == "__main__":
    sys.exit(main())
