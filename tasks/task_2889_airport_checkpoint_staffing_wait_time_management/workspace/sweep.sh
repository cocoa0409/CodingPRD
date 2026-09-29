#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2889.
#
# USAGE (always launch it exactly like this, detached under setsid):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2889_airport_checkpoint_staffing_wait_time_management/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2889_airport_checkpoint_staffing_wait_time_management/workspace/sweep.log 2>&1 &
#
# Then POLL for the 8 results files. Do NOT relaunch: the setsid wrapper may
# return long before the rounds finish, and a second sweep doubles host load.
#   ls .../workspace/implementation/results.*.json
#
# Diagnose ONLY from the per-round results.$i.json files. sweep.log is 8
# concurrent writers sharing one fd, so its text is spliced garbage.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2889_airport_checkpoint_staffing_wait_time_management
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
echo "SWEEP_DONE $(date -u +%Y-%m-%dT%H:%M:%SZ)"
