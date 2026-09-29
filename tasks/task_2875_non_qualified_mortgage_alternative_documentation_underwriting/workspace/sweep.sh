#!/usr/bin/env bash
# 8-round parallel stability sweep. Run it as:
#     setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2875_non_qualified_mortgage_alternative_documentation_underwriting/workspace/sweep.sh > /home/ubuntu/github/CodingPRD/tasks/task_2875_non_qualified_mortgage_alternative_documentation_underwriting/workspace/sweep.log 2>&1 &
# setsid is MANDATORY: without it the 8 background rounds take SIGTERM the instant any
# unrelated foreground Bash call in your agent returns, and every round dies mid-request
# with RemoteDisconnected / ConnectionResetError at the same wall-clock instant.
# Note the wrapper returns long before the rounds finish; do NOT relaunch. Poll for
# results.1..8.json instead, and diagnose ONLY from those per-round files --
# sweep.log itself is 8 fds spliced together and is unreliable as a diagnostic.
T=/home/ubuntu/github/CodingPRD/tasks/task_2875_non_qualified_mortgage_alternative_documentation_underwriting
rm -f "$T"/workspace/implementation/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $T/workspace/implementation && bash start.sh" \
    --test-dir       "$T/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$T/workspace/implementation/results.$i.json" &
done
wait
echo "SWEEP_WRAPPER_DONE"
