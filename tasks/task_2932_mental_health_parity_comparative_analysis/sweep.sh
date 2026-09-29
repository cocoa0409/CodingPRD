#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2932.
#
# Usage:   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2932_mental_health_parity_comparative_analysis/sweep.sh > /dev/null 2>&1 &
#
# Then POLL for the sentinel file:
#   /home/ubuntu/github/CodingPRD/tasks/task_2932_mental_health_parity_comparative_analysis/workspace/SWEEP_DONE
# Do NOT relaunch just because the setsid wrapper returned early -- it always
# returns before the rounds finish. Wait for SWEEP_DONE to appear.
#
# Diagnose ONLY from the per-round results.$i.json files. Never from sweep.log
# (8 rounds share one fd, so its contents are interleaved garbage).

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2932_mental_health_parity_comparative_analysis
IMPL="$TASK/workspace/implementation"
WS="$TASK/workspace"

rm -f "$IMPL"/results.*.json
rm -f "$WS/SWEEP_DONE"
rm -f "$WS"/round.*.log

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$TASK/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.$i.json" \
    > "$WS/round.$i.log" 2>&1 &
done

wait

date -u +%Y-%m-%dT%H:%M:%S.%3NZ > "$WS/SWEEP_DONE"
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL/results.$i.json" ]; then
    echo "round $i: results file present" >> "$WS/SWEEP_DONE"
  else
    echo "round $i: MISSING results file" >> "$WS/SWEEP_DONE"
  fi
done
