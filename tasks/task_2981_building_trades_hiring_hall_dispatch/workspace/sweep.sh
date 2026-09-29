#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2981_building_trades_hiring_hall_dispatch.
#
# Pre-written by the pipeline orchestrator. DO NOT rewrite the sweep as an inline
# `setsid nohup bash -c '...'` one-liner: the nested quoting mangles
# --start-command and every round dies at t=0 with ServerStartError.
#
# Invoke it EXACTLY like this (one Bash call, then poll -- never re-launch):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2981_building_trades_hiring_hall_dispatch/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2981_building_trades_hiring_hall_dispatch/workspace/sweep.log 2>&1 &
#
# The wrapper returns within ~1 minute while the 8 rounds are still running.
# That early return is EXPECTED and is not a failure. Poll for the sentinel:
#   ls .../workspace/SWEEP_DONE
# and only read results once it exists. Relaunching because the wrapper
# returned will double the load and corrupt the results files.
#
# sweep.log is 8 concurrent writers sharing one fd -- it is spliced garbage.
# Diagnose ONLY from the per-round results.$i.json files.
set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2981_building_trades_hiring_hall_dispatch
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
