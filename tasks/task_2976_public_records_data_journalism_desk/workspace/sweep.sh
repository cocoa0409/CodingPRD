#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2976.
#
# Usage (ALWAYS launch it exactly like this, from any cwd):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2976_public_records_data_journalism_desk/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2976_public_records_data_journalism_desk/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel; do NOT relaunch. The setsid wrapper can return
# long before the rounds finish:
#   ls .../workspace/SWEEP_DONE   # appears only after all 8 rounds joined
#
# Do NOT diagnose from sweep.log — 8 concurrent rounds share one fd and the log
# is spliced garbage. Diagnose ONLY from the per-round results.$i.json files.
set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2976_public_records_data_journalism_desk
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
    --results-file  "$IMPL/results.$i.json" \
    > "$TASK/workspace/round.$i.log" 2>&1 &
done

wait

touch "$TASK/workspace/SWEEP_DONE"
