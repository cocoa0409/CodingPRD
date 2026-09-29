#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2852.
#
# USAGE (always launch it exactly like this, detached from the agent's process group):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2852_plant_breeding_program_variety_trials/workspace/run_sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2852_plant_breeding_program_variety_trials/workspace/sweep.log 2>&1 &
#
# Then POLL for completion (do NOT relaunch — the setsid wrapper returns almost
# immediately while the 8 rounds keep running):
#   ls -la .../implementation/results.*.json      # 8 files == sweep finished
#
# Never diagnose from sweep.log: 8 concurrent rounds share one fd and the log is
# spliced garbage. Read only the per-round results.$i.json files.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2852_plant_breeding_program_variety_trials
IMPL="$TASK/workspace/implementation"

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

echo "SWEEP_DONE $(date -u +%Y-%m-%dT%H:%M:%SZ)"
