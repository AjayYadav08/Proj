"""
utils/diff_parser.py
====================
STEP 1: PARSE PR DIFF

This module extracts and parses git diffs into structured code changes:
1. Obtains unified diff from git (e.g. `git diff <base>...<head> --unified=0`).
2. Parses git headers (`diff --git`, `--- a/...`, `+++ b/...`).
3. Tracks hunks (`@@ -old_start,old_count +new_start,new_count @@`) and extracts
   removed lines (-) and added lines (+) with accurate source line numbers.
4. Filters files to keep only target code file extensions (.py, .js, .ts, etc.),
   deliberately excluding docs and binary files from code analysis.
"""

from dataclasses import dataclass, field
from pathlib import Path
import re
import subprocess
from typing import List, Optional, Tuple


# Code extensions to analyze (as specified in requirements)
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".go", ".rs", ".java",
    ".yaml", ".yml", ".toml", ".json", ".env", ".cfg", ".ini"
}

# Documentation extensions to exclude from code diff parsing
DOC_EXTENSIONS = {".md", ".rst", ".txt", ".adoc", ".markdown"}


@dataclass
class DiffLine:
    """Represents a single line added or removed in a diff."""
    line_type: str  # '-' for removed, '+' for added
    content: str    # Raw line content without leading '-' or '+'
    line_number: int  # Source line number in old file (-) or new file (+)


@dataclass
class DiffHunk:
    """Represents a unified diff hunk."""
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    removed_lines: List[DiffLine] = field(default_factory=list)
    added_lines: List[DiffLine] = field(default_factory=list)


@dataclass
class FileDiff:
    """Represents diff changes belonging to a single code file."""
    file_path: str
    old_file_path: Optional[str] = None
    is_new: bool = False
    is_deleted: bool = False
    hunks: List[DiffHunk] = field(default_factory=list)
    removed_lines: List[DiffLine] = field(default_factory=list)
    added_lines: List[DiffLine] = field(default_factory=list)


def is_code_file(filepath: str) -> bool:
    """
    Check if a file qualifies as a code file based on extension and filename.
    Only considers .py, .js, .ts, .go, .rs, .java, .yaml, .yml, .toml, .json, .env, .cfg, .ini.
    Excludes documentation files (.md, .rst, etc.).
    """
    path = Path(filepath)
    ext = path.suffix.lower()
    name = path.name.lower()

    # Direct match on known extension
    if ext in CODE_EXTENSIONS:
        return True

    # Special handling for dotfiles like .env, .env.example, .env.local
    if name == ".env" or name.startswith(".env."):
        return True

    return False


def get_git_diff(
    base: Optional[str] = None,
    head: Optional[str] = None,
    repo_dir: str = "."
) -> str:
    """
    STEP 1.1: Fetch git diff from repository using subprocess.
    Uses `git diff <base>...<head> --unified=0`.
    Falls back gracefully if 3-dot merge-base is unavailable.
    """
    # Build candidate commands based on provided arguments
    commands_to_try = []

    if base and head:
        # Preferred PR diff: three-dot merge base
        commands_to_try.append(["git", "diff", f"{base}...{head}", "--unified=0"])
        # Fallback to direct two-dot diff
        commands_to_try.append(["git", "diff", base, head, "--unified=0"])
    elif base:
        commands_to_try.append(["git", "diff", f"{base}...HEAD", "--unified=0"])
        commands_to_try.append(["git", "diff", base, "--unified=0"])
    elif head:
        commands_to_try.append(["git", "diff", f"{head}~1...{head}", "--unified=0"])
    else:
        # Default behavior: compare working tree against HEAD, or HEAD~1 against HEAD
        commands_to_try.append(["git", "diff", "HEAD", "--unified=0"])
        commands_to_try.append(["git", "diff", "HEAD~1", "HEAD", "--unified=0"])

    errors = []
    for cmd in commands_to_try:
        try:
            result = subprocess.run(
                cmd,
                cwd=repo_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False
            )
            if result.returncode == 0:
                return result.stdout
            else:
                errors.append(f"Command {' '.join(cmd)} failed: {result.stderr.strip()}")
        except Exception as e:
            errors.append(f"Error running {' '.join(cmd)}: {str(e)}")

    # If all attempts failed or returned empty in non-git environment, raise informative error
    raise RuntimeError(
        f"Unable to retrieve git diff. Attempts:\n" + "\n".join(errors)
    )


def parse_diff(diff_text: str) -> List[FileDiff]:
    """
    STEP 1.2: Parse git diff into structured FileDiff objects.
    - Identifies which file each change belongs to (+++ b/file.py header).
    - Filters only code files (.py, .js, .yaml, etc.).
    - Tracks line numbers for added (+) and removed (-) lines.
    """
    files: List[FileDiff] = []
    current_file: Optional[FileDiff] = None
    current_hunk: Optional[DiffHunk] = None

    old_line_cursor = 0
    new_line_cursor = 0

    hunk_regex = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")

    lines = diff_text.splitlines()

    for line in lines:
        # Check for new file diff header: diff --git a/path b/path
        if line.startswith("diff --git "):
            current_file = None
            current_hunk = None
            continue

        # Check for file deletion / new file markers
        if line.startswith("--- "):
            old_path = line[4:].strip()
            if old_path.startswith("a/"):
                old_path = old_path[2:]
            if current_file:
                current_file.old_file_path = old_path
            continue

        if line.startswith("+++ "):
            new_path = line[4:].strip()
            if new_path.startswith("b/"):
                new_path = new_path[2:]
            elif new_path == "/dev/null":
                # File was deleted
                if current_file:
                    current_file.is_deleted = True
                continue

            # Check if this file qualifies as a code file
            if is_code_file(new_path):
                current_file = FileDiff(file_path=new_path)
                files.append(current_file)
            else:
                current_file = None  # Skip non-code file (docs, assets, etc.)
            continue

        if current_file is None:
            continue

        # Check for hunk header: @@ -old_start,old_count +new_start,new_count @@
        hunk_match = hunk_regex.match(line)
        if hunk_match:
            old_start = int(hunk_match.group(1))
            old_count = int(hunk_match.group(2)) if hunk_match.group(2) else 1
            new_start = int(hunk_match.group(3))
            new_count = int(hunk_match.group(4)) if hunk_match.group(4) else 1

            current_hunk = DiffHunk(
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count
            )
            current_file.hunks.append(current_hunk)

            old_line_cursor = old_start
            new_line_cursor = new_start
            continue

        # If we are inside a hunk, process changed lines
        if current_hunk is not None:
            if line.startswith("-") and not line.startswith("---"):
                content = line[1:]
                diff_line = DiffLine(
                    line_type="-",
                    content=content,
                    line_number=old_line_cursor
                )
                current_hunk.removed_lines.append(diff_line)
                current_file.removed_lines.append(diff_line)
                old_line_cursor += 1

            elif line.startswith("+") and not line.startswith("+++"):
                content = line[1:]
                diff_line = DiffLine(
                    line_type="+",
                    content=content,
                    line_number=new_line_cursor
                )
                current_hunk.added_lines.append(diff_line)
                current_file.added_lines.append(diff_line)
                new_line_cursor += 1

            elif line.startswith(" "):
                # Context line (if unified > 0)
                old_line_cursor += 1
                new_line_cursor += 1

    return files

