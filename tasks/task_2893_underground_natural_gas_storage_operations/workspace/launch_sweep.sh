#!/usr/bin/env bash
# Detached launcher: immune to SIGTERM when a foreground Bash call in the agent returns.
TD=/home/ubuntu/github/CodingPRD/tasks/task_2893_underground_natural_gas_storage_operations
setsid nohup bash "$TD/workspace/sweep.sh" > "$TD/workspace/sweep.log" 2>&1 < /dev/null &
disown
echo "sweep launched detached; poll for $TD/workspace/implementation/results.{1..8}.json and for SWEEP_DONE in workspace/sweep.log"
