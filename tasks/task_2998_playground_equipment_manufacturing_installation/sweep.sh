#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2998.
# Usage:  setsid nohup bash /abs/path/sweep.sh > /abs/path/workspace/sweep.log 2>&1 &
# Then poll for workspace/SWEEP_DONE (created only after all 8 rounds have joined).
# NEVER relaunch just because the wrapper returned early -- poll for the sentinel.
TASK=/home/ubuntu/github/CodingPRD/tasks/task_2998_playground_equipment_manufacturing_installation
IMPL="$TASK/workspace/implementation"

rm -f "$IMPL"/results.*.json "$TASK/workspace/SWEEP_DONE"

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
touch "$TASK/workspace/SWEEP_DONE"
echo "ALL 8 ROUNDS JOINED"
