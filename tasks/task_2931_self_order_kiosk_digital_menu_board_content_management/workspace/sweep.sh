#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2931.
#
# USAGE (always launch it exactly like this, detached from the agent's process group):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2931_self_order_kiosk_digital_menu_board_content_management/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2931_self_order_kiosk_digital_menu_board_content_management/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel file SWEEP_DONE. Do NOT relaunch the sweep because the
# launching command returned quickly — setsid returns almost immediately while the 8
# rounds keep running. Poll like this:
#   while [ ! -f .../workspace/SWEEP_DONE ]; do sleep 60; done
#
# Diagnose ONLY from the per-round results.$i.json files. workspace/sweep.log is 8
# concurrent writers sharing one fd, so its contents are interleaved garbage.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2931_self_order_kiosk_digital_menu_board_content_management
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

date -u +%Y-%m-%dT%H:%M:%S.%3NZ > "$TASK_DIR/workspace/SWEEP_DONE"
