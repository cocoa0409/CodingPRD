"""Consistency breadth: every write answers with the figures it just reconciled."""

import pytest
from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers import (
    assert_acre_feet,
    assert_cents,
    assert_cfs,
    assert_instant,
    assert_total_count,
)
from test_helpers import factories as f
from test_helpers.constants import (
    CLOCK_ORIGIN,
    DELINQUENCY_CURRENT,
    DELINQUENCY_DELINQUENT,
    DRAWDOWN_COORDINATED,
    ENTRY_ANNUAL_REGISTRATION_FEE,
    ENTRY_CIVIL_PENALTY,
    ENTRY_PAYMENT_RECEIVED,
)
from test_helpers.test_users import make_owner_headers


# ---------------------------------------------------------------------------
# The coordination reply and the reads that follow it agree at once
# ---------------------------------------------------------------------------
@pytest.fixture()
def pending_release(program, base):
    """A SIGNIFICANT dam with a MONITORING event and a REQUESTED 200-cfs six-hour order."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    event = program.declare_event(base.dam_id)
    order = program.request_drawdown(
        base.dam_id, event["id"], requested_release_cfs=200
    )
    return {
        "event": event,
        "order": order,
        "reach_version": program.reach_version(base.reach_id),
    }


def test_the_coordination_reply_carries_the_committed_release(
    api, program, base, pending_release
):
    """The coordinating call answers with the moved status and the planned volume.

    PRD 3.7: "The window's duration is measured in hours, fractional hours allowed, as `window_end` less `window_start`; that number of hours is multiplied by `requested_release_cfs` and by the conversion factor 0.0826446 acre-feet per cubic-foot-per-second-hour, and the product is rounded half up to three decimal places."

    Design: Corner/consistency_model/coordination_response_already_reflects_the_new_reach_commitment
    """
    coordinated = validate_success(
        api.coordinate_drawdown(
            pending_release["order"]["id"],
            f.coordinate_payload(pending_release["reach_version"]),
            program.admin,
        )
    )
    assert coordinated["status"] == DRAWDOWN_COORDINATED
    assert_acre_feet(
        coordinated["planned_release_acre_ft"], 99.174, "planned_release_acre_ft"
    )
    assert_cfs(coordinated["requested_release_cfs"], 200, "requested_release_cfs")
    assert_instant(coordinated["coordinated_at"], CLOCK_ORIGIN, "coordinated_at")


def test_the_reach_read_that_follows_needs_no_second_call(
    api, program, base, pending_release
):
    """One read of the reach already shows the commitment and the advanced version.

    PRD 2.9: "A reach's `active_drawdown_count` is the number of its drawdown orders whose status is `COORDINATED` or `ACTIVE`, and its `committed_release_cfs` the sum of those orders' requested release rates."

    Design: Corner/consistency_model/coordination_response_already_reflects_the_new_reach_commitment
    """
    before = pending_release["reach_version"]
    program.coordinate_drawdown(
        pending_release["order"]["id"], expected_reach_version=before
    )

    reach = validate_success(api.get_river_reach(base.reach_id, program.admin))
    assert_cfs(reach["committed_release_cfs"], 200, "committed_release_cfs")
    assert reach["active_drawdown_count"] == 1
    assert reach["version"] == before + 1
    assert_cfs(reach["channel_capacity_cfs"], 1200, "channel_capacity_cfs")
    assert_cfs(
        reach["channel_capacity_cfs"] - reach["committed_release_cfs"],
        1000,
        "remaining channel capacity",
    )


def test_the_snapshot_already_splits_the_reservoir_storage(
    api, program, base, pending_release
):
    """The dam's storage split is whole in the very next snapshot of the dam.

    PRD 3.7: "The storage split is maintained as a strict conservation law: a dam's `committed_drawdown_acre_ft` is the sum of `planned_release_acre_ft` over its orders in `COORDINATED` or `ACTIVE`, and its `available_conservation_storage_acre_ft` is `gross_storage_acre_ft` less that committed figure, rounded half up to three decimal places, so that committed plus available always equals gross storage — before and after every coordination, completion, cancellation and cascade cancellation."

    Design: Corner/consistency_model/coordination_response_already_reflects_the_new_reach_commitment
    """
    program.coordinate_drawdown(
        pending_release["order"]["id"],
        expected_reach_version=pending_release["reach_version"],
    )

    summary = program.summary(base.dam_id)
    assert_acre_feet(
        summary["committed_drawdown_acre_ft"], 99.174, "committed_drawdown_acre_ft"
    )
    assert_acre_feet(
        summary["available_conservation_storage_acre_ft"],
        1400.826,
        "available_conservation_storage_acre_ft",
    )

    dam = program.get_dam(base.dam_id)
    assert_acre_feet(
        dam["committed_drawdown_acre_ft"], 99.174, "committed_drawdown_acre_ft"
    )
    assert_acre_feet(
        dam["available_conservation_storage_acre_ft"],
        1400.826,
        "available_conservation_storage_acre_ft",
    )


# ---------------------------------------------------------------------------
# Every ledger posting answers with the replayed balance
# ---------------------------------------------------------------------------
@pytest.fixture()
def billed_owner(program):
    """One owner with an empty fee ledger."""
    return program.create_owner()


def test_each_posting_reports_its_own_running_balance(api, program, billed_owner):
    """Three postings walk the balance 20,000 then 30,000 then 0 in sequence.

    PRD 3.8: "The replay walks the owner's entries in ascending `sequence_no`, accumulating the signed amounts, and writes the accumulated figure into each entry's `balance_after_cents`; the final accumulated figure is the owner's `fee_balance_cents`."

    Design: Corner/consistency_model/fee_adjustment_response_carries_the_recomputed_balance
    """
    owner_id = billed_owner["id"]
    first = program.post_ledger_entry(
        owner_id,
        entry_type=ENTRY_ANNUAL_REGISTRATION_FEE,
        amount_cents=20_000,
        memo="2026 registration",
    )
    assert first["sequence_no"] == 1
    assert_cents(first["balance_after_cents"], 20_000, "balance_after_cents")

    second = program.post_ledger_entry(
        owner_id,
        entry_type=ENTRY_CIVIL_PENALTY,
        amount_cents=10_000,
        memo="Late response",
    )
    assert second["sequence_no"] == 2
    assert_cents(second["balance_after_cents"], 30_000, "balance_after_cents")

    third = program.post_ledger_entry(
        owner_id,
        entry_type=ENTRY_PAYMENT_RECEIVED,
        amount_cents=-30_000,
        memo="Cleared in full",
    )
    assert third["sequence_no"] == 3
    assert_cents(third["balance_after_cents"], 0, "balance_after_cents")


def test_delinquency_is_recomputed_by_the_posting_itself(api, program, billed_owner):
    """Crossing and clearing the threshold both show up without any further write.

    PRD 3.8: "`delinquency_status` is a pure function of the replayed balance and is recomputed on every posting: it reads `DELINQUENT` when `fee_balance_cents` is at or above 25,000 cents — two hundred and fifty dollars, and the threshold is inclusive, so a balance of exactly 25,000 cents is delinquent — and `CURRENT` otherwise."

    Design: Corner/consistency_model/fee_adjustment_response_carries_the_recomputed_balance
    """
    owner_id = billed_owner["id"]
    assert billed_owner["delinquency_status"] == DELINQUENCY_CURRENT

    program.post_ledger_entry(
        owner_id, entry_type=ENTRY_ANNUAL_REGISTRATION_FEE, amount_cents=20_000
    )
    after_fee = program.get_owner(owner_id)
    assert_cents(after_fee["fee_balance_cents"], 20_000, "fee_balance_cents")
    assert after_fee["delinquency_status"] == DELINQUENCY_CURRENT

    program.post_ledger_entry(
        owner_id, entry_type=ENTRY_CIVIL_PENALTY, amount_cents=10_000
    )
    after_penalty = program.get_owner(owner_id)
    assert_cents(after_penalty["fee_balance_cents"], 30_000, "fee_balance_cents")
    assert after_penalty["delinquency_status"] == DELINQUENCY_DELINQUENT

    program.post_ledger_entry(
        owner_id, entry_type=ENTRY_PAYMENT_RECEIVED, amount_cents=-30_000
    )
    after_payment = program.get_owner(owner_id)
    assert_cents(after_payment["fee_balance_cents"], 0, "fee_balance_cents")
    assert after_payment["delinquency_status"] == DELINQUENCY_CURRENT


def test_the_owners_own_ledger_read_replays_the_same_three_rows(
    api, program, billed_owner
):
    """The owner reads their journal back in posting order with the same balances.

    PRD 3.8: "`sequence_no` is a monotonic per-owner posting sequence starting at 1: a new entry takes the greatest existing `sequence_no` for that owner plus 1, or 1 when the owner has no entries yet."

    Design: Corner/consistency_model/fee_adjustment_response_carries_the_recomputed_balance
    """
    owner_id = billed_owner["id"]
    program.post_ledger_entry(
        owner_id, entry_type=ENTRY_ANNUAL_REGISTRATION_FEE, amount_cents=20_000
    )
    program.post_ledger_entry(
        owner_id, entry_type=ENTRY_CIVIL_PENALTY, amount_cents=10_000
    )
    program.post_ledger_entry(
        owner_id, entry_type=ENTRY_PAYMENT_RECEIVED, amount_cents=-30_000
    )

    rows, meta = validate_paginated(
        api.list_fee_ledger_entries(owner_id, make_owner_headers(owner_id))
    )
    assert_total_count(meta, 3)
    assert [row["sequence_no"] for row in rows] == [1, 2, 3]
    assert [row["balance_after_cents"] for row in rows] == [20_000, 30_000, 0]
    assert [row["entry_type"] for row in rows] == [
        ENTRY_ANNUAL_REGISTRATION_FEE,
        ENTRY_CIVIL_PENALTY,
        ENTRY_PAYMENT_RECEIVED,
    ]

    owner = program.get_owner(owner_id)
    assert_cents(owner["fee_balance_cents"], 0, "fee_balance_cents")
    assert owner["delinquency_status"] == DELINQUENCY_CURRENT
