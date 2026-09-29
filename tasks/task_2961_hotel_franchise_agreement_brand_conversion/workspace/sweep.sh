#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2961.
#
# Usage (ALWAYS launch it exactly like this, detached from the agent's process group):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2961_hotel_franchise_agreement_brand_conversion/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2961_hotel_franchise_agreement_brand_conversion/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel; do NOT relaunch just because the wrapper returned early:
#   ls .../workspace/SWEEP_DONE
# The sentinel file is created only after all 8 rounds have been joined with `wait`.
#
# Diagnose ONLY from the per-round results.$i.json files. sweep.log is 8 concurrent
# writers sharing one fd, so its interleaved text is unreliable.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2961_hotel_franchise_agreement_brand_conversion
IMPL_DIR="$TASK_DIR/workspace/implementation"

rm -f "$IMPL_DIR"/results.*.json
rm -f "$TASK_DIR/workspace/SWEEP_DONE"

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL_DIR && bash start.sh" \
    --test-dir      "$TASK_DIR/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL_DIR/results.$i.json" \
    > "$TASK_DIR/workspace/round.$i.log" 2>&1 &
done

wait

touch "$TASK_DIR/workspace/SWEEP_DONE"
echo "ALL 8 ROUNDS JOINED"
