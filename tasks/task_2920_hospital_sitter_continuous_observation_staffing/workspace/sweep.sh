#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2920.
#
# Usage (ALWAYS launch it detached, exactly like this):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2920_hospital_sitter_continuous_observation_staffing/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2920_hospital_sitter_continuous_observation_staffing/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel; do NOT relaunch just because the wrapper returned:
#   ls .../workspace/SWEEP_DONE
# The setsid wrapper often reports success within a minute while the 8 rounds are
# still running. SWEEP_DONE is touched only after `wait` returns, i.e. after all
# 8 rounds have genuinely finished.
#
# Never diagnose from sweep.log: 8 concurrent rounds share one fd and the log is
# interleaved garbage. Diagnose only from the per-round results.$i.json files.
set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2920_hospital_sitter_continuous_observation_staffing
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
