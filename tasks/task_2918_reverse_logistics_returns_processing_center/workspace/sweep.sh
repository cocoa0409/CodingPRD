#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2918.
#
# Usage (ALWAYS launch it detached so the rounds cannot be reaped when an
# unrelated foreground Bash call in the same agent returns):
#
#   TASK=/home/ubuntu/github/CodingPRD/tasks/task_2918_reverse_logistics_returns_processing_center
#   rm -f "$TASK/workspace/SWEEP_DONE"
#   setsid nohup bash "$TASK/workspace/sweep.sh" > "$TASK/workspace/sweep.log" 2>&1 < /dev/null &
#
# Then POLL for the sentinel — do NOT relaunch just because the wrapper
# returned early:
#
#   ls "$TASK/workspace/SWEEP_DONE" 2>/dev/null && echo finished
#
# Diagnose ONLY from the per-round results.$i.json files. sweep.log is written
# by 8 concurrent processes sharing one fd, so its text is spliced garbage.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2918_reverse_logistics_returns_processing_center
IMPL="$TASK/workspace/implementation"

rm -f "$IMPL"/results.*.json
rm -f "$TASK/workspace/SWEEP_DONE"

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$TASK/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.$i.json" &
done

wait

touch "$TASK/workspace/SWEEP_DONE"
echo "SWEEP COMPLETE"
