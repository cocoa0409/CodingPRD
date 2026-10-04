"""Difficulty queue: non-linear state machines — the Item revert-and-repropose
branch and the ProductTransfer FAIL-reset self-loop with auto-execution.
"""
from datetime import datetime, timezone

from test_helpers import (
    CLOCK_START_ISO,
    TEST_USERS,
    api_client,
    assert_item,
    compute_sell_through_deadline,
    create_decide_payload,
    create_rationalization_case_payload,
    decide_case,
    get_item,
    get_transfer,
    propose_case,
    record_fail_run,
    record_pass_run,
    record_run,
    setup_listed_item,
    setup_transfer_planned,
    validate_created,
    validate_ok,
)

PM_PROPOSER_2 = TEST_USERS["portfolio_manager_proposer_2_headers"]
PM_DECIDER = TEST_USERS["portfolio_manager_decider_headers"]


def _iso_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant regardless of fractional-digit style."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class TestItemCutProposedRevertThenRepropose:
    def test_reject_reverts_item_to_listed(self):
        """PRD §3.2: "A `REJECT` decision is a compensating revert: the case
        moves from `SCORED` to `REJECTED` and the item returns from
        `CUT_PROPOSED` to `LISTED`, which releases the open-case slot and
        conserves the brand's count of `LISTED` items across the
        propose-then-reject round trip (invariant `inv_item_unit_and_listed`)."

        Design: Difficulty/non_linear_state_machine/item_cut_proposed_revert_then_repropose
        """
        _, _, item = setup_listed_item(
            {"annual_units": 4000, "unit_net_revenue_cents": 2000,
             "unit_cost_cents": 1700, "units_on_hand": 10}
        )
        case = propose_case(item["id"])
        assert get_item(item["id"])["item_status"] == "CUT_PROPOSED"
        decided = decide_case(case["id"], "REJECT")
        assert decided["case_status"] == "REJECTED"
        item_after = get_item(item["id"])
        assert_item(item_after)
        assert item_after["item_status"] == "LISTED", (
            f"REJECT must revert the item to LISTED, got {item_after['item_status']}"
        )

    def test_repropose_after_reject_then_approve(self):
        """PRD §2.9: "A rejected rationalization case releases its item's
        open-case slot (the item returns to `LISTED`), so a later case may be
        proposed again for the same item."
        PRD §3.2: "stamping the item's `sell_through_deadline` as the
        logical-clock timestamp of the decision plus exactly 90 days, with the
        time-of-day preserved."

        Design: Difficulty/non_linear_state_machine/item_cut_proposed_revert_then_repropose
        """
        _, _, item = setup_listed_item(
            {"annual_units": 4000, "unit_net_revenue_cents": 2000,
             "unit_cost_cents": 1700, "units_on_hand": 10}
        )
        case1 = propose_case(item["id"])
        decide_case(case1["id"], "REJECT")
        # The open-case slot is released: a second case can be proposed.
        resp2 = api_client.create_rationalization_case(
            create_rationalization_case_payload(item["id"]), PM_PROPOSER_2
        )
        case2 = validate_created(resp2)
        assert case2["id"] != case1["id"]
        # Approve at the default clock 2026-09-01 -> deadline 2026-11-30.
        resp3 = api_client.decide_rationalization_case(
            case2["id"], create_decide_payload("APPROVE"), PM_DECIDER
        )
        case2_decided = validate_ok(resp3)
        assert case2_decided["case_status"] == "EXECUTING"
        item_final = get_item(item["id"])
        assert item_final["item_status"] == "SELL_THROUGH"
        expected = _iso_instant(compute_sell_through_deadline(CLOCK_START_ISO))
        assert _iso_instant(item_final["sell_through_deadline"]) == expected, (
            f"deadline must be decide instant + 90 days = 2026-11-30T00:00:00Z, "
            f"got {item_final['sell_through_deadline']}"
        )


class TestTransferFailResetSelfLoop:
    def test_fail_run_resets_consecutive_pass_count(self):
        """PRD §3.4: "Each `PASS` increments the transfer's
        `consecutive_pass_count` by 1; each `FAIL` resets it to 0 — there is no
        failure ceiling and no cancel transition, so a string of failures
        simply keeps the transfer in `QUALIFYING`."

        Design: Difficulty/non_linear_state_machine/transfer_fail_reset_self_loop_then_auto_execute
        """
        _, _, target_plant, _, transfer = setup_transfer_planned(
            {"annual_units": 4000, "unit_net_revenue_cents": 2000,
             "unit_cost_cents": 1700, "units_on_hand": 0}
        )
        # 300 of 10000 = 300bp > 250bp -> FAIL; 100 -> PASS; 900 -> FAIL.
        r1 = record_run(transfer["id"], target_plant["id"],
                        run_date="2026-09-02T00:00:00Z",
                        units_produced=10000, units_rejected=300)
        r2 = record_pass_run(transfer["id"], target_plant["id"],
                             run_date="2026-09-03T00:00:00Z")
        r3 = record_fail_run(transfer["id"], target_plant["id"],
                             run_date="2026-09-04T00:00:00Z", units_rejected=900)
        assert (r1["result"], r2["result"], r3["result"]) == ("FAIL", "PASS", "FAIL")
        mid = get_transfer(transfer["id"])
        assert mid["transfer_status"] == "QUALIFYING", (
            f"FAIL self-loops inside QUALIFYING, got {mid['transfer_status']}"
        )
        assert mid["consecutive_pass_count"] == 0, (
            f"FAIL must reset the pass counter to 0, got {mid['consecutive_pass_count']}"
        )

    def test_two_consecutive_passes_auto_execute_after_reset(self):
        """PRD §3.4: "When a `PASS` brings `consecutive_pass_count` to 2, the
        transfer auto-executes in the same request: `transfer_status` becomes
        `EXECUTED`, the item's `primary_plant_id` is rewritten to the
        `target_plant_id`, both the source and the target plant recompute their
        `committed_units_per_quarter` and `utilization_pct`, the transfer's
        `version` increments, and the item's `version` increments by 1 as well."

        Design: Difficulty/non_linear_state_machine/transfer_fail_reset_self_loop_then_auto_execute
        """
        _, source_plant, target_plant, item, transfer = setup_transfer_planned(
            {"annual_units": 4000, "unit_net_revenue_cents": 2000,
             "unit_cost_cents": 1700, "units_on_hand": 0}
        )
        # FAIL, PASS, FAIL — isolated PASSes separated by a FAIL never execute.
        record_run(transfer["id"], target_plant["id"],
                   run_date="2026-09-02T00:00:00Z",
                   units_produced=10000, units_rejected=300)
        record_pass_run(transfer["id"], target_plant["id"],
                        run_date="2026-09-03T00:00:00Z")
        record_fail_run(transfer["id"], target_plant["id"],
                        run_date="2026-09-04T00:00:00Z", units_rejected=900)
        assert get_transfer(transfer["id"])["transfer_status"] == "QUALIFYING"
        # Two CONSECUTIVE PASSes auto-execute.
        record_pass_run(transfer["id"], target_plant["id"],
                        run_date="2026-09-05T00:00:00Z")
        record_pass_run(transfer["id"], target_plant["id"],
                        run_date="2026-09-06T00:00:00Z")
        final = get_transfer(transfer["id"])
        assert final["transfer_status"] == "EXECUTED"
        assert final["consecutive_pass_count"] == 2
        item_after = get_item(item["id"])
        assert item_after["primary_plant_id"] == target_plant["id"], (
            f"auto-execution must rewire primary_plant_id to the target "
            f"{target_plant['id']}, got {item_after['primary_plant_id']}"
        )
        assert item_after["primary_plant_id"] != source_plant["id"]
