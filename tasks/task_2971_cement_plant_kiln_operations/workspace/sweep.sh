#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2971_cement_plant_kiln_operations.
#
# Launch it EXACTLY like this (setsid detaches it from the agent's process group so
# an unrelated foreground Bash call returning cannot SIGTERM the rounds mid-request):
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2971_cement_plant_kiln_operations/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2971_cement_plant_kiln_operations/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel file .../workspace/SWEEP_DONE. The setsid wrapper
# returns almost immediately while the rounds keep running — do NOT interpret an
# early return as "the sweep finished", and NEVER relaunch a sweep that is still
# running. Poll like this:
#
#   ls /home/ubuntu/github/CodingPRD/tasks/task_2971_cement_plant_kiln_operations/workspace/SWEEP_DONE
#
# Diagnose ONLY from the per-round results.$i.json files. sweep.log is 8 concurrent
# processes sharing one fd, so its text is spliced garbage and must not be trusted.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2971_cement_plant_kiln_operations
IMPL="$TASK/workspace/implementation"

rm -f "$TASK/workspace/SWEEP_DONE"
rm -f "$IMPL"/results.*.json

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
