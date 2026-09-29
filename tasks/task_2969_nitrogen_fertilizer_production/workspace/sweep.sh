#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2969_nitrogen_fertilizer_production.
#
# Usage (ALWAYS launch it this way, detached so it cannot be reaped):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2969_nitrogen_fertilizer_production/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2969_nitrogen_fertilizer_production/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel — do NOT relaunch just because the wrapper returned:
#   ls /home/ubuntu/github/CodingPRD/tasks/task_2969_nitrogen_fertilizer_production/workspace/SWEEP_DONE
#
# Only read the per-round results.$i.json files. sweep.log is 8 concurrent writers
# sharing one fd, so its contents are interleaved garbage and must never be used
# for diagnosis.

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2969_nitrogen_fertilizer_production
IMPL_DIR="$TASK_DIR/workspace/implementation"

rm -f "$IMPL_DIR"/results.*.json
rm -f "$TASK_DIR/workspace/SWEEP_DONE"

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL_DIR && bash start.sh" \
    --test-dir      "$TASK_DIR/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL_DIR/results.$i.json" &
done

wait

touch "$TASK_DIR/workspace/SWEEP_DONE"
