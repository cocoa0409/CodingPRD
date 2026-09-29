#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2952.
# Usage:  setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2952_resort_spa_operations_treatment_scheduling/sweep.sh \
#             > /home/ubuntu/github/CodingPRD/tasks/task_2952_resort_spa_operations_treatment_scheduling/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel. Never relaunch just because the wrapper returned:
#   ls .../workspace/implementation/SWEEP_DONE
# sweep.log is 8 interleaved streams and is unreadable garbage — diagnose ONLY
# from the per-round results.$i.json files.
set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2952_resort_spa_operations_treatment_scheduling
IMPL="$TASK/workspace/implementation"

rm -f "$IMPL"/results.*.json "$IMPL/SWEEP_DONE"

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$TASK/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.$i.json" \
    > "$IMPL/round.$i.log" 2>&1 &
done

wait

touch "$IMPL/SWEEP_DONE"
echo "SWEEP COMPLETE: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
