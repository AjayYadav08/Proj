"""
utils/reporter.py
=================
STEP 5: REPORTING ENGINE (User-Friendly Human Text, JSON, GitHub Actions)

Generates clean, readable, and developer-friendly reports:
1. Card-Based Terminal UI: Visual cards with rounded borders, colored diffs
   (Current Docs ❌ vs Proposed Fix ✅), code culprits, and actionable steps.
2. Smart Issue Consolidation: Deduplicates redundant alerts on the same line.
3. Action Checklist: Generates a checklist of files and lines to update before merging.
4. JSON Output: Machine-readable schema for API / tool consumption.
5. GitHub Actions Integration: Workflow command annotations (::error, ::warning)
   and GitHub PR Step Summary Markdown.
"""

from collections import defaultdict
from dataclasses import asdict
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from detectors import CodeChange
from .doc_finder import DriftIssue


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


class ConsolidatedIssue:
    """Grouped drift issue to eliminate redundant duplicates on the same doc sentence."""
    def __init__(self, primary: DriftIssue):
        self.issue_type = primary.issue_type
        self.confidence = primary.confidence
        self.doc_file = primary.doc_file
        self.doc_line = primary.doc_line
        self.doc_sentence = primary.doc_sentence
        self.proposed_sentence = primary.proposed_sentence
        self.old_value = primary.old_value
        self.new_value = primary.new_value
        self.old_name = primary.old_name
        self.new_name = primary.new_name
        self.suggestion = primary.suggestion
        self.ai_verified = primary.details.get("ai_verified", False)
        self.ai_reasoning = primary.details.get("ai_reasoning")
        self.ai_model = primary.details.get("ai_model")
        # Track all contributing code culprits: list of (file, line, name, diff_str)
        self.code_culprits: List[Tuple[str, int, str, str]] = [
            (primary.code_file, primary.code_line, primary.code_name, self._format_diff(primary))
        ]

    def _format_diff(self, issue: DriftIssue) -> str:
        if issue.old_value is not None and issue.new_value is not None:
            return f"{issue.old_value} ──▶ {issue.new_value}"
        elif issue.old_name is not None and issue.new_name is not None:
            return f"{issue.old_name} ──▶ {issue.new_name}"
        return issue.code_name

    def add_culprit(self, issue: DriftIssue):
        diff_str = self._format_diff(issue)
        item = (issue.code_file, issue.code_line, issue.code_name, diff_str)
        if item not in self.code_culprits:
            self.code_culprits.append(item)


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
        self.use_colors = use_colors and "NO_COLOR" not in os.environ

    def _c(self, text: str, color_code: str) -> str:
        """Wrap text in ANSI color if colors are enabled."""
        if not self.use_colors:
            return text
        return f"{color_code}{text}{Colors.RESET}"

    def get_consolidated_issues(self) -> List[ConsolidatedIssue]:
        """
        Deduplicates issues where multiple code changes flag the exact same
        documentation line and sentence with identical changes.
        """
        groups: Dict[Tuple[str, int, str], ConsolidatedIssue] = {}
        for issue in self.drift_issues:
            key = (issue.doc_file, issue.doc_line, issue.doc_sentence.strip())
            if key not in groups:
                groups[key] = ConsolidatedIssue(issue)
            else:
                groups[key].add_culprit(issue)
        return list(groups.values())

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

    def _highlight_token(self, text: str, token: Optional[str], color_code: str) -> str:
        """Highlights a specific token within text with color and underline."""
        if not text or not token or not self.use_colors:
            return text
        clean = token.strip("'\"")
        if not clean or clean not in text:
            return text
        escaped = re.escape(clean)
        replacement = f"{color_code}{Colors.BOLD}{Colors.UNDERLINE}{clean}{Colors.RESET}"
        return re.sub(rf"\b{escaped}\b", replacement, text, count=1)

    def to_text(self) -> str:
        """
        Generate human-readable, card-based CLI report designed for maximum clarity:
        - Boxed visual cards
        - Current Docs (❌) vs Proposed Fix (✅)
        - Contributing code change culprits
        - Action checklist at the end
        """
        stats = self.get_summary_stats()
        consolidated = self.get_consolidated_issues()
        out: List[str] = []

        # -------------------------------------------------------------
        # 1. Header Banner
        # -------------------------------------------------------------
        banner = "=" * 74
        out.append(self._c(banner, Colors.CYAN))
        out.append(self._c("  DOCUMENTATION DRIFT DETECTOR — PR ANALYSIS", Colors.BOLD + Colors.CYAN))
        out.append(self._c(banner, Colors.CYAN))

        # Overview metadata
        out.append(
            f"Code Changes Analyzed: {self._c(str(stats['total_code_changes']), Colors.BOLD)} | "
            f"Doc Files Scanned: {self._c(str(stats['doc_files_scanned']), Colors.BOLD)}"
        )

        status_color = Colors.RED if stats['high_confidence'] > 0 else (Colors.YELLOW if stats['medium_confidence'] > 0 else Colors.GREEN)
        status_text = "🔴 MERGE BLOCKED — Documentation out of sync" if stats['high_confidence'] > 0 else (
            "🟡 REVIEW NEEDED" if stats['medium_confidence'] > 0 else "🟢 PASSED — All docs match code"
        )

        out.append(
            f"Drift Issues Found   : {self._c(str(len(consolidated)), Colors.BOLD)} "
            f"({self._c(str(stats['high_confidence']) + ' HIGH', Colors.RED + Colors.BOLD)}, "
            f"{self._c(str(stats['medium_confidence']) + ' MEDIUM', Colors.YELLOW)}, "
            f"{self._c(str(stats['low_confidence']) + ' LOW', Colors.DIM)})"
        )
        out.append(f"Status               : {self._c(status_text, status_color + Colors.BOLD)}")
        out.append("-" * 74)

        if not self.drift_issues:
            out.append(self._c(" ✨ SUCCESS: No documentation drift detected! Documentation is up to date.", Colors.GREEN + Colors.BOLD))
            out.append("=" * 74)
            return "\n".join(out)

        # -------------------------------------------------------------
        # 2. Issue Cards
        # -------------------------------------------------------------
        for idx, item in enumerate(consolidated, start=1):
            is_high = item.confidence == "HIGH"
            badge = self._c("[HIGH - MERGE BLOCKER]", Colors.RED + Colors.BOLD) if is_high else self._c("[MEDIUM - WARNING]", Colors.YELLOW + Colors.BOLD)
            if item.ai_verified:
                ai_badge = self._c(f"🤖 AI VERIFIED ({item.ai_model or 'Ollama'})", Colors.CYAN + Colors.BOLD)
                badge = f"{badge}  {ai_badge}"

            type_title = {
                "DEFAULT_VALUE_CHANGED": "Outdated Default Value",
                "FLAG_RENAMED": "Renamed Flag / Config Key",
                "PARAM_CHANGED": "Parameter Signature Mismatch",
                "FEATURE_REMOVED": "Removed Feature Reference",
            }.get(item.issue_type, item.issue_type)

            border_c = Colors.RED if is_high else Colors.YELLOW

            out.append("")
            out.append(self._c(f"╭─ Issue #{idx}: {type_title}  {badge} ", border_c) + self._c("─" * 15, border_c))
            out.append(self._c("│", border_c) + f"  {self._c('📄 Doc Location :', Colors.BOLD)} {item.doc_file}:{item.doc_line}")
            out.append(self._c("│", border_c))

            # Display Current Documentation with highlighted outdated value
            current_highlighted = item.doc_sentence
            if item.old_value:
                current_highlighted = self._highlight_token(current_highlighted, item.old_value, Colors.RED)
            elif item.old_name:
                current_highlighted = self._highlight_token(current_highlighted, item.old_name, Colors.RED)

            out.append(self._c("│", border_c) + f"  {self._c('❌ Current Docs :', Colors.RED + Colors.BOLD)} \"{current_highlighted}\"")

            # Display Proposed Fix if available
            if item.proposed_sentence:
                proposed_highlighted = item.proposed_sentence
                if item.new_value:
                    proposed_highlighted = self._highlight_token(proposed_highlighted, item.new_value, Colors.GREEN)
                elif item.new_name:
                    proposed_highlighted = self._highlight_token(proposed_highlighted, item.new_name, Colors.GREEN)
                out.append(self._c("│", border_c) + f"  {self._c('✅ Proposed Fix :', Colors.GREEN + Colors.BOLD)} \"{proposed_highlighted}\"")
            elif item.issue_type == "FEATURE_REMOVED":
                out.append(self._c("│", border_c) + f"  {self._c('✅ Proposed Fix :', Colors.GREEN + Colors.BOLD)} [Remove section or add deprecation notice]")

            # Display AI Reasoning if available
            if item.ai_reasoning:
                out.append(self._c("│", border_c) + f"  {self._c('🤖 AI Analysis  :', Colors.CYAN + Colors.BOLD)} \"{item.ai_reasoning}\"")

            out.append(self._c("│", border_c))

            # Code culprit(s)
            culprit_strs = []
            for c_file, c_line, c_name, c_diff in item.code_culprits:
                culprit_strs.append(f"{c_file}:{c_line} [{c_name}] ({c_diff})")
            
            out.append(self._c("│", border_c) + f"  {self._c('🔍 Code Culprit  :', Colors.BOLD)} {culprit_strs[0]}")
            for extra in culprit_strs[1:]:
                out.append(self._c("│", border_c) + f"                     {extra}")

            # Suggested Fix action
            if item.suggestion:
                out.append(self._c("│", border_c) + f"  {self._c('💡 Action        :', Colors.CYAN + Colors.BOLD)} {item.suggestion}")

            out.append(self._c("╰" + "─" * 73, border_c))

        # -------------------------------------------------------------
        # 3. Action Checklist (Grouped by file)
        # -------------------------------------------------------------
        files_map = defaultdict(list)
        for item in consolidated:
            action_desc = item.suggestion or f"Update line for {item.issue_type}"
            files_map[item.doc_file].append((item.doc_line, action_desc))

        out.append("\n" + self._c("=" * 74, Colors.CYAN))
        out.append(self._c("📋 ACTION CHECKLIST (Files to update before merging):", Colors.BOLD + Colors.CYAN))

        for doc_file, actions in files_map.items():
            out.append(f"\n  📁 {self._c(doc_file, Colors.BOLD)}")
            for line_no, desc in actions:
                out.append(f"     [ ] Line {line_no:2d}: {desc}")

        out.append("\n" + self._c("=" * 74, Colors.CYAN))
        if stats["high_confidence"] > 0:
            out.append(self._c(f" ❌ FAILED: {stats['high_confidence']} high-confidence issue(s) must be fixed before merging.", Colors.RED + Colors.BOLD))
            out.append(self._c("    Run `python3 drift_detector.py` again after editing to confirm resolution.", Colors.DIM))
        else:
            out.append(self._c(" ✅ PASSED: All documentation is verified in sync.", Colors.GREEN + Colors.BOLD))
        out.append(self._c("=" * 74, Colors.CYAN))

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
            if issue.proposed_sentence:
                message += f" | Proposed fix: \"{issue.proposed_sentence}\""
            lines.append(f"::{cmd} file={issue.doc_file},line={issue.doc_line},title={title}::{message}")
        return "\n".join(lines)

    def to_markdown_summary(self) -> str:
        """
        Generate Markdown summary for GitHub Step Summary ($GITHUB_STEP_SUMMARY).
        """
        stats = self.get_summary_stats()
        consolidated = self.get_consolidated_issues()
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
        md.append("| Severity | Issue Type | Location | Current Documentation | Proposed Fix | Code Change |")
        md.append("| :--- | :--- | :--- | :--- | :--- | :--- |")

        for item in consolidated:
            badge = "🔴 **HIGH**" if item.confidence == "HIGH" else "🟡 **MEDIUM**"
            proposed = f"`{item.proposed_sentence}`" if item.proposed_sentence else item.suggestion
            culprits = "<br>".join([f"`{c[0]}:{c[1]}` (`{c[2]}`)" for c in item.code_culprits])
            md.append(
                f"| {badge} | `{item.issue_type}` | `{item.doc_file}:{item.doc_line}` | "
                f"*{item.doc_sentence}* | {proposed} | {culprits} |"
            )

        md.append("")
        return "\n".join(md)
