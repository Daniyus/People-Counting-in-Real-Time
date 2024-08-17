#!/bin/bash

# Check if CAMERA_NAME is set
if [ -z "$CAMERA_NAME" ]; then
    echo "CAMERA_NAME environment variable is not set."
    exit 1
fi

# Run the Python script with the CAMERA_NAME argument
exec python people_counter.py "$CAMERA_NAME"
