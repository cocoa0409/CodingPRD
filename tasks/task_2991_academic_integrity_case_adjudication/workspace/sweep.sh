#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2991_academic_integrity_case_adjudication.
#
# Usage (ALWAYS launch it detached, exactly like this):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2991_academic_integrity_case_adjudication/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2991_academic_integrity_case_adjudication/workspace/sweep.log 2>&1 &
#
# The setsid wrapper is mandatory: without it the 8 background rounds receive
# SIGTERM the instant any unrelated foreground Bash call in the calling agent
# returns, and the tests die mid-request with RemoteDisconnected /
# ConnectionResetError -- indistinguishable from a flaky implementation.
#
# The wrapper command RETURNS IMMEDIATELY (in ~1 minute) while the rounds keep
# running. Do NOT relaunch it. Poll for the sentinel instead:
#   test -f .../workspace/SWEEP_DONE
# and only then read results.1.json .. results.8.json.
#
# sweep.log is 8 concurrent writers sharing one fd -- it is spliced garbage.
# NEVER diagnose from sweep.log. Diagnose only from the per-round
# results.$i.json files.

set -u

T=/home/ubuntu/github/CodingPRD/tasks/task_2991_academic_integrity_case_adjudication
IMPL="$T/workspace/implementation"

rm -f "$IMPL"/results.*.json
rm -f "$T/workspace/SWEEP_DONE"

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$T/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.$i.json" &
done

wait

touch "$T/workspace/SWEEP_DONE"
echo "SWEEP COMPLETE"
