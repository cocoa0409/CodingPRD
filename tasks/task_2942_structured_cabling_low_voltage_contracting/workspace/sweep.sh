#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2942_structured_cabling_low_voltage_contracting.
#
# Usage (ALWAYS launch it exactly like this, detached from the calling agent's
# process group so the rounds cannot be reaped by an unrelated foreground call):
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2942_structured_cabling_low_voltage_contracting/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2942_structured_cabling_low_voltage_contracting/workspace/sweep.log 2>&1 &
#
# The wrapper returns almost immediately; the sweep keeps running. Do NOT relaunch it.
# Poll for completion by waiting for the sentinel file SWEEP_DONE:
#
#   while [ ! -f .../workspace/SWEEP_DONE ]; do sleep 30; done
#
# Then read ONLY the per-round results.$i.json files. Never diagnose from sweep.log:
# all 8 rounds share one fd and their output is spliced together into garbage.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2942_structured_cabling_low_voltage_contracting
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
