#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2993.
#
# Usage (ALWAYS launch it exactly like this, detached from your Bash call's process group):
#   rm -f /home/ubuntu/github/CodingPRD/tasks/task_2993_coal_combustion_residual_closure_groundwater_monitoring/workspace/SWEEP_DONE
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2993_coal_combustion_residual_closure_groundwater_monitoring/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2993_coal_combustion_residual_closure_groundwater_monitoring/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel file SWEEP_DONE. The setsid wrapper returns almost
# immediately while the 8 rounds keep running -- an early return is NOT a finished
# sweep. NEVER relaunch the sweep because the wrapper returned; wait for SWEEP_DONE.
#
# Do not diagnose from sweep.log: 8 concurrent rounds share one stdout fd, so the
# log is interleaved garbage. Diagnose only from the per-round results.$i.json files.

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2993_coal_combustion_residual_closure_groundwater_monitoring
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
