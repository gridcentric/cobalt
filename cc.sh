#!/bin/bash

# Use ccache if available to speed up compiling C extensions.
if which ccache >/dev/null; then
    exec ccache gcc "$@"
else
    exec gcc "$@"
fi
