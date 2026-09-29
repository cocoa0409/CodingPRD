#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2878.
# Launch ALWAYS via:  setsid nohup bash workspace/sweep.sh > workspace/sweep.log 2>&1 &
# Never inline this as a quoted one-liner -- the nested-quote escaping corrupts
# --start-command and every round dies at t=0 with ServerStartError.
T=/home/ubuntu/github/CodingPRD/tasks/task_2878_trade_promotion_planning_deduction_management

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
