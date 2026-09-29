#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2866_manufactured_home_chattel_lending.
#
# Usage (ALWAYS launch it exactly like this, from any cwd):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2866_manufactured_home_chattel_lending/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2866_manufactured_home_chattel_lending/workspace/sweep.log 2>&1 &
#
# The `setsid` is mandatory: without it the 8 backgrounded rounds receive SIGTERM
# the instant any unrelated foreground Bash call in the calling agent returns, and
# the tests die mid-request with RemoteDisconnected / ConnectionResetError — which
# looks exactly like a flaky implementation but is not.
#
# The wrapper returns quickly while the rounds keep running. Do NOT relaunch it.
# Poll for completion instead:
#   ls /home/ubuntu/github/CodingPRD/tasks/task_2866_manufactured_home_chattel_lending/workspace/implementation/results.*.json | wc -l
# and wait until it reads 8. Diagnose ONLY from the per-round results.$i.json files —
# sweep.log is 8 concurrent writers on one fd and is spliced garbage.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2866_manufactured_home_chattel_lending
IMPL_DIR="$TASK_DIR/workspace/implementation"

rm -f "$IMPL_DIR"/results.*.json

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL_DIR && bash start.sh" \
    --test-dir       "$TASK_DIR/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL_DIR/results.$i.json" &
done

wait
echo "SWEEP_COMPLETE"
