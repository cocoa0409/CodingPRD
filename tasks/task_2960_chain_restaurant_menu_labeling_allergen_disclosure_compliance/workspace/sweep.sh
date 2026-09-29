#!/usr/bin/env bash
# 8-round parallel stability sweep for task_2960.
#
# Usage (ALWAYS launch it exactly like this, from any cwd):
#   rm -f /home/ubuntu/github/CodingPRD/tasks/task_2960_chain_restaurant_menu_labeling_allergen_disclosure_compliance/workspace/SWEEP_DONE
#   setsid nohup bash /home/ubuntu/github/CodingPRD/tasks/task_2960_chain_restaurant_menu_labeling_allergen_disclosure_compliance/workspace/sweep.sh \
#     > /home/ubuntu/github/CodingPRD/tasks/task_2960_chain_restaurant_menu_labeling_allergen_disclosure_compliance/workspace/sweep.log 2>&1 &
#
# Then POLL for the sentinel file workspace/SWEEP_DONE. Do NOT relaunch: the
# setsid wrapper returns almost immediately while the 8 rounds keep running.
# SWEEP_DONE is touched only after `wait` returns, i.e. after all 8 rounds
# have genuinely finished.
#
# Diagnose ONLY from the per-round results.$i.json files. sweep.log is 8
# concurrent writers sharing one fd, so its text is spliced garbage.

TASK=/home/ubuntu/github/CodingPRD/tasks/task_2960_chain_restaurant_menu_labeling_allergen_disclosure_compliance
IMPL=$TASK/workspace/implementation

rm -f "$IMPL"/results.*.json
rm -f "$TASK"/workspace/SWEEP_DONE

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
