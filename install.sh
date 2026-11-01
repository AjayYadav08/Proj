#!/bin/sh
# DocDrift One-Command Setup
# Usage: curl -fsSL https://raw.githubusercontent.com/AjayYadav08/Proj/main/install.sh | sh

set -e

REPO="https://github.com/AjayYadav08/Proj.git"
SUBDIR="doc-drift-detector"
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo "${CYAN}  ╔══════════════════════════════════════════════════════╗${NC}"
echo "${CYAN}  ║   DocDrift — Fast Automated Setup                    ║${NC}"
echo "${CYAN}  ╚══════════════════════════════════════════════════════╝${NC}"
echo ""

# Check Python
if ! command -v python3 >/dev/null 2>&1; then
  echo "${RED}✗ Python 3 not found. Please install Python 3.9+ from https://python.org${NC}"
  exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [ "$PYTHON_VERSION" -lt 9 ]; then
  echo "${RED}✗ Python 3.9+ required. Found: $(python3 --version)${NC}"
  exit 1
fi

echo "  ✔ Python $(python3 --version | awk '{print $2}') verified"

# Check pip
if ! command -v pip3 >/dev/null 2>&1; then
  echo "${RED}✗ pip3 not found. Run: python3 -m ensurepip${NC}"
  exit 1
fi

echo "  ✔ pip verified"
echo "  → Installing docdrift CLI..."

# Install globally / user environment
pip3 install --quiet \
  "git+${REPO}#subdirectory=${SUBDIR}" \
  2>/dev/null || \
pip3 install --quiet --break-system-packages \
  "git+${REPO}#subdirectory=${SUBDIR}"

echo "${GREEN}  ✔ docdrift CLI installed globally${NC}"

# Check if inside a git repository
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo ""
  echo "  📦 Git repository detected!"
  echo "  → Configuring automatic GitHub Actions PR workflow..."
  
  mkdir -p .github/workflows
  cat << 'EOF' > .github/workflows/doc-drift.yml
name: Documentation Drift Detection

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
          echo "Comparing base ($BASE_SHA) with head ($HEAD_SHA)..."

          # 1. Output GitHub Annotations inline on changed files
          docdrift --base "$BASE_SHA" --head "$HEAD_SHA" --format github || true

          # 2. Add Markdown Summary to PR Check report
          docdrift --base "$BASE_SHA" --head "$HEAD_SHA" --format markdown >> $GITHUB_STEP_SUMMARY || true

          # 3. Block PR merge if high confidence documentation drift is detected
          docdrift --base "$BASE_SHA" --head "$HEAD_SHA" --fail-on high
EOF

  echo "${GREEN}  ✔ Created .github/workflows/doc-drift.yml${NC}"
  echo ""
  echo "${YELLOW}  👉 Just push to activate automatic PR checks:${NC}"
  echo "     git add .github/workflows/doc-drift.yml"
  echo "     git commit -m 'ci: enable automatic documentation drift checks'"
  echo "     git push"
else
  echo ""
  echo "  ℹ️ To enable automatic PR checks in any repo, cd into it and run:"
  echo "     docdrift init"
fi

echo ""
echo "${GREEN}  🎉 All done!${NC}"
echo "     Run 'docdrift --help' for CLI options."
echo ""
