#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2900.
#
# Launch it EXACTLY like this, so the backgrounded rounds cannot be reaped by
# SIGTERM when an unrelated foreground Bash call in the agent returns:
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2900_electronic_resource_licensing_consortium_purchasing/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2900_electronic_resource_licensing_consortium_purchasing/workspace/sweep.log 2>&1 &
#
# The launcher returns in about a minute while the 8 rounds keep running.
# Do NOT relaunch. Poll for the 8 results files instead:
#
#   ls /home/ubuntu/github/CodingPRD/tasks/task_2900_electronic_resource_licensing_consortium_purchasing/workspace/implementation/results.*.json | wc -l
#
# sweep.log is 8 concurrent writers on one fd and is therefore spliced garbage.
# Diagnose ONLY from the per-round results.$i.json files.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2900_electronic_resource_licensing_consortium_purchasing
IMPL="$TASK/workspace/implementation"

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
echo "SWEEP_DONE"
