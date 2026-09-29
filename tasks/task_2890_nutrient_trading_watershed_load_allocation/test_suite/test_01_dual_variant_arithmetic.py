"""Dual-variant arithmetic: the same inputs evaluated under two declared variants."""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_batch_buckets,
    assert_integer,
    assert_is_null,
    assert_load,
    assert_load_conservation,
    assert_ratio,
)
from test_helpers.test_users import ADMIN, ANALYST, PERMITTEE_1, REGISTRY


def _background_samples(api, reaches):
    """Two ACCEPTED background samples inside the assessment period.

    0.0250 mg/L at 100.00 cfs annualises to 4921.11 lbs/yr and 0.0200 mg/L at
    100.00 cfs to 3936.89 lbs/yr, so their arithmetic mean is exactly 4429.00.
    """
    first = fx.make_sample(api, reaches["r_bg"]["id"], "2026-03-01T12:00:00Z", 0.0250, 100.00)
    second = fx.make_sample(api, reaches["r_bg"]["id"], "2026-04-01T12:00:00Z", 0.0200, 100.00)
    assert_load(first["computed_load_lbs_yr"], 4921.11, "first background sample load")
    assert_load(second["computed_load_lbs_yr"], 3936.89, "second background sample load")
    return first, second


def test_provisional_variant_uses_the_analyst_estimate_verbatim(api):
    """When the parent assessment is DRAFT the run takes the analyst's estimate.

    "When the parent assessment's status at run time is `DRAFT`, `PUBLIC_COMMENT`
    or `REVISION`, the run's `variant` is `PROVISIONAL` and the effective
    background is the analyst's estimate in the assessment's
    `background_load_lbs_yr`, used verbatim with no adjustment."

    Design: Difficulty/dual_variant_calc/allocation_background_variant_provisional_vs_final_divergence
    """
    world = fx.scr_base(api, with_background=True)
    _background_samples(api, world["reaches"])

    run = fx.make_allocation_run(api, world["assessment_id"], "RUN-PROVISIONAL")

    assert run["variant"] == "PROVISIONAL", run
    assert run["status"] == "ACTIVE", run
    assert_load(run["effective_background_lbs_yr"], 6000.00, "effective_background_lbs_yr")
    assert_load(run["margin_of_safety_lbs_yr"], 6000.00, "margin_of_safety_lbs_yr")
    assert_load(run["allocable_load_lbs_yr"], 48000.00, "allocable_load_lbs_yr")
    assert_load(run["point_pool_lbs_yr"], 27360.00, "point_pool_lbs_yr")
    assert_load(run["nonpoint_pool_lbs_yr"], 18240.00, "nonpoint_pool_lbs_yr")
    assert_load(run["wla_total_lbs_yr"], 27360.00, "wla_total_lbs_yr")
    assert_load(run["la_total_lbs_yr"], 18240.00, "la_total_lbs_yr")
    assert_load(run["reserve_allocation_lbs_yr"], 2400.00, "reserve_allocation_lbs_yr")
    assert_integer(run["included_source_count"], 4, "included_source_count")

    allocations = {
        row["source_assessment_id"]: row["allocated_load_lbs_yr"] for row in run["allocations"]
    }
    assert_load(allocations[world["sa_p1"]["id"]], 21888.00, "City WWTP allocation")
    assert_load(allocations[world["sa_p2"]["id"]], 5472.00, "Village WWTP allocation")
    assert_load(allocations[world["sa_n1"]["id"]], 13680.00, "Upper Cropland allocation")
    assert_load(allocations[world["sa_n2"]["id"]], 4560.00, "Upper Pasture allocation")

    assessment = get_success_data(api.get_tmdl_assessment(world["assessment_id"], ANALYST))
    assert assessment["allocation_variant"] == "PROVISIONAL", assessment
    assert_load_conservation(assessment)

    watershed = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_load(watershed["reserve_pool_lbs"], 2400.00, "reserve_pool_lbs")


def test_final_variant_consumes_the_monitored_background_and_diverges(api):
    """After approval the same sources under the same method allocate differently.

    "Because a monitored background normally differs from the estimate, the same
    source rows under the same method yield a different allocable load, different
    per-source allocations, a different `wla_total_lbs_yr` and a different
    `reserve_allocation_lbs_yr` under the final variant than under the
    provisional one."

    Design: Difficulty/dual_variant_calc/allocation_background_variant_provisional_vs_final_divergence
    """
    world = fx.scr_base(api, with_background=True)
    _background_samples(api, world["reaches"])
    provisional = fx.make_allocation_run(api, world["assessment_id"], "RUN-PROVISIONAL")
    fx.publish_and_approve(api, world["assessment_id"])

    final_run = fx.make_allocation_run(api, world["assessment_id"], "RUN-FINAL")

    assert final_run["variant"] == "FINAL", final_run
    assert final_run["status"] == "ACTIVE", final_run
    # The monitored mean of 4921.11 and 3936.89, rounded half-up to 2 places.
    assert_load(final_run["effective_background_lbs_yr"], 4429.00, "effective_background_lbs_yr")
    assert_load(final_run["margin_of_safety_lbs_yr"], 6000.00, "margin_of_safety_lbs_yr")
    assert_load(final_run["allocable_load_lbs_yr"], 49571.00, "allocable_load_lbs_yr")
    assert_load(final_run["point_pool_lbs_yr"], 28255.47, "point_pool_lbs_yr")
    assert_load(final_run["nonpoint_pool_lbs_yr"], 18836.98, "nonpoint_pool_lbs_yr")
    assert_load(final_run["wla_total_lbs_yr"], 28255.47, "wla_total_lbs_yr")
    assert_load(final_run["la_total_lbs_yr"], 18836.99, "la_total_lbs_yr")
    assert_load(final_run["reserve_allocation_lbs_yr"], 2478.54, "reserve_allocation_lbs_yr")

    allocations = {
        row["source_assessment_id"]: row["allocated_load_lbs_yr"]
        for row in final_run["allocations"]
    }
    assert_load(allocations[world["sa_p1"]["id"]], 22604.38, "City WWTP allocation")
    assert_load(allocations[world["sa_p2"]["id"]], 5651.09, "Village WWTP allocation")
    assert_load(allocations[world["sa_n1"]["id"]], 14127.74, "Upper Cropland allocation")
    assert_load(allocations[world["sa_n2"]["id"]], 4709.25, "Upper Pasture allocation")

    superseded = get_success_data(api.get_allocation_run(provisional["id"], ANALYST))
    assert superseded["status"] == "SUPERSEDED", superseded

    assessment = get_success_data(api.get_tmdl_assessment(world["assessment_id"], ANALYST))
    assert assessment["allocation_variant"] == "FINAL", assessment
    assert_load_conservation(assessment)

    watershed = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_load(watershed["reserve_pool_lbs"], 2478.54, "reserve_pool_lbs")


def test_proposal_variant_ignores_the_batch_verified_ratio_entirely(api):
    """At proposal the gross quantity is the full request, unreduced by verification.

    "At proposal time the gross quantity is the full `requested_gross_lbs`, and
    the batch's `verified_ratio` is ignored entirely."

    Design: Difficulty/dual_variant_calc/credit_delivery_proposed_vs_settled_variant_divergence
    """
    world = fx.scr_trading_ready(api)

    assert_load(world["batch"]["gross_reduction_lbs_yr"], 520.40, "gross_reduction_lbs_yr")
    assert_integer(world["batch"]["issued_lbs"], 520, "issued_lbs")
    assert_ratio(world["batch"]["verified_ratio"], 1.0000, "verified_ratio")

    txn = fx.propose_transaction(api, world["batch_id"], world["permit_id"], 500.00)

    assert txn["status"] == "PROPOSED", txn
    assert_ratio(txn["delivery_ratio"], 0.9000, "delivery_ratio")
    assert_integer(txn["path_reach_count"], 2, "path_reach_count")
    assert_load(txn["retired_to_reserve_lbs"], 50.00, "retired_to_reserve_lbs")
    assert_load(txn["tradable_lbs"], 450.00, "tradable_lbs")
    assert_load(txn["proposed_delivered_lbs"], 202.50, "proposed_delivered_lbs")
    assert_load(txn["permit_gap_at_proposal_lbs"], 1084.00, "permit_gap_at_proposal_lbs")
    assert_is_null(txn["applied_lbs"], "applied_lbs")
    assert_is_null(txn["settled_gross_lbs"], "settled_gross_lbs")
    assert_is_null(txn["settled_delivered_lbs"], "settled_delivered_lbs")

    batch = get_success_data(api.get_credit_batch(world["batch_id"], REGISTRY))
    assert_batch_buckets(batch, available=20.00, reserved=500.00, retired=0.00, invalidated=0.00)

    watershed = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_load(watershed["reserve_pool_lbs"], 2400.40, "reserve_pool_lbs at proposal time")


def test_settled_delivery_falls_below_the_proposed_delivery_after_a_partial(api):
    """A downward reverification between proposal and approval shrinks the settlement.

    "The consequence of a downward reverification between proposal and approval
    is therefore explicit: with identical request data, `settled_delivered_lbs`
    is strictly less than `proposed_delivered_lbs`."

    Design: Difficulty/dual_variant_calc/credit_delivery_proposed_vs_settled_variant_divergence
    """
    world = fx.scr_trading_ready(api)
    txn = fx.propose_transaction(api, world["batch_id"], world["permit_id"], 500.00)

    fx.reverify(api, world["project_id"], "PARTIAL", verified_acres=60.00)
    reverified_batch = get_success_data(api.get_credit_batch(world["batch_id"], REGISTRY))
    assert_ratio(reverified_batch["verified_ratio"], 0.7500, "verified_ratio after PARTIAL")

    settled = fx.approve_transaction(api, txn["id"])

    assert settled["status"] == "APPROVED", settled
    assert_load(settled["settled_gross_lbs"], 375.00, "settled_gross_lbs")
    assert_load(settled["retired_to_reserve_lbs"], 37.50, "retired_to_reserve_lbs")
    assert_load(settled["settled_delivered_lbs"], 151.88, "settled_delivered_lbs")
    assert_load(settled["applied_lbs"], 151.88, "applied_lbs")
    assert settled["settled_delivered_lbs"] < settled["proposed_delivered_lbs"], settled

    batch = get_success_data(api.get_credit_batch(world["batch_id"], REGISTRY))
    assert_batch_buckets(batch, available=145.00, reserved=0.00, retired=375.00, invalidated=0.00)
    assert_integer(batch["issued_lbs"], 520, "issued_lbs is never restated")

    permit = validate_success(api.get_permit(world["permit_id"], PERMITTEE_1))
    assert_load(permit["credit_applied_lbs"], 151.88, "credit_applied_lbs")
    assert_load(permit["compliance_gap_lbs"], 932.12, "compliance_gap_lbs")
    assert permit["compliance_status"] == "SHORTFALL", permit
