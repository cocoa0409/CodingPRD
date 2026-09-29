#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2951.
# Usage:  setsid nohup bash /path/to/workspace/sweep.sh > /path/to/workspace/sweep.log 2>&1 &
# Then poll for the SWEEP_DONE sentinel; never relaunch while it is absent.
T=/home/ubuntu/github/CodingPRD/tasks/task_2951_cosmetology_board_inspection_establishment_compliance
IMPL="$T/workspace/implementation"
rm -f "$IMPL"/results.*.json "$T/workspace/SWEEP_DONE"
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$T/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.$i.json" &
done
wait
touch "$T/workspace/SWEEP_DONE"
