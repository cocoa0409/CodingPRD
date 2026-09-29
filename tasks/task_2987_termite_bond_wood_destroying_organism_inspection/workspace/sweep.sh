#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2987.
#
# Usage (ALWAYS launch it detached so the rounds cannot be reaped by a
# later foreground Bash call in the same agent):
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2987_termite_bond_wood_destroying_organism_inspection/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2987_termite_bond_wood_destroying_organism_inspection/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel file SWEEP_DONE. Do NOT relaunch the sweep just
# because the setsid wrapper returned early -- it returns long before the
# rounds finish.
#
#   ls .../workspace/SWEEP_DONE            # appears only after all 8 rounds joined
#   ls .../workspace/implementation/results.*.json
#
# Diagnose ONLY from the per-round results.$i.json files. sweep.log is 8
# concurrent writers sharing one fd; its interleaved text is not trustworthy.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2987_termite_bond_wood_destroying_organism_inspection
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

date -u +%Y-%m-%dT%H:%M:%S.%3NZ > "$TASK/workspace/SWEEP_DONE"
echo "SWEEP COMPLETE" >> "$TASK/workspace/SWEEP_DONE"
