#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2891.
# Usage:  bash /home/ubuntu/github/CodingPRD/tasks/task_2891_game_development_milestone_publisher_funding/workspace/sweep.sh
# Launches itself detached under setsid so the 8 background rounds cannot be
# reaped by SIGTERM when an unrelated foreground Bash call in the calling agent returns.
T=/home/ubuntu/github/CodingPRD/tasks/task_2891_game_development_milestone_publisher_funding
IMPL=$T/workspace/implementation

if [ "${SWEEP_CHILD:-0}" != "1" ]; then
  rm -f $IMPL/results.*.json
  rm -f $T/workspace/sweep.log
  SWEEP_CHILD=1 setsid nohup bash "$0" > $T/workspace/sweep.log 2>&1 &
  echo "sweep launched detached; poll for $IMPL/results.{1..8}.json"
  exit 0
fi

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      $T/test_suite \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  $IMPL/results.$i.json &
done
wait
echo "SWEEP_DONE"
