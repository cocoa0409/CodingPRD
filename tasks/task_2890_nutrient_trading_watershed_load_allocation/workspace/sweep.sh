#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2890.
#
# Usage:  bash /home/ubuntu/github/CodingPRD/tasks/task_2890_nutrient_trading_watershed_load_allocation/workspace/sweep.sh
#
# Launch it detached so the rounds cannot be reaped when an unrelated
# foreground Bash call in the same agent returns:
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2890_nutrient_trading_watershed_load_allocation/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2890_nutrient_trading_watershed_load_allocation/workspace/sweep.log 2>&1 &
#
# Then POLL for the 8 results files; do NOT relaunch. The setsid wrapper can
# return long before the rounds finish.
#
#   ls -la .../workspace/implementation/results.*.json
#
# Diagnose ONLY from the per-round results.$i.json files. sweep.log is 8
# concurrent writers sharing one fd, so its text is spliced garbage.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2890_nutrient_trading_watershed_load_allocation
IMPL_DIR="$TASK_DIR/workspace/implementation"

rm -f "$IMPL_DIR"/results.*.json

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL_DIR && bash start.sh" \
    --test-dir      "$TASK_DIR/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL_DIR/results.${i}.json" &
done

wait

echo "SWEEP_DONE $(date -u +%Y-%m-%dT%H:%M:%SZ)"
