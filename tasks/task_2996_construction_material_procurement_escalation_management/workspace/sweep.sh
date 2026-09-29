#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2996.
#
# Usage (ALWAYS launch it exactly like this, detached, so the rounds cannot be reaped):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2996_construction_material_procurement_escalation_management/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2996_construction_material_procurement_escalation_management/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel — never relaunch:
#   ls .../implementation/SWEEP_DONE   # appears only after all 8 rounds have joined
#
# Notes for whoever maintains this:
#  * setsid is mandatory. Without it the backgrounded rounds take SIGTERM the moment
#    any unrelated foreground Bash call in the calling agent returns, and tests die
#    mid-request with RemoteDisconnected / ConnectionResetError. The tell is a server
#    log ending in `Terminated` (the runner itself only ever uses kill -9 / `Killed`)
#    and every round dying at the same wall-clock instant.
#  * The wrapper command may return long before the sweep finishes. That is expected.
#    Poll SWEEP_DONE / results.$i.json. Relaunching on an early return doubles the load
#    and corrupts the results files.
#  * Do NOT diagnose from sweep.log — 8 concurrent rounds share one fd and the file is
#    spliced garbage. Diagnose only from the per-round results.$i.json files.
#  * --start-command MUST contain the `cd` into the implementation dir, or every round
#    dies within seconds with ServerStartError and writes no results file at all.
#  * Omit --api-url: the runner claims a free port per round via its ports.tsv lock and
#    exports it as $PORT, so concurrent rounds (and other pipelines) do not collide.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2996_construction_material_procurement_escalation_management
IMPL_DIR="$TASK_DIR/workspace/implementation"

rm -f "$IMPL_DIR"/results.*.json "$IMPL_DIR/SWEEP_DONE"

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
touch "$IMPL_DIR/SWEEP_DONE"
