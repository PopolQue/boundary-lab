#!/bin/bash
set -e

# ============================================================
# Boundary Lab install / update / repair (macOS)
# ============================================================

if [ "${BLAB_INTERNAL_RUN:-}" != "1" ]; then
    ORIGINAL_DIR="$(cd "$(dirname "$0")" && pwd -P)"
    TEMP_SCRIPT="$(mktemp "${TMPDIR:-/tmp}/blab_install_update.XXXXXX.sh")"
    cp "$0" "$TEMP_SCRIPT"
    chmod +x "$TEMP_SCRIPT"
    BLAB_INTERNAL_RUN=1 BLAB_ORIGINAL_DIR="$ORIGINAL_DIR" exec "$TEMP_SCRIPT" "$@"
fi
trap 'rm -f "$0"' EXIT

ORIGINAL_DIR="${BLAB_ORIGINAL_DIR:-$(cd "$(dirname "$0")" && pwd -P)}"
PROJECT_DIR=""
REPO_URL="https://github.com/JWSound/boundary-lab.git"
OPTIONAL_SOLVER_WARNING=0

# Locate project directory
if [ -f "$ORIGINAL_DIR/pyproject.toml" ] && [ -d "$ORIGINAL_DIR/src/blab" ]; then
    PROJECT_DIR="$ORIGINAL_DIR"
elif [ -f "$ORIGINAL_DIR/boundary-lab/pyproject.toml" ] && [ -d "$ORIGINAL_DIR/boundary-lab/src/blab" ]; then
    PROJECT_DIR="$ORIGINAL_DIR/boundary-lab"
fi

ask_yn() {
    local prompt="$1"
    local default="$2"
    local reply=""
    if [ "$default" = "Y" ]; then
        read -r -p "$prompt [Y/n]: " reply || true
        reply="${reply:-Y}"
    else
        read -r -p "$prompt [y/N]: " reply || true
        reply="${reply:-N}"
    fi
    case "$reply" in
        [yY]|[yY][eE][sS]) return 0 ;;
        *) return 1 ;;
    esac
}

resolve_latest_release() {
    curl -fsSL -H "User-Agent: Boundary-Lab-Updater" https://api.github.com/repos/JWSound/boundary-lab/releases/latest 2>/dev/null \
        | grep '"tag_name":' \
        | sed -E 's/.*"tag_name"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/'
}

echo "============================================================"
echo "Boundary Lab install / update / repair (macOS)"
echo "============================================================"
echo ""

if [ -z "$PROJECT_DIR" ]; then
    if [ -d "$ORIGINAL_DIR/boundary-lab" ]; then
        echo "ERROR: The folder exists but is not a Boundary Lab checkout:"
        echo "  $ORIGINAL_DIR/boundary-lab"
        exit 1
    fi
    PROJECT_DIR="$ORIGINAL_DIR/boundary-lab"
    echo "No checkout was found. Boundary Lab will install the latest stable release."
    echo ""
    if ! command -v git >/dev/null 2>&1; then
        echo "ERROR: git is required to clone Boundary Lab."
        echo "Install Xcode Command Line Tools with: xcode-select --install"
        exit 1
    fi
    LATEST_RELEASE=$(resolve_latest_release)
    if [ -z "$LATEST_RELEASE" ]; then
        echo "ERROR: Could not resolve the latest stable release tag."
        exit 1
    fi
    git clone --branch "$LATEST_RELEASE" --single-branch "$REPO_URL" "$PROJECT_DIR"
fi


cd "$PROJECT_DIR"
echo "Using project folder:"
echo "  $PROJECT_DIR"
echo ""

# Handle Git updates if applicable
if [ -d ".git" ]; then
    echo "Existing Git checkout detected."
    if ask_yn "Update to the latest published stable release" "N"; then
        LATEST_RELEASE=$(resolve_latest_release)
        if [ -n "$LATEST_RELEASE" ]; then
            CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || true)
            if [ -n "$CURRENT_BRANCH" ] && [ "$CURRENT_BRANCH" != "main" ]; then
                echo "ERROR: Automatic updates require main or a detached release tag."
                echo "Development branches must be managed manually. Keeping current branch."
            elif [ -z "$CURRENT_BRANCH" ] && ! git describe --tags --exact-match HEAD >/dev/null 2>&1; then
                echo "ERROR: Automatic updates require main or a detached release tag."
                echo "Development branches must be managed manually. Keeping current branch."
            elif ! git diff --quiet || ! git diff --cached --quiet; then
                echo "ERROR: Tracked files contain local changes. The update was not attempted."
            else
                git fetch "$REPO_URL" "refs/heads/main:refs/remotes/blab-release/main" "refs/tags/$LATEST_RELEASE:refs/tags/$LATEST_RELEASE"
                if git merge-base --is-ancestor HEAD refs/remotes/blab-release/main; then
                    echo "Checking out stable release $LATEST_RELEASE..."
                    git checkout --detach "refs/tags/$LATEST_RELEASE"
                else
                    echo "ERROR: This checkout contains unpublished commits. Update skipped."
                fi
            fi
        else
            echo "WARNING: Could not check for latest release online. Continuing with current checkout."
        fi
    fi
    echo ""
fi

# Locate Python 3.11+
PYTHON_CMD=""
for cand in python3.13 python3.12 python3.11 python3 /opt/homebrew/bin/python3 python; do

    if command -v "$cand" >/dev/null 2>&1; then
        if "$cand" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
            PYTHON_CMD="$cand"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo "Python 3.11 or newer was not found."
    if command -v brew >/dev/null 2>&1; then
        if ask_yn "Install Python 3.12 with Homebrew" "Y"; then
            brew install python@3.12
            PYTHON_CMD="/opt/homebrew/bin/python3.12"
        fi
    fi
fi

if [ -z "$PYTHON_CMD" ]; then
    echo "ERROR: Python 3.11 or newer is required to run Boundary Lab."
    echo "Install it via Homebrew ('brew install python@3.12') or from https://www.python.org"
    exit 1
fi

echo "Using Python:"
echo "  $PYTHON_CMD ($("$PYTHON_CMD" --version))"
echo ""

VENV_DIR="$PROJECT_DIR/.venv"
VENV_PY="$VENV_DIR/bin/python"
BLAB_BIN="$VENV_DIR/bin/blab"

if [ -f "$VENV_PY" ]; then
    if ! "$VENV_PY" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
        echo "ERROR: The existing .venv uses Python older than 3.11."
        echo "Remove '$VENV_DIR' and run this script again."
        exit 1
    fi
    echo "Existing Python virtual environment found."
else
    echo "Creating Python virtual environment..."
    "$PYTHON_CMD" -m venv "$VENV_DIR"
fi

echo ""
echo "Updating pip and installing / repairing Boundary Lab..."
"$VENV_PY" -m pip install --upgrade pip
"$VENV_PY" -m pip install -e ".[gui]"

echo ""
echo "Checking Python package environment..."
"$VENV_PY" -m pip check

if [ ! -f "$BLAB_BIN" ]; then
    echo "ERROR: The installation did not create $BLAB_BIN."
    exit 1
fi

"$BLAB_BIN" --help >/dev/null 2>&1
echo "Boundary Lab command line verified."
echo ""
echo "Python application setup completed successfully."
echo ""

# Optional BEAT Engine solvers
if ask_yn "Install or update the optional Julia-based BEAT Engine solvers" "N"; then
    JULIA_CMD=""
    if command -v julia >/dev/null 2>&1; then
        JULIA_CMD="julia"
    elif [ -x "$HOME/.juliaup/bin/julia" ]; then
        JULIA_CMD="$HOME/.juliaup/bin/julia"
    elif [ -x "/Applications/Julia-1.12.app/Contents/Resources/julia/bin/julia" ]; then
        JULIA_CMD="/Applications/Julia-1.12.app/Contents/Resources/julia/bin/julia"
    elif [ -x "/Applications/Julia-1.11.app/Contents/Resources/julia/bin/julia" ]; then
        JULIA_CMD="/Applications/Julia-1.11.app/Contents/Resources/julia/bin/julia"
    elif [ -x "/Applications/Julia-1.10.app/Contents/Resources/julia/bin/julia" ]; then
        JULIA_CMD="/Applications/Julia-1.10.app/Contents/Resources/julia/bin/julia"
    elif [ -x "/opt/homebrew/bin/julia" ]; then
        JULIA_CMD="/opt/homebrew/bin/julia"
    fi

    if [ -z "$JULIA_CMD" ]; then
        echo "Julia was not found."
        if command -v brew >/dev/null 2>&1; then
            if ask_yn "Install Julia using Homebrew" "Y"; then
                brew install --cask julia
                JULIA_CMD="julia"
            fi
        fi
    fi

    if [ -z "$JULIA_CMD" ] || ! "$JULIA_CMD" --version >/dev/null 2>&1; then
        echo "WARNING: Julia is not available on PATH."
        echo "Download Julia from https://julialang.org/downloads/ to enable BEAT solving."
        OPTIONAL_SOLVER_WARNING=1
    else
        echo "Using Julia:"
        "$JULIA_CMD" --version
        echo ""

        BEAT_CPU_PROJECT=$("$VENV_PY" -c "from beat_engine import engine_paths; print(engine_paths('cpu').project)" 2>/dev/null || true)
        BEAT_METAL_PROJECT=$("$VENV_PY" -c "from beat_engine import engine_paths; print(engine_paths('metal').project)" 2>/dev/null || true)

        if [ -n "$BEAT_CPU_PROJECT" ]; then
            echo "Installing / updating the BEAT Engine CPU environment..."
            if ! "$JULIA_CMD" --project="$BEAT_CPU_PROJECT" -e "using Pkg; Pkg.instantiate(); Pkg.precompile()"; then
                echo "ERROR: The BEAT Engine CPU environment could not be prepared."
                OPTIONAL_SOLVER_WARNING=1
            fi
        else
            echo "WARNING: Could not locate BEAT Engine CPU environment in Python installation."
            OPTIONAL_SOLVER_WARNING=1
        fi


        # Check for Apple Silicon / Metal support
        if [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ] && [ -n "$BEAT_METAL_PROJECT" ]; then
            echo ""
            echo "Apple Silicon detected with Metal GPU capability."
            if ask_yn "Install or update Apple Metal GPU solver support" "Y"; then
                echo "Installing / updating the BEAT Engine Metal environment..."
                if "$JULIA_CMD" --project="$BEAT_METAL_PROJECT" -e "using Pkg; Pkg.instantiate(); Pkg.precompile()"; then
                    echo "Verifying Metal access from Julia..."
                    if "$JULIA_CMD" --project="$BEAT_METAL_PROJECT" -e 'using Metal; Metal.functional() || error("Metal is not functional"); Metal.versioninfo()'; then
                        echo "Apple Metal solver verified and ready."
                    else
                        echo "WARNING: Metal packages were installed, but the Metal runtime check failed."
                        echo "Boundary Lab and the CPU solver can still be used."
                        OPTIONAL_SOLVER_WARNING=1
                    fi
                else
                    echo "ERROR: The BEAT Engine Metal environment could not be prepared."
                    OPTIONAL_SOLVER_WARNING=1
                fi
            fi
        fi
    fi
fi

LAUNCHER="$PROJECT_DIR/02_start_boundary_lab.command"
echo ""
echo "============================================================"
if [ "$OPTIONAL_SOLVER_WARNING" = "1" ]; then
    echo "Boundary Lab is ready; optional solver setup needs attention."
else
    echo "Boundary Lab installation / update completed successfully."
fi
echo "============================================================"
echo ""
echo "Start Boundary Lab with:"
echo "  $LAUNCHER"
echo "or:"
echo "  $PROJECT_DIR/02_start_boundary_lab.sh"
echo ""
