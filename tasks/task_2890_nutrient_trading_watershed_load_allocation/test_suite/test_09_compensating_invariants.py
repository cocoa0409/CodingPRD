"""Invariants that must hold at every intermediate point of a compensating round trip."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_ALLOCATION_RUN_IN_USE
from test_helpers.assertions import (
    assert_batch_buckets,
    assert_instant_equals,
    assert_integer,
    assert_is_null,
    assert_load,
    assert_load_conservation,
    assert_ratio,
)
from test_helpers.constants import CLOCK_BASE
from test_helpers.test_users import ADMIN, ANALYST, PERMITTEE_1, PERMIT_WRITER, REGISTRY


def _trading_world(api):
    """A LISTED 520 lb batch, a permit short by 1084.00 lbs, reserve pool at 2400.00."""
    world = fx.scr_trading_ready(api, reported_annual_load_lbs=25000.00)
    assert_integer(world["batch"]["issued_lbs"], 520, "issued_lbs")
    assert_ratio(world["batch"]["verified_ratio"], 1.0000, "verified_ratio")
    assert_batch_buckets(
        world["batch"], available=520.00, reserved=0.00, retired=0.00, invalidated=0.00
    )
    assert_load(world["permit"]["compliance_gap_lbs"], 1084.00, "compliance_gap_lbs")
    assert_load(world["permit"]["credit_applied_lbs"], 0.00, "credit_applied_lbs")
    assert_load(world["watershed"]["reserve_pool_lbs"], 2400.40, "reserve_pool_lbs")
    return world


def test_encumbrance_then_settlement_moves_pounds_without_creating_any(api):
    """A proposal reserves, an approval retires, and the reserve pool waits for settlement.

    "A batch's `issued_lbs` is exactly equal to the sum of `available_lbs`,
    `reserved_lbs`, `retired_lbs` and `invalidated_lbs` at every instant of the
    batch's life. ... A proposed transaction never credited the reserve pool"

    Design: Difficulty/compensating_invariant/credit_mass_invariant_restored_exactly_by_voiding_a_proposed_and_an_approved_transaction
    """
    world = _trading_world(api)

    proposed = fx.propose_transaction(api, world["batch_id"], world["permit_id"], 500.00)

    assert proposed["status"] == "PROPOSED", proposed
    assert_ratio(proposed["delivery_ratio"], 0.9000, "delivery_ratio")
    assert_integer(proposed["path_reach_count"], 2, "path_reach_count")
    assert_load(proposed["retired_to_reserve_lbs"], 50.00, "retired_to_reserve_lbs")
    assert_load(proposed["tradable_lbs"], 450.00, "tradable_lbs")
    assert_load(proposed["proposed_delivered_lbs"], 202.50, "proposed_delivered_lbs")
    assert_load(proposed["permit_gap_at_proposal_lbs"], 1084.00, "permit_gap_at_proposal_lbs")
    assert_is_null(proposed["applied_lbs"], "applied_lbs while PROPOSED")

    encumbered = get_success_data(api.get_credit_batch(world["batch_id"], REGISTRY))
    assert_batch_buckets(encumbered, available=20.00, reserved=500.00, retired=0.00, invalidated=0.00)
    held = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_load(held["reserve_pool_lbs"], 2400.40, "reserve_pool_lbs while only PROPOSED")

    settled = fx.approve_transaction(api, proposed["id"])

    assert settled["status"] == "APPROVED", settled
    assert_load(settled["settled_gross_lbs"], 500.00, "settled_gross_lbs")
    assert_load(settled["settled_delivered_lbs"], 202.50, "settled_delivered_lbs")
    assert_load(settled["applied_lbs"], 202.50, "applied_lbs")

    retired = get_success_data(api.get_credit_batch(world["batch_id"], REGISTRY))
    assert_batch_buckets(retired, available=20.00, reserved=0.00, retired=500.00, invalidated=0.00)
    credited = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_load(credited["reserve_pool_lbs"], 2450.40, "reserve_pool_lbs after settlement")

    permit = validate_success(api.get_permit(world["permit_id"], PERMITTEE_1))
    assert_load(permit["credit_applied_lbs"], 202.50, "credit_applied_lbs")
    assert_load(permit["compliance_gap_lbs"], 881.50, "compliance_gap_lbs")
    assert permit["compliance_status"] == "SHORTFALL", permit


def test_voiding_a_proposed_and_an_approved_trade_restores_every_bucket_exactly(api):
    """The two void paths compensate different buckets and leave no cent of drift.

    "A proposed transaction never credited the reserve pool, so voiding one leaves
    `reserve_pool_lbs` alone. ... Either way the watershed's `reserve_pool_lbs`
    decreases by the transaction's `retired_to_reserve_lbs`"

    Design: Difficulty/compensating_invariant/credit_mass_invariant_restored_exactly_by_voiding_a_proposed_and_an_approved_transaction
    """
    world = _trading_world(api)
    settled_txn = fx.approve_transaction(
        api, fx.propose_transaction(api, world["batch_id"], world["permit_id"], 500.00)["id"]
    )
    version_after_settlement = fx.read_batch_version(api, world["batch_id"])
    open_txn = fx.propose_transaction(api, world["batch_id"], world["permit_id"], 20.00)
    assert_load(open_txn["proposed_delivered_lbs"], 8.10, "proposed_delivered_lbs")
    assert_load(open_txn["permit_gap_at_proposal_lbs"], 881.50, "permit_gap_at_proposal_lbs")
    both_encumbered = get_success_data(api.get_credit_batch(world["batch_id"], REGISTRY))
    assert_batch_buckets(
        both_encumbered, available=0.00, reserved=20.00, retired=500.00, invalidated=0.00
    )

    voided_open = fx.void_transaction(
        api, open_txn["id"], "Permittee withdrew the second purchase."
    )

    assert voided_open["status"] == "VOIDED", voided_open
    assert voided_open["void_reason"] == "REGISTRY_ACTION", voided_open
    assert_instant_equals(voided_open["voided_at"], CLOCK_BASE, "voided_at")
    after_first_void = get_success_data(api.get_credit_batch(world["batch_id"], REGISTRY))
    assert_batch_buckets(
        after_first_void, available=20.00, reserved=0.00, retired=500.00, invalidated=0.00
    )
    untouched = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_load(untouched["reserve_pool_lbs"], 2450.40, "reserve_pool_lbs after a PROPOSED void")
    unchanged_permit = validate_success(api.get_permit(world["permit_id"], PERMITTEE_1))
    assert_load(unchanged_permit["credit_applied_lbs"], 202.50, "credit_applied_lbs")
    assert_load(unchanged_permit["compliance_gap_lbs"], 881.50, "compliance_gap_lbs")

    voided_settled = fx.void_transaction(
        api, settled_txn["id"], "Registry unwound the settled purchase after an audit."
    )

    assert voided_settled["status"] == "VOIDED", voided_settled
    assert voided_settled["void_reason"] == "REGISTRY_ACTION", voided_settled
    restored = get_success_data(api.get_credit_batch(world["batch_id"], REGISTRY))
    assert_batch_buckets(restored, available=520.00, reserved=0.00, retired=0.00, invalidated=0.00)
    assert_integer(restored["issued_lbs"], 520, "issued_lbs after the round trip")
    assert restored["status"] == "LISTED", restored
    assert restored["version"] > version_after_settlement, restored

    drained = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_load(drained["reserve_pool_lbs"], 2400.40, "reserve_pool_lbs restored")
    permit = validate_success(api.get_permit(world["permit_id"], PERMITTEE_1))
    assert_load(permit["credit_applied_lbs"], 0.00, "credit_applied_lbs restored")
    assert_load(permit["compliance_gap_lbs"], 1084.00, "compliance_gap_lbs restored")
    assert permit["compliance_status"] == "SHORTFALL", permit
    assert permit["enforcement_flag"] is False, permit


def _allocated_world(api):
    """SCR with one ACTIVE PRO_RATA run and the conservation identity satisfied."""
    world = fx.scr_allocated(api)
    assessment = get_success_data(api.get_tmdl_assessment(world["assessment_id"], ANALYST))
    assert_load(assessment["margin_of_safety_lbs_yr"], 6000.00, "margin_of_safety_lbs_yr")
    assert_load(assessment["effective_background_lbs_yr"], 6000.00, "effective_background_lbs_yr")
    assert_load(assessment["wla_total_lbs_yr"], 27360.00, "wla_total_lbs_yr")
    assert_load(assessment["la_total_lbs_yr"], 18240.00, "la_total_lbs_yr")
    assert_load(assessment["reserve_allocation_lbs_yr"], 2400.00, "reserve_allocation_lbs_yr")
    assert_load_conservation(assessment)

    watershed = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_load(watershed["reserve_pool_lbs"], 2400.00, "reserve_pool_lbs")
    assert_load(watershed["allocated_wla_total_lbs_yr"], 27360.00, "allocated_wla_total_lbs_yr")
    assert_load(watershed["allocated_la_total_lbs_yr"], 18240.00, "allocated_la_total_lbs_yr")
    world["assessment_row"] = assessment
    return world


def test_rescission_zeroes_every_contribution_and_a_re_run_rebuilds_them_to_the_cent(api):
    """The conservation identity degenerates cleanly and is then rebuilt identically.

    "every source assessment carrying this run's identifier has its
    `allocated_load_lbs_yr` and its `allocation_run_id` set back to null ... and the
    watershed's `reserve_pool_lbs` is decreased by this run's
    `reserve_allocation_lbs_yr`, restoring the pre-run balance"

    Design: Difficulty/compensating_invariant/load_conservation_restored_by_rescinding_an_allocation_run_but_refused_once_a_permit_relies_on_it
    """
    world = _allocated_world(api)

    rescinded = validate_success(
        api.rescind_allocation_run(
            world["run_id"], f.rescind_payload("Loading capacity re-opened for public comment."), ANALYST
        )
    )

    assert rescinded["status"] == "RESCINDED", rescinded
    assert_instant_equals(rescinded["rescinded_at"], CLOCK_BASE, "rescinded_at")

    for key in ("sa_p1", "sa_p2", "sa_n1", "sa_n2"):
        source = get_success_data(api.get_source_assessment(world[key]["id"], ANALYST))
        assert_is_null(source["allocated_load_lbs_yr"], "{} allocated_load_lbs_yr".format(key))
        assert_is_null(source["allocation_run_id"], "{} allocation_run_id".format(key))

    emptied = get_success_data(api.get_tmdl_assessment(world["assessment_id"], ANALYST))
    assert_load(emptied["margin_of_safety_lbs_yr"], 0.00, "margin_of_safety_lbs_yr")
    assert_load(emptied["allocable_load_lbs_yr"], 0.00, "allocable_load_lbs_yr")
    assert_load(emptied["wla_total_lbs_yr"], 0.00, "wla_total_lbs_yr")
    assert_load(emptied["la_total_lbs_yr"], 0.00, "la_total_lbs_yr")
    assert_load(emptied["reserve_allocation_lbs_yr"], 0.00, "reserve_allocation_lbs_yr")
    assert_is_null(emptied["effective_background_lbs_yr"], "effective_background_lbs_yr")
    assert_is_null(emptied["allocation_variant"], "allocation_variant")

    drained = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_load(drained["reserve_pool_lbs"], 0.00, "reserve_pool_lbs")
    assert_load(drained["allocated_wla_total_lbs_yr"], 0.00, "allocated_wla_total_lbs_yr")
    assert_load(drained["allocated_la_total_lbs_yr"], 0.00, "allocated_la_total_lbs_yr")

    rerun = fx.make_allocation_run(api, world["assessment_id"], "RUN-2")

    assert_load(rerun["allocable_load_lbs_yr"], 48000.00, "allocable_load_lbs_yr")
    assert_load(rerun["point_pool_lbs_yr"], 27360.00, "point_pool_lbs_yr")
    assert_load(rerun["nonpoint_pool_lbs_yr"], 18240.00, "nonpoint_pool_lbs_yr")
    assert_load(rerun["wla_total_lbs_yr"], 27360.00, "wla_total_lbs_yr")
    assert_load(rerun["la_total_lbs_yr"], 18240.00, "la_total_lbs_yr")
    assert_load(rerun["reserve_allocation_lbs_yr"], 2400.00, "reserve_allocation_lbs_yr")

    expected = {"sa_p1": 21888.00, "sa_p2": 5472.00, "sa_n1": 13680.00, "sa_n2": 4560.00}
    for key, amount in expected.items():
        source = get_success_data(api.get_source_assessment(world[key]["id"], ANALYST))
        assert_load(source["allocated_load_lbs_yr"], amount, "{} allocation".format(key))

    rebuilt = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_load(rebuilt["reserve_pool_lbs"], 2400.00, "reserve_pool_lbs rebuilt, not doubled")
    assert_load_conservation(get_success_data(api.get_tmdl_assessment(world["assessment_id"], ANALYST)))


def test_rescission_is_refused_once_a_permit_has_derived_limits_from_the_run(api):
    """A relied-upon allocation is frozen, and the refusal mutates nothing at all.

    "Rescission is blocked once the allocation has been relied upon: if any permit
    whose `source_assessment_id` points at a source assessment carrying this run's
    `allocation_run_id` has a `limit_status` of `INTERIM` or `FINAL`, the request is
    rejected with `ERR_ALLOCATION_RUN_IN_USE`."

    Design: Difficulty/compensating_invariant/load_conservation_restored_by_rescinding_an_allocation_run_but_refused_once_a_permit_relies_on_it
    """
    world = _allocated_world(api)
    permit = fx.make_permit(api, world["watershed_id"], world["sa_p1"]["id"])
    derived = fx.derive_limits(api, permit["id"])
    assert derived["limit_status"] == "INTERIM", derived
    assert_load(derived["wla_lbs_yr"], 21888.00, "wla_lbs_yr")

    refused = api.rescind_allocation_run(
        world["run_id"], f.rescind_payload("Second attempt to re-open the allocation."), ANALYST
    )

    validate_error(refused, ERR_ALLOCATION_RUN_IN_USE, 409)

    run = get_success_data(api.get_allocation_run(world["run_id"], ANALYST))
    assert run["status"] == "ACTIVE", run
    assert_is_null(run["rescinded_at"], "rescinded_at")

    source = get_success_data(api.get_source_assessment(world["sa_p1"]["id"], ANALYST))
    assert_load(source["allocated_load_lbs_yr"], 21888.00, "allocated_load_lbs_yr")
    assert source["allocation_run_id"] == world["run_id"], source

    watershed = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_load(watershed["reserve_pool_lbs"], 2400.00, "reserve_pool_lbs")
    assessment = get_success_data(api.get_tmdl_assessment(world["assessment_id"], ANALYST))
    assert_load(assessment["reserve_allocation_lbs_yr"], 2400.00, "reserve_allocation_lbs_yr")
    assert_load_conservation(assessment)

    still_derived = validate_success(api.get_permit(permit["id"], PERMIT_WRITER))
    assert still_derived["limit_status"] == "INTERIM", still_derived
