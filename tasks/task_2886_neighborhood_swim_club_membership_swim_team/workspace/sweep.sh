#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2886_neighborhood_swim_club_membership_swim_team.
#
# Usage (ALWAYS launch it this way, detached, so the rounds cannot be reaped):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2886_neighborhood_swim_club_membership_swim_team/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2886_neighborhood_swim_club_membership_swim_team/workspace/sweep.log 2>&1 &
#
# Then POLL for the 8 results files:
#   ls -la .../workspace/implementation/results.*.json
# The setsid wrapper returns almost immediately while the rounds keep running.
# NEVER relaunch the sweep because the wrapper "finished" — wait for 8 results files.
#
# Do NOT diagnose from sweep.log: 8 concurrent rounds share one fd and the log is
# spliced garbage. Diagnose only from the per-round results.$i.json files.

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2886_neighborhood_swim_club_membership_swim_team
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
echo "SWEEP_COMPLETE"
