#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2904.
#
# Usage:   bash /home/ubuntu/github/CodingPRD/tasks/task_2904_collision_repair_estimating_parts_procurement/workspace/run_sweep.sh
#
# This launches the 8 rounds detached via setsid so they CANNOT be reaped when an
# unrelated foreground Bash call in the calling agent returns. It returns almost
# immediately; the rounds keep running. Poll for results.1.json .. results.8.json
# (8 files present == sweep finished). NEVER relaunch just because this script
# returned quickly -- that is expected behaviour.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2904_collision_repair_estimating_parts_procurement
IMPL_DIR="$TASK_DIR/workspace/implementation"

rm -f "$IMPL_DIR"/results.*.json
rm -f "$TASK_DIR"/workspace/sweep.*.log

setsid nohup bash -c '
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2904_collision_repair_estimating_parts_procurement
IMPL_DIR="$TASK_DIR/workspace/implementation"
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL_DIR && bash start.sh" \
    --test-dir      "$TASK_DIR/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL_DIR/results.$i.json" \
    > "$TASK_DIR/workspace/sweep.$i.log" 2>&1 &
done
wait
' > "$TASK_DIR/workspace/sweep.log" 2>&1 &

disown || true
echo "sweep launched detached; poll for $IMPL_DIR/results.{1..8}.json"
