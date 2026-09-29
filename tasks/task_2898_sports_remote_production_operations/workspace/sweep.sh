#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2898_sports_remote_production_operations.
# Launch ONLY like this (the setsid is mandatory — without it the rounds get SIGTERM
# the moment any unrelated foreground Bash call in the calling agent returns):
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2898_sports_remote_production_operations/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2898_sports_remote_production_operations/workspace/sweep.log 2>&1 < /dev/null &
#
# Then POLL for the 8 results files. Do NOT relaunch just because the wrapper returned:
#   ls -la .../implementation/results.*.json ; test -f .../workspace/SWEEP_DONE
# SWEEP_DONE is written only after all 8 rounds have joined.
#
# Never diagnose from sweep.log — 8 concurrent rounds share one fd and the log is
# interleaved garbage. Diagnose only from the per-round results.$i.json files.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2898_sports_remote_production_operations
IMPL="$TASK/workspace/implementation"

rm -f "$IMPL"/results.*.json
rm -f "$TASK/workspace/SWEEP_DONE"
find "$TASK" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null

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

date -u +%Y-%m-%dT%H:%M:%SZ > "$TASK/workspace/SWEEP_DONE"
