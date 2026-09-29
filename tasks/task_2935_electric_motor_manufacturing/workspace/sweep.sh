#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2935_electric_motor_manufacturing.
#
# Launch it ALWAYS like this (setsid detaches it from the agent's process group so
# the rounds cannot be reaped by SIGTERM when an unrelated foreground Bash call returns):
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2935_electric_motor_manufacturing/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2935_electric_motor_manufacturing/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel; do NOT relaunch just because the wrapper returned early:
#   ls /home/ubuntu/github/CodingPRD/tasks/task_2935_electric_motor_manufacturing/workspace/SWEEP_DONE
# When SWEEP_DONE exists, all 8 rounds have finished. Diagnose ONLY from the per-round
# results.$i.json files — sweep.log is 8 concurrent writers sharing one fd and is spliced garbage.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2935_electric_motor_manufacturing
IMPL_DIR="$TASK_DIR/workspace/implementation"

rm -f "$IMPL_DIR"/results.*.json
rm -f "$TASK_DIR/workspace/SWEEP_DONE"

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL_DIR && bash start.sh" \
    --test-dir       "$TASK_DIR/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL_DIR/results.$i.json" &
done

wait

touch "$TASK_DIR/workspace/SWEEP_DONE"
echo "SWEEP COMPLETE"
