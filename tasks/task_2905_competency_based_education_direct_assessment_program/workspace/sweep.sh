#!/bin/bash
# 8-round parallel stability sweep for task_2905. Run it as:
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2905_competency_based_education_direct_assessment_program/workspace/sweep.sh > /home/ubuntu/github/CodingPRD/tasks/task_2905_competency_based_education_direct_assessment_program/workspace/sweep.log 2>&1 &
# Then POLL for results.1..8.json. Never relaunch while a sweep is in flight.
TD=/home/ubuntu/github/CodingPRD/tasks/task_2905_competency_based_education_direct_assessment_program
IMPL=$TD/workspace/implementation
rm -f $IMPL/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$TD/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.$i.json" \
    > "$TD/workspace/round.$i.log" 2>&1 &
done
wait
echo "SWEEP_COMPLETE"
