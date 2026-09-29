#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2855.
# Usage (ALWAYS launch it exactly like this, from any cwd):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2855_affiliate_marketing_program_management/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2855_affiliate_marketing_program_management/workspace/sweep.log 2>&1 < /dev/null &
# Then POLL for results.1.json .. results.8.json. Never relaunch while a sweep is in flight.
set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2855_affiliate_marketing_program_management
IMPL="$TASK/workspace/implementation"

rm -f "$IMPL"/results.*.json

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
echo "SWEEP_DONE"
