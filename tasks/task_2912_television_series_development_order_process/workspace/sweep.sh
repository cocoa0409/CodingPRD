#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2912.
# Usage: bash /home/ubuntu/github/CodingPRD/tasks/task_2912_television_series_development_order_process/workspace/sweep.sh
# Launches under setsid so the rounds cannot be reaped when a foreground Bash call returns.
T=/home/ubuntu/github/CodingPRD/tasks/task_2912_television_series_development_order_process
IMPL="$T/workspace/implementation"

rm -f "$IMPL"/results.*.json "$T"/workspace/sweep.round.*.log

setsid nohup bash -c '
T=/home/ubuntu/github/CodingPRD/tasks/task_2912_television_series_development_order_process
IMPL="$T/workspace/implementation"
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$T/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.$i.json" \
    > "$T/workspace/sweep.round.$i.log" 2>&1 &
done
wait
echo "SWEEP_ALL_ROUNDS_DONE"
' > "$T/workspace/sweep.log" 2>&1 &

echo "sweep launched detached; poll for $IMPL/results.{1..8}.json"
