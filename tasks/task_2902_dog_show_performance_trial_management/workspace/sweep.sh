#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2902.
# Usage:  setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2902_dog_show_performance_trial_management/workspace/sweep.sh > /home/ubuntu/github/CodingPRD/tasks/task_2902_dog_show_performance_trial_management/workspace/sweep.log 2>&1 &
#
# setsid detaches the round processes into their own session so that a foreground
# Bash call returning in the calling agent cannot SIGTERM them mid-request.
# Never diagnose from sweep.log (8 rounds share one fd, output is spliced);
# read the per-round results.$i.json files only.

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2902_dog_show_performance_trial_management
IMPL=$TASK/workspace/implementation

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
echo "SWEEP_COMPLETE"
