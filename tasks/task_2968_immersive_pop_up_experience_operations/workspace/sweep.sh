#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2968_immersive_pop_up_experience_operations.
#
# Usage (ALWAYS launch it exactly like this, detached under setsid so the rounds
# cannot be reaped when an unrelated foreground Bash call in the same agent returns):
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2968_immersive_pop_up_experience_operations/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2968_immersive_pop_up_experience_operations/workspace/sweep.log 2>&1 &
#
# The launcher command above returns in well under a minute while the 8 rounds are
# still running. That early return is EXPECTED and is NOT a failure. Do not relaunch.
# Poll for the sentinel instead:
#
#   ls .../workspace/SWEEP_DONE            # exists only after all 8 rounds joined
#   ls .../workspace/implementation/results.*.json
#
# Diagnose ONLY from the per-round results.$i.json files. Never diagnose from
# sweep.log: all 8 rounds share one file descriptor, so its contents are spliced
# garbage that reads like phantom errors.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2968_immersive_pop_up_experience_operations
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
    --results-file  "$IMPL/results.$i.json" \
    > "$TASK/workspace/round.$i.log" 2>&1 &
done

wait

touch "$TASK/workspace/SWEEP_DONE"
echo "SWEEP COMPLETE: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
