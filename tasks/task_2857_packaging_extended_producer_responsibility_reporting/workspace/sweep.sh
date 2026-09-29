#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2857.
# Usage (ALWAYS launch detached so the rounds cannot be reaped):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2857_packaging_extended_producer_responsibility_reporting/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2857_packaging_extended_producer_responsibility_reporting/workspace/sweep.log 2>&1 &
#
# Then POLL for the 8 result files. Do NOT relaunch: the setsid wrapper returns
# long before the rounds finish.
#   ls /home/ubuntu/github/CodingPRD/tasks/task_2857_packaging_extended_producer_responsibility_reporting/workspace/implementation/results.*.json
#
# Diagnose ONLY from the per-round results.$i.json files. sweep.log is 8
# concurrent writers sharing one fd, so its text is spliced garbage.

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2857_packaging_extended_producer_responsibility_reporting
IMPL_DIR="$TASK_DIR/workspace/implementation"

rm -f "$IMPL_DIR"/results.*.json

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
