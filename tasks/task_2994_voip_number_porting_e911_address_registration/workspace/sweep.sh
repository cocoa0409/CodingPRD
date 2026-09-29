#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2994.
#
# Usage:  setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2994_voip_number_porting_e911_address_registration/workspace/sweep.sh \
#             > /home/ubuntu/github/CodingPRD/tasks/task_2994_voip_number_porting_e911_address_registration/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel; do NOT relaunch just because the wrapper returned:
#   ls .../workspace/SWEEP_DONE
#
# Notes:
#  - setsid detaches the process group so the backgrounded rounds are not SIGTERMed
#    when an unrelated foreground Bash call in the calling agent returns.
#  - The `cd` into implementation/ inside --start-command is MANDATORY.
#  - Do NOT pass --api-url; the runner claims a free port per round and exports $PORT.
#  - sweep.log interleaves 8 concurrent writers and is spliced garbage. Diagnose ONLY
#    from the per-round results.$i.json files.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2994_voip_number_porting_e911_address_registration
IMPL=$TASK/workspace/implementation

rm -f "$TASK"/workspace/SWEEP_DONE
rm -f "$IMPL"/results.*.json

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
echo "SWEEP COMPLETE"
