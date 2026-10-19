#!/usr/bin/env bash
# verify.sh — run after installing: checks iptinfo works on a sample file.
# Usage: verify.sh FILE.ipt
set -e
F="$1"
[ -z "$F" ] && { echo "usage: verify.sh FILE.ipt"; exit 2; }
echo "== iptinfo version check =="
iptinfo "$F" | head -3
echo "== parameters =="
iptinfo --json "$F" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('  part:', d['part_title'])
print('  params:', d['parameters'])
print('  topology:', (d.get('asm_topology') or {}))
"
echo "== thumbnail extraction =="
iptinfo --thumbnail /tmp/verify_thumb "$F" >/dev/null && file /tmp/verify_thumb.png
echo "ALL CHECKS DONE — installation is working."
