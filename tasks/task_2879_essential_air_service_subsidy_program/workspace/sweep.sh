#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2879.
#
# USAGE (always launch it exactly like this, never inline the loop yourself):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2879_essential_air_service_subsidy_program/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2879_essential_air_service_subsidy_program/workspace/sweep.log 2>&1 &
#
# Then POLL for completion — do not relaunch:
#   ls /home/ubuntu/github/CodingPRD/tasks/task_2879_essential_air_service_subsidy_program/workspace/implementation/results.*.json
#   test -f .../workspace/sweep.DONE
# `setsid` detaches the process group so the 8 rounds cannot be SIGTERM'd when an
# unrelated foreground Bash call in the calling agent returns. The wrapper may
# appear to return long before the rounds finish; that is expected.
#
# NOTE: sweep.log interleaves 8 concurrent writers on one fd and is spliced
# garbage. Diagnose ONLY from the per-round results.$i.json files.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2879_essential_air_service_subsidy_program
IMPL="$TASK/workspace/implementation"

rm -f "$IMPL"/results.*.json
rm -f "$TASK/workspace/sweep.DONE"

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

date -u +%Y-%m-%dT%H:%M:%S.%3NZ > "$TASK/workspace/sweep.DONE"
