#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2901.
# Launch with:   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2901_certificate_of_need_application_review/workspace/sweep.sh > /home/ubuntu/github/CodingPRD/tasks/task_2901_certificate_of_need_application_review/workspace/sweep.log 2>&1 &
# then POLL for results.1.json .. results.8.json. Do NOT relaunch just because
# the wrapper returned early -- setsid detaches and the rounds keep running.
#
# Diagnose ONLY from the per-round results.$i.json files. sweep.log is 8
# concurrent writers on one fd and is spliced garbage by construction.

T=/home/ubuntu/github/CodingPRD/tasks/task_2901_certificate_of_need_application_review
IMPL=$T/workspace/implementation

rm -f $IMPL/results.*.json

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$T/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.$i.json" &
done

wait
echo "SWEEP_COMPLETE"
