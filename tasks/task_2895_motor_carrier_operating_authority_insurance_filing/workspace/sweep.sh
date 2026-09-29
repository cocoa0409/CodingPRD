#!/usr/bin/env bash
# 8-round parallel stability sweep, detached from the calling agent's process group
# via setsid (see the launcher one-liner below). Do NOT inline this loop into a
# Bash tool call -- quoting the $i inside nested single quotes corrupts
# --start-command and every round dies at t=0 with ServerStartError.
T=/home/ubuntu/github/CodingPRD/tasks/task_2895_motor_carrier_operating_authority_insurance_filing
IMPL="$T/workspace/implementation"
rm -f "$IMPL"/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$T/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.$i.json" \
    > "$T/workspace/round.$i.log" 2>&1 &
done
wait
echo "SWEEP_DONE"
