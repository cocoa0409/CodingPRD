#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2884.
# Usage:  setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2884_ballot_measure_petition_signature_verification/workspace/sweep.sh > /home/ubuntu/github/CodingPRD/tasks/task_2884_ballot_measure_petition_signature_verification/workspace/sweep.log 2>&1 &
#
# Then POLL for the 8 results files. Do NOT relaunch: the setsid wrapper returns
# long before the rounds finish.
#
#   ls -la .../workspace/implementation/results.*.json
#
# Never diagnose from sweep.log — 8 concurrent rounds share one fd and the log is
# spliced garbage. Diagnose only from the per-round results.$i.json files.

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2884_ballot_measure_petition_signature_verification
IMPL="$TASK/workspace/implementation"

rm -f "$IMPL"/results.*.json

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$TASK/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.${i}.json" \
    > "$TASK/workspace/round.${i}.log" 2>&1 &
done

wait
echo "SWEEP_COMPLETE"
