#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2950.
# Usage:  setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2950_pediatric_private_duty_nursing_authorization_staffing/sweep.sh > /dev/null 2>&1 &
# Then poll for SWEEP_DONE. NEVER relaunch while SWEEP_DONE is absent and rounds are still alive.
TASK=/home/ubuntu/github/CodingPRD/tasks/task_2950_pediatric_private_duty_nursing_authorization_staffing
IMPL="$TASK/workspace/implementation"

rm -f "$IMPL"/results.*.json "$TASK/workspace/SWEEP_DONE" "$TASK/workspace"/sweep.round.*.log

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$TASK/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.$i.json" \
    > "$TASK/workspace/sweep.round.$i.log" 2>&1 &
done
wait
date -u +%Y-%m-%dT%H:%M:%S.%3NZ > "$TASK/workspace/SWEEP_DONE"
