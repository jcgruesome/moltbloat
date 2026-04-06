#!/bin/bash
# Check dependencies and provide helpful errors

MISSING=()

if ! command -v python3 &> /dev/null; then
    MISSING+=("python3")
fi

if ! command -v bash &> /dev/null; then
    MISSING+=("bash")
fi

# jq is optional but recommended
if ! command -v jq &> /dev/null; then
    echo "[moltbloat] Warning: jq not found. Some features will use fallback methods." >&2
    echo "[moltbloat] Install jq for better JSON handling: https://stedolan.github.io/jq/" >&2
fi

if [ ${#MISSING[@]} -ne 0 ]; then
    echo "[moltbloat] ERROR: Missing required dependencies: ${MISSING[*]}" >&2
    echo "[moltbloat] Please install these and try again." >&2
    exit 1
fi

exit 0
