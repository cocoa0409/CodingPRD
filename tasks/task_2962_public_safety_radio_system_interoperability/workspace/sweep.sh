#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2962.
#
# Usage (ALWAYS launch it detached, so the rounds cannot be reaped when an
# unrelated foreground Bash call in the same agent returns):
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2962_public_safety_radio_system_interoperability/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2962_public_safety_radio_system_interoperability/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel — do NOT relaunch just because the wrapper returned:
#   ls .../workspace/implementation/SWEEP_DONE
# SWEEP_DONE only appears after `wait` returns, i.e. after all 8 rounds finished.
#
# Diagnose ONLY from the per-round results.$i.json files. sweep.log is 8
# concurrent writers sharing one fd, so its text is spliced garbage.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2962_public_safety_radio_system_interoperability
IMPL="$TASK/workspace/implementation"

rm -f "$IMPL"/results.*.json "$IMPL/SWEEP_DONE"

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$TASK/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.$i.json" &
done

wait

touch "$IMPL/SWEEP_DONE"
echo "SWEEP COMPLETE"
