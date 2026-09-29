#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2909.
# Usage:  setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2909_global_payroll_aggregation_in_country_provider_management/workspace/sweep.sh > /home/ubuntu/github/CodingPRD/tasks/task_2909_global_payroll_aggregation_in_country_provider_management/workspace/sweep.log 2>&1 &
# Then POLL for results.1.json .. results.8.json; do NOT relaunch. sweep.log is
# spliced garbage (8 rounds share one fd) — diagnose only from the per-round json.
T=/home/ubuntu/github/CodingPRD/tasks/task_2909_global_payroll_aggregation_in_country_provider_management
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
