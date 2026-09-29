#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2936_pooled_employer_plan_administration.
#
# Usage (ALWAYS launch it exactly like this, from any cwd):
#   rm -f /home/ubuntu/github/CodingPRD/tasks/task_2936_pooled_employer_plan_administration/workspace/SWEEP_DONE
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2936_pooled_employer_plan_administration/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2936_pooled_employer_plan_administration/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel; do NOT relaunch just because the wrapper returned:
#   ls /home/ubuntu/github/CodingPRD/tasks/task_2936_pooled_employer_plan_administration/workspace/SWEEP_DONE
#
# Diagnose ONLY from the per-round results.$i.json files. sweep.log is 8 concurrent
# writers sharing one fd — its interleaved text is garbage and must not be trusted.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2936_pooled_employer_plan_administration
IMPL=$TASK/workspace/implementation

rm -f "$TASK"/workspace/SWEEP_DONE
rm -f "$IMPL"/results.*.json

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

touch "$TASK"/workspace/SWEEP_DONE
