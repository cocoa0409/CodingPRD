#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2933.
#
# USAGE (always launch it exactly like this, detached so nothing can reap it):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2933_craft_brewery_taproom_self_distribution_operations/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2933_craft_brewery_taproom_self_distribution_operations/workspace/sweep.log 2>&1 &
#
# Then POLL for completion — do NOT relaunch:
#   ls .../workspace/implementation/SWEEP_DONE            # sentinel appears only after all 8 rounds finish
#   ls .../workspace/implementation/results.*.json
#
# Notes:
#  * setsid detaches the process group so a later foreground Bash call in the
#    agent cannot SIGTERM the backgrounded rounds mid-request.
#  * The wrapper command may return long before the rounds finish; the ONLY
#    completion signal is the SWEEP_DONE sentinel.
#  * sweep.log interleaves 8 concurrent writers and is spliced garbage —
#    diagnose only from the per-round results.$i.json files.
#  * No --api-url: the runner claims a free port per round via its lockfile.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2933_craft_brewery_taproom_self_distribution_operations
IMPL="$TASK/workspace/implementation"

rm -f "$IMPL"/results.*.json "$IMPL/SWEEP_DONE"

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

touch "$IMPL/SWEEP_DONE"
