#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2958.
#
# Usage (ALWAYS launch it this way — never inline the loop):
#   rm -f /home/ubuntu/github/CodingPRD/tasks/task_2958_technical_documentation_release_notes_publishing/workspace/implementation/results.*.json \
#         /home/ubuntu/github/CodingPRD/tasks/task_2958_technical_documentation_release_notes_publishing/workspace/SWEEP_DONE
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2958_technical_documentation_release_notes_publishing/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2958_technical_documentation_release_notes_publishing/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel; do NOT relaunch:
#   ls /home/ubuntu/github/CodingPRD/tasks/task_2958_technical_documentation_release_notes_publishing/workspace/SWEEP_DONE
#
# Notes:
#  - setsid detaches the process group, so the 8 background rounds are NOT
#    SIGTERMed when an unrelated foreground Bash call in the agent returns.
#    Without it, rounds die mid-request with RemoteDisconnected and it looks
#    exactly like a flaky implementation.
#  - The setsid wrapper returns almost immediately. That is NOT completion.
#    SWEEP_DONE is the only completion signal.
#  - sweep.log interleaves 8 concurrent writers into one fd and is spliced
#    garbage. Diagnose ONLY from the per-round results.$i.json files.
#  - No --api-url: the runner claims a free port per round via its lockfile.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2958_technical_documentation_release_notes_publishing
IMPL_DIR="$TASK_DIR/workspace/implementation"

rm -f "$TASK_DIR/workspace/SWEEP_DONE"
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

touch "$TASK_DIR/workspace/SWEEP_DONE"
echo "SWEEP COMPLETE: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
ls -la "$IMPL_DIR"/results.*.json
