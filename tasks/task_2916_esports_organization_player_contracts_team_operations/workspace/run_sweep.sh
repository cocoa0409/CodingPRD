#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2916.
#
# Usage (ALWAYS launch it exactly like this, from anywhere):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2916_esports_organization_player_contracts_team_operations/workspace/run_sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2916_esports_organization_player_contracts_team_operations/workspace/sweep.log 2>&1 &
#
# setsid detaches the round processes into their own session so they are NOT
# reaped with SIGTERM when an unrelated foreground Bash call in the agent
# returns. Without it every round dies at the same instant with
# RemoteDisconnected / ConnectionResetError and the server log ends in
# `Terminated` -- which looks exactly like a flaky implementation but is not.
#
# The wrapper returns almost immediately; the rounds keep running. Do NOT
# relaunch. Poll for the 8 results files instead:
#   ls -la .../implementation/results.*.json
# and only read them once all 8 exist AND no prd-bench-local-run processes for
# this task remain (pgrep -fa "results.*task_2916").
#
# Never diagnose from sweep.log -- 8 concurrent rounds share one fd and the log
# is spliced garbage. Diagnose only from the per-round results.$i.json files.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2916_esports_organization_player_contracts_team_operations
IMPL="$TASK/workspace/implementation"

rm -f "$IMPL"/results.*.json

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$TASK/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.${i}.json" &
done

wait
echo "SWEEP_DONE $(date -u +%Y-%m-%dT%H:%M:%SZ)"
