#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2949_destination_sales_convention_attraction.
#
# Usage (ALWAYS launch it exactly like this, detached under setsid):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2949_destination_sales_convention_attraction/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2949_destination_sales_convention_attraction/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel file SWEEP_DONE. Do NOT relaunch the sweep just because
# the launching shell returned quickly — setsid detaches, so the wrapper returns long
# before the 8 rounds finish. The rounds are done only when SWEEP_DONE exists.
#
#   ls /home/ubuntu/github/CodingPRD/tasks/task_2949_destination_sales_convention_attraction/workspace/SWEEP_DONE
#
# Never diagnose from sweep.log: 8 concurrent rounds share one fd, so its contents are
# spliced garbage. Diagnose ONLY from the per-round implementation/results.$i.json files.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2949_destination_sales_convention_attraction
IMPL_DIR="$TASK_DIR/workspace/implementation"
WS="$TASK_DIR/workspace"

rm -f "$IMPL_DIR"/results.*.json
rm -f "$WS/SWEEP_DONE"

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

touch "$WS/SWEEP_DONE"
echo "SWEEP COMPLETE"
