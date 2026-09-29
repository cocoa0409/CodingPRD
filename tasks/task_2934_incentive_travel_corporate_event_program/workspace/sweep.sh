#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2934.
# Usage:  setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2934_incentive_travel_corporate_event_program/workspace/sweep.sh > /home/ubuntu/github/CodingPRD/tasks/task_2934_incentive_travel_corporate_event_program/workspace/sweep.log 2>&1 &
# Then POLL for workspace/SWEEP_DONE. Never relaunch just because the wrapper returned.
TASK=/home/ubuntu/github/CodingPRD/tasks/task_2934_incentive_travel_corporate_event_program
IMPL=$TASK/workspace/implementation
rm -f $IMPL/results.*.json $TASK/workspace/SWEEP_DONE
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       $TASK/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   $IMPL/results.$i.json \
    > $TASK/workspace/round.$i.log 2>&1 &
done
wait
touch $TASK/workspace/SWEEP_DONE
