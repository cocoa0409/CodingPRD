#!/usr/bin/env bash
# 8-round parallel stability sweep for task 2893.
# Usage: bash sweep.sh          (blocks until all 8 rounds finish)
#        bash launch_sweep.sh   (detached wrapper; poll for results.*.json)
TD=/home/ubuntu/github/CodingPRD/tasks/task_2893_underground_natural_gas_storage_operations
IMPL="$TD/workspace/implementation"
rm -f "$IMPL"/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$TD/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.$i.json" \
    > "$TD/workspace/round.$i.log" 2>&1 &
done
wait
echo "SWEEP_DONE"
