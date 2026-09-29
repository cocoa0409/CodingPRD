#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2882.
# Usage:  setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2882_equity_award_administration_trading_plan_oversight/workspace/sweep.sh > /home/ubuntu/github/CodingPRD/tasks/task_2882_equity_award_administration_trading_plan_oversight/workspace/sweep.log 2>&1 &
# Then POLL for results.1.json .. results.8.json. Never relaunch just because the
# wrapper returned early -- setsid detaches and the rounds keep running.
T=/home/ubuntu/github/CodingPRD/tasks/task_2882_equity_award_administration_trading_plan_oversight
rm -f "$T/workspace/implementation/results."*.json
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
echo "SWEEP_DONE $(date -u +%Y-%m-%dT%H:%M:%SZ)"
