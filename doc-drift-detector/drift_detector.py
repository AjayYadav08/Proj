#!/usr/bin/env python3
"""
drift_detector.py
=================
Main CLI entry point for Documentation Drift Detection.

Orchestrates the 5 core steps:
1. STEP 1 — PARSE PR DIFF: Fetch unified git diff and isolate modified code files.
2. STEP 2 — EXTRACT CODE CHANGES: Run semantic detectors for:
            - Changed default values / constants (.py, .yaml, .json, .env)
            - Renamed CLI flags & config keys
            - Modified function parameters & defaults
            - Removed features/classes
3. STEP 3 — FIND RELATED DOCUMENTATION: Search .md, .rst, .txt, .adoc files with
            case & delimiter normalization.
4. STEP 4 — DETECT DRIFT: Verify if documentation genuinely drifted (e.g. old value present).
5. STEP 5 — REPORT: Output human-readable CLI text, JSON schema, or GitHub Action annotations.
"""

import argparse
from pathlib import Path
import sys
from typing import List, Optional, Set

# Local project imports
from ai import OllamaClient, SemanticVerifier, ProseRewriter
from detectors import (
    CodeChange,
    detect_default_values,
    detect_flag_renames,
    detect_param_changes,
    detect_feature_removals,
)
from utils.diff_parser import parse_diff, get_git_diff, FileDiff
from utils.doc_finder import (
    find_documentation_files,
    search_name_in_docs,
    detect_drift_for_change,
    apply_autofixes,
    DocMatch,
    DriftIssue,
)
from utils.reporter import DriftReporter


# Typed container for analysis results
GITHUB_WORKFLOW_TEMPLATE = """name: Documentation Drift Detection

on:
  pull_request:
    branches: [ main, master ]
    types: [ opened, synchronize, reopened ]

jobs:
  check-documentation-drift:
    name: Check Documentation Drift
    runs-on: ubuntu-latest

    steps:
      - name: Checkout Code Repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install DocDrift
        run: |
          pip install "git+https://github.com/AjayYadav08/Proj.git#subdirectory=doc-drift-detector"

      - name: Run Documentation Drift Detector
        run: |
          BASE_SHA="${{ github.event.pull_request.base.sha }}"
          HEAD_SHA="${{ github.event.pull_request.head.sha }}"
          echo "Checking documentation drift between $BASE_SHA and $HEAD_SHA..."
          
          # Annotate changed files on GitHub PR
          docdrift --base "$BASE_SHA" --head "$HEAD_SHA" --format github || true
          
          # Add markdown summary to PR check results
          docdrift --base "$BASE_SHA" --head "$HEAD_SHA" --format markdown >> $GITHUB_STEP_SUMMARY || true
          
          # Block merge if high confidence drift is found
          docdrift --base "$BASE_SHA" --head "$HEAD_SHA" --fail-on high
"""


def init_github_workflow(repo_dir: str = ".") -> bool:
    repo_path = Path(repo_dir).resolve()
    workflow_dir = repo_path / ".github" / "workflows"
    workflow_file = workflow_dir / "doc-drift.yml"
    
    workflow_dir.mkdir(parents=True, exist_ok=True)
    workflow_file.write_text(GITHUB_WORKFLOW_TEMPLATE, encoding="utf-8")
    print(f"✔ Successfully configured GitHub Actions workflow at:\n  {workflow_file}")
    print("\nNext step: Commit and push to your repo:")
    print("  git add .github/workflows/doc-drift.yml")
    print("  git commit -m 'ci: enable automatic documentation drift checks'")
    print("  git push")
    return True


class PipelineResult:
    def __init__(
        self,
        file_diffs: List[FileDiff],
        code_changes: List[CodeChange],
        drift_issues: List[DriftIssue],
        doc_files_scanned: int
    ):
        self.file_diffs = file_diffs
        self.code_changes = code_changes
        self.drift_issues = drift_issues
        self.doc_files_scanned = doc_files_scanned


def execute_drift_detection(
    diff_text: str,
    repo_dir: str = ".",
    docs_dir: Optional[str] = None,
    min_confidence: str = "medium",
    use_ai: bool = False,
    ai_model: Optional[str] = None,
    verbose: bool = False
) -> PipelineResult:
    """
    Executes the full documentation drift detection pipeline.
    Supports Hybrid mode: Static AST analysis + local Ollama LLM verification.
    """
    # -------------------------------------------------------------
    # STEP 1: PARSE PR DIFF
    # -------------------------------------------------------------
    if verbose:
        print("[STEP 1] Parsing diff and isolating code files...", file=sys.stderr)

    file_diffs = parse_diff(diff_text)

    if verbose:
        print(f"  -> Found {len(file_diffs)} modified code files in diff.", file=sys.stderr)

    # -------------------------------------------------------------
    # STEP 2: EXTRACT CODE CHANGES (SEMANTIC)
    # -------------------------------------------------------------
    if verbose:
        print("[STEP 2] Extracting semantic code changes...", file=sys.stderr)

    code_changes: List[CodeChange] = []

    # Pre-collect all added names across the PR to avoid false "feature removed" alerts
    all_added_names: Set[str] = set()
    for fd in file_diffs:
        for line in fd.added_lines:
            words = line.content.split()
            if words:
                all_added_names.update(words)

    for fd in file_diffs:
        # A) Default value changed
        default_val_changes = detect_default_values(fd)
        code_changes.extend(default_val_changes)

        # B) Flag renamed / config key renamed
        flag_rename_changes = detect_flag_renames(fd)
        code_changes.extend(flag_rename_changes)

        # C) Parameter changed
        param_changes = detect_param_changes(fd)
        code_changes.extend(param_changes)

        # D) Feature removed
        feature_removals = detect_feature_removals(
            fd,
            all_added_lines_by_name=all_added_names,
            repo_dir=repo_dir
        )
        code_changes.extend(feature_removals)

    if verbose:
        print(f"  -> Extracted {len(code_changes)} semantic code changes.", file=sys.stderr)
        for c in code_changes:
            print(f"     [{c.change_type}] {c.name} in {c.file}:{c.line}", file=sys.stderr)

    # -------------------------------------------------------------
    # STEP 3: FIND RELATED DOCUMENTATION
    # -------------------------------------------------------------
    if verbose:
        print("[STEP 3] Discovering documentation files...", file=sys.stderr)

    doc_files = find_documentation_files(repo_dir=repo_dir, custom_docs_dir=docs_dir)

    if verbose:
        print(f"  -> Discovered {len(doc_files)} documentation files.", file=sys.stderr)

    # -------------------------------------------------------------
    # STEP 4: DETECT DRIFT (SMART FILTERING & CONFIDENCE SCORING)
    # -------------------------------------------------------------
    if verbose:
        print("[STEP 4] Cross-referencing changes with documentation and detecting drift...", file=sys.stderr)

    drift_issues: List[DriftIssue] = []
    confidence_levels = {"high": 3, "medium": 2, "low": 1}
    min_level = confidence_levels.get(min_confidence.lower(), 2)

    for change in code_changes:
        # Search documentation for this code identifier (case-insensitive + normalized)
        doc_matches = search_name_in_docs(change.name, doc_files, repo_dir=repo_dir)

        # If it's a flag rename, also search for the old flag name explicitly
        if change.change_type == "FLAG_RENAMED" and change.old_name and change.old_name != change.name:
            extra_matches = search_name_in_docs(change.old_name, doc_files, repo_dir=repo_dir)
            doc_matches.extend(extra_matches)

        if not doc_matches:
            continue

        # Evaluate drift rules on matches
        potential_issues = detect_drift_for_change(change, doc_matches)

        # Filter by minimum confidence threshold
        for issue in potential_issues:
            issue_level = confidence_levels.get(issue.confidence.lower(), 1)
            if issue_level >= min_level:
                drift_issues.append(issue)

    # -------------------------------------------------------------
    # STEP 4B: OLLAMA AI HYBRID ENHANCEMENT (VERIFY & REWRITE)
    # -------------------------------------------------------------
    if use_ai:
        ollama = OllamaClient()
        if ollama.is_available():
            active_model = ai_model or ollama.get_preferred_model()
            if verbose:
                print(f"[AI HYBRID] Connected to local Ollama (model: {active_model}). Verifying candidates...", file=sys.stderr)

            verifier = SemanticVerifier(ollama)
            rewriter = ProseRewriter(ollama)
            change_by_name = {c.name: c for c in code_changes}

            for issue in drift_issues:
                rel_change = change_by_name.get(issue.code_name)
                if not rel_change and code_changes:
                    rel_change = code_changes[0]

                if rel_change:
                    match_obj = DocMatch(
                        file_path=issue.doc_file,
                        line_number=issue.doc_line,
                        line_content=issue.doc_sentence,
                        sentence=issue.doc_sentence,
                        matched_variant=issue.code_name
                    )
                    # 1. AI Verification
                    ai_verif = verifier.verify_candidate(rel_change, match_obj, model=active_model)
                    if ai_verif:
                        issue.details["ai_verified"] = True
                        issue.details["ai_model"] = active_model
                        issue.details["ai_reasoning"] = ai_verif.reasoning
                        if ai_verif.suggested_action:
                            issue.suggestion = ai_verif.suggested_action

                    # 2. AI Prose Rewriting
                    ai_rewritten = rewriter.rewrite_sentence(issue.doc_sentence, rel_change, model=active_model)
                    if ai_rewritten and ai_rewritten != issue.doc_sentence:
                        issue.proposed_sentence = ai_rewritten
                        issue.details["ai_rewritten"] = True
        elif verbose:
            print("[AI Warning] Ollama daemon unreachable at http://localhost:11434. Fallback to static engine.", file=sys.stderr)

    if verbose:
        print(f"  -> Identified {len(drift_issues)} documentation drift issues.", file=sys.stderr)

    return PipelineResult(
        file_diffs=file_diffs,
        code_changes=code_changes,
        drift_issues=drift_issues,
        doc_files_scanned=len(doc_files)
    )


def main():
    parser = argparse.ArgumentParser(
        description="Documentation Drift Detector — Detect outdated prose, tables, and configs after code changes in PRs."
    )
    parser.add_argument(
        "--base",
        type=str,
        default=None,
        help="Base branch/commit (e.g. main, origin/main, HEAD~1) for git diff."
    )
    parser.add_argument(
        "--head",
        type=str,
        default=None,
        help="Head branch/commit (e.g. HEAD, feature-branch) for git diff."
    )
    parser.add_argument(
        "--diff-file",
        type=str,
        default=None,
        help="Path to an existing git diff file (for offline testing or pipeline hooks)."
    )
    parser.add_argument(
        "--diff-text",
        type=str,
        default=None,
        help="Raw diff string passed directly via CLI."
    )
    parser.add_argument(
        "--repo-dir",
        type=str,
        default=".",
        help="Path to repository root directory (default: current working directory)."
    )
    parser.add_argument(
        "--docs-dir",
        type=str,
        default=None,
        help="Optional path to directory containing documentation (e.g. docs/)."
    )
    parser.add_argument(
        "--format",
        choices=["text", "json", "github", "markdown"],
        default="text",
        help="Output report format (default: text)."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Shorthand for --format json."
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Path to file where report should be written."
    )
    parser.add_argument(
        "--min-confidence",
        choices=["high", "medium", "low"],
        default="medium",
        help="Minimum confidence level to include in the report (default: medium)."
    )
    parser.add_argument(
        "--fail-on",
        choices=["high", "medium", "any", "none"],
        default="high",
        help="Fail with exit code 1 if drift of this confidence level or higher is detected (default: high)."
    )
    parser.add_argument(
        "--fix", "--autofix",
        dest="fix",
        action="store_true",
        help="Automatically apply proposed fixes directly into the documentation files."
    )
    parser.add_argument(
        "--ai",
        action="store_true",
        help="Enable local Ollama AI hybrid verification and prose rewriting."
    )
    parser.add_argument(
        "--ai-model",
        type=str,
        default=None,
        help="Specify Ollama model name (e.g. llama3.2:1b). Auto-detected if omitted."
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="Set up GitHub Actions automatic workflow (.github/workflows/doc-drift.yml) in the current repo."
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable detailed debug logging."
    )

    # Allow convenient shortcut: `docdrift init`
    if len(sys.argv) > 1 and sys.argv[1] == "init":
        init_github_workflow(".")
        sys.exit(0)

    args = parser.parse_args()

    if args.init:
        init_github_workflow(args.repo_dir)
        sys.exit(0)

    # Determine diff source
    diff_text = ""
    if args.diff_file:
        try:
            diff_text = Path(args.diff_file).read_text(encoding="utf-8")
        except Exception as e:
            print(f"Error reading diff file '{args.diff_file}': {e}", file=sys.stderr)
            sys.exit(2)
    elif args.diff_text:
        diff_text = args.diff_text
    else:
        try:
            diff_text = get_git_diff(base=args.base, head=args.head, repo_dir=args.repo_dir)
        except Exception as e:
            print(f"Error fetching git diff: {e}", file=sys.stderr)
            print("Hint: You can provide --diff-file <path> or ensure git repository has commits.", file=sys.stderr)
            sys.exit(2)

    # Execute pipeline
    result = execute_drift_detection(
        diff_text=diff_text,
        repo_dir=args.repo_dir,
        docs_dir=args.docs_dir,
        min_confidence=args.min_confidence,
        use_ai=args.ai,
        ai_model=args.ai_model,
        verbose=args.verbose
    )

    # -------------------------------------------------------------
    # STEP 5: REPORT
    # -------------------------------------------------------------
    reporter = DriftReporter(
        code_changes=result.code_changes,
        drift_issues=result.drift_issues,
        doc_files_scanned=result.doc_files_scanned,
        use_colors=True
    )

    target_format = "json" if args.json else args.format

    if target_format == "json":
        output_content = reporter.to_json()
    elif target_format == "github":
        output_content = reporter.to_github_commands()
    elif target_format == "markdown":
        output_content = reporter.to_markdown_summary()
    else:
        output_content = reporter.to_text()

    # Print to stdout
    print(output_content)

    # If --fix / --autofix is requested, apply fixes in-place
    if args.fix:
        fixed_count, fix_logs = apply_autofixes(result.drift_issues, repo_dir=args.repo_dir)
        print("\n" + "=" * 74)
        if fixed_count > 0:
            print(f" ✨ AUTO-FIX APPLIED: Successfully updated {fixed_count} documentation issue(s)!")
            for log in fix_logs:
                print(f"    • {log}")
        else:
            print(" ℹ️  No auto-fixable issues found (some issues require manual restructuring).")
        print("=" * 74)
        sys.exit(0)

    # If --output file specified, save report
    if args.output:
        try:
            out_path = Path(args.output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(output_content, encoding="utf-8")
            if args.verbose:
                print(f"Report saved to {args.output}", file=sys.stderr)
        except Exception as e:
            print(f"Warning: Failed to write output file: {e}", file=sys.stderr)

    # Determine exit code according to --fail-on
    stats = reporter.get_summary_stats()
    should_fail = False

    if args.fail_on == "high" and stats["high_confidence"] > 0:
        should_fail = True
    elif args.fail_on == "medium" and (stats["high_confidence"] > 0 or stats["medium_confidence"] > 0):
        should_fail = True
    elif args.fail_on == "any" and stats["total_drift_issues"] > 0:
        should_fail = True

    if should_fail:
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()

