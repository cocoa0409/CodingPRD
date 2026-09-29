#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2924.
#
# Usage (ALWAYS launch it exactly like this, detached, so the rounds cannot be
# reaped when an unrelated foreground Bash call in your agent returns):
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2924_obstacle_race_wave_start_course_operations/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2924_obstacle_race_wave_start_course_operations/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel file:
#   ls .../workspace/SWEEP_DONE
# The `setsid nohup ... &` wrapper returns almost immediately — that return does
# NOT mean the sweep finished. Never relaunch the sweep because the wrapper
# returned; wait for SWEEP_DONE to appear, then read results.1..8.json.
#
# Do not diagnose anything from sweep.log — 8 concurrent rounds share one fd and
# the log is interleaved garbage. Diagnose ONLY from the per-round
# implementation/results.$i.json files.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2924_obstacle_race_wave_start_course_operations
IMPL_DIR="$TASK_DIR/workspace/implementation"

rm -f "$IMPL_DIR"/results.*.json
rm -f "$TASK_DIR/workspace/SWEEP_DONE"

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

touch "$TASK_DIR/workspace/SWEEP_DONE"
echo "SWEEP COMPLETE"
