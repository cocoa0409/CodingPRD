#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2871.
#
# Usage:  setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2871_stroke_center_certification_telestroke_network/workspace/sweep.sh \
#             > /home/ubuntu/github/CodingPRD/tasks/task_2871_stroke_center_certification_telestroke_network/workspace/sweep.log 2>&1 &
#
# Then POLL for the 8 results files. Do NOT relaunch: the setsid wrapper returns
# long before the rounds finish, and a second launch doubles host load.
#
#   ls -la .../workspace/implementation/results.*.json
#
# Notes:
#  * setsid detaches the process group so an unrelated foreground Bash call in the
#    calling agent cannot SIGTERM the backgrounded rounds mid-request. A server log
#    ending in `Terminated` plus all rounds dying at the same instant is that bug,
#    not a flaky implementation (the runner itself only ever uses kill -9 / `Killed`).
#  * sweep.log interleaves 8 concurrent writers on one fd and is spliced garbage.
#    Diagnose ONLY from the per-round results.$i.json files.
#  * No --api-url: the runner claims a free port per round via its ports.tsv lock.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2871_stroke_center_certification_telestroke_network
IMPL_DIR="$TASK_DIR/workspace/implementation"

rm -f "$IMPL_DIR"/results.*.json

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
echo "SWEEP_COMPLETE"
