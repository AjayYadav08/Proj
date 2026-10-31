"""
utils/doc_finder.py
===================
STEP 3 & STEP 4: FIND RELATED DOCUMENTATION & DETECT DRIFT

Walks the repository documentation files (.md, .rst, .txt, .adoc):
1. Normalizes identifier names across formatting conventions:
   `DEFAULT_TIMEOUT` == `default_timeout` == `default-timeout` == `default timeout` == `defaultTimeout`.
2. Searches documentation files for matches.
3. Extracts the EXACT sentence or table cell where the reference appears.
4. Detects DRIFT by cross-referencing code changes with documentation content:
   - DEFAULT_VALUE_CHANGED: Only flags if the OLD value appears in the doc line/sentence!
   - FLAG_RENAMED: Flags if the OLD flag or config key appears.
   - PARAM_CHANGED: Flags if removed parameter or old default appears in doc.
   - FEATURE_REMOVED: Flags if removed feature is documented.
5. Computes confidence score (HIGH, MEDIUM, LOW) and generates actionable fix suggestions.
"""

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from detectors import CodeChange


DOC_EXTENSIONS = {".md", ".rst", ".txt", ".adoc", ".markdown", ".mdown"}
IGNORE_DIRS = {
    ".git", "node_modules", "venv", ".venv", "dist", "build",
    "__pycache__", ".tox", ".eggs", ".mypy_cache", ".pytest_cache"
}


@dataclass
class DocMatch:
    """Represents a location in documentation matching a code change identifier."""
    file_path: str
    line_number: int
    line_content: str
    sentence: str
    matched_variant: str


@dataclass
class DriftIssue:
    """Represents a confirmed or potential documentation drift issue."""
    issue_type: str        # DEFAULT_VALUE_CHANGED, FLAG_RENAMED, PARAM_CHANGED, FEATURE_REMOVED
    confidence: str        # HIGH, MEDIUM, LOW
    doc_file: str          # File path to documentation
    doc_line: int          # Line number in doc
    doc_sentence: str      # Exact documentation sentence that is wrong
    code_file: str         # File path to code change
    code_line: int         # Line number in code
    code_name: str         # Identifier name (e.g. DEFAULT_TIMEOUT, --timeout)
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    old_name: Optional[str] = None
    new_name: Optional[str] = None
    suggestion: str = ""   # Suggested fix
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert drift issue to JSON-serializable dictionary."""
        data = {
            "type": self.issue_type,
            "confidence": self.confidence,
            "doc_location": {
                "file": self.doc_file,
                "line": self.doc_line,
                "sentence": self.doc_sentence,
            },
            "code_reference": {
                "file": self.code_file,
                "line": self.code_line,
                "name": self.code_name,
            },
            "suggestion": self.suggestion,
        }
        if self.old_value is not None:
            data["old_value"] = self.old_value
        if self.new_value is not None:
            data["new_value"] = self.new_value
        if self.old_name is not None:
            data["old_name"] = self.old_name
        if self.new_name is not None:
            data["new_name"] = self.new_name
        if self.details:
            data["details"] = self.details
        return data


def find_documentation_files(
    repo_dir: str = ".",
    custom_docs_dir: Optional[str] = None
) -> List[Path]:
    """
    STEP 3.1: Walk repo or docs directory to collect all documentation files.
    Skips ignored directories (.git, node_modules, venv, etc.).
    """
    search_root = Path(custom_docs_dir) if custom_docs_dir else Path(repo_dir)
    doc_files: List[Path] = []

    if not search_root.exists():
        return doc_files

    for path in search_root.rglob("*"):
        if not path.is_file():
            continue
        # Skip ignored directories
        if any(ignored in path.parts for ignored in IGNORE_DIRS):
            continue
        # Check documentation extension
        if path.suffix.lower() in DOC_EXTENSIONS:
            doc_files.append(path)

    return sorted(doc_files)


def generate_name_variants(name: str) -> List[str]:
    """
    STEP 3.2: Generates case-insensitive and normalized variants of an identifier.
    DEFAULT_TIMEOUT -> ['DEFAULT_TIMEOUT', 'default_timeout', 'default timeout', 'default-timeout', 'defaultTimeout']
    --dry-run -> ['--dry-run', 'dry-run', 'dry run', 'dry_run']
    """
    variants: Set[str] = set()
    cleaned = name.strip()
    if not cleaned:
        return []

    variants.add(cleaned)
    variants.add(cleaned.lower())
    variants.add(cleaned.upper())

    # Strip CLI dashes if present: --dry-run -> dry-run
    bare_name = cleaned.lstrip("-")
    if bare_name != cleaned:
        variants.add(bare_name)
        variants.add(bare_name.lower())

    # Split words by underscores or hyphens or camelCase
    words = re.split(r"[_\-\s]+", bare_name)
    if len(words) == 1 and not bare_name.isupper() and not bare_name.islower():
        # Might be camelCase or PascalCase: split on uppercase transitions
        words = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\b)", bare_name)

    if words:
        words_lower = [w.lower() for w in words if w]
        # space separated: "default timeout"
        variants.add(" ".join(words_lower))
        # underscore separated: "default_timeout"
        variants.add("_".join(words_lower))
        # hyphen separated: "default-timeout"
        variants.add("-".join(words_lower))
        # camelCase: "defaultTimeout"
        if len(words_lower) > 1:
            camel = words_lower[0] + "".join(w.capitalize() for w in words_lower[1:])
            variants.add(camel)
            # PascalCase: "DefaultTimeout"
            pascal = "".join(w.capitalize() for w in words_lower)
            variants.add(pascal)

    # Sort longer variants first to match most specific form
    return sorted(list(variants), key=lambda x: len(x), reverse=True)


def extract_exact_sentence(text_block: str, target: str) -> str:
    """
    STEP 3.3: Extracts the exact sentence or table cell containing the target string.
    Uses punctuation boundaries (. ? !), table row separators (|), or list bullets.
    """
    # If the text is a markdown table row
    if text_block.strip().startswith("|") and text_block.strip().endswith("|"):
        cells = [c.strip() for c in text_block.strip().split("|")[1:-1]]
        for cell in cells:
            if re.search(rf"\b{re.escape(target)}\b", cell, re.IGNORECASE) or target.lower() in cell.lower():
                return f"| {cell} |"
        return text_block.strip()

    # Split text by sentence terminators
    sentences = re.split(r"(?<=[.!?])\s+", text_block)
    for sentence in sentences:
        s_clean = sentence.strip()
        if not s_clean:
            continue
        # Check boundary match first, or substring match
        pattern = rf"\b{re.escape(target)}\b"
        if re.search(pattern, s_clean, re.IGNORECASE) or target.lower() in s_clean.lower():
            return s_clean

    # Fallback to the first non-empty line
    lines = [ln.strip() for ln in text_block.splitlines() if ln.strip()]
    return lines[0] if lines else text_block.strip()


def search_name_in_docs(
    name: str,
    doc_files: List[Path],
    repo_dir: str = "."
) -> List[DocMatch]:
    """
    STEP 3.4: Searches all documentation files for matches of the identifier variants.
    Returns list of DocMatch objects containing file, line number, content, and sentence.
    """
    matches: List[DocMatch] = []
    variants = generate_name_variants(name)
    repo_path = Path(repo_dir)

    for doc_file in doc_files:
        try:
            content = doc_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        rel_path = str(doc_file.relative_to(repo_path)) if doc_file.is_relative_to(repo_path) else str(doc_file)
        lines = content.splitlines()

        for line_idx, line in enumerate(lines, start=1):
            line_str = line.strip()
            if not line_str:
                continue

            for variant in variants:
                # Use regex word boundary where applicable, or exact token match
                escaped = re.escape(variant)
                if variant.startswith("-"):
                    pattern = rf"(?:^|\s|`){escaped}(?:$|\s|`|[.,:;])"
                else:
                    pattern = rf"\b{escaped}\b"

                if re.search(pattern, line_str, re.IGNORECASE):
                    sentence = extract_exact_sentence(line_str, variant)
                    matches.append(
                        DocMatch(
                            file_path=rel_path,
                            line_number=line_idx,
                            line_content=line,
                            sentence=sentence,
                            matched_variant=variant
                        )
                    )
                    break  # Matched one variant on this line, proceed to next line

    return matches


def check_value_in_text(val: str, text: str) -> bool:
    """
    Checks if an old value appears in a text sentence.
    Handles numbers, booleans, strings, and unit suffixes (e.g. 30 -> 30s, 30 seconds).
    """
    if not val:
        return False

    clean_v = val.strip().strip("'\"")
    if not clean_v:
        return False

    # Boolean values
    if clean_v.lower() in ("true", "false"):
        return bool(re.search(rf"\b{clean_v}\b", text, re.IGNORECASE))

    # Numeric values (e.g. 30 -> 30, 30s, 30 ms, 30 seconds)
    if clean_v.isdigit() or re.match(r"^\d+(?:\.\d+)?$", clean_v):
        num_pattern = rf"\b{re.escape(clean_v)}(?:\s*(?:s|sec|seconds|ms|m|minutes|h|hours|px|kb|mb|gb))?\b"
        return bool(re.search(num_pattern, text, re.IGNORECASE))

    # General string / token match
    escaped_v = re.escape(clean_v)
    return bool(re.search(rf"\b{escaped_v}\b", text, re.IGNORECASE) or clean_v.lower() in text.lower())


def detect_drift_for_change(
    change: CodeChange,
    doc_matches: List[DocMatch]
) -> List[DriftIssue]:
    """
    STEP 4: DETECT DRIFT (the smart part)
    Decides whether each (code_change, doc_match) pair is truly drift:

    1. DEFAULT_VALUE_CHANGED:
       - Flag ONLY IF the OLD value appears in the doc line (e.g. "30" or "30 seconds").
       - If only the name appears without the old value, SKIP (avoid false alarms!).
       - Confidence: HIGH (exact name match + old value present in doc).
    2. FLAG_RENAMED:
       - Flag IF the OLD flag name appears in docs.
       - Confidence: HIGH (exact flag match) or MEDIUM (config key rename).
    3. PARAM_CHANGED:
       - Flag IF doc mentions removed/renamed parameter or old signature/default.
       - Confidence: HIGH if removed param or old default is in doc; MEDIUM if func mentioned.
    4. FEATURE_REMOVED:
       - Flag IF doc mentions the removed feature.
       - Confidence: HIGH if code block or backticks reference; MEDIUM if prose mention.
    """
    issues: List[DriftIssue] = []

    for match in doc_matches:
        sentence = match.sentence

        # ---------------------------------------------------------
        # Case A: DEFAULT_VALUE_CHANGED
        # ---------------------------------------------------------
        if change.change_type == "DEFAULT_VALUE_CHANGED":
            old_val = change.old_value or ""
            new_val = change.new_value or ""

            # SMART FILTER: ONLY flag if the old value is present in doc line/sentence!
            if check_value_in_text(old_val, sentence) or check_value_in_text(old_val, match.line_content):
                # High confidence: exact name or variant + old value confirmed
                confidence = "HIGH"
                suggestion = f"Update default value from '{old_val}' to '{new_val}'"
                issues.append(
                    DriftIssue(
                        issue_type="DEFAULT_VALUE_CHANGED",
                        confidence=confidence,
                        doc_file=match.file_path,
                        doc_line=match.line_number,
                        doc_sentence=sentence,
                        code_file=change.file,
                        code_line=change.line,
                        code_name=change.name,
                        old_value=old_val,
                        new_value=new_val,
                        suggestion=suggestion,
                        details={"matched_variant": match.matched_variant}
                    )
                )
            else:
                # If only the name appears without old value, SKIP to avoid false alarms!
                continue

        # ---------------------------------------------------------
        # Case B: FLAG_RENAMED
        # ---------------------------------------------------------
        elif change.change_type == "FLAG_RENAMED":
            old_name = change.old_name or change.name
            new_name = change.new_name or ""

            # Flag IF old flag name appears in doc sentence/line
            if old_name.lower() in match.line_content.lower():
                confidence = "HIGH" if old_name.startswith("-") else "MEDIUM"
                suggestion = f"Rename flag/key '{old_name}' to '{new_name}'"
                issues.append(
                    DriftIssue(
                        issue_type="FLAG_RENAMED",
                        confidence=confidence,
                        doc_file=match.file_path,
                        doc_line=match.line_number,
                        doc_sentence=sentence,
                        code_file=change.file,
                        code_line=change.line,
                        code_name=old_name,
                        old_name=old_name,
                        new_name=new_name,
                        suggestion=suggestion,
                        details=change.details
                    )
                )

        # ---------------------------------------------------------
        # Case C: PARAM_CHANGED
        # ---------------------------------------------------------
        elif change.change_type == "PARAM_CHANGED":
            removed_params = change.details.get("removed_params", [])
            modified_defaults = change.details.get("modified_defaults", {})

            # Check if any removed parameter is cited in the doc
            found_removed_p = [p for p in removed_params if p.lower() in match.line_content.lower()]

            # Check if any old default value is cited
            found_old_default = False
            default_details = []
            for p_name, (old_def, new_def) in modified_defaults.items():
                if check_value_in_text(old_def, sentence) or p_name.lower() in match.line_content.lower():
                    found_old_default = True
                    default_details.append(f"{p_name}={new_def}")

            if found_removed_p or found_old_default:
                confidence = "HIGH"
                if found_removed_p:
                    suggestion = f"Remove parameter(s) '{', '.join(found_removed_p)}' from documentation or signature"
                else:
                    suggestion = f"Update parameter defaults: {', '.join(default_details)}"

                issues.append(
                    DriftIssue(
                        issue_type="PARAM_CHANGED",
                        confidence=confidence,
                        doc_file=match.file_path,
                        doc_line=match.line_number,
                        doc_sentence=sentence,
                        code_file=change.file,
                        code_line=change.line,
                        code_name=change.name,
                        old_value=change.old_value,
                        new_value=change.new_value,
                        suggestion=suggestion,
                        details={
                            "removed_params": found_removed_p,
                            "modified_defaults": modified_defaults
                        }
                    )
                )
            else:
                # Function name matches, but no specific removed param was mentioned
                confidence = "MEDIUM"
                suggestion = f"Verify signature for '{change.name}({change.new_value})'"
                issues.append(
                    DriftIssue(
                        issue_type="PARAM_CHANGED",
                        confidence=confidence,
                        doc_file=match.file_path,
                        doc_line=match.line_number,
                        doc_sentence=sentence,
                        code_file=change.file,
                        code_line=change.line,
                        code_name=change.name,
                        old_value=change.old_value,
                        new_value=change.new_value,
                        suggestion=suggestion,
                        details=change.details
                    )
                )

        # ---------------------------------------------------------
        # Case D: FEATURE_REMOVED
        # ---------------------------------------------------------
        elif change.change_type == "FEATURE_REMOVED":
            # Check if reference is in code blocks or backticks
            is_code_ref = f"`{change.name}`" in match.line_content or f"{change.name}(" in match.line_content
            confidence = "HIGH" if is_code_ref else "MEDIUM"
            suggestion = f"Remove reference to deleted feature '{change.name}' or mark as deprecated/removed"

            issues.append(
                DriftIssue(
                    issue_type="FEATURE_REMOVED",
                    confidence=confidence,
                    doc_file=match.file_path,
                    doc_line=match.line_number,
                    doc_sentence=sentence,
                    code_file=change.file,
                    code_line=change.line,
                    code_name=change.name,
                    suggestion=suggestion,
                    details=change.details
                )
            )

    return issues

