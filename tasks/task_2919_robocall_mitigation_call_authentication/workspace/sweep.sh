#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2919.
#
# Usage (ALWAYS launch it detached, exactly like this):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2919_robocall_mitigation_call_authentication/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2919_robocall_mitigation_call_authentication/workspace/sweep.log 2>&1 < /dev/null &
#
# Then POLL for the sentinel file SWEEP_DONE. Do NOT relaunch: the setsid
# wrapper returns to your shell almost immediately while the 8 rounds keep
# running in their own session. Relaunching stacks 16 rounds and corrupts
# both sets of results.
#
#   while [ ! -f .../workspace/SWEEP_DONE ]; do sleep 60; done
#
# Diagnose ONLY from the per-round results.$i.json files. sweep.log is 8
# concurrent writers sharing one fd, so its text is spliced garbage.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2919_robocall_mitigation_call_authentication
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
