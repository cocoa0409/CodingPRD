#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2956.
#
# Usage:  setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2956_physician_practice_acquisition_integration/workspace/sweep.sh > /home/ubuntu/github/CodingPRD/tasks/task_2956_physician_practice_acquisition_integration/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel file:
#   /home/ubuntu/github/CodingPRD/tasks/task_2956_physician_practice_acquisition_integration/workspace/SWEEP_DONE
# The `setsid nohup ... &` wrapper RETURNS IMMEDIATELY (often within ~1 minute)
# while the 8 rounds keep running.  Do NOT interpret that early return as the
# sweep having finished, and NEVER relaunch the sweep because the wrapper
# returned — you will get 16 concurrent rounds.  The sweep is finished when, and
# only when, SWEEP_DONE exists.
#
# Do not read sweep.log for diagnosis: all 8 rounds share one stdout fd, so the
# log is interleaved garbage.  Diagnose ONLY from the per-round
# implementation/results.$i.json files.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2956_physician_practice_acquisition_integration
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
    --results-file  "$IMPL/results.$i.json" &
done

wait

touch "$TASK/workspace/SWEEP_DONE"
