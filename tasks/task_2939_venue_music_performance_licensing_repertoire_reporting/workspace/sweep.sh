#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2939.
#
# USAGE (always launch it exactly like this — do NOT hand-inline the loop):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2939_venue_music_performance_licensing_repertoire_reporting/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2939_venue_music_performance_licensing_repertoire_reporting/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel file (do NOT relaunch — setsid makes the wrapper
# return long before the rounds finish):
#   ls .../workspace/SWEEP_DONE   # appears only after all 8 rounds joined
#
# Diagnose ONLY from the per-round results.$i.json files. sweep.log is 8
# concurrent processes sharing one fd and is spliced garbage by construction.

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2939_venue_music_performance_licensing_repertoire_reporting
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
echo "ALL 8 ROUNDS JOINED"
