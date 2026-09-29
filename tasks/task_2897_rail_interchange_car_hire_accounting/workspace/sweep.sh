#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2897_rail_interchange_car_hire_accounting.
#
# Usage (ALWAYS launch it exactly like this, from the Step 7 subagent):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2897_rail_interchange_car_hire_accounting/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2897_rail_interchange_car_hire_accounting/workspace/sweep.log 2>&1 &
#
# Why a script file and not an inline one-liner: quoting $i through
# `setsid nohup bash -c '...'` inside a Bash tool call reliably injects literal
# quote characters into --start-command, and all 8 rounds then die at t=0 with
# ServerStartError and no results.*.json at all. A file has no quoting layers.
#
# Why setsid: without it the backgrounded rounds take SIGTERM the moment any
# unrelated foreground Bash call in the agent returns. Tests then die mid-request
# with RemoteDisconnected / ConnectionResetError, which is indistinguishable from
# a flaky implementation. Tell: server log ending in `Terminated` (the runner
# itself only ever uses kill -9 / `Killed`) and every round dying at the same
# wall-clock instant.
#
# Note: setsid returns ~immediately while the rounds keep running. Do NOT relaunch.
# Poll for all 8 results.$i.json files instead.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2897_rail_interchange_car_hire_accounting
IMPL="$TASK/workspace/implementation"

rm -f "$IMPL"/results.*.json

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
echo "SWEEP_COMPLETE $(date -u +%Y-%m-%dT%H:%M:%SZ)"
