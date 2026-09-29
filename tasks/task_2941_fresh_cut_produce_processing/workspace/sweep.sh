#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2941_fresh_cut_produce_processing.
#
# USAGE (always launch exactly like this, never inline the loop yourself):
#   cd /home/ubuntu/github/CodingPRD/tasks/task_2941_fresh_cut_produce_processing/workspace
#   setsid nohup bash sweep.sh > /dev/null 2>&1 &
#   # then POLL for the sentinel; do NOT relaunch:
#   #   ls SWEEP_DONE 2>/dev/null && echo done
#
# Notes / hard-won rules:
#  * setsid detaches the round processes from this agent's process group, so an
#    unrelated foreground Bash call returning does NOT SIGTERM the rounds
#    mid-request (which looks exactly like a flaky implementation).
#  * The wrapper may return long before the sweep finishes. NEVER relaunch.
#    Poll for SWEEP_DONE / results.*.json instead.
#  * All 8 rounds share one sweep.log fd, so sweep.log is spliced garbage.
#    Diagnose ONLY from the per-round results.$i.json files.
#  * The runner claims a free port per round via its own lockfile, so no
#    --api-url is passed and the 8 rounds cannot collide.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2941_fresh_cut_produce_processing
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
    > "$TASK/workspace/sweep.round.$i.log" 2>&1 &
done

wait

touch "$TASK/workspace/SWEEP_DONE"
