#!/bin/bash
# 8-round parallel stability sweep for task_2913. Invoke as:
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2913_bowling_league_sanctioned_average_administration/workspace/sweep.sh > /home/ubuntu/github/CodingPRD/tasks/task_2913_bowling_league_sanctioned_average_administration/workspace/sweep.log 2>&1 &
# then POLL for results.1.json .. results.8.json. Never relaunch while a sweep is in flight.
TASK=/home/ubuntu/github/CodingPRD/tasks/task_2913_bowling_league_sanctioned_average_administration
IMPL=$TASK/workspace/implementation
rm -f $IMPL/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.$i.json" &
done
wait
echo "SWEEP_COMPLETE"
