#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2945.
#
# Usage (ALWAYS launch it exactly like this, detached):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2945_neighborhood_fiber_build_preorder_campaign/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2945_neighborhood_fiber_build_preorder_campaign/workspace/sweep.log 2>&1 &
#
# Then POLL for completion — do NOT relaunch:
#   while [ ! -f .../workspace/SWEEP_DONE ]; do sleep 30; done
#
# Why this exists as a script file rather than an inline one-liner:
#  * setsid detaches the round PGID so no unrelated foreground Bash call in the
#    calling agent can SIGTERM the rounds mid-request (that failure looks exactly
#    like a flaky implementation: RemoteDisconnected / ConnectionResetError, every
#    round dying at the same instant, server log ending in `Terminated`).
#  * A script file avoids the nested-quoting bug that injects literal quote
#    characters into --start-command, which kills all 8 rounds at t=0 with
#    ServerStartError and no results.*.json at all.
#  * The setsid wrapper RETURNS EARLY (~1 min) while the rounds keep running, so
#    exit status means nothing. SWEEP_DONE below is the only completion signal.
#  * --start-command MUST include the `cd` into implementation/, or every round
#    dies in seconds.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2945_neighborhood_fiber_build_preorder_campaign
IMPL=$TASK/workspace/implementation

rm -f "$IMPL"/results.*.json
rm -f "$TASK/workspace/SWEEP_DONE"

echo "=== sweep start $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

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

echo "=== sweep end $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
touch "$TASK/workspace/SWEEP_DONE"
