#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2921_markdown_optimization_season_exit.
#
# Launch ALWAYS like this (never inline the loop in a Bash tool call):
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2921_markdown_optimization_season_exit/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2921_markdown_optimization_season_exit/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel file SWEEP_DONE. Do NOT relaunch just because the
# launching Bash call returned - setsid makes it return in seconds while the
# rounds keep running.
#   while [ ! -f .../workspace/SWEEP_DONE ]; do sleep 60; done
#
# Notes:
#  - setsid detaches the process group so backgrounded rounds are not SIGTERMed
#    when an unrelated foreground Bash call in the agent returns.
#  - sweep.log is 8 concurrent writers on one fd => spliced garbage. Diagnose
#    ONLY from the per-round results.$i.json files.
#  - --api-url is deliberately omitted: the runner claims a free port per round.

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2921_markdown_optimization_season_exit
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
    --results-file  "$IMPL/results.$i.json" &
done

wait

touch "$TASK/workspace/SWEEP_DONE"
