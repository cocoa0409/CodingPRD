#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2978.
#
# Usage (ALWAYS launch it exactly like this, from any cwd):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2978_hotel_channel_management_rate_distribution/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2978_hotel_channel_management_rate_distribution/workspace/sweep.log 2>&1 &
#
# The setsid wrapper is MANDATORY. Without it the 8 backgrounded rounds are
# reaped with SIGTERM the instant any unrelated foreground Bash call in the
# calling agent returns; the tests then die mid-request with
# RemoteDisconnected / ConnectionResetError, which is indistinguishable from a
# flaky implementation. The tell is a server log ending in `Terminated` (the
# runner itself only ever uses kill -9 / `Killed`) plus every round dying at
# the same wall-clock instant.
#
# The setsid launcher RETURNS IN ABOUT A MINUTE while the rounds are still
# running. That early return is NOT completion and NOT failure. Never relaunch
# on it. Poll for the sentinel instead:
#
#   while [ ! -f "$IMPL/SWEEP_DONE" ]; do sleep 30; done
#
# SWEEP_DONE is touched only after `wait` reaps all 8 rounds.
#
# Diagnose ONLY from the per-round results.$i.json files. sweep.log is 8
# concurrent rounds sharing one file descriptor, so its text is spliced
# garbage and interleaved mid-line; it is useless for diagnosis.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2978_hotel_channel_management_rate_distribution
IMPL="$TASK/workspace/implementation"

rm -f "$IMPL"/results.*.json "$IMPL/SWEEP_DONE"

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$TASK/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.$i.json" \
    > "$IMPL/round.$i.log" 2>&1 &
done

wait

touch "$IMPL/SWEEP_DONE"
echo "SWEEP COMPLETE"
ls -la "$IMPL"/results.*.json
