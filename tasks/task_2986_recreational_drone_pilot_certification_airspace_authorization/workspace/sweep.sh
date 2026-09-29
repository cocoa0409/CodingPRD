#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2986.
# Usage:  setsid nohup bash /path/to/workspace/sweep.sh > /path/to/workspace/sweep.log 2>&1 &
# Then poll for the sentinel file workspace/SWEEP_DONE (created only after all 8 rounds join).
T=/home/ubuntu/github/CodingPRD/tasks/task_2986_recreational_drone_pilot_certification_airspace_authorization
IMPL="$T/workspace/implementation"
rm -f "$IMPL"/results.*.json "$T/workspace/SWEEP_DONE"
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$T/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.$i.json" \
    > "$T/workspace/round.$i.log" 2>&1 &
done
wait
date -u +%Y-%m-%dT%H:%M:%SZ > "$T/workspace/SWEEP_DONE"
