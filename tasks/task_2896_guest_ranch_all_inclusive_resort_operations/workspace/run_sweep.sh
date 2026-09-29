#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2896.
#
# Usage:  bash /home/ubuntu/github/CodingPRD/tasks/task_2896_guest_ranch_all_inclusive_resort_operations/workspace/run_sweep.sh
#
# Launches all 8 rounds detached under setsid so that a later foreground Bash
# call in the calling agent cannot SIGTERM them mid-request. Returns almost
# immediately; poll for results.1..8.json instead of trusting the exit code.
#
# Do NOT edit the --start-command: the `cd .../implementation &&` prefix is
# required, or every round dies in seconds with ServerStartError.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2896_guest_ranch_all_inclusive_resort_operations
IMPL_DIR="$TASK_DIR/workspace/implementation"

rm -f "$IMPL_DIR"/results.*.json
rm -f "$TASK_DIR"/workspace/sweep.log

setsid nohup bash -c '
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2896_guest_ranch_all_inclusive_resort_operations
IMPL_DIR="$TASK_DIR/workspace/implementation"
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL_DIR && bash start.sh" \
    --test-dir      "$TASK_DIR/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL_DIR/results.$i.json" &
done
wait
echo "SWEEP_COMPLETE"
' > "$TASK_DIR/workspace/sweep.log" 2>&1 &

echo "sweep launched detached; poll for $IMPL_DIR/results.{1..8}.json"
