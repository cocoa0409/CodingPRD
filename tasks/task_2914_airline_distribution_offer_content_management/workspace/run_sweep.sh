#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2914.
#
# Usage (ALWAYS launch it detached so the rounds cannot be reaped when an
# unrelated foreground Bash call in the same agent returns):
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2914_airline_distribution_offer_content_management/workspace/run_sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2914_airline_distribution_offer_content_management/workspace/sweep.log 2>&1 &
#
# Then POLL for the 8 results files; the wrapper may return long before the
# rounds finish. Never relaunch a sweep that is still running.
#
#   ls -la .../workspace/implementation/results.*.json
#
# Diagnose ONLY from the per-round results.$i.json files. sweep.log is 8
# concurrent writers sharing one fd, so its text is interleaved garbage.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2914_airline_distribution_offer_content_management
IMPL_DIR="${TASK_DIR}/workspace/implementation"

rm -f "${IMPL_DIR}"/results.*.json

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd ${IMPL_DIR} && bash start.sh" \
    --test-dir      "${TASK_DIR}/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "${IMPL_DIR}/results.${i}.json" \
    > "${TASK_DIR}/workspace/sweep.round.${i}.log" 2>&1 &
done

wait

echo "SWEEP_COMPLETE $(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)"
