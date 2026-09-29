#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2995_reentry_employment_services.
#
# Usage (ALWAYS launch it exactly like this, detached from your Bash call):
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2995_reentry_employment_services/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2995_reentry_employment_services/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel file:
#   .../workspace/implementation/SWEEP_DONE
# It is touched only after all 8 rounds have been joined with `wait`.
#
# NOTES
#  * setsid is mandatory. Without it the 8 background rounds take SIGTERM the
#    moment any unrelated foreground Bash call in the agent returns, and tests
#    die mid-request with RemoteDisconnected / ConnectionResetError — which is
#    indistinguishable from a flaky implementation.
#  * The `setsid` wrapper often RETURNS WITHIN ~1 MINUTE while the rounds are
#    still running. That is expected. NEVER relaunch on early return — poll for
#    SWEEP_DONE instead.
#  * Diagnose only from the per-round results.$i.json files. sweep.log is 8
#    concurrent writers sharing one fd, so its text is interleaved garbage.
#  * results.json schema: top level has passed/total; per-test entries live in
#    `tests[]` with keys `name`, `status`, `error_message`. It is `status`, NOT
#    pytest's `outcome`, and `error_message`, NOT `message`.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2995_reentry_employment_services
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
    > "$TASK_DIR/workspace/round.$i.log" 2>&1 &
done

wait

touch "$IMPL_DIR/SWEEP_DONE"
echo "SWEEP COMPLETE: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
