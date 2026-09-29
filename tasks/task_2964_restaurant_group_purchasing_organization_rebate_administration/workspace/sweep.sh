#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2964.
#
# USAGE (always launch it exactly like this, detached so nothing can reap it):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2964_restaurant_group_purchasing_organization_rebate_administration/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2964_restaurant_group_purchasing_organization_rebate_administration/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel — do NOT relaunch just because the wrapper returned:
#   ls .../workspace/SWEEP_DONE
# The setsid wrapper returns within ~1 minute while the 8 rounds are still running.
# SWEEP_DONE is touched only after `wait` returns, i.e. after all 8 rounds finish.
#
# Diagnose ONLY from the per-round results.$i.json files. sweep.log is 8 concurrent
# rounds sharing one fd; its interleaved text is not reliable evidence of anything.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2964_restaurant_group_purchasing_organization_rebate_administration
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
