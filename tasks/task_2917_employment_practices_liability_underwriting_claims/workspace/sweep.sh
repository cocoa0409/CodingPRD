#!/bin/bash
# 8-round parallel stability sweep for task_2917.
# Usage:  setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2917_employment_practices_liability_underwriting_claims/workspace/sweep.sh > /home/ubuntu/github/CodingPRD/tasks/task_2917_employment_practices_liability_underwriting_claims/workspace/sweep.log 2>&1 &
# Then POLL for workspace/implementation/results.1..8.json — do NOT relaunch; the
# setsid wrapper returns long before the rounds finish.
TD=/home/ubuntu/github/CodingPRD/tasks/task_2917_employment_practices_liability_underwriting_claims
rm -f "$TD"/workspace/implementation/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $TD/workspace/implementation && bash start.sh" \
    --test-dir     "$TD/test_suite" \
    --isolation    per-test-server \
    --timeout      120 \
    --test-timeout 30 \
    --results-file "$TD/workspace/implementation/results.$i.json" \
    > "$TD/workspace/round.$i.log" 2>&1 &
done
wait
echo "SWEEP_DONE"
