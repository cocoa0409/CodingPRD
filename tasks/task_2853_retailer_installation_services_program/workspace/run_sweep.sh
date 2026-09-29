#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2853.
#
# Usage:   bash /home/ubuntu/github/CodingPRD/tasks/task_2853_retailer_installation_services_program/workspace/run_sweep.sh
#
# This script MUST be launched detached so the rounds cannot be reaped when an
# unrelated foreground Bash call in the calling agent returns:
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2853_retailer_installation_services_program/workspace/run_sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2853_retailer_installation_services_program/workspace/sweep.log 2>&1 &
#
# Then POLL for the 8 results files. Do NOT relaunch: the setsid wrapper often
# returns 0 within a minute while the rounds are still running.
#
#   ls -la .../implementation/results.*.json      # until 8 files exist and are stable
#
# Diagnose ONLY from the per-round results.$i.json files. sweep.log is 8
# concurrent writers sharing one fd — its interleaved text is not diagnosable.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2853_retailer_installation_services_program
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

echo "SWEEP_COMPLETE"
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL_DIR/results.$i.json" ]; then
    echo "round $i: present"
  else
    echo "round $i: MISSING"
  fi
done
