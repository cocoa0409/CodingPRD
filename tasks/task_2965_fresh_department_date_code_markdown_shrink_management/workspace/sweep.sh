#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2965.
#
# Usage (ALWAYS launch it exactly like this, from any cwd):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2965_fresh_department_date_code_markdown_shrink_management/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2965_fresh_department_date_code_markdown_shrink_management/workspace/sweep.log 2>&1 &
#
# Why a script file and not an inline one-liner: the inline
# `'"'"'$T'"'"'`-style quoting needed to nest a for-loop inside
# `setsid nohup bash -c '...'` has repeatedly injected literal quote
# characters into --start-command, which kills all 8 rounds at t=0 with
# ServerStartError and no results.*.json at all. A file has no quoting layer.
#
# Why setsid: without it the backgrounded rounds take SIGTERM the moment any
# unrelated foreground Bash call in the calling agent returns. Tests then die
# mid-request with RemoteDisconnected / ConnectionResetError, every round dies
# at the same wall-clock instant, and the server log ends in `Terminated`
# (the runner itself only ever uses kill -9 / `Killed`). That is
# indistinguishable from a flaky implementation.
#
# Why the DONE sentinel: `setsid nohup ... &` returns to the caller in ~1
# minute while the rounds are still running. Do NOT interpret that early
# return as completion and do NOT relaunch. Poll for SWEEP_DONE instead:
#   while [ ! -f .../workspace/SWEEP_DONE ]; do sleep 60; done
# then read results.1.json .. results.8.json.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2965_fresh_department_date_code_markdown_shrink_management
IMPL="$TASK/workspace/implementation"

rm -f "$IMPL"/results.*.json
rm -f "$TASK/workspace/SWEEP_DONE"

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

touch "$TASK/workspace/SWEEP_DONE"
echo "SWEEP COMPLETE"
