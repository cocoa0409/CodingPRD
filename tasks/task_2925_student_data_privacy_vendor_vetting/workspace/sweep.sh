#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2925_student_data_privacy_vendor_vetting.
#
# Launch it ONLY like this (setsid keeps the rounds out of the agent's process
# group so they are not SIGTERM'd when an unrelated foreground Bash call ends):
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2925_student_data_privacy_vendor_vetting/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2925_student_data_privacy_vendor_vetting/workspace/sweep.log 2>&1 &
#
# The wrapper returns almost immediately -- that does NOT mean the sweep is done.
# NEVER relaunch. Poll for the sentinel instead:
#
#   ls .../workspace/SWEEP_DONE  &&  ls .../workspace/implementation/results.*.json
#
# Diagnose ONLY from the per-round results.$i.json files. sweep.log is 8
# concurrent rounds sharing one fd, so its text is spliced garbage.

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2925_student_data_privacy_vendor_vetting
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
    --results-file  "$IMPL/results.$i.json" \
    > "$TASK/workspace/round.$i.log" 2>&1 &
done

wait

touch "$TASK/workspace/SWEEP_DONE"
