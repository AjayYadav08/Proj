"""
detectors/default_value.py
==========================
STEP 2A: DEFAULT VALUE CHANGED DETECTOR

Detects when default values, configuration constants, or parameter defaults have
changed in code files.

Patterns handled:
1. Python:
   - UPPER_CASE constants: `DEFAULT_TIMEOUT = 30` -> `DEFAULT_TIMEOUT = 60`
   - Lowercase config variables: `timeout = 30` -> `timeout = 60`
   - Dictionary key/value defaults: `"timeout": 30` -> `"timeout": 60`
   - Function parameter default values: `def foo(timeout=30)` -> `def foo(timeout=60)`
2. YAML / TOML / JSON:
   - `timeout: 30` -> `timeout: 60`
   - `port = 8080` -> `port = 9000`
3. .env / .ini / .cfg files:
   - `DEFAULT_PORT=3000` -> `DEFAULT_PORT=8080`

Output:
  CodeChange(type="DEFAULT_VALUE_CHANGED", name=..., old_value=..., new_value=..., file=..., line=...)
"""

from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple

from utils.diff_parser import FileDiff, DiffLine
from . import CodeChange


def clean_value(val: str) -> str:
    """
    Strips surrounding whitespace, quotes, trailing commas, and trailing comments.
    E.g. '"30",  # timeout in seconds' -> '30'
    """
    if not val:
        return ""
    val = val.strip()
    # Strip inline comments (e.g., # or //)
    val = re.sub(r"\s*(?:#|//).*$", "", val).strip()
    # Strip trailing commas
    val = val.rstrip(",;").strip()
    # Strip matching surrounding quotes
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        val = val[1:-1]
    return val.strip()


def extract_assignment(line_text: str) -> Optional[Tuple[str, str]]:
    """
    Extracts variable/key name and assigned value from a line of code or config.
    Supports:
      - Variable assignment: `NAME = VALUE` or `self.name = VALUE`
      - Dictionary / YAML / JSON: `'key': value`, `"key": value`, `key: value`
      - TOML / .env: `KEY = VALUE`, `KEY=VALUE`
    """
    stripped = line_text.strip()
    if not stripped or stripped.startswith(("#", "//", "/*", "*")):
        return None

    # Pattern 1: Dict or YAML/JSON style -> "key": value or key: value
    dict_match = re.match(r"^['\"]?([a-zA-Z0-9_\.\-]+)['\"]?\s*:\s*([^#\n]+)", stripped)
    if dict_match:
        name = dict_match.group(1).strip()
        val = clean_value(dict_match.group(2))
        return name, val

    # Pattern 2: Assignment style -> NAME = VALUE or self.NAME = VALUE
    assign_match = re.match(r"^(?:(?:self|cls)\.)?([a-zA-Z0-9_\.\-]+)\s*=\s*([^#\n]+)", stripped)
    if assign_match:
        name = assign_match.group(1).strip()
        val = clean_value(assign_match.group(2))
        return name, val

    # Pattern 3: Function kwarg default within a def/function line: def foo(..., name=value, ...)
    kwarg_match = re.findall(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*([a-zA-Z0-9_\"'\.\-]+)", stripped)
    # If it's a def line with a single kwarg change or we need to extract kwargs
    if stripped.startswith("def ") or stripped.startswith("function "):
        # Return first kwarg match if any
        if kwarg_match:
            return kwarg_match[0][0], clean_value(kwarg_match[0][1])

    return None


def detect_default_values(file_diff: FileDiff) -> List[CodeChange]:
    """
    STEP 2A: Detect changed default values in a FileDiff.
    Compares removed lines (-) against added lines (+) looking for identical
    variable/key names whose values differ.
    """
    changes: List[CodeChange] = []

    # Map removed assignments: name -> (old_value, line_number)
    removed_assignments: Dict[str, Tuple[str, int]] = {}

    for line in file_diff.removed_lines:
        extracted = extract_assignment(line.content)
        if extracted:
            name, old_val = extracted
            # Only store non-empty values
            if old_val:
                removed_assignments[name] = (old_val, line.line_number)

    # Now inspect added lines to find matching names with new values
    matched_names = set()
    for line in file_diff.added_lines:
        extracted = extract_assignment(line.content)
        if extracted:
            name, new_val = extracted
            if name in removed_assignments:
                old_val, old_line_num = removed_assignments[name]
                # Only flag if value has actually changed!
                if old_val != new_val and name not in matched_names:
                    matched_names.add(name)
                    changes.append(
                        CodeChange(
                            change_type="DEFAULT_VALUE_CHANGED",
                            name=name,
                            file=file_diff.file_path,
                            line=line.line_number,
                            old_value=old_val,
                            new_value=new_val,
                            details={
                                "old_line": old_line_num,
                                "new_line": line.line_number,
                                "raw_diff": f"- {name} = {old_val} / + {name} = {new_val}"
                            }
                        )
                    )

    return changes

