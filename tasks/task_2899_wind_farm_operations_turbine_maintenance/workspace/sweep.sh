#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2899.
# Usage:  bash /home/ubuntu/github/CodingPRD/tasks/task_2899_wind_farm_operations_turbine_maintenance/workspace/sweep.sh
#
# Launches the sweep under setsid so the backgrounded rounds survive the exit of
# any unrelated foreground Bash call in the calling agent. Returns immediately;
# poll for results.1.json .. results.8.json to know when the sweep is done.

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2899_wind_farm_operations_turbine_maintenance
IMPL=$TASK/workspace/implementation

rm -f "$IMPL"/results.*.json
rm -f "$TASK"/workspace/sweep.log

setsid nohup bash -c '
TASK=/home/ubuntu/github/CodingPRD/tasks/task_2899_wind_farm_operations_turbine_maintenance
IMPL=$TASK/workspace/implementation
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
' > "$TASK/workspace/sweep.log" 2>&1 < /dev/null &

echo "sweep launched under setsid; poll $IMPL/results.{1..8}.json"
