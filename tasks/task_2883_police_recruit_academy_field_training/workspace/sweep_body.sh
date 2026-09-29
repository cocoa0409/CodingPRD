#!/bin/bash
# 8-round parallel stability sweep body. Do NOT run this directly --
# run ./sweep.sh, which launches this under setsid so it cannot be reaped.
T=/home/ubuntu/github/CodingPRD/tasks/task_2883_police_recruit_academy_field_training

rm -f "$T"/workspace/implementation/results.*.json
rm -f "$T"/workspace/sweep.done
rm -f "$T"/workspace/sweep.round*.log

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $T/workspace/implementation && bash start.sh" \
    --test-dir      "$T/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$T/workspace/implementation/results.$i.json" \
    > "$T/workspace/sweep.round$i.log" 2>&1 &
done
wait

echo "all 8 rounds exited at $(date -Is)" > "$T/workspace/sweep.done"
