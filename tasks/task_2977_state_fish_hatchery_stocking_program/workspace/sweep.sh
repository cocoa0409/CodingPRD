#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2977_state_fish_hatchery_stocking_program.
# Run it as:   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2977_state_fish_hatchery_stocking_program/workspace/sweep.sh > /dev/null 2>&1 &
# Then POLL for the sentinel:  ls .../workspace/SWEEP_DONE
# NEVER relaunch because the wrapper "returned" — setsid returns in ~1 minute while the rounds keep running.
T=/home/ubuntu/github/CodingPRD/tasks/task_2977_state_fish_hatchery_stocking_program
IMPL=$T/workspace/implementation
rm -f $IMPL/results.*.json $T/workspace/SWEEP_DONE $T/workspace/round.*.log
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       $T/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   $IMPL/results.$i.json \
    > $T/workspace/round.$i.log 2>&1 &
done
wait
touch $T/workspace/SWEEP_DONE
