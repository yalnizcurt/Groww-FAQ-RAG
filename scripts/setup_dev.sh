#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# setup_dev.sh  –  Set up the local development environment for mf_faq
#
# Usage:
#   cd /path/to/Groww-FAQ-RAG
#   bash scripts/setup_dev.sh
#
# What it does:
#   1. Detects / installs Python 3.11 (via pyenv or brew)
#   2. Creates .venv in the project root
#   3. Installs CPU-only torch==2.7.0 (compatible with numpy 2.4.x)
#   4. Installs all backend/requirements.txt
#   5. Installs playwright chromium
# ─────────────────────────────────────────────────────────────────────────────
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$REPO_ROOT/backend"
VENV="$REPO_ROOT/.venv"

echo "==> Repo root: $REPO_ROOT"

# ── 1. Locate Python 3.11+ ──────────────────────────────────────────────────
PYTHON=""
for candidate in python3.13 python3.12 python3.11; do
    if command -v "$candidate" &>/dev/null; then
        VER=$("$candidate" -c "import sys; print(sys.version_info[:2])")
        if [[ "$VER" > "(3, 10)" ]]; then
            PYTHON=$(command -v "$candidate")
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "Python 3.11+ not found. Installing via pyenv..."
    if ! command -v pyenv &>/dev/null; then
        echo "Installing pyenv first..."
        curl https://pyenv.run | bash
        export PYENV_ROOT="$HOME/.pyenv"
        export PATH="$PYENV_ROOT/bin:$PATH"
        eval "$(pyenv init -)"
    fi
    pyenv install -s 3.11.9
    pyenv local 3.11.9
    PYTHON="$(pyenv which python)"
fi

echo "==> Using Python: $PYTHON ($($PYTHON --version))"

# ── 2. Create virtual environment ───────────────────────────────────────────
if [ ! -d "$VENV" ]; then
    echo "==> Creating virtual environment at $VENV..."
    "$PYTHON" -m venv "$VENV"
fi

PIP="$VENV/bin/pip"
PYTHON_VENV="$VENV/bin/python"

echo "==> Upgrading pip..."
"$PIP" install --upgrade pip

# ── 3. Install CPU-only PyTorch 2.7.0 first ─────────────────────────────────
# torch 2.7.0 is ABI-compatible with numpy 2.x (unlike 2.5.1 which predates numpy 2.4.x)
echo "==> Installing torch==2.7.0 (CPU-only)..."
"$PIP" install --no-cache-dir torch==2.7.0 --index-url https://download.pytorch.org/whl/cpu

# ── 4. Install all backend requirements ─────────────────────────────────────
echo "==> Installing backend/requirements.txt..."
"$PIP" install --no-cache-dir -r "$BACKEND/requirements.txt"

# ── 5. Install Playwright chromium ──────────────────────────────────────────
echo "==> Installing Playwright chromium..."
"$PYTHON_VENV" -m playwright install chromium --with-deps

echo ""
echo "✓ Dev environment ready!"
echo ""
echo "Activate with:  source .venv/bin/activate"
echo "Run pipeline:   cd backend && python -c \\"from mf_faq.ingestion.pipeline import refresh; import json; r = refresh(); print(json.dumps(r.to_dict(), indent=2, default=str))\\""
echo "Run tests:      cd backend && python -m tests.test_core"
