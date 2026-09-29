#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2854.
#
# USAGE (always launch it exactly like this, detached under setsid so the
# rounds cannot be reaped when an unrelated foreground Bash call returns):
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2854_education_savings_account_school_choice_scholarship_administration/workspace/run_sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2854_education_savings_account_school_choice_scholarship_administration/workspace/sweep.log 2>&1 &
#
# Then POLL for completion — do not relaunch. The setsid wrapper returns long
# before the sweep finishes:
#
#   ls /home/ubuntu/github/CodingPRD/tasks/task_2854_education_savings_account_school_choice_scholarship_administration/workspace/implementation/results.*.json
#   # ...and wait for SWEEP_DONE:
#   ls /home/ubuntu/github/CodingPRD/tasks/task_2854_education_savings_account_school_choice_scholarship_administration/workspace/SWEEP_DONE
#
# Diagnose ONLY from the per-round results.$i.json files. workspace/sweep.log is
# 8 concurrent processes sharing one fd — its text is spliced garbage.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2854_education_savings_account_school_choice_scholarship_administration
IMPL_DIR="${TASK_DIR}/workspace/implementation"

rm -f "${IMPL_DIR}"/results.*.json
rm -f "${TASK_DIR}/workspace/SWEEP_DONE"

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd ${IMPL_DIR} && bash start.sh" \
    --test-dir      "${TASK_DIR}/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "${IMPL_DIR}/results.${i}.json" &
done

wait

date -u +"%Y-%m-%dT%H:%M:%SZ" > "${TASK_DIR}/workspace/SWEEP_DONE"
