"""
Evaluation scope: which data sources to run (SQL / Blob / Local / Stream / All).

Used by main.py for interactive selection and by load_and_profile(location_types=...).
"""
from __future__ import annotations

import sys
from typing import Dict, FrozenSet, Optional, Set

# Canonical YAML location types under source.locations
TYPE_DATABASE = "database"
TYPE_AZURE_BLOB = "azure_blob"
TYPE_FILESYSTEM = "filesystem"

# User-facing mode keys
MODE_SQL = "sql"
MODE_BLOB = "blob"
MODE_LOCAL = "local"
MODE_STREAM = "stream"
MODE_ALL = "all"
MODE_INTERACTIVE = "interactive"

_MODE_TO_TYPES: Dict[str, FrozenSet[str]] = {
    MODE_SQL: frozenset({TYPE_DATABASE}),
    MODE_BLOB: frozenset({TYPE_AZURE_BLOB}),
    MODE_LOCAL: frozenset({TYPE_FILESYSTEM}),
}

VALID_MODES = frozenset({MODE_SQL, MODE_BLOB, MODE_LOCAL, MODE_STREAM, MODE_ALL, MODE_INTERACTIVE})


def location_types_for_mode(mode: str) -> Optional[Set[str]]:
    """
    Return set of YAML location types to include, or None = all types (except stream; stream is separate).

    Stream mode does not use locations from sources.yaml for load_and_profile.
    """
    m = (mode or "").strip().lower()
    if m == MODE_ALL:
        return None
    if m == MODE_STREAM:
        return frozenset()  # caller handles stream separately
    if m in _MODE_TO_TYPES:
        return set(_MODE_TO_TYPES[m])
    return None


def interactive_select_mode() -> str:
    """TTY menu; returns MODE_SQL | MODE_BLOB | MODE_LOCAL | MODE_STREAM | MODE_ALL."""
    print("\n=== Agent Dhara — select data to evaluate ===\n")
    print("  1) Azure SQL only      (database locations in sources.yaml)")
    print("  2) Azure Blob only     (azure_blob assessment containers)")
    print("  3) Local files only    (filesystem paths in sources.yaml)")
    print("  4) Stream only         (JSON array file — batch / snapshot)")
    print("  5) Full report         (all connected sources above)")
    print("  0) Exit")
    while True:
        try:
            choice = input("\nEnter choice [1-5, 0=exit]: ").strip()
        except EOFError:
            print("\nNo input; defaulting to 'all'.")
            return MODE_ALL
        if choice == "0":
            sys.exit(0)
        if choice == "1":
            return MODE_SQL
        if choice == "2":
            return MODE_BLOB
        if choice == "3":
            return MODE_LOCAL
        if choice == "4":
            return MODE_STREAM
        if choice == "5":
            return MODE_ALL
        print("Invalid choice. Enter 1, 2, 3, 4, 5, or 0.")


def prompt_stream_file_path() -> str:
    while True:
        try:
            p = input("Path to JSON array file (stream snapshot): ").strip().strip('"')
        except EOFError:
            return ""
        if p:
            return p
        print("Path required.")


def default_evaluate_mode() -> str:
    """Used when --evaluate=auto: menu if stdin is a TTY, else evaluate all sources."""
    return MODE_INTERACTIVE if sys.stdin.isatty() else MODE_ALL
