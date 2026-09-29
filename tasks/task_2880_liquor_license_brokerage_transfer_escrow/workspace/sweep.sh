#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2880.
#
# Usage (ALWAYS launch it exactly like this, detached, so the rounds cannot be
# reaped when an unrelated foreground Bash call in the agent returns):
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2880_liquor_license_brokerage_transfer_escrow/workspace/sweep.sh \
#       > /home/ubuntu/github/CodingPRD/tasks/task_2880_liquor_license_brokerage_transfer_escrow/workspace/sweep.log 2>&1 &
#
# Then POLL for the 8 results files. Never relaunch just because the wrapper
# returned early -- setsid detaches and the wrapper's exit says nothing about
# whether the rounds finished.

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2880_liquor_license_brokerage_transfer_escrow
IMPL="$TASK/workspace/implementation"

rm -f "$IMPL"/results.*.json
rm -f "$TASK/workspace"/sweep.done

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

echo "ALL_ROUNDS_DONE" > "$TASK/workspace/sweep.done"
date -u +%Y-%m-%dT%H:%M:%SZ >> "$TASK/workspace/sweep.done"
