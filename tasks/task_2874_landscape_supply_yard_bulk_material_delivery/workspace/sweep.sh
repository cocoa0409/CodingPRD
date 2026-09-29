#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2874.
# Usage:  setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2874_landscape_supply_yard_bulk_material_delivery/workspace/sweep.sh > /home/ubuntu/github/CodingPRD/tasks/task_2874_landscape_supply_yard_bulk_material_delivery/workspace/sweep.log 2>&1 &
# Then POLL for results.1.json .. results.8.json. Do NOT relaunch: the setsid wrapper
# returns almost immediately while the 8 rounds keep running detached.
T=/home/ubuntu/github/CodingPRD/tasks/task_2874_landscape_supply_yard_bulk_material_delivery
rm -f "$T"/workspace/implementation/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $T/workspace/implementation && bash start.sh" \
    --test-dir       "$T/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$T/workspace/implementation/results.$i.json" \
    > "$T/workspace/round.$i.log" 2>&1 &
done
wait
echo "ALL_ROUNDS_DONE"
