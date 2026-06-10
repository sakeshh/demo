from __future__ import annotations
import datetime
from typing import Any, Dict, Optional

def build_improvement_narrative(
    current_run: Dict[str, Any],
    prior_run: Optional[Dict[str, Any]],
    drift_result: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Generates a beautiful, premium markdown comparison narrative between the current
    assessment run and a prior run.
    """
    if not current_run:
        return "No run data available."

    lines = []
    lines.append("### 📊 Data Quality Run Comparison")

    curr_score = current_run.get("dq_score") or 0
    curr_issues = current_run.get("dq_issue_count") or 0
    curr_ts = current_run.get("run_ts") or 0

    if prior_run:
        prior_score = prior_run.get("dq_score") or 0
        prior_issues = prior_run.get("dq_issue_count") or 0
        prior_ts = prior_run.get("run_ts") or 0
        
        # Time formatting
        prior_dt = datetime.datetime.fromtimestamp(prior_ts)
        prior_date_str = prior_dt.strftime("%b %d, %H:%M")
        
        # Score diff
        score_diff = curr_score - prior_score
        if score_diff > 0:
            score_status = f"(↑{score_diff} points since {prior_date_str})"
        elif score_diff < 0:
            score_status = f"(↓{abs(score_diff)} points since {prior_date_str})"
        else:
            score_status = f"(no change since {prior_date_str})"
            
        lines.append(f"* **DQ Score**: {curr_score}/100 {score_status}")
        
        # Issues diff
        issue_diff = curr_issues - prior_issues
        if issue_diff < 0:
            issue_status = f"(decreased by {abs(issue_diff)} from {prior_issues})"
            lines.append(f"* **Issues**: {curr_issues} {issue_status} ✅")
        elif issue_diff > 0:
            issue_status = f"(increased by {issue_diff} from {prior_issues})"
            lines.append(f"* **Issues**: {curr_issues} {issue_status} ⚠️")
        else:
            lines.append(f"* **Issues**: {curr_issues} (no change)")
            
        # Schema change
        curr_schema = current_run.get("schema_hash")
        prior_schema = prior_run.get("schema_hash")
        if curr_schema and prior_schema:
            if curr_schema == prior_schema:
                lines.append("* **Schema**: Unchanged since last run ✅")
            else:
                lines.append("* **Schema**: Schema changes detected! ⚠️")
        else:
            lines.append("* **Schema**: Unknown (baseline signature missing)")
            
    else:
        # First run narrative
        lines.append(f"* **DQ Score**: {curr_score}/100 (Initial Run Baseline)")
        lines.append(f"* **Issues**: {curr_issues}")
        lines.append("* **Schema**: Registered new schema baseline ✅")

    if drift_result and isinstance(drift_result, dict):
        drift_found = drift_result.get("drift_detected", False)
        if drift_found:
            lines.append(f"* **Data Drift**: Drift detected in features: {', '.join(drift_result.get('drifted_columns', []))} ⚠️")
        else:
            lines.append("* **Data Drift**: No significant distribution drift detected ✅")

    return "\n".join(lines)
