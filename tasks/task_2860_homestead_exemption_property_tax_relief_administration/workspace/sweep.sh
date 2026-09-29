#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2860.
# Usage:  setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2860_homestead_exemption_property_tax_relief_administration/workspace/sweep.sh > /home/ubuntu/github/CodingPRD/tasks/task_2860_homestead_exemption_property_tax_relief_administration/workspace/sweep.log 2>&1 &
# Then POLL for results.1..8.json — do NOT relaunch. The setsid wrapper returns
# almost immediately while the rounds keep running.
T=/home/ubuntu/github/CodingPRD/tasks/task_2860_homestead_exemption_property_tax_relief_administration
IMPL="$T/workspace/implementation"
rm -f "$IMPL"/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$T/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.$i.json" \
    > "$T/workspace/round.$i.log" 2>&1 &
done
wait
echo "SWEEP-DONE"
