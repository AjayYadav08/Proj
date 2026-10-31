"""
detectors/flag_rename.py
========================
STEP 2B: FLAG & CONFIG KEY RENAMED DETECTOR

Detects when CLI flags or configuration keys have been renamed:
1. CLI Flags:
   Lines containing `--old-flag` removed, and `--new-flag` added.
   Supports argparse (`add_argument('--old-flag')`), click (`@click.option('--old-flag')`),
   typer, docstrings, or custom CLI frameworks.
2. Config Key Renames:
   `old_key: <value>` removed, and `new_key: <value>` added where the value is
   identical or nearly identical.

Output:
  CodeChange(type="FLAG_RENAMED", name=old_name, old_name=old_name, new_name=new_name, file=..., line=...)
"""

from pathlib import Path
import re
from typing import Dict, List, Optional, Set, Tuple

from utils.diff_parser import FileDiff, DiffLine
from . import CodeChange
from .default_value import clean_value, extract_assignment


# Regex for finding CLI flags like --flag-name or --flag_name
CLI_FLAG_REGEX = re.compile(r"(--[a-zA-Z0-9][a-zA-Z0-9_\-]*)")


def extract_flags_from_line(line_text: str) -> List[str]:
    """Extract all CLI flag mentions (e.g. '--timeout', '--dry-run') from a line."""
    return CLI_FLAG_REGEX.findall(line_text)


def detect_flag_renames(file_diff: FileDiff) -> List[CodeChange]:
    """
    STEP 2B: Detect renamed CLI flags and config keys in a FileDiff.
    """
    changes: List[CodeChange] = []
    already_flagged_old_names: Set[str] = set()

    # -------------------------------------------------------------
    # 1. Detect CLI flag renames: --old-flag -> --new-flag
    # -------------------------------------------------------------
    # First check per hunk for tight locality
    for hunk in file_diff.hunks:
        removed_flags: List[Tuple[str, int]] = []
        for line in hunk.removed_lines:
            flags = extract_flags_from_line(line.content)
            for f in flags:
                removed_flags.append((f, line.line_number))

        added_flags: List[Tuple[str, int]] = []
        for line in hunk.added_lines:
            flags = extract_flags_from_line(line.content)
            for f in flags:
                added_flags.append((f, line.line_number))

        # Check for flags present in removed but replaced in added
        rem_set = {f for f, _ in removed_flags}
        add_set = {f for f, _ in added_flags}
        truly_removed = [item for item in removed_flags if item[0] not in add_set]
        truly_added = [item for item in added_flags if item[0] not in rem_set]

        # Pair them up if counts match or 1-to-1
        if len(truly_removed) == 1 and len(truly_added) == 1:
            old_flag, old_line = truly_removed[0]
            new_flag, new_line = truly_added[0]
            if old_flag not in already_flagged_old_names:
                already_flagged_old_names.add(old_flag)
                changes.append(
                    CodeChange(
                        change_type="FLAG_RENAMED",
                        name=old_flag,
                        old_name=old_flag,
                        new_name=new_flag,
                        file=file_diff.file_path,
                        line=new_line,
                        details={
                            "old_line": old_line,
                            "kind": "cli_flag",
                            "raw_diff": f"- {old_flag} / + {new_flag}"
                        }
                    )
                )
        elif len(truly_removed) > 1 and len(truly_added) > 1:
            # Pair by index if identical length
            limit = min(len(truly_removed), len(truly_added))
            for i in range(limit):
                old_flag, old_line = truly_removed[i]
                new_flag, new_line = truly_added[i]
                if old_flag not in already_flagged_old_names:
                    already_flagged_old_names.add(old_flag)
                    changes.append(
                        CodeChange(
                            change_type="FLAG_RENAMED",
                            name=old_flag,
                            old_name=old_flag,
                            new_name=new_flag,
                            file=file_diff.file_path,
                            line=new_line,
                            details={
                                "old_line": old_line,
                                "kind": "cli_flag",
                                "raw_diff": f"- {old_flag} / + {new_flag}"
                            }
                        )
                    )

    # -------------------------------------------------------------
    # 2. Detect Config Key Renames: old_key: val -> new_key: val
    # -------------------------------------------------------------
    # When a key changes name but the assigned value remains the exact same
    removed_keyed_values: Dict[str, Tuple[str, int]] = {}  # value -> (key_name, line_num)

    for line in file_diff.removed_lines:
        extracted = extract_assignment(line.content)
        if extracted:
            key, val = extracted
            # Only track meaningful non-trivial values (length > 1, not empty)
            if val and len(val) > 1:
                removed_keyed_values[val] = (key, line.line_number)

    for line in file_diff.added_lines:
        extracted = extract_assignment(line.content)
        if extracted:
            new_key, new_val = extracted
            if new_val in removed_keyed_values:
                old_key, old_line = removed_keyed_values[new_val]
                if old_key != new_key and old_key not in already_flagged_old_names:
                    already_flagged_old_names.add(old_key)
                    changes.append(
                        CodeChange(
                            change_type="FLAG_RENAMED",
                            name=old_key,
                            old_name=old_key,
                            new_name=new_key,
                            file=file_diff.file_path,
                            line=line.line_number,
                            details={
                                "old_line": old_line,
                                "kind": "config_key",
                                "common_value": new_val,
                                "raw_diff": f"- {old_key}: {new_val} / + {new_key}: {new_val}"
                            }
                        )
                    )

    return changes

