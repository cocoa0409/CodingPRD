#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2973_academic_program_review_discontinuation.
#
# Usage (ALWAYS launch it exactly like this, from the fix subagent):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2973_academic_program_review_discontinuation/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2973_academic_program_review_discontinuation/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel file SWEEP_DONE:
#   ls .../workspace/SWEEP_DONE
# The `setsid nohup ... &` wrapper often RETURNS WITHIN A MINUTE while the 8
# rounds are still running. That early return is NOT the sweep finishing.
# NEVER relaunch the sweep because the launch command returned. Poll SWEEP_DONE.
#
# Do not read sweep.log for diagnosis: 8 concurrent rounds share one fd and the
# output is interleaved garbage. Diagnose ONLY from results.$i.json.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2973_academic_program_review_discontinuation
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
echo "SWEEP COMPLETE $(date -u +%Y-%m-%dT%H:%M:%SZ)"
