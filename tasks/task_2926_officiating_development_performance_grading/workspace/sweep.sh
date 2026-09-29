#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2926.
# Usage:  bash /home/ubuntu/github/CodingPRD/tasks/task_2926_officiating_development_performance_grading/workspace/run_sweep.sh
# Do NOT invoke this file directly in the foreground of an agent Bash call --
# use run_sweep.sh, which wraps it in setsid nohup so the rounds cannot be reaped.

T=/home/ubuntu/github/CodingPRD/tasks/task_2926_officiating_development_performance_grading
IMPL=$T/workspace/implementation

rm -f "$IMPL"/results.*.json
rm -f "$T"/workspace/SWEEP_DONE

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$T/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.$i.json" \
    > "$T/workspace/round.$i.log" 2>&1 &
done

wait

touch "$T/workspace/SWEEP_DONE"
