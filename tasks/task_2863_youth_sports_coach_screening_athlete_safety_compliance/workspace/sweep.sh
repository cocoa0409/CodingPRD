#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2863.
# Launch it ONLY like this, so the rounds cannot be reaped when an unrelated
# foreground Bash call returns:
#
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2863_youth_sports_coach_screening_athlete_safety_compliance/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2863_youth_sports_coach_screening_athlete_safety_compliance/workspace/sweep.log 2>&1 &
#
# Then POLL for the 8 results files; do NOT relaunch just because the wrapper
# returned early:
#   ls -la .../workspace/implementation/results.*.json
#
# sweep.log itself is 8 interleaved fds and is unreadable garbage — diagnose
# ONLY from the per-round results.$i.json files.

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_2863_youth_sports_coach_screening_athlete_safety_compliance
IMPL_DIR="$TASK_DIR/workspace/implementation"

rm -f "$IMPL_DIR"/results.*.json

for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL_DIR && bash start.sh" \
    --test-dir      "$TASK_DIR/test_suite" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL_DIR/results.$i.json" \
    > "$TASK_DIR/workspace/round.$i.log" 2>&1 &
done

wait
echo "SWEEP_COMPLETE"
