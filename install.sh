#!/bin/sh
# DocDrift Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/AjayYadav08/Proj/main/install.sh | sh

set -e

REPO="https://github.com/AjayYadav08/Proj.git"
SUBDIR="doc-drift-detector"
CYAN='\033[0;36m'
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo "${CYAN}  ╔══════════════════════════════════════╗${NC}"
echo "${CYAN}  ║   DocDrift — Installing...           ║${NC}"
echo "${CYAN}  ╚══════════════════════════════════════╝${NC}"
echo ""

# Check Python
if ! command -v python3 >/dev/null 2>&1; then
  echo "${RED}✗ Python 3 not found. Install it from https://python.org${NC}"
  exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [ "$PYTHON_VERSION" -lt 9 ]; then
  echo "${RED}✗ Python 3.9+ required. Found: $(python3 --version)${NC}"
  exit 1
fi

echo "  ✔ Python $(python3 --version) found"

# Check pip
if ! command -v pip3 >/dev/null 2>&1; then
  echo "${RED}✗ pip3 not found. Run: python3 -m ensurepip${NC}"
  exit 1
fi

echo "  ✔ pip found"
echo "  → Installing docdrift..."

# Install
pip3 install --quiet \
  "git+${REPO}#subdirectory=${SUBDIR}" \
  2>/dev/null || \
pip3 install --quiet --break-system-packages \
  "git+${REPO}#subdirectory=${SUBDIR}"

echo ""
echo "${GREEN}  ✔ docdrift installed successfully!${NC}"
echo ""
echo "  Usage:"
echo "    docdrift --base main --head your-branch"
echo "    docdrift --diff-file changes.diff"
echo "    docdrift --base main --head your-branch --ai"
echo ""
echo "  Run 'docdrift --help' for all options."
echo ""
