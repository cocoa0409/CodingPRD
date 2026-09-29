#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2861.
#
# Usage:  bash /home/ubuntu/github/CodingPRD/tasks/task_2861_consulting_bench_management_utilization/workspace/sweep.sh
#
# Launches all 8 rounds detached under setsid so they CANNOT be reaped when an
# unrelated foreground Bash call in the calling agent returns. Returns almost
# immediately; poll for results.1.json .. results.8.json to know when it is done.
set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2861_consulting_bench_management_utilization
IMPL="$TASK/workspace/implementation"

rm -f "$IMPL"/results.*.json

setsid nohup bash -c '
TASK=/home/ubuntu/github/CodingPRD/tasks/task_2861_consulting_bench_management_utilization
IMPL="$TASK/workspace/implementation"
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$TASK/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.$i.json" \
    > "$TASK/workspace/round.$i.log" 2>&1 &
done
wait
' > "$TASK/workspace/sweep.log" 2>&1 &

echo "sweep launched detached; poll for $IMPL/results.*.json"
