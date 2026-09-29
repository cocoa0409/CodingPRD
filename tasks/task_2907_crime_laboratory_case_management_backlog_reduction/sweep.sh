#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2907.
#
# Usage (ALWAYS launch it this way, never inline):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2907_crime_laboratory_case_management_backlog_reduction/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2907_crime_laboratory_case_management_backlog_reduction/workspace/sweep.log 2>&1 &
#
# Then POLL for the 8 results files; do NOT relaunch. The setsid wrapper returns
# almost immediately while the rounds keep running detached.
#   ls -la .../workspace/implementation/results.*.json
#
# Never diagnose from sweep.log: 8 concurrent rounds share one fd and the log is
# spliced garbage. Diagnose only from the per-round results.$i.json files.

set -u

T=/home/ubuntu/github/CodingPRD/tasks/task_2907_crime_laboratory_case_management_backlog_reduction
IMPL="$T/workspace/implementation"

rm -f "$IMPL"/results.*.json

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir     "$T/test_suite" \
    --isolation    per-test-server \
    --timeout      120 \
    --test-timeout 30 \
    --results-file "$IMPL/results.$i.json" &
done

wait
echo "SWEEP_COMPLETE"
