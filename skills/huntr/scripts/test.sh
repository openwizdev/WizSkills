#!/bin/sh
set -eu
exec node --test "$(dirname "$0")/gate.test.mjs" "$(dirname "$0")/manifest.test.mjs" "$(dirname "$0")/records.test.mjs" "$(dirname "$0")/controller.test.mjs" "$(dirname "$0")/targets.test.mjs" "$(dirname "$0")/findings.test.mjs"
