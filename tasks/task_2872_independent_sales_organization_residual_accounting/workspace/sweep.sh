#!/bin/bash
# 8-round parallel stability sweep for task_2872.
# Usage:  setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2872_independent_sales_organization_residual_accounting/workspace/sweep.sh > /home/ubuntu/github/CodingPRD/tasks/task_2872_independent_sales_organization_residual_accounting/workspace/sweep.log 2>&1 &
#
# Why the script file: an inline setsid one-liner needs nested single-quote escaping
# around --start-command, which has historically injected literal quotes and killed
# all 8 rounds at t=0 with ServerStartError. Keep the invocation in a file.
#
# Diagnose ONLY from the per-round results.$i.json files. sweep.log is 8 concurrent
# writers sharing one fd and is spliced garbage.

T=/home/ubuntu/github/CodingPRD/tasks/task_2872_independent_sales_organization_residual_accounting

rm -f "$T"/workspace/implementation/results.*.json

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $T/workspace/implementation && bash start.sh" \
    --test-dir      "$T/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$T/workspace/implementation/results.$i.json" &
done
wait
echo "SWEEP_DONE $(date -u +%Y-%m-%dT%H:%M:%SZ)"
