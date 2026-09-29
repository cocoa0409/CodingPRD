#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2999.
#
# Usage (ALWAYS launch it detached so the rounds cannot be reaped when an
# unrelated foreground Bash call in the same agent returns):
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2999_otolaryngology_practice_allergy_testing_balloon_sinuplasty/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2999_otolaryngology_practice_allergy_testing_balloon_sinuplasty/workspace/sweep.log 2>&1 &
#
# Then POLL for completion — do NOT relaunch:
#   ls .../workspace/implementation/SWEEP_DONE      # sentinel, written only after `wait`
#   ls .../workspace/implementation/results.*.json  # must be 8 files
#
# The setsid wrapper returns almost immediately; that is expected and does NOT
# mean the sweep finished. Never diagnose from sweep.log — 8 concurrent rounds
# share one fd and the file is interleaved garbage. Diagnose only from the
# per-round results.$i.json files.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2999_otolaryngology_practice_allergy_testing_balloon_sinuplasty
IMPL_DIR="$TASK_DIR/workspace/implementation"

rm -f "$IMPL_DIR"/results.*.json "$IMPL_DIR/SWEEP_DONE"

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL_DIR && bash start.sh" \
    --test-dir      "$TASK_DIR/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL_DIR/results.$i.json" \
    > "$IMPL_DIR/round.$i.log" 2>&1 &
done

wait

touch "$IMPL_DIR/SWEEP_DONE"
echo "SWEEP COMPLETE: $(ls -1 "$IMPL_DIR"/results.*.json 2>/dev/null | wc -l) result files"
