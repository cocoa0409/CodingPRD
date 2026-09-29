#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2982.
#
# Usage (ALWAYS launch it this way, detached, so the rounds cannot be reaped
# by an unrelated foreground Bash call returning in the same agent):
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2982_renewable_energy_land_lease_easement_origination/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2982_renewable_energy_land_lease_easement_origination/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel file SWEEP_DONE. Do NOT relaunch the sweep just
# because the wrapper command returned quickly -- setsid returns immediately
# while the 8 rounds keep running.
#
#   ls .../workspace/SWEEP_DONE   # appears only after all 8 rounds finished
#
# Diagnose ONLY from the per-round results.$i.json files. sweep.log interleaves
# 8 concurrent writers on one fd and is spliced garbage.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2982_renewable_energy_land_lease_easement_origination
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
