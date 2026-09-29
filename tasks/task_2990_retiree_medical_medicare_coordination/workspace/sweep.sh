#!/bin/bash
# 8-round parallel stability sweep for task_2990_retiree_medical_medicare_coordination.
#
# Usage (ALWAYS launch it exactly like this, detached from the agent's process group):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2990_retiree_medical_medicare_coordination/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2990_retiree_medical_medicare_coordination/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel file SWEEP_DONE. Do NOT relaunch just because the
# launching command returned quickly — setsid returns almost immediately while the
# 8 rounds keep running. Poll like this:
#   while [ ! -f .../workspace/SWEEP_DONE ]; do sleep 30; done
#
# Never diagnose from sweep.log: 8 concurrent rounds share one fd and the log is
# spliced garbage. Diagnose ONLY from the per-round results.$i.json files.

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2990_retiree_medical_medicare_coordination
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
