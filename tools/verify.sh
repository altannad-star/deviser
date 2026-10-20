#!/usr/bin/env bash
# verify.sh — full Deviser suite check (session 19).
# Usage: verify.sh SAMPLE.ipt  (also accepts a directory of samples)
set -e
F="$1"
[ -z "$F" ] && { echo "usage: verify.sh FILE.ipt"; exit 2; }
DIR="$(dirname "$0")"

echo "== 1. iptinfo parse =="
python3 "$DIR/iptinfo" "$F" | head -4

echo "== 2. parameters + topology (JSON) =="
python3 "$DIR/iptinfo" --json "$F" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('  part:', d['part_title'])
print('  params:', d['parameters'])
print('  topology:', (d.get('asm_topology') or {}))
print('  occurrences:', len(d.get('occurrences') or []))
"

echo "== 3. thumbnail =="
python3 "$DIR/iptinfo" --thumbnail /tmp/verify_thumb "$F" >/dev/null && file /tmp/verify_thumb.png

echo "== 4. .devp round-trip =="
python3 "$DIR/ipt2devp" "$F" -o /tmp/verify.devp >/dev/null && echo "  wrote /tmp/verify.devp"

case "$F" in
  *.iam)
    echo "== 5. .deva assembly round-trip =="
    python3 "$DIR/ipt2deva" "$F" -o /tmp/verify.deva --round-trip
    echo "== 6. .devx explosion round-trip =="
    python3 "$DIR/ipt2devx" "$F" -o /tmp/verify.devx --round-trip
    ;;
  *.ipt)
    echo "== 5. .devd drawing + SVG render =="
    python3 "$DIR/ipt2devd" "$F" -o /tmp/verify.devd --round-trip --svg /tmp/verify.svg
    ;;
esac

echo "ALL CHECKS DONE — full suite is working."
