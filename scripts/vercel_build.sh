#!/bin/sh
# Vercel build step: compile the cparse frontend so the Python function can run it.
set -e

for tool in gcc make flex bison; do
    command -v "$tool" >/dev/null 2>&1 || MISSING=1
done
if [ -n "$MISSING" ]; then
    dnf install -y gcc make flex bison
fi

make build
mkdir -p sca/bin
cp build/cparse sca/bin/cparse
