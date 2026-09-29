#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2983.
# Launch ONLY like this (detached from the agent's process group so nothing reaps it):
#   rm -f /home/ubuntu/github/CodingPRD/tasks/task_2983_retina_practice_intravitreal_injection_buy_and_bill/workspace/SWEEP_DONE
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2983_retina_practice_intravitreal_injection_buy_and_bill/workspace/sweep.sh > /dev/null 2>&1 &
# Then POLL for workspace/SWEEP_DONE. Never relaunch just because the launcher returned.
TD=/home/ubuntu/github/CodingPRD/tasks/task_2983_retina_practice_intravitreal_injection_buy_and_bill
IMPL="$TD/workspace/implementation"

rm -f "$IMPL"/results.*.json "$TD"/workspace/SWEEP_DONE "$TD"/workspace/sweep.round.*.log

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$TD/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.$i.json" \
    > "$TD/workspace/sweep.round.$i.log" 2>&1 &
done
wait
date -u +%Y-%m-%dT%H:%M:%SZ > "$TD/workspace/SWEEP_DONE"
