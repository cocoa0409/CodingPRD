#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2966.
# Launch it EXACTLY like this (never inline the loop in a Bash tool call):
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2966_in_vitro_diagnostic_reagent_manufacturing/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2966_in_vitro_diagnostic_reagent_manufacturing/workspace/sweep.log 2>&1 &
#
# then POLL for workspace/SWEEP_DONE. The setsid wrapper can return long before
# the rounds finish; SWEEP_DONE is the only reliable completion signal. Never
# relaunch the sweep because the launcher returned.
#
# Each round writes its own log (round.$i.log) because 8 rounds sharing one fd
# produces spliced, unreadable output. Diagnose only from results.$i.json and
# the matching round.$i.log.

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2966_in_vitro_diagnostic_reagent_manufacturing
IMPL="$TASK/workspace/implementation"

rm -f "$IMPL"/results.*.json "$TASK"/workspace/SWEEP_DONE "$TASK"/workspace/round.*.log

echo "sweep start: $(date -u +%Y-%m-%dT%H:%M:%SZ)"

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir     "$TASK/test_suite" \
    --isolation    per-test-server \
    --timeout      120 \
    --test-timeout 30 \
    --results-file "$IMPL/results.$i.json" \
    > "$TASK/workspace/round.$i.log" 2>&1 &
done

wait

echo "sweep end: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
touch "$TASK/workspace/SWEEP_DONE"
