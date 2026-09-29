#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2887. Run it as:
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2887_fiber_route_engineering_permitting/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2887_fiber_route_engineering_permitting/workspace/sweep.log 2>&1 &
# Then POLL for results.1.json .. results.8.json. Never relaunch just because the
# wrapper returned early -- setsid detaches, so the rounds outlive the wrapper.
TASK=/home/ubuntu/github/CodingPRD/tasks/task_2887_fiber_route_engineering_permitting
IMPL=$TASK/workspace/implementation
rm -f $IMPL/results.*.json
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
echo "SWEEP_WRAPPER_DONE"
