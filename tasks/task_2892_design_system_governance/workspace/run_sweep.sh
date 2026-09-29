#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2892_design_system_governance.
#
# Usage (ALWAYS launch it exactly like this, detached from the agent's process group):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2892_design_system_governance/workspace/run_sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2892_design_system_governance/workspace/sweep.log 2>&1 &
#
# Then POLL for the 8 results files; do NOT relaunch just because the wrapper
# returned early:
#   ls /home/ubuntu/github/CodingPRD/tasks/task_2892_design_system_governance/workspace/implementation/results.*.json
#
# Never diagnose from sweep.log — 8 concurrent rounds share one fd and the log is
# spliced garbage. Diagnose only from the per-round results.$i.json files.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2892_design_system_governance
IMPL_DIR="$TASK_DIR/workspace/implementation"

rm -f "$IMPL_DIR"/results.*.json

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL_DIR && bash start.sh" \
    --test-dir      "$TASK_DIR/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL_DIR/results.$i.json" \
    > "$TASK_DIR/workspace/round.$i.log" 2>&1 &
done

wait

echo "SWEEP_DONE $(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)"
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL_DIR/results.$i.json" ]; then
    python3 - "$IMPL_DIR/results.$i.json" <<'PY'
import json, sys
p = sys.argv[1]
try:
    d = json.load(open(p))
    print(p.split('/')[-1], "passed:", d.get("passed"), "total:", d.get("total"))
except Exception as e:
    print(p.split('/')[-1], "UNREADABLE", e)
PY
  else
    echo "results.$i.json MISSING"
  fi
done
