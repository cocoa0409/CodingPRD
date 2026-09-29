#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2923.
# Usage:  setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2923_crash_preventability_review_liability_claim_handling/workspace/sweep.sh > /dev/null 2>&1 &
#
# Then POLL for the sentinel; do NOT relaunch:
#   ls .../workspace/SWEEP_DONE   (appears only after all 8 rounds have exited)
#
# Each round writes its own results file AND its own log. Never diagnose from a
# shared log — 8 concurrent rounds interleave into unreadable garbage.

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2923_crash_preventability_review_liability_claim_handling
IMPL=$TASK/workspace/implementation

rm -f "$TASK/workspace/SWEEP_DONE"
rm -f "$IMPL"/results.*.json
rm -f "$TASK/workspace"/round.*.log

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$TASK/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.$i.json" \
    > "$TASK/workspace/round.$i.log" 2>&1 &
done

wait

touch "$TASK/workspace/SWEEP_DONE"
