#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2930.
#
# Usage (ALWAYS launch it detached so the rounds cannot be reaped by a later
# foreground Bash call in the same agent):
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2930_agricultural_carbon_program_enrollment_credit_issuance/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2930_agricultural_carbon_program_enrollment_credit_issuance/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel file SWEEP_DONE. Do NOT relaunch the sweep just
# because the launching command returned quickly — setsid returns immediately
# while the 8 rounds keep running:
#
#   ls .../workspace/SWEEP_DONE  &&  ls .../workspace/implementation/results.*.json
#
# Diagnose ONLY from the per-round results.$i.json files. sweep.log is 8
# concurrent writers sharing one fd, so its text is interleaved garbage.

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2930_agricultural_carbon_program_enrollment_credit_issuance
IMPL="$TASK/workspace/implementation"

rm -f "$IMPL"/results.*.json
rm -f "$TASK/workspace/SWEEP_DONE"

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

touch "$TASK/workspace/SWEEP_DONE"
echo "SWEEP COMPLETE"
