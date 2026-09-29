#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2876.
#
# Usage:   bash /home/ubuntu/github/CodingPRD/tasks/task_2876_brand_recommerce_resale_as_a_service/workspace/sweep.sh
#
# Launches the sweep DETACHED via setsid so the 8 background rounds cannot be
# reaped when an unrelated foreground Bash call in the agent returns. Returns
# almost immediately; the rounds keep running. Poll for the 8 results files:
#
#   ls -la .../workspace/implementation/results.*.json
#
# NEVER relaunch just because this script returned quickly -- that is expected.

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2876_brand_recommerce_resale_as_a_service
IMPL="$TASK/workspace/implementation"

rm -f "$IMPL"/results.*.json
rm -f "$TASK"/workspace/sweep.round*.log
: > "$TASK/workspace/sweep.done"
rm -f "$TASK/workspace/sweep.done"

setsid nohup bash -c '
TASK=/home/ubuntu/github/CodingPRD/tasks/task_2876_brand_recommerce_resale_as_a_service
IMPL="$TASK/workspace/implementation"
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$TASK/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.$i.json" \
    > "$TASK/workspace/sweep.round$i.log" 2>&1 &
done
wait
touch "$TASK/workspace/sweep.done"
' > "$TASK/workspace/sweep.log" 2>&1 < /dev/null &

echo "sweep launched detached; poll for $IMPL/results.{1..8}.json and $TASK/workspace/sweep.done"
