#!/bin/sh
# Point this clone's git at the tracked hooks in .githooks, so every commit and
# every push runs the public-content check. Run it once per clone, from anywhere
# inside it.
set -eu
top=$(git rev-parse --show-toplevel)
git -C "$top" config core.hooksPath .githooks
echo "git hooks now run from $top/.githooks: the public-content check runs on every commit and push"
