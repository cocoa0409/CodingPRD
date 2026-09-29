#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2946.
#
# Usage (ALWAYS launch it exactly like this, detached from the agent session):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2946_retail_health_clinic_operations_scope_protocols/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2946_retail_health_clinic_operations_scope_protocols/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel file SWEEP_DONE. Do NOT trust the exit status of the
# launching command: setsid returns almost immediately while the 8 rounds keep
# running. Never relaunch the sweep because the wrapper "already returned".
#
#   while [ ! -f .../workspace/SWEEP_DONE ]; do sleep 60; done
#
# Diagnose ONLY from the per-round results.$i.json files. sweep.log is 8 rounds
# sharing one file descriptor, so its contents are interleaved garbage.

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2946_retail_health_clinic_operations_scope_protocols
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
