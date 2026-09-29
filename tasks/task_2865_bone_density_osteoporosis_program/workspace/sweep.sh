#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2865_bone_density_osteoporosis_program.
#
# Usage:  setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2865_bone_density_osteoporosis_program/workspace/sweep.sh > /home/ubuntu/github/CodingPRD/tasks/task_2865_bone_density_osteoporosis_program/workspace/sweep.log 2>&1 &
#
# setsid detaches the rounds into their own session so they are NOT reaped
# (SIGTERM) when an unrelated foreground Bash call in the calling agent returns.
# Never launch the rounds inline; never drop setsid.
#
# The wrapper returns long before the rounds finish. Do NOT relaunch it.
# Poll for the 8 results files instead:
#   ls /home/ubuntu/github/CodingPRD/tasks/task_2865_bone_density_osteoporosis_program/workspace/implementation/results.*.json | wc -l
# and only read results once DONE.marker exists (written after `wait`).

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2865_bone_density_osteoporosis_program
IMPL="$TASK/workspace/implementation"

rm -f "$IMPL"/results.*.json "$TASK/workspace/DONE.marker"

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

echo "sweep finished at $(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$TASK/workspace/DONE.marker"
