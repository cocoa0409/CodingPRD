#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2910.
# Launch with:  setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2910_emerging_contaminant_sampling_treatment_compliance/workspace/sweep.sh > /home/ubuntu/github/CodingPRD/tasks/task_2910_emerging_contaminant_sampling_treatment_compliance/workspace/sweep.log 2>&1 &
# then POLL for results.1.json .. results.8.json. Do NOT relaunch: the setsid
# wrapper returns long before the rounds finish.
T=/home/ubuntu/github/CodingPRD/tasks/task_2910_emerging_contaminant_sampling_treatment_compliance
IMPL="$T/workspace/implementation"

rm -f "$IMPL"/results.*.json

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$T/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.$i.json" &
done
wait
echo "SWEEP_DONE"
