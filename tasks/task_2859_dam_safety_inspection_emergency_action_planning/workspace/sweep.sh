#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2859.
#
# Usage:   bash /home/ubuntu/github/CodingPRD/tasks/task_2859_dam_safety_inspection_emergency_action_planning/workspace/sweep.sh
#
# Launch it detached so no unrelated foreground Bash call can reap the rounds:
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2859_dam_safety_inspection_emergency_action_planning/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2859_dam_safety_inspection_emergency_action_planning/workspace/sweep.log 2>&1 &
#
# NOTE: the setsid wrapper returns almost immediately (~1 min) while the rounds keep
# running. Do NOT relaunch. Poll for the 8 results files instead:
#   ls /home/ubuntu/github/CodingPRD/tasks/task_2859_dam_safety_inspection_emergency_action_planning/workspace/implementation/results.*.json
# and only read them once all 8 exist AND `pgrep -f "results.*json" | wc -l` has gone to 0.
#
# Also NOTE: all 8 rounds share this script's stdout, so sweep.log is interleaved
# garbage. Diagnose ONLY from the per-round results.$i.json files.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2859_dam_safety_inspection_emergency_action_planning
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
echo "SWEEP_DONE"
