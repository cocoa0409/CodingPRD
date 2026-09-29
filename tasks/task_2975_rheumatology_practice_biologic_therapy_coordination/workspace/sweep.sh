#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2975.
# Usage:  setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2975_rheumatology_practice_biologic_therapy_coordination/workspace/sweep.sh > /home/ubuntu/github/CodingPRD/tasks/task_2975_rheumatology_practice_biologic_therapy_coordination/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel -- do NOT relaunch:
#   ls /home/ubuntu/github/CodingPRD/tasks/task_2975_rheumatology_practice_biologic_therapy_coordination/workspace/SWEEP_DONE
# The wrapper can return long before the rounds finish; the sentinel is the only
# reliable completion signal. Diagnose ONLY from the per-round results.$i.json
# files -- sweep.log is 8 interleaved streams sharing one fd and is spliced garbage.

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2975_rheumatology_practice_biologic_therapy_coordination
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
