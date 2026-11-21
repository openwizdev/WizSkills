#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 2 || -z ${1-} || -z ${2-} ]]; then
  printf '%s\n' 'usage: bash hitl-loop.template.sh "scenario step" "exact symptom question"' >&2
  exit 2
fi

inconclusive() {
  printf '%s\n' 'inconclusive: a completed step and an explicit y or n observation are required' >&2
  exit 2
}

printf '\n>>> %s\n' "$1"
printf '%s\n' '    Follow the step yourself; do not enter credentials here. Press Enter when done.'
IFS= read -r completed || inconclusive
printf '\n>>> %s\n' "$2"
printf '%s\n' '    Symptom present? Enter y or n only; no secrets or raw error text.'
IFS= read -r answer || inconclusive
case "$answer" in
  y) printf '%s\n' 'SYMPTOM_PRESENT=yes'; exit 1 ;;
  n) printf '%s\n' 'SYMPTOM_PRESENT=no'; exit 0 ;;
  *) inconclusive ;;
esac
