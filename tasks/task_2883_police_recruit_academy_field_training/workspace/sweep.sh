#!/bin/bash
# Launch the 8-round sweep detached, in its own session, so no foreground
# Bash call in the calling agent can SIGTERM the rounds mid-request.
#
# This script RETURNS IMMEDIATELY. The sweep keeps running.
# Poll for workspace/sweep.done -- do not relaunch.
T=/home/ubuntu/github/CodingPRD/tasks/task_2883_police_recruit_academy_field_training

setsid nohup bash "$T/workspace/sweep_body.sh" \
  > "$T/workspace/sweep.log" 2>&1 &

echo "sweep launched detached; poll for $T/workspace/sweep.done"
