#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2851_institutional_research_federal_data_reporting.
#
# Usage (ALWAYS launch it exactly like this, from any cwd):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2851_institutional_research_federal_data_reporting/workspace/run_sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2851_institutional_research_federal_data_reporting/workspace/sweep.log 2>&1 &
#
# Why setsid: without it, the 8 backgrounded rounds receive SIGTERM the moment any
# unrelated foreground Bash call in the calling agent returns. The tests then die
# mid-request with RemoteDisconnected / ConnectionResetError, which is indistinguishable
# from a flaky implementation. Tell: server log ending in `Terminated` (the runner itself
# only ever uses kill -9 / `Killed`) and every round dying at the same wall-clock instant.
#
# Why a script file instead of an inline one-liner: the nested-quote escaping needed to
# interpolate $i into --results-file inside `setsid nohup bash -c '...'` reliably injects
# literal quote characters into --start-command, so all 8 rounds die at t=0 with
# ServerStartError and zero results files.
#
# Do NOT read sweep.log to diagnose: 8 concurrent rounds share one stdout fd, so its
# content is spliced garbage. Diagnose only from the per-round results.$i.json files.
#
# This script never relaunches and never polls. Poll for the 8 results files yourself.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2851_institutional_research_federal_data_reporting
IMPL_DIR="${TASK_DIR}/workspace/implementation"

rm -f "${IMPL_DIR}"/results.*.json
rm -f "${TASK_DIR}/workspace/sweep.done"

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd ${IMPL_DIR} && bash start.sh" \
    --test-dir      "${TASK_DIR}/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "${IMPL_DIR}/results.${i}.json" \
    > "${TASK_DIR}/workspace/round.${i}.log" 2>&1 &
done

wait

date -u +%Y-%m-%dT%H:%M:%SZ > "${TASK_DIR}/workspace/sweep.done"
