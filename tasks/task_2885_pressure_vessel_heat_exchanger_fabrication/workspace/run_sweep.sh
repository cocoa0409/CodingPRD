#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2885.
#
# Usage:  setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2885_pressure_vessel_heat_exchanger_fabrication/workspace/run_sweep.sh \
#             > /home/ubuntu/github/CodingPRD/tasks/task_2885_pressure_vessel_heat_exchanger_fabrication/workspace/sweep.log 2>&1 &
#
# NOTES (do not "simplify" these away):
#  * setsid is mandatory. Without it the backgrounded rounds take SIGTERM the moment any
#    unrelated foreground Bash call in the calling agent returns, and tests die mid-request
#    with RemoteDisconnected / ConnectionResetError -- indistinguishable from a flaky impl.
#    The tell is a server log ending in `Terminated` (the runner itself only ever uses
#    kill -9 / `Killed`) and every round dying at the same wall-clock instant.
#  * The setsid wrapper RETURNS EARLY (~1 min) while the rounds keep running. Do NOT relaunch.
#    Poll for results.$i.json (i=1..8) plus the DONE marker below instead.
#  * sweep.log is spliced garbage -- 8 concurrent rounds share one fd. Diagnose ONLY from the
#    per-round results.$i.json files.
#  * --start-command MUST include the `cd .../implementation` or every round dies in seconds
#    with ServerStartError and no results file at all.
#  * Omit --api-url: the runner claims a free port per round via
#    ~/.cache/prd-bench-local-runner/ports.tsv and exports it as $PORT.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2885_pressure_vessel_heat_exchanger_fabrication
IMPL_DIR="$TASK_DIR/workspace/implementation"

rm -f "$IMPL_DIR"/results.*.json
rm -f "$TASK_DIR/workspace/sweep.DONE"

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

date -u +%Y-%m-%dT%H:%M:%SZ > "$TASK_DIR/workspace/sweep.DONE"
echo "SWEEP COMPLETE"
