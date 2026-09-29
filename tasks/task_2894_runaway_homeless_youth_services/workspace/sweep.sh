#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2894_runaway_homeless_youth_services.
#
# Usage:  setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2894_runaway_homeless_youth_services/workspace/sweep.sh \
#             > /home/ubuntu/github/CodingPRD/tasks/task_2894_runaway_homeless_youth_services/workspace/sweep.log 2>&1 &
#
# setsid is MANDATORY: without it the eight backgrounded rounds take SIGTERM the
# moment any unrelated foreground Bash call in the calling agent returns, and the
# tests die mid-request with RemoteDisconnected / ConnectionResetError -- which is
# indistinguishable from a flaky implementation.
#
# The wrapper returns almost immediately; that does NOT mean the sweep finished.
# Poll for the eight results.$i.json files. Never relaunch a sweep that is still running.
#
# Do not add --api-url: the runner claims a free port per round via
# ~/.cache/prd-bench-local-runner/ports.tsv (flock) and exports it as $PORT.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2894_runaway_homeless_youth_services
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
