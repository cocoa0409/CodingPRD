#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2877.
#
# Usage:  bash /home/ubuntu/github/CodingPRD/tasks/task_2877_build_to_rent_community_development_lease_up/workspace/sweep.sh
#
# Launches all 8 rounds detached via setsid so that no unrelated foreground Bash
# call in the calling agent can reap them with SIGTERM.  Returns almost
# immediately -- it does NOT wait for the sweep.  Poll for the 8 result files:
#
#   ls -la .../workspace/implementation/results.*.json
#
# NEVER relaunch the sweep while a previous one is still running, and NEVER use a
# broad pkill to clean up -- up to 32 other pipelines share this host.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2877_build_to_rent_community_development_lease_up
IMPL="$TASK/workspace/implementation"

rm -f "$IMPL"/results.*.json
rm -f "$TASK"/workspace/sweep.log

setsid nohup bash -c '
TASK=/home/ubuntu/github/CodingPRD/tasks/task_2877_build_to_rent_community_development_lease_up
IMPL="$TASK/workspace/implementation"
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
echo "SWEEP_ALL_ROUNDS_EXITED"
' > "$TASK/workspace/sweep.log" 2>&1 < /dev/null &

echo "sweep launched detached; poll for $IMPL/results.{1..8}.json"
