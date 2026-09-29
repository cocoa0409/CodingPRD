#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2908.
# Launch ONLY like this (setsid detaches it so foreground Bash calls cannot reap it):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2908_wholesale_auction_arbitration_condition_disputes/workspace/sweep.sh > /home/ubuntu/github/CodingPRD/tasks/task_2908_wholesale_auction_arbitration_condition_disputes/workspace/sweep.log 2>&1 &
# Then POLL for the 8 results.$i.json files. Never relaunch just because the
# wrapper returned early -- setsid returns before the rounds finish.
# Diagnose ONLY from the per-round results.$i.json files: all 8 rounds share one
# fd for sweep.log, so sweep.log itself is spliced garbage.

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2908_wholesale_auction_arbitration_condition_disputes
IMPL="$TASK/workspace/implementation"

rm -f "$IMPL"/results.*.json

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
echo "SWEEP_DONE"
