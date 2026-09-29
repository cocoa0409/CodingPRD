#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2858_school_bus_manufacturing.
#
# Usage:   bash /home/ubuntu/github/CodingPRD/tasks/task_2858_school_bus_manufacturing/workspace/sweep.sh
#
# ALWAYS launch it detached so the rounds cannot be reaped when an unrelated
# foreground Bash call in your agent returns:
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2858_school_bus_manufacturing/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2858_school_bus_manufacturing/workspace/sweep.log 2>&1 &
#
# The setsid wrapper returns almost immediately while the 8 rounds keep running.
# Do NOT relaunch it. Poll for the 8 results files instead:
#
#   ls -la /home/ubuntu/github/CodingPRD/tasks/task_2858_school_bus_manufacturing/workspace/implementation/results.*.json
#
# Diagnose ONLY from the per-round results.$i.json files. sweep.log is 8
# concurrent writers sharing one fd, so its text is interleaved garbage.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2858_school_bus_manufacturing
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

echo "SWEEP COMPLETE"
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL_DIR/results.$i.json" ]; then
    python3 - "$IMPL_DIR/results.$i.json" <<'PYEOF'
import json, sys
p = sys.argv[1]
try:
    d = json.load(open(p))
    print(f"{p}: passed={d.get('passed')} failed={d.get('failed')} total={d.get('total')}")
except Exception as e:
    print(f"{p}: UNREADABLE {e}")
PYEOF
  else
    echo "$IMPL_DIR/results.$i.json: MISSING"
  fi
done
