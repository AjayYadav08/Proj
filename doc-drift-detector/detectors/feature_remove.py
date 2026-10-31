"""
detectors/feature_remove.py
===========================
STEP 2D: FEATURE REMOVED DETECTOR

Detects when functions, classes, or public features have been deleted from code:
- Python: `def feature_name(` or `class FeatureName`
- JavaScript / TypeScript: `function featureName(`, `class FeatureName`
- Go: `func FeatureName(`
- Rust: `fn feature_name(`

Verification check:
- Present in removed lines (-)
- NOT present in added lines (+)
- NOT found anywhere else in the repository (to avoid false alarms if a function
  was merely moved or refactored into a different module).

Output:
  CodeChange(type="FEATURE_REMOVED", name=feature_name, file=..., line=...)
"""

from pathlib import Path
import re
from typing import List, Optional, Set, Tuple

from utils.diff_parser import FileDiff, DiffLine, CODE_EXTENSIONS
from . import CodeChange


FEATURE_DEF_REGEX = re.compile(
    r"""
    ^\s*(?:async\s+)?(?:export\s+)?(?:default\s+)?
    (?:def|class|function|func|fn)\s+
    ([a-zA-Z_][a-zA-Z0-9_]*)
    """,
    re.VERBOSE
)


def extract_feature_name(line_text: str) -> Optional[str]:
    """Extracts function or class name from a declaration line."""
    match = FEATURE_DEF_REGEX.match(line_text.strip())
    if match:
        name = match.group(1)
        # Skip special dunder methods like __init__, __str__
        if name.startswith("__") and name.endswith("__"):
            return None
        return name
    return None


def exists_elsewhere_in_repo(feature_name: str, repo_dir: str, skip_file: str) -> bool:
    """
    Checks if feature_name definition still exists anywhere else in the repo.
    Searches only code files, excluding documentation and ignored directories.
    """
    repo_path = Path(repo_dir)
    target_pattern = re.compile(
        rf"(?:def|class|function|func|fn)\s+{re.escape(feature_name)}\b"
    )

    ignore_dirs = {".git", "node_modules", "venv", ".venv", "dist", "build", "__pycache__", ".tox"}

    try:
        for p in repo_path.rglob("*"):
            if not p.is_file():
                continue
            # Skip ignored directories
            if any(ignored in p.parts for ignored in ignore_dirs):
                continue
            # Skip the file being modified
            if str(p.relative_to(repo_path)) == skip_file or str(p) == skip_file:
                continue
            # Only check code files
            if p.suffix.lower() not in CODE_EXTENSIONS:
                continue

            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
                if target_pattern.search(content):
                    return True
            except Exception:
                continue
    except Exception:
        pass

    return False


def detect_feature_removals(
    file_diff: FileDiff,
    all_added_lines_by_name: Optional[Set[str]] = None,
    repo_dir: str = "."
) -> List[CodeChange]:
    """
    STEP 2D: Detect removed functions or classes in a FileDiff.
    Ensures feature is NOT added back anywhere in the diff, and does NOT exist
    elsewhere in the repo.
    """
    changes: List[CodeChange] = []

    # Features added in this file
    added_in_file = set()
    for line in file_diff.added_lines:
        feat = extract_feature_name(line.content)
        if feat:
            added_in_file.add(feat)

    # Features removed in this file
    removed_features: List[Tuple[str, int]] = []
    for line in file_diff.removed_lines:
        feat = extract_feature_name(line.content)
        if feat:
            removed_features.append((feat, line.line_number))

    for feat_name, line_num in removed_features:
        # 1. Must NOT be in added lines of this file
        if feat_name in added_in_file:
            continue

        # 2. Must NOT be added in any other modified file in the diff
        if all_added_lines_by_name and feat_name in all_added_lines_by_name:
            continue

        # 3. Must NOT exist elsewhere in the repo
        if exists_elsewhere_in_repo(feat_name, repo_dir, file_diff.file_path):
            continue

        changes.append(
            CodeChange(
                change_type="FEATURE_REMOVED",
                name=feat_name,
                file=file_diff.file_path,
                line=line_num,
                details={
                    "kind": "function_or_class",
                    "raw_diff": f"- deleted {feat_name}"
                }
            )
        )

    return changes

