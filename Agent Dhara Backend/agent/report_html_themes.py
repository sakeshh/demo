"""
HTML report theme loader.

Default (and only supported): Theme 2 (executive / enterprise).
"""

from __future__ import annotations

import os

_THEMES_DIR = os.path.join(os.path.dirname(__file__), "report_themes")


def get_report_html_css(theme: str | None = None) -> str:
    path = os.path.join(_THEMES_DIR, "theme2.css")
    with open(path, encoding="utf-8") as f:
        return f.read()
