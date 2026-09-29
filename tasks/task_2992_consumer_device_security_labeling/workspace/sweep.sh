#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2992_consumer_device_security_labeling.
#
# Usage (ALWAYS launch it exactly like this, from any cwd):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2992_consumer_device_security_labeling/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2992_consumer_device_security_labeling/workspace/sweep.log 2>&1 &
#
# WHY setsid: without it, the 8 backgrounded rounds are reaped with SIGTERM the
# moment ANY unrelated foreground Bash call in the same agent returns. The tests
# then die mid-request with RemoteDisconnected / ConnectionResetError, which is
# indistinguishable from a flaky implementation. Tell-tale sign: a server log
# ending in `Terminated` (the runner itself only ever uses kill -9 / `Killed`)
# and all 8 rounds dying at the same wall-clock instant.
#
# WHY a sentinel file: `setsid nohup ... &` returns to the caller in well under a
# minute while the rounds are still running. Do NOT interpret that early return
# as "the sweep finished", and NEVER relaunch on top of a running sweep. Poll for
# SWEEP_DONE instead:
#   while [ ! -f .../workspace/SWEEP_DONE ]; do sleep 30; done
#
# WHY you must not diagnose from sweep.log: all 8 rounds share one stdout fd, so
# the log is spliced garbage. Diagnose ONLY from the per-round results.$i.json.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2992_consumer_device_security_labeling
IMPL_DIR="$TASK_DIR/workspace/implementation"

rm -f "$IMPL_DIR"/results.*.json
rm -f "$TASK_DIR/workspace/SWEEP_DONE"

echo "=== sweep start $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

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

echo "=== sweep end $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
touch "$TASK_DIR/workspace/SWEEP_DONE"
