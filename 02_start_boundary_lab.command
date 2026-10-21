#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
"$SCRIPT_DIR/02_start_boundary_lab.sh" "$@"
EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ] && [ -t 0 ]; then
    echo ""
    read -r -p "Press Enter to close this window..." _ || true
fi

exit $EXIT_CODE
