#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2954.
#
# Usage (ALWAYS launch it detached so the rounds cannot be reaped):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2954_automated_grocery_fulfillment_center_operations/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2954_automated_grocery_fulfillment_center_operations/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel; do NOT relaunch just because the wrapper returned:
#   while [ ! -f .../workspace/SWEEP_DONE ]; do sleep 60; done
#
# Notes baked in on purpose:
#  * The 8 rounds share one stdout, so sweep.log is spliced garbage. Diagnose ONLY
#    from the per-round results.$i.json files.
#  * No --api-url: the runner claims a free port per round via its lockfile and
#    exports $PORT, so concurrent rounds (and other pipelines) do not collide.
#  * The --start-command MUST contain the `cd` into implementation/, otherwise
#    every round dies in seconds with ServerStartError and writes no results.
set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2954_automated_grocery_fulfillment_center_operations
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
echo "SWEEP COMPLETE $(date -u +%Y-%m-%dT%H:%M:%SZ)"
