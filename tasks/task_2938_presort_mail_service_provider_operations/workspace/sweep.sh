#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2938.
#
# Usage (ALWAYS launch it detached so the rounds cannot be reaped when an
# unrelated foreground Bash call in the same agent returns):
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2938_presort_mail_service_provider_operations/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2938_presort_mail_service_provider_operations/workspace/sweep.log 2>&1 &
#
# Then POLL for completion — do NOT relaunch just because the wrapper returned:
#
#   ls .../workspace/SWEEP_DONE            # sentinel: written only after `wait`
#   ls .../workspace/implementation/results.*.json
#
# Never diagnose from sweep.log: 8 concurrent rounds share one fd, so its
# contents are interleaved garbage. Diagnose only from results.$i.json.

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2938_presort_mail_service_provider_operations
IMPL="$TASK/workspace/implementation"

rm -f "$IMPL"/results.*.json
rm -f "$TASK/workspace/SWEEP_DONE"

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$TASK/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.$i.json" &
done

wait

touch "$TASK/workspace/SWEEP_DONE"
echo "SWEEP COMPLETE"
