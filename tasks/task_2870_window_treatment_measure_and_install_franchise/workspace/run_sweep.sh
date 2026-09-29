#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2870.
#
# Usage (ALWAYS launch it detached so the rounds cannot be reaped when an
# unrelated foreground Bash call in the same agent returns):
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2870_window_treatment_measure_and_install_franchise/workspace/run_sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2870_window_treatment_measure_and_install_franchise/workspace/sweep.log 2>&1 &
#
# Then POLL for the 8 results files. Do NOT relaunch just because the wrapper
# returned: setsid returns almost immediately while the rounds keep running.
#
#   ls -la .../workspace/implementation/results.*.json
#
# Diagnose ONLY from the per-round results.$i.json files. sweep.log is 8
# concurrent writers sharing one fd, so its text is interleaved garbage.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2870_window_treatment_measure_and_install_franchise
IMPL_DIR="$TASK_DIR/workspace/implementation"

rm -f "$IMPL_DIR"/results.*.json

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL_DIR && bash start.sh" \
    --test-dir      "$TASK_DIR/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL_DIR/results.$i.json" &
done

wait

echo "SWEEP_WRAPPER_DONE"
ls -la "$IMPL_DIR"/results.*.json
