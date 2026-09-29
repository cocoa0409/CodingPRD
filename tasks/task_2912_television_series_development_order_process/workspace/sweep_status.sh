#!/usr/bin/env bash
# Prints per-round pass/total for whichever results files exist yet.
T=/home/ubuntu/github/CodingPRD/tasks/task_2912_television_series_development_order_process
IMPL="$T/workspace/implementation"
n=$(ls "$IMPL"/results.*.json 2>/dev/null | wc -l)
echo "results files present: $n/8"
for i in 1 2 3 4 5 6 7 8; do
  f="$IMPL/results.$i.json"
  if [ -f "$f" ]; then
    python3 - "$f" <<'PY'
import json,sys
f=sys.argv[1]
try:
    d=json.load(open(f))
except Exception as e:
    print(f, "UNREADABLE", e); raise SystemExit
p=d.get("passed"); t=d.get("total")
if p is None:
    tests=d.get("tests") or d.get("results") or []
    t=len(tests); p=sum(1 for x in tests if str(x.get("outcome") or x.get("status")).lower() in ("passed","pass"))
print(f.split("/")[-1], f"passed={p} total={t}")
PY
  else
    echo "results.$i.json MISSING"
  fi
done
