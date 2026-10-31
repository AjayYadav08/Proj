"""
tests/test_basic.py
===================
Comprehensive test suite for Documentation Drift Detector.
Covers diff parsing, semantic detectors, doc matching, sentence extraction,
and end-to-end drift reporting.
"""

from pathlib import Path
import pytest
import sys
import tempfile

# Add doc-drift-detector to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from detectors import (
    CodeChange,
    detect_default_values,
    detect_flag_renames,
    detect_param_changes,
    detect_feature_removals,
)
from utils.diff_parser import parse_diff, FileDiff, DiffLine, DiffHunk
from utils.doc_finder import (
    find_documentation_files,
    generate_name_variants,
    extract_exact_sentence,
    search_name_in_docs,
    check_value_in_text,
    detect_drift_for_change,
    DocMatch,
    DriftIssue,
)
from utils.reporter import DriftReporter
from drift_detector import execute_drift_detection


# =====================================================================
# 1. DIFF PARSER TESTS
# =====================================================================

SAMPLE_DIFF = """diff --git a/config.py b/config.py
--- a/config.py
+++ b/config.py
@@ -10,1 +10,1 @@
-DEFAULT_TIMEOUT = 30
+DEFAULT_TIMEOUT = 60
diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -5,1 +5,1 @@
-Old doc line
+New doc line
diff --git a/server.env b/server.env
--- a/server.env
+++ b/server.env
@@ -1,1 +1,1 @@
-PORT=3000
+PORT=8080
"""


def test_diff_parser_filters_code_files():
    file_diffs = parse_diff(SAMPLE_DIFF)
    file_paths = [fd.file_path for fd in file_diffs]

    # Must include code files (.py, .env) and exclude doc files (.md)
    assert "config.py" in file_paths
    assert "server.env" in file_paths
    assert "README.md" not in file_paths


def test_diff_parser_tracks_lines():
    file_diffs = parse_diff(SAMPLE_DIFF)
    config_diff = next(fd for fd in file_diffs if fd.file_path == "config.py")

    assert len(config_diff.removed_lines) == 1
    assert config_diff.removed_lines[0].content == "DEFAULT_TIMEOUT = 30"
    assert config_diff.removed_lines[0].line_number == 10

    assert len(config_diff.added_lines) == 1
    assert config_diff.added_lines[0].content == "DEFAULT_TIMEOUT = 60"
    assert config_diff.added_lines[0].line_number == 10


# =====================================================================
# 2. DEFAULT VALUE DETECTOR TESTS
# =====================================================================

def test_detect_default_value_python_constant():
    diff = FileDiff(
        file_path="src/settings.py",
        removed_lines=[DiffLine("-", "DEFAULT_TIMEOUT = 30", 15)],
        added_lines=[DiffLine("+", "DEFAULT_TIMEOUT = 60", 15)],
    )
    changes = detect_default_values(diff)
    assert len(changes) == 1
    assert changes[0].change_type == "DEFAULT_VALUE_CHANGED"
    assert changes[0].name == "DEFAULT_TIMEOUT"
    assert changes[0].old_value == "30"
    assert changes[0].new_value == "60"


def test_detect_default_value_yaml_json():
    diff = FileDiff(
        file_path="config.yaml",
        removed_lines=[DiffLine("-", "  max_retries: 3", 8)],
        added_lines=[DiffLine("+", "  max_retries: 5", 8)],
    )
    changes = detect_default_values(diff)
    assert len(changes) == 1
    assert changes[0].name == "max_retries"
    assert changes[0].old_value == "3", f"Got {changes[0].old_value}"
    assert changes[0].new_value == "5"


def test_detect_default_value_env():
    diff = FileDiff(
        file_path=".env",
        removed_lines=[DiffLine("-", "DATABASE_PORT=5432", 2)],
        added_lines=[DiffLine("+", "DATABASE_PORT=5433", 2)],
    )
    changes = detect_default_values(diff)
    assert len(changes) == 1
    assert changes[0].name == "DATABASE_PORT"
    assert changes[0].old_value == "5432"
    assert changes[0].new_value == "5433"


# =====================================================================
# 3. FLAG RENAMED DETECTOR TESTS
# =====================================================================

def test_detect_flag_renames_cli():
    hunk = DiffHunk(
        old_start=20, old_count=1, new_start=20, new_count=1,
        removed_lines=[DiffLine("-", 'parser.add_argument("--old-timeout", type=int)', 20)],
        added_lines=[DiffLine("+", 'parser.add_argument("--new-timeout", type=int)', 20)]
    )
    diff = FileDiff(
        file_path="cli.py",
        hunks=[hunk],
        removed_lines=hunk.removed_lines,
        added_lines=hunk.added_lines
    )
    changes = detect_flag_renames(diff)
    assert len(changes) == 1
    assert changes[0].change_type == "FLAG_RENAMED"
    assert changes[0].old_name == "--old-timeout"
    assert changes[0].new_name == "--new-timeout"


def test_detect_flag_renames_config_key():
    diff = FileDiff(
        file_path="config.json",
        hunks=[],
        removed_lines=[DiffLine("-", '"legacy_host": "api.example.com"', 12)],
        added_lines=[DiffLine("+", '"base_url": "api.example.com"', 12)]
    )
    changes = detect_flag_renames(diff)
    assert len(changes) == 1
    assert changes[0].change_type == "FLAG_RENAMED"
    assert changes[0].old_name == "legacy_host"
    assert changes[0].new_name == "base_url"


# =====================================================================
# 4. PARAMETER CHANGED DETECTOR TESTS
# =====================================================================

def test_detect_param_change_added_parameter():
    diff = FileDiff(
        file_path="client.py",
        removed_lines=[DiffLine("-", "def connect(host, port):", 30)],
        added_lines=[DiffLine("+", "def connect(host, port, ssl=True):", 30)]
    )
    changes = detect_param_changes(diff)
    assert len(changes) == 1
    assert changes[0].change_type == "PARAM_CHANGED"
    assert changes[0].name == "connect"
    assert "ssl=True" in changes[0].details["added_params"] or "ssl" in changes[0].details["added_params"]


def test_detect_param_change_modified_default():
    diff = FileDiff(
        file_path="client.py",
        removed_lines=[DiffLine("-", "def fetch(url, timeout=30):", 45)],
        added_lines=[DiffLine("+", "def fetch(url, timeout=60):", 45)]
    )
    changes = detect_param_changes(diff)
    assert len(changes) == 1
    assert "timeout" in changes[0].details["modified_defaults"]
    assert changes[0].details["modified_defaults"]["timeout"] == ("30", "60")


# =====================================================================
# 5. FEATURE REMOVED DETECTOR TESTS
# =====================================================================

def test_detect_feature_removal(tmp_path):
    repo_dir = str(tmp_path)
    # File being modified in diff
    mod_file = tmp_path / "legacy.py"
    mod_file.write_text("# empty file\n")

    diff = FileDiff(
        file_path="legacy.py",
        removed_lines=[DiffLine("-", "def deprecated_helper(data):", 50)],
        added_lines=[]
    )
    changes = detect_feature_removals(diff, repo_dir=repo_dir)
    assert len(changes) == 1
    assert changes[0].change_type == "FEATURE_REMOVED"
    assert changes[0].name == "deprecated_helper"


# =====================================================================
# 6. DOC FINDER & DRIFT ENGINE TESTS
# =====================================================================

def test_name_variants_normalization():
    variants = generate_name_variants("DEFAULT_TIMEOUT")
    assert "DEFAULT_TIMEOUT" in variants
    assert "default_timeout" in variants
    assert "default timeout" in variants
    assert "default-timeout" in variants


def test_extract_exact_sentence():
    paragraph = (
        "Antigravity client configuration guide. "
        "The DEFAULT_TIMEOUT is 30 seconds before closing socket. "
        "You can override this in production."
    )
    sentence = extract_exact_sentence(paragraph, "DEFAULT_TIMEOUT")
    assert sentence == "The DEFAULT_TIMEOUT is 30 seconds before closing socket."


def test_drift_default_value_smart_filter():
    # Scenario: Code changes DEFAULT_TIMEOUT from 30 to 60.
    change = CodeChange(
        change_type="DEFAULT_VALUE_CHANGED",
        name="DEFAULT_TIMEOUT",
        file="config.py",
        line=10,
        old_value="30",
        new_value="60"
    )

    # Doc 1: Mentions the name AND the old value (30) -> SHOULD FLAG!
    match1 = DocMatch(
        file_path="docs/guide.md",
        line_number=25,
        line_content="The default timeout is 30 seconds.",
        sentence="The default timeout is 30 seconds.",
        matched_variant="default timeout"
    )
    issues1 = detect_drift_for_change(change, [match1])
    assert len(issues1) == 1
    assert issues1[0].confidence == "HIGH"
    assert "30" in issues1[0].suggestion
    assert "60" in issues1[0].suggestion

    # Doc 2: Mentions the name WITHOUT the old value -> MUST SKIP (avoid false alarms)
    match2 = DocMatch(
        file_path="docs/api.md",
        line_number=100,
        line_content="Configure DEFAULT_TIMEOUT according to your cluster latency.",
        sentence="Configure DEFAULT_TIMEOUT according to your cluster latency.",
        matched_variant="DEFAULT_TIMEOUT"
    )
    issues2 = detect_drift_for_change(change, [match2])
    assert len(issues2) == 0, "False alarm: Should NOT flag when old value is absent!"


# =====================================================================
# 7. END-TO-END INTEGRATION TEST
# =====================================================================

def test_end_to_end_pipeline(tmp_path):
    repo_dir = tmp_path
    docs_dir = repo_dir / "docs"
    docs_dir.mkdir(parents=True)

    # Create documentation files
    doc_file = docs_dir / "settings.md"
    doc_file.write_text(
        "# Settings Guide\n\n"
        "By default, the DEFAULT_TIMEOUT is 30 seconds.\n"
        "Pass the `--old-flag` to enable legacy streaming.\n"
        "Always call `fetch_old_stats()` on startup.\n"
    )

    # Git diff simulating PR changes
    diff_content = """diff --git a/settings.py b/settings.py
--- a/settings.py
+++ b/settings.py
@@ -5,1 +5,1 @@
-DEFAULT_TIMEOUT = 30
+DEFAULT_TIMEOUT = 60
@@ -20,1 +20,1 @@
-parser.add_argument("--old-flag")
+parser.add_argument("--new-flag")
@@ -50,3 +50,0 @@
-def fetch_old_stats():
-    pass
"""

    result = execute_drift_detection(
        diff_text=diff_content,
        repo_dir=str(repo_dir),
        docs_dir=str(docs_dir),
        min_confidence="medium",
        verbose=False
    )

    # Verify detected issues
    assert len(result.code_changes) >= 3
    assert len(result.drift_issues) >= 2

    reporter = DriftReporter(result.code_changes, result.drift_issues, result.doc_files_scanned)
    text_report = reporter.to_text()
    json_report = reporter.to_json()

    assert "DOCUMENTATION DRIFT DETECTOR" in text_report
    assert "DEFAULT_TIMEOUT" in text_report
    assert "30" in text_report
    assert "60" in text_report
    assert '"summary"' in json_report
    assert '"drift_issues"' in json_report

    # Test auto-fix functionality
    from utils.doc_finder import apply_autofixes
    fixed_count, logs = apply_autofixes(result.drift_issues, repo_dir=str(repo_dir))
    assert fixed_count >= 1

    # Verify that the documentation file on disk was modified with the fix
    updated_doc = doc_file.read_text(encoding="utf-8")
    assert "60 seconds" in updated_doc
    assert "--new-flag" in updated_doc

