"""
utils/reporter.py
=================
STEP 5: REPORTING ENGINE (Text, JSON, GitHub Actions)

Generates beautiful and structured outputs:
1. Human-Readable Text: ANSI colored, boxed issue breakdowns, highlighting the
   exact documentation sentence, code diff link, and suggested fix.
2. JSON Output: Machine-readable schema for API / tool consumption.
3. GitHub Actions Integration: Workflow command annotations (::error, ::warning)
   and GitHub PR Step Summary Markdown.
"""

from dataclasses import asdict
import json
import os
from typing import Any, Dict, List, Optional

from detectors import CodeChange
from .doc_finder import DriftIssue


# ANSI Color Codes for terminal beauty
class Colors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    DIM = "\033[2m"
    RESET = "\033[0m"


class DriftReporter:
    """Formatter and reporter for documentation drift detection results."""

    def __init__(
        self,
        code_changes: List[CodeChange],
        drift_issues: List[DriftIssue],
        doc_files_scanned: int = 0,
        use_colors: bool = True
    ):
        self.code_changes = code_changes
        self.drift_issues = drift_issues
        self.doc_files_scanned = doc_files_scanned
        # Disable colors if NO_COLOR environment variable is set
        self.use_colors = use_colors and "NO_COLOR" not in os.environ

    def _c(self, text: str, color_code: str) -> str:
        """Wrap text in ANSI color if colors are enabled."""
        if not self.use_colors:
            return text
        return f"{color_code}{text}{Colors.RESET}"

    def get_summary_stats(self) -> Dict[str, int]:
        """Calculates counts for high, medium, low issues."""
        high = sum(1 for i in self.drift_issues if i.confidence == "HIGH")
        med = sum(1 for i in self.drift_issues if i.confidence == "MEDIUM")
        low = sum(1 for i in self.drift_issues if i.confidence == "LOW")
        return {
            "total_code_changes": len(self.code_changes),
            "doc_files_scanned": self.doc_files_scanned,
            "total_drift_issues": len(self.drift_issues),
            "high_confidence": high,
            "medium_confidence": med,
            "low_confidence": low,
        }

    def to_text(self) -> str:
        """
        Generate human-readable CLI report with colored boxes, issue details,
        exact doc sentences, code links, and suggested fixes.
        """
        stats = self.get_summary_stats()
        out: List[str] = []

        # Banner Header
        banner = "=" * 70
        out.append(self._c(banner, Colors.CYAN))
        out.append(self._c("  DOCUMENTATION DRIFT DETECTOR — PR ANALYSIS", Colors.BOLD + Colors.CYAN))
        out.append(self._c(banner, Colors.CYAN))

        # Overview Statistics
        out.append(
            f"Code Changes Analyzed: {self._c(str(stats['total_code_changes']), Colors.BOLD)} | "
            f"Doc Files Scanned: {self._c(str(stats['doc_files_scanned']), Colors.BOLD)}"
        )

        status_line = (
            f"Drift Issues Found: {self._c(str(stats['total_drift_issues']), Colors.BOLD)} "
            f"({self._c(str(stats['high_confidence']) + ' HIGH', Colors.RED + Colors.BOLD)}, "
            f"{self._c(str(stats['medium_confidence']) + ' MEDIUM', Colors.YELLOW)}, "
            f"{self._c(str(stats['low_confidence']) + ' LOW', Colors.DIM)})"
        )
        out.append(status_line)
        out.append("-" * 70)

        if not self.drift_issues:
            out.append(self._c(" SUCCESS: No documentation drift detected! Docs are in sync with code.", Colors.GREEN + Colors.BOLD))
            out.append("=" * 70)
            return "\n".join(out)

        # Iterate over detected drift issues
        for idx, issue in enumerate(self.drift_issues, start=1):
            conf_badge = (
                self._c("[HIGH - MERGE BLOCKER]", Colors.RED + Colors.BOLD)
                if issue.confidence == "HIGH"
                else self._c("[MEDIUM - REVIEW NEEDED]", Colors.YELLOW + Colors.BOLD)
                if issue.confidence == "MEDIUM"
                else self._c("[LOW - INFO]", Colors.DIM)
            )

            type_label = {
                "DEFAULT_VALUE_CHANGED": "DEFAULT VALUE DRIFT",
                "FLAG_RENAMED": "FLAG / CONFIG RENAME DRIFT",
                "PARAM_CHANGED": "PARAMETER SIGNATURE DRIFT",
                "FEATURE_REMOVED": "REMOVED FEATURE DRIFT",
            }.get(issue.issue_type, issue.issue_type)

            out.append(f"\n{self._c(f'Issue #{idx}: {type_label}', Colors.BOLD)}  {conf_badge}")

            # Documentation location & exact sentence
            out.append(f"  {self._c('Doc Location  :', Colors.BOLD)} {issue.doc_file}:{issue.doc_line}")
            out.append(f"  {self._c('Wrong Sentence:', Colors.RED + Colors.BOLD)} \"{issue.doc_sentence}\"")

            # Code change culprit
            val_diff = ""
            if issue.old_value is not None and issue.new_value is not None:
                val_diff = f" ({issue.old_value} -> {issue.new_value})"
            elif issue.old_name is not None and issue.new_name is not None:
                val_diff = f" ({issue.old_name} -> {issue.new_name})"

            out.append(f"  {self._c('Code Culprit  :', Colors.BOLD)} {issue.code_file}:{issue.code_line} [{issue.code_name}]{val_diff}")

            # Actionable fix suggestion
            if issue.suggestion:
                out.append(f"  {self._c('Suggested Fix :', Colors.GREEN + Colors.BOLD)} {issue.suggestion}")

        out.append("\n" + "=" * 70)
        if stats["high_confidence"] > 0:
            out.append(self._c(f" FAILED: {stats['high_confidence']} high-confidence drift issue(s) require documentation updates.", Colors.RED + Colors.BOLD))
        else:
            out.append(self._c(" PASSED: No blocking drift issues found.", Colors.GREEN + Colors.BOLD))
        out.append("=" * 70)

        return "\n".join(out)

    def to_json(self, indent: int = 2) -> str:
        """Generate structured JSON report string."""
        stats = self.get_summary_stats()
        data = {
            "summary": stats,
            "code_changes": [c.to_dict() for c in self.code_changes],
            "drift_issues": [issue.to_dict() for issue in self.drift_issues],
        }
        return json.dumps(data, indent=indent)

    def to_github_commands(self) -> str:
        """
        Generate GitHub Actions workflow command annotations (::error, ::warning).
        This renders inline annotations directly on the GitHub PR diff / files!
        """
        lines: List[str] = []
        for issue in self.drift_issues:
            cmd = "error" if issue.confidence == "HIGH" else "warning"
            title = f"Doc Drift ({issue.issue_type})"
            message = (
                f"Documentation drift detected: \"{issue.doc_sentence}\". "
                f"Code changed at {issue.code_file}:{issue.code_line}. "
                f"Suggestion: {issue.suggestion}"
            )
            lines.append(f"::{cmd} file={issue.doc_file},line={issue.doc_line},title={title}::{message}")
        return "\n".join(lines)

    def to_markdown_summary(self) -> str:
        """
        Generate Markdown summary for GitHub Step Summary ($GITHUB_STEP_SUMMARY).
        """
        stats = self.get_summary_stats()
        md: List[str] = []
        md.append("## 🔍 Documentation Drift Detection Report")
        md.append("")
        md.append("| Metric | Count |")
        md.append("| :--- | :--- |")
        md.append(f"| **Code Changes Analyzed** | {stats['total_code_changes']} |")
        md.append(f"| **Doc Files Scanned** | {stats['doc_files_scanned']} |")
        md.append(f"| **High-Confidence Drift (Blockers)** | {stats['high_confidence']} |")
        md.append(f"| **Medium-Confidence Drift (Warnings)** | {stats['medium_confidence']} |")
        md.append(f"| **Low-Confidence Drift** | {stats['low_confidence']} |")
        md.append("")

        if not self.drift_issues:
            md.append("✅ **All documentation is up-to-date with code changes!**")
            return "\n".join(md)

        md.append("### ⚠️ Detected Drift Issues")
        md.append("")
        md.append("| Severity | Issue Type | Documentation Location | Code Culprit | Suggested Fix |")
        md.append("| :--- | :--- | :--- | :--- | :--- |")

        for issue in self.drift_issues:
            badge = "🔴 **HIGH**" if issue.confidence == "HIGH" else "🟡 **MEDIUM**"
            md.append(
                f"| {badge} | `{issue.issue_type}` | `{issue.doc_file}:{issue.doc_line}`<br>*{issue.doc_sentence}* | "
                f"`{issue.code_file}:{issue.code_line}` (`{issue.code_name}`) | {issue.suggestion} |"
            )

        md.append("")
        return "\n".join(md)

