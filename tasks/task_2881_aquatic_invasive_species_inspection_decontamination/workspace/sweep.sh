#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2881.
# Usage:  setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2881_aquatic_invasive_species_inspection_decontamination/workspace/sweep.sh > /home/ubuntu/github/CodingPRD/tasks/task_2881_aquatic_invasive_species_inspection_decontamination/workspace/sweep.log 2>&1 &
#
# NEVER inline this loop into a shell one-liner with nested quoting — the
# '"'"'$i'"'"' escape corrupts --start-command and all 8 rounds die at t=0.
# NEVER launch it without setsid — the rounds take SIGTERM when any unrelated
# foreground Bash call in the same agent returns.
#
# sweep.log is 8 concurrent writers sharing one fd; it is spliced garbage.
# Diagnose ONLY from the per-round results.$i.json files.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2881_aquatic_invasive_species_inspection_decontamination
IMPL="$TASK/workspace/implementation"

rm -f "$IMPL"/results.*.json

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
echo "SWEEP_DONE"
