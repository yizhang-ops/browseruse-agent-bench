#!/bin/bash
set -e

# Activate the virtual environment
VENV_PATH="${VENV_PATH:-/app/.venv}"
source "${VENV_PATH}/bin/activate"

# Execute the command passed to the container
exec "$@"
