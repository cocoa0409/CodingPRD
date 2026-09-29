#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2940.
#
# USAGE (always launch it exactly like this, detached, so the rounds cannot be reaped):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2940_surcharge_cash_discount_program_compliance/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2940_surcharge_cash_discount_program_compliance/workspace/sweep.log 2>&1 &
#
# The wrapper command returns almost immediately while the 8 rounds keep running.
# DO NOT relaunch it. Poll for the sentinel instead:
#   ls .../workspace/SWEEP_DONE   (created only after all 8 rounds have joined)
# and then read the 8 per-round results files:
#   .../workspace/implementation/results.1.json ... results.8.json
#
# Never diagnose from sweep.log: 8 concurrent rounds share one file descriptor,
# so its lines are spliced together. Diagnose ONLY from results.$i.json.

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2940_surcharge_cash_discount_program_compliance
IMPL_DIR="$TASK_DIR/workspace/implementation"

rm -f "$IMPL_DIR"/results.*.json
rm -f "$TASK_DIR/workspace/SWEEP_DONE"

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL_DIR && bash start.sh" \
    --test-dir      "$TASK_DIR/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL_DIR/results.$i.json" \
    > "$TASK_DIR/workspace/round.$i.log" 2>&1 &
done

wait

touch "$TASK_DIR/workspace/SWEEP_DONE"
echo "ALL 8 ROUNDS JOINED"
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL_DIR/results.$i.json" ]; then
    python3 -c "
import json,sys
d=json.load(open('$IMPL_DIR/results.$i.json'))
print('round $i:', d.get('passed'), '/', d.get('total'))
" 2>/dev/null || echo "round $i: results file unparseable"
  else
    echo "round $i: MISSING results file"
  fi
done
