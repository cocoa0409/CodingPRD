#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2888.
#
# ALWAYS launch it detached, exactly like this (from any cwd):
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2888_tourism_improvement_district_administration/workspace/run_sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2888_tourism_improvement_district_administration/workspace/sweep.log 2>&1 < /dev/null &
#
# Then POLL for the 8 results files. Do not relaunch: the setsid wrapper returns
# almost immediately while the rounds keep running, and a second launch would
# double the load and clobber the results files.
#
# Each round writes its own log (round.$i.log) so output is never interleaved.
# Diagnose only from results.$i.json / round.$i.log, never from sweep.log.

set -uo pipefail

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2888_tourism_improvement_district_administration
IMPL="$TASK/workspace/implementation"

rm -f "$IMPL"/results.*.json
rm -f "$TASK"/workspace/round.*.log
rm -f "$TASK"/workspace/SWEEP_DONE

echo "SWEEP_START $(date -u +%Y-%m-%dT%H:%M:%SZ)"

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir "$TASK/test_suite" \
    --isolation per-test-server \
    --timeout 120 \
    --test-timeout 30 \
    --results-file "$IMPL/results.$i.json" \
    > "$TASK/workspace/round.$i.log" 2>&1 &
done

wait

echo "SWEEP_DONE $(date -u +%Y-%m-%dT%H:%M:%SZ)"
date -u +%Y-%m-%dT%H:%M:%SZ > "$TASK/workspace/SWEEP_DONE"
