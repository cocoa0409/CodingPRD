#!/bin/bash
# 8-round parallel stability sweep for task_2906.
# Launch ONLY as:  setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2906_apartment_doorstep_trash_valet_service/workspace/sweep.sh > /home/ubuntu/github/CodingPRD/tasks/task_2906_apartment_doorstep_trash_valet_service/workspace/sweep.log 2>&1 &
# Never inline the loop in a Bash tool call: unquoted $i / nested quoting corrupts --start-command.
T=/home/ubuntu/github/CodingPRD/tasks/task_2906_apartment_doorstep_trash_valet_service
rm -f "$T"/workspace/implementation/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $T/workspace/implementation && bash start.sh" \
    --test-dir       "$T/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$T/workspace/implementation/results.$i.json" \
    > "$T/workspace/round.$i.log" 2>&1 &
done
wait
echo "SWEEP_COMPLETE"
