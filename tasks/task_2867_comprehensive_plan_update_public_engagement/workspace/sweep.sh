#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2867.
#
# Run it EXACTLY like this (setsid detaches the process group so the background
# rounds cannot be reaped by SIGTERM when an unrelated foreground Bash call in
# the same agent returns):
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2867_comprehensive_plan_update_public_engagement/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2867_comprehensive_plan_update_public_engagement/workspace/sweep.log 2>&1 &
#
# The wrapper returns almost immediately while the 8 rounds keep running. Do NOT
# relaunch it. Poll for the 8 results files instead:
#
#   ls -la .../workspace/implementation/results.*.json
#
# and only start diagnosing once all 8 exist and are non-empty.
#
# NOTE: sweep.log is 8 concurrent writers sharing one fd, so its contents are
# spliced garbage. Never diagnose from sweep.log — diagnose only from the
# per-round results.$i.json files.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2867_comprehensive_plan_update_public_engagement
IMPL_DIR="$TASK_DIR/workspace/implementation"

rm -f "$IMPL_DIR"/results.*.json

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL_DIR && bash start.sh" \
    --test-dir      "$TASK_DIR/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL_DIR/results.$i.json" &
done

wait

echo "SWEEP_COMPLETE"
for i in 1 2 3 4 5 6 7 8; do
  if [ -s "$IMPL_DIR/results.$i.json" ]; then
    python3 -c "
import json,sys
d=json.load(open('$IMPL_DIR/results.$i.json'))
print('round $i:', d.get('passed'), '/', d.get('total'))
" 2>/dev/null || echo "round $i: results file present but unparseable"
  else
    echo "round $i: MISSING or empty"
  fi
done
