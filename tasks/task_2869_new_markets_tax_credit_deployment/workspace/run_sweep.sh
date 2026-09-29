#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2869_new_markets_tax_credit_deployment.
#
# USAGE (always launch it exactly like this, detached, so the rounds cannot be reaped):
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2869_new_markets_tax_credit_deployment/workspace/run_sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2869_new_markets_tax_credit_deployment/workspace/sweep.log 2>&1 &
#
# Then POLL for completion — do NOT relaunch. The setsid wrapper returns almost
# immediately while the 8 rounds keep running:
#
#   ls -la .../workspace/implementation/results.*.json      # want 8 files
#   cat .../workspace/implementation/sweep.done             # written only when all 8 rounds have exited
#
# Never diagnose from sweep.log — 8 concurrent rounds share one fd and the log is
# spliced garbage. Diagnose ONLY from the per-round results.$i.json files.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2869_new_markets_tax_credit_deployment
IMPL_DIR="$TASK_DIR/workspace/implementation"

rm -f "$IMPL_DIR"/results.*.json "$IMPL_DIR/sweep.done"

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL_DIR && bash start.sh" \
    --test-dir      "$TASK_DIR/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL_DIR/results.$i.json" \
    > "$IMPL_DIR/round.$i.log" 2>&1 &
done

wait

date -u +%Y-%m-%dT%H:%M:%S.%3NZ > "$IMPL_DIR/sweep.done"
echo "sweep complete" >> "$IMPL_DIR/sweep.done"
