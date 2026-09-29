#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2953_accreditation_body_assessor_program.
#
# Usage (ALWAYS launch it this way, from any cwd):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2953_accreditation_body_assessor_program/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2953_accreditation_body_assessor_program/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel; do NOT relaunch:
#   ls .../workspace/SWEEP_DONE
# The setsid wrapper returns almost immediately while the 8 rounds keep running,
# so an early return is NOT a failure signal. Only SWEEP_DONE means finished.
#
# Diagnose ONLY from the per-round results.$i.json files. sweep.log is 8 concurrent
# rounds sharing one fd — its interleaved text is spliced garbage, not evidence.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2953_accreditation_body_assessor_program
IMPL_DIR="$TASK_DIR/workspace/implementation"

rm -f "$IMPL_DIR"/results.*.json
rm -f "$TASK_DIR/workspace/SWEEP_DONE"

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL_DIR && bash start.sh" \
    --test-dir       "$TASK_DIR/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL_DIR/results.$i.json" \
    > "$TASK_DIR/workspace/round.$i.log" 2>&1 &
done

wait

touch "$TASK_DIR/workspace/SWEEP_DONE"
