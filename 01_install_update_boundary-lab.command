#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
"$SCRIPT_DIR/01_install_update_boundary-lab.sh" "$@"
EXIT_CODE=$?
if [ -t 0 ]; then
    echo ""
    read -r -p "Press Enter to close this window..." _ || true
fi

exit $EXIT_CODE
