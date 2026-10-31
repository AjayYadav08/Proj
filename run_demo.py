#!/usr/bin/env python3
"""
run_demo.py
===========
Live Interactive Demonstration of Documentation Drift Detection.

Simulates a Pull Request that introduces multiple types of documentation drift:
1. Changed constant default value: DEFAULT_TIMEOUT = 30 -> 60 (doc says 30 seconds)
2. Renamed CLI flag: --legacy-auth -> --token-auth (doc says --legacy-auth)
3. Modified function parameter: def connect(url, timeout=30) -> def connect(url, timeout=60, retries=3)
4. Removed deprecated feature: def old_cleanup_cache() (doc mentions old_cleanup_cache)
"""

from pathlib import Path
import subprocess
import sys

# Ensure repository root is in python path
ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR / "doc-drift-detector"))

from drift_detector import execute_drift_detection
from utils.reporter import DriftReporter


DEMO_DOC_CONTENT = """# Antigravity Service Documentation

## Configuration & Defaults
The client initializes with sane defaults:
- The default timeout is 30 seconds before timing out.
- Maximum retry count is set to 3 attempts.

## Authentication
When configuring your authentication provider, pass `--legacy-auth` to enable compatibility mode.

## API Reference
### `connect(url, timeout=30)`
Establishes a connection to the remote cluster. Takes the server URL and timeout.

### `old_cleanup_cache()`
Call `old_cleanup_cache()` when shutting down workers to clear temporary files.
"""

SAMPLE_PR_DIFF = """diff --git a/src/settings.py b/src/settings.py
--- a/src/settings.py
+++ b/src/settings.py
@@ -10,1 +10,1 @@
-DEFAULT_TIMEOUT = 30
+DEFAULT_TIMEOUT = 60
@@ -25,1 +25,1 @@
-parser.add_argument("--legacy-auth", action="store_true")
+parser.add_argument("--token-auth", action="store_true")
diff --git a/src/client.py b/src/client.py
--- a/src/client.py
+++ b/src/client.py
@@ -15,1 +15,1 @@
-def connect(url, timeout=30):
+def connect(url, timeout=60, retries=3):
@@ -80,3 +80,0 @@
-def old_cleanup_cache():
-    pass
"""


def main():
    print("\n" + "=" * 70)
    print(" 🚀 RUNNING LIVE DOCUMENTATION DRIFT DETECTION DEMO")
    print("=" * 70)

    # Create temporary demo environment
    demo_dir = ROOT_DIR / ".demo_workspace"
    docs_dir = demo_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    demo_doc = docs_dir / "service_guide.md"
    demo_doc.write_text(DEMO_DOC_CONTENT, encoding="utf-8")

    print("\n1. Simulated PR Code Changes (git diff):")
    print("-" * 50)
    for line in SAMPLE_PR_DIFF.strip().splitlines()[:15]:
        print(f"  {line}")
    print("  ... [truncated for display]")

    print("\n2. Executing DocDrift Detection Pipeline...")
    result = execute_drift_detection(
        diff_text=SAMPLE_PR_DIFF,
        repo_dir=str(demo_dir),
        docs_dir=str(docs_dir),
        min_confidence="medium",
        verbose=False
    )

    reporter = DriftReporter(
        code_changes=result.code_changes,
        drift_issues=result.drift_issues,
        doc_files_scanned=result.doc_files_scanned,
        use_colors=True
    )

    print("\n3. Generated Report:")
    print(reporter.to_text())

    # Cleanup demo files
    try:
        import shutil
        shutil.rmtree(demo_dir)
    except Exception:
        pass


if __name__ == "__main__":
    main()

