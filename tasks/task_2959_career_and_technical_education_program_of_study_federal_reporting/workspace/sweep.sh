#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2959.
#
# Usage (ALWAYS launch it detached so the rounds cannot be reaped when an
# unrelated foreground Bash call in the same agent returns):
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2959_career_and_technical_education_program_of_study_federal_reporting/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2959_career_and_technical_education_program_of_study_federal_reporting/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel; do NOT relaunch just because the wrapper returned:
#
#   ls -la .../workspace/SWEEP_DONE .../workspace/implementation/results.*.json
#
# The setsid wrapper often returns 0 within ~1 minute while the 8 rounds are
# still running. SWEEP_DONE is touched only after `wait` returns, so its
# presence — not the wrapper's exit — is the completion signal.
#
# Diagnose ONLY from the per-round results.$i.json files. sweep.log is 8
# concurrent writers sharing one fd, so its text is interleaved garbage.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2959_career_and_technical_education_program_of_study_federal_reporting
IMPL_DIR="$TASK_DIR/workspace/implementation"
WS="$TASK_DIR/workspace"

rm -f "$IMPL_DIR"/results.*.json
rm -f "$WS/SWEEP_DONE"

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

date -u +"%Y-%m-%dT%H:%M:%S.%3NZ" > "$WS/SWEEP_DONE"
echo "SWEEP COMPLETE" >> "$WS/SWEEP_DONE"
