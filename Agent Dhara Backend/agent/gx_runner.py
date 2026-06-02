"""
GX runner shim — delegates to specialists.gx_validation_specialist.
"""
from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from agent.specialists.gx_validation_specialist import run_gx_validation


def run_suite(
    datasets: Dict[str, pd.DataFrame],
    assessment: Dict[str, Any],
) -> Dict[str, Any]:
    """Alias for `run_gx_validation` (plan naming: gx_runner)."""
    return run_gx_validation(datasets, assessment)
