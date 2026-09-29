#!/usr/bin/env bash
# Launcher: starts sweep.sh detached under setsid so that the 8 background
# rounds survive the return of any later foreground Bash call in the agent.
# Returns almost immediately -- that is EXPECTED and does NOT mean the sweep
# finished. Poll for $T/workspace/SWEEP_DONE, then read results.1..8.json.
# NEVER relaunch on the early return.

T=/home/ubuntu/github/CodingPRD/tasks/task_2926_officiating_development_performance_grading

setsid nohup bash "$T/workspace/sweep.sh" > "$T/workspace/sweep.log" 2>&1 < /dev/null &
disown 2>/dev/null || true
echo "sweep launched detached; poll for $T/workspace/SWEEP_DONE"
