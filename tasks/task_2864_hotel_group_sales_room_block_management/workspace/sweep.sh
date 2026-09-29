#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2864.
# Run it ONLY like this (setsid detaches the round processes from the agent's
# process group, so an unrelated foreground Bash call cannot SIGTERM them):
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2864_hotel_group_sales_room_block_management/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2864_hotel_group_sales_room_block_management/workspace/sweep.log 2>&1 &
#
# The wrapper returns almost immediately; that does NOT mean the sweep is done.
# Poll for the 8 results files instead of relaunching:
#   ls .../workspace/implementation/results.*.json | wc -l
# Never diagnose from sweep.log — 8 rounds share one fd and the text interleaves
# into garbage. Diagnose only from the per-round results.$i.json files.

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2864_hotel_group_sales_room_block_management
IMPL_DIR="$TASK_DIR/workspace/implementation"

rm -f "$IMPL_DIR"/results.*.json

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
echo "SWEEP_DONE"
