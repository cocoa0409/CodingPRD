#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2862.
# Usage:  setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2862_security_awareness_phishing_simulation/workspace/sweep.sh > /home/ubuntu/github/CodingPRD/tasks/task_2862_security_awareness_phishing_simulation/workspace/sweep.log 2>&1 &
# Then poll for the 8 results files; do NOT relaunch just because the wrapper returned.
T=/home/ubuntu/github/CodingPRD/tasks/task_2862_security_awareness_phishing_simulation

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
