#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2943.
#
# USAGE (always launch it exactly like this — detached, so the rounds cannot be
# reaped when an unrelated foreground Bash call in your agent returns):
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2943_rental_car_fleet_planning_remarketing/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2943_rental_car_fleet_planning_remarketing/workspace/sweep.log 2>&1 &
#
# Then POLL for completion — do NOT relaunch. The wrapper may return long before
# the rounds finish:
#
#   ls /home/ubuntu/github/CodingPRD/tasks/task_2943_rental_car_fleet_planning_remarketing/workspace/SWEEP_DONE
#
# SWEEP_DONE only appears after `wait` returns, i.e. after all 8 rounds have
# completed. Until then the sweep is still running, however quiet it looks.
#
# NOTE: sweep.log interleaves 8 concurrent writers on one fd and is therefore
# spliced garbage. Diagnose ONLY from the per-round results.$i.json files.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2943_rental_car_fleet_planning_remarketing
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
