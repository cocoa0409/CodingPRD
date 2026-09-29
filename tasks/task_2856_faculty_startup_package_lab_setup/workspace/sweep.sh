#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2856. Run it as:
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2856_faculty_startup_package_lab_setup/workspace/sweep.sh > /home/ubuntu/github/CodingPRD/tasks/task_2856_faculty_startup_package_lab_setup/workspace/sweep.log 2>&1 &
# Then POLL for results.1.json .. results.8.json. Never relaunch while a sweep is in flight.
T=/home/ubuntu/github/CodingPRD/tasks/task_2856_faculty_startup_package_lab_setup
rm -f "$T"/workspace/implementation/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $T/workspace/implementation && bash start.sh" \
    --test-dir       "$T/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$T/workspace/implementation/results.$i.json" &
done
wait
echo "SWEEP_DONE"
