#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2989.
#
# Usage (ALWAYS launch it exactly like this, detached so it cannot be reaped):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2989_recipe_costing_menu_engineering_plate_cost_management/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2989_recipe_costing_menu_engineering_plate_cost_management/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel file SWEEP_DONE. Do NOT relaunch just because the
# setsid wrapper returned early -- it returns long before the rounds finish:
#   while [ ! -f .../workspace/SWEEP_DONE ]; do sleep 30; done
#
# Never diagnose from sweep.log -- 8 concurrent rounds share one fd and the log
# is spliced garbage. Diagnose ONLY from the per-round results.$i.json files.

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2989_recipe_costing_menu_engineering_plate_cost_management
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
