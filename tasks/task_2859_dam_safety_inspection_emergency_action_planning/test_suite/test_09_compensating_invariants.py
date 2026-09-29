"""Paired operations that must leave a conserved quantity exactly where it started."""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    assert_acre_feet,
    assert_cents,
    assert_cfs,
    assert_instant,
    assert_storage_conservation,
)
from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    DELINQUENCY_CURRENT,
    DELINQUENCY_DELINQUENT,
    DRAWDOWN_CANCELLED,
    DRAWDOWN_COORDINATED,
    ENTRY_FEE_VOID,
    ENTRY_PERMIT_REVIEW_FEE,
    PERMIT_SUBMITTED,
    PERMIT_TYPE_CONSTRUCTION,
)


# ---------------------------------------------------------------------------
# Coordinate then cancel restores the storage identity
# ---------------------------------------------------------------------------
@pytest.fixture()
def coordinated_release(program, base):
    """A COORDINATED 400-cfs release holding 198.347 acre-feet of the reservoir."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    event = program.declare_event(
        base.dam_id,
        declared_at="2026-08-01T00:00:00Z",
        trigger_description="Rain-on-snow event forecast for the basin.",
        declared_inflow_cfs=900,
    )
    order = program.request_drawdown(
        base.dam_id,
        event["id"],
        requested_release_cfs=400,
        window_start="2026-08-01T06:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )
    return program.coordinate_drawdown(order["id"], reach_id=base.reach_id)


def test_the_coordination_takes_storage_that_still_reconciles_to_gross(
    program, base, coordinated_release
):
    """Before the cancellation, committed plus available already equals gross storage.

    PRD 3.7: "The storage split is maintained as a strict conservation law: a dam's `committed_drawdown_acre_ft` is the sum of `planned_release_acre_ft` over its orders in `COORDINATED` or `ACTIVE`, and its `available_conservation_storage_acre_ft` is `gross_storage_acre_ft` less that committed figure, rounded half up to three decimal places, so that committed plus available always equals gross storage — before and after every coordination, completion, cancellation and cascade cancellation."

    Design: Difficulty/compensating_invariant/cancelling_a_coordinated_drawdown_restores_the_storage_conservation_identity
    """
    assert coordinated_release["status"] == DRAWDOWN_COORDINATED
    assert_acre_feet(
        coordinated_release["planned_release_acre_ft"],
        198.347,
        "planned_release_acre_ft",
    )

    dam = program.get_dam(base.dam_id)
    assert_acre_feet(
        dam["committed_drawdown_acre_ft"], 198.347, "committed_drawdown_acre_ft"
    )
    assert_acre_feet(
        dam["available_conservation_storage_acre_ft"],
        1301.653,
        "available_conservation_storage_acre_ft",
    )
    assert_storage_conservation(dam)

    reach = program.get_reach(base.reach_id)
    assert_cfs(reach["committed_release_cfs"], 400.000, "committed_release_cfs")
    assert reach["active_drawdown_count"] == 1


def test_cancelling_the_coordinated_release_returns_both_quantities_exactly(
    program, base, coordinated_release
):
    """Coordinate-then-cancel is a round trip on the reach and on the reservoir.

    PRD 3.7: "A `COORDINATED` or `ACTIVE` order releases exactly the reach capacity and dam storage it took, incrementing both the reach's and the dam's `version` — the pair of coordinate-then-cancel leaves both conserved quantities precisely as they were."

    Design: Difficulty/compensating_invariant/cancelling_a_coordinated_drawdown_restores_the_storage_conservation_identity
    """
    cancelled = program.cancel_drawdown(
        coordinated_release["id"],
        program.coordinator,
        reason="Forecast revised downward; release no longer required.",
    )
    assert cancelled["status"] == DRAWDOWN_CANCELLED
    assert_instant(cancelled["cancelled_at"], "2026-08-01T00:00:00Z", "cancelled_at")
    assert cancelled["cancel_reason"] == (
        "Forecast revised downward; release no longer required."
    )

    dam = program.get_dam(base.dam_id)
    assert_acre_feet(
        dam["committed_drawdown_acre_ft"], 0.000, "committed_drawdown_acre_ft"
    )
    assert_acre_feet(
        dam["available_conservation_storage_acre_ft"],
        1500.000,
        "available_conservation_storage_acre_ft",
    )
    assert_storage_conservation(dam)

    reach = program.get_reach(base.reach_id)
    assert_cfs(reach["committed_release_cfs"], 0.000, "committed_release_cfs")
    assert reach["active_drawdown_count"] == 0


def test_the_cancelled_order_keeps_its_planned_volume_and_records_no_actual(
    program, coordinated_release
):
    """The released commitment is forgotten by the dam but not by the order row.

    PRD 3.7: "Cancelling an `ACTIVE` order leaves `actual_release_acre_ft` null."

    Design: Difficulty/compensating_invariant/cancelling_a_coordinated_drawdown_restores_the_storage_conservation_identity
    """
    program.cancel_drawdown(
        coordinated_release["id"],
        program.coordinator,
        reason="Forecast revised downward; release no longer required.",
    )
    stored = program.get_drawdown(coordinated_release["id"])
    assert stored["status"] == DRAWDOWN_CANCELLED
    assert_acre_feet(
        stored["planned_release_acre_ft"], 198.347, "planned_release_acre_ft"
    )
    assert stored["actual_release_acre_ft"] is None
    assert stored["activated_at"] is None


# ---------------------------------------------------------------------------
# A charge and its FEE_VOID return the ledger to zero
# ---------------------------------------------------------------------------
@pytest.fixture()
def charged_owner(program, base):
    """An owner made delinquent by a single 166,000-cent permit review fee."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    permit = program.apply_permit(
        base.dam_id,
        base.owner_id,
        permit_type=PERMIT_TYPE_CONSTRUCTION,
        scope_description="New crest gates on the service spillway.",
        estimated_project_cost_cents=8_000_000,
    )
    return permit


def test_the_permit_fee_alone_is_enough_to_make_the_owner_delinquent(
    program, base, charged_owner
):
    """One charge, one ledger row, one balance above the threshold.

    PRD 3.8: "`sequence_no` is a monotonic per-owner posting sequence starting at 1: a new entry takes the greatest existing `sequence_no` for that owner plus 1, or 1 when the owner has no entries yet."

    Design: Difficulty/compensating_invariant/fee_void_entry_returns_the_owner_ledger_to_a_zero_balance
    """
    assert_cents(charged_owner["total_fee_cents"], 166000, "total_fee_cents")

    rows, meta = program.ledger(base.owner_id)
    assert meta["total_count"] == 1
    assert rows[0]["entry_type"] == ENTRY_PERMIT_REVIEW_FEE
    assert rows[0]["sequence_no"] == 1
    assert_cents(rows[0]["amount_cents"], 166000, "amount_cents")
    assert_cents(rows[0]["balance_after_cents"], 166000, "balance_after_cents")

    owner = program.get_owner(base.owner_id)
    assert_cents(owner["fee_balance_cents"], 166000, "fee_balance_cents")
    assert owner["delinquency_status"] == DELINQUENCY_DELINQUENT


def test_a_matching_fee_void_returns_the_balance_to_zero_and_clears_delinquency(
    program, base, charged_owner
):
    """The reversal is a new row, not an edit, and the replay lands back on zero.

    PRD 3.8: "The replay walks the owner's entries in ascending `sequence_no`, accumulating the signed amounts, and writes the accumulated figure into each entry's `balance_after_cents`; the final accumulated figure is the owner's `fee_balance_cents`."

    Design: Difficulty/compensating_invariant/fee_void_entry_returns_the_owner_ledger_to_a_zero_balance
    """
    voided = program.post_ledger_entry(
        base.owner_id,
        entry_type=ENTRY_FEE_VOID,
        amount_cents=-166000,
        source_ref=charged_owner["id"],
        memo="Review fee voided; application withdrawn from the fee schedule.",
    )
    assert voided["sequence_no"] == 2
    assert_cents(voided["amount_cents"], -166000, "amount_cents")
    assert_cents(voided["balance_after_cents"], 0, "balance_after_cents")
    assert voided["source_ref"] == charged_owner["id"]

    owner = program.get_owner(base.owner_id)
    assert_cents(owner["fee_balance_cents"], 0, "fee_balance_cents")
    assert owner["delinquency_status"] == DELINQUENCY_CURRENT

    # The permit itself is untouched by the fiscal reversal.
    permit = program.get_permit(charged_owner["id"])
    assert_cents(permit["total_fee_cents"], 166000, "total_fee_cents")
    assert permit["status"] == PERMIT_SUBMITTED


def test_a_positively_signed_fee_void_is_refused_outright(
    api, program, base, charged_owner
):
    """The reversal must be negative, so a positive one cannot fake the round trip.

    PRD 3.8: "An entry whose `amount_cents` sign disagrees with its `entry_type` is rejected with `ERR_LEDGER_SIGN_MISMATCH`, and an `amount_cents` of exactly 0 is never accepted at all — it is caught as a malformed request."

    Design: Difficulty/compensating_invariant/fee_void_entry_returns_the_owner_ledger_to_a_zero_balance
    """
    response = api.create_fee_adjustment(
        base.owner_id,
        f.fee_adjustment_payload(
            entry_type=ENTRY_FEE_VOID,
            amount_cents=166000,
            source_ref=charged_owner["id"],
            memo="Review fee voided; application withdrawn from the fee schedule.",
        ),
        program.admin,
    )
    validate_error(response, ApiErrorId.ERR_LEDGER_SIGN_MISMATCH.value, 422)

    rows, meta = program.ledger(base.owner_id)
    assert meta["total_count"] == 1
    owner = program.get_owner(base.owner_id)
    assert_cents(owner["fee_balance_cents"], 166000, "fee_balance_cents")
    assert owner["delinquency_status"] == DELINQUENCY_DELINQUENT
