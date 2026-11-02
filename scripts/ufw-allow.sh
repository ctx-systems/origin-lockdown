#!/usr/bin/env bash
# Print (or with --apply, run) ufw rules allowing every IP in the given lists
# on the given ports.
#   scripts/ufw-allow.sh --ports 80,443 ips/cloudflare-v4.txt ips/cloudflare-v6.txt
#   scripts/ufw-allow.sh --ports 22 --apply ips/spinupwp-v4.txt
set -euo pipefail

ports="80,443"; apply=0; files=()
while [ $# -gt 0 ]; do
  case "$1" in
    --ports) ports="$2"; shift 2 ;;
    --apply) apply=1; shift ;;
    *) files+=("$1"); shift ;;
  esac
done
[ ${#files[@]} -gt 0 ] || { echo "usage: $0 [--ports 80,443] [--apply] list.txt..." >&2; exit 1; }

IFS=, read -ra port_list <<< "$ports"
for f in "${files[@]}"; do
  comment="origin-lockdown:$(basename "$f" .txt)"
  grep -vE '^\s*(#|$)' "$f" | while read -r ip; do
    for port in "${port_list[@]}"; do
      cmd=(ufw allow proto tcp from "$ip" to any port "$port" comment "$comment")
      if [ "$apply" = 1 ]; then "${cmd[@]}" >/dev/null; else echo "${cmd[*]}"; fi
    done
  done
done
