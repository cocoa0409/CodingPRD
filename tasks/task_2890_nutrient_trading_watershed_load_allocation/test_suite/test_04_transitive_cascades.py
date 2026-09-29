"""Cascades that travel three or four links away from the row the caller named."""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_batch_buckets,
    assert_instant_equals,
    assert_integer,
    assert_load,
    assert_pct,
    assert_trading_gate,
)
from test_helpers.constants import CLOCK_BASE
from test_helpers.test_users import ADMIN, PERMITTEE_1, REGISTRY


def _settled_trade_world(api):
    """An ACTIVE program with one settled trade that resolved the buyer permit.

    Practice project PP-B on tract T-202 models a 4000.00 lb reduction over 200
    enrolled acres, all 200 of which are verified, so the batch issues exactly
    4000 whole pounds with no fractional residual. A 3000.00 lb purchase delivers
    1215.00 lbs, of which the permit's 1084.00 lb gap absorbs all it needs.
    """
    world = fx.scr_active_program(api)
    world["permit"] = fx.permit_in_shortfall(
        api, world["watershed_id"], world["sa_p1"]["id"], reported_annual_load_lbs=25000.00
    )
    world["permit_id"] = world["permit"]["id"]
    assert_load(world["permit"]["compliance_gap_lbs"], 1084.00, "compliance_gap_lbs")

    world["producer"] = fx.make_producer(api)
    listed = fx.listed_batch(
        api,
        world["producer"]["id"],
        world["reaches"]["r_up"]["id"],
        "T-202",
        verified_acres=200.00,
        enrolled_acres=200.00,
        pre_load_lbs_yr=5300.00,
        post_load_lbs_yr=1300.00,
    )
    world["project"] = listed["project"]
    world["project_id"] = listed["project"]["id"]
    world["batch"] = listed["batch"]
    world["batch_id"] = listed["batch"]["id"]
    assert_integer(world["batch"]["issued_lbs"], 4000, "issued_lbs")
    assert_load(world["batch"]["residual_lbs"], 0.00, "residual_lbs")

    txn = fx.propose_transaction(api, world["batch_id"], world["permit_id"], 3000.00)
    world["txn"] = fx.approve_transaction(api, txn["id"])
    world["txn_id"] = txn["id"]
    assert_load(world["txn"]["applied_lbs"], 1084.00, "applied_lbs")
    assert_load(world["txn"]["retired_to_reserve_lbs"], 300.00, "retired_to_reserve_lbs")

    resolved = validate_success(api.get_permit(world["permit_id"], PERMITTEE_1))
    assert resolved["compliance_status"] == "RESOLVED", resolved
    assert_load(resolved["compliance_gap_lbs"], 0.00, "compliance_gap_lbs")

    batch = get_success_data(api.get_credit_batch(world["batch_id"], REGISTRY))
    assert_batch_buckets(batch, available=1000.00, reserved=0.00, retired=3000.00, invalidated=0.00)

    watershed = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_load(watershed["reserve_pool_lbs"], 2700.00, "reserve_pool_lbs")
    return world


def test_off_track_verdict_suspends_the_watershed_it_evaluated(api):
    """A monitored shortfall against the interim target closes the market.

    "An `OFF_TRACK` verdict is the adaptive-management trigger and sets off the
    full suspension cascade. Its first link moves the watershed
    `ACTIVE → ADAPTIVE_HOLD` — but only when the watershed's `program_status` is
    `ACTIVE` at that moment — with `trading_enabled` becoming false and the
    watershed's `version` incremented by 1."

    Design: Difficulty/transitive_cascade/adaptive_review_off_track_cascade_watershed_to_transaction_to_batch_and_permit
    """
    world = _settled_trade_world(api)
    sample = fx.make_sample(
        api, world["reaches"]["r_out"]["id"], "2026-07-01T12:00:00Z", 0.0549, 1000.00
    )
    assert_load(sample["computed_load_lbs_yr"], 108067.63, "computed_load_lbs_yr")
    review = fx.make_adaptive_review(
        api, world["watershed_id"], "AR-2026", "2026-01-01", "2026-12-31"
    )

    finalized = fx.finalize_adaptive_review(api, review["id"])

    assert finalized["status"] == "FINALIZED", finalized
    assert_integer(finalized["sample_count"], 1, "sample_count")
    assert_load(finalized["observed_load_lbs_yr"], 108067.63, "observed_load_lbs_yr")
    assert_pct(finalized["achieved_reduction_pct"], 19.89, "achieved_reduction_pct")
    assert finalized["verdict"] == "OFF_TRACK", finalized
    assert_integer(finalized["voided_transaction_count"], 1, "voided_transaction_count")

    watershed = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_trading_gate(watershed, "ADAPTIVE_HOLD")
    assert_load(watershed["reserve_pool_lbs"], 2400.00, "reserve_pool_lbs")


def test_off_track_cascade_voids_the_trade_restores_the_batch_and_reopens_the_gap(api):
    """The suspension unwinds the settled trade all the way back to the buyer.

    "A permit that had been resolved solely by credits therefore falls back into
    shortfall the moment the program loses confidence in the watershed's
    trajectory — which is exactly the enforceability the trading programme
    promises."

    Design: Difficulty/transitive_cascade/adaptive_review_off_track_cascade_watershed_to_transaction_to_batch_and_permit
    """
    world = _settled_trade_world(api)
    fx.make_sample(api, world["reaches"]["r_out"]["id"], "2026-07-01T12:00:00Z", 0.0549, 1000.00)
    review = fx.make_adaptive_review(
        api, world["watershed_id"], "AR-2026", "2026-01-01", "2026-12-31"
    )

    fx.finalize_adaptive_review(api, review["id"])

    txn = get_success_data(api.get_credit_transaction(world["txn_id"], REGISTRY))
    assert txn["status"] == "VOIDED", txn
    assert txn["void_reason"] == "ADAPTIVE_HOLD", txn
    assert_instant_equals(txn["voided_at"], CLOCK_BASE, "voided_at")

    batch = get_success_data(api.get_credit_batch(world["batch_id"], REGISTRY))
    assert batch["status"] == "LISTED", batch
    assert_batch_buckets(batch, available=4000.00, reserved=0.00, retired=0.00, invalidated=0.00)

    permit = validate_success(api.get_permit(world["permit_id"], PERMITTEE_1))
    assert_load(permit["credit_applied_lbs"], 0.00, "credit_applied_lbs")
    assert_load(permit["compliance_gap_lbs"], 1084.00, "compliance_gap_lbs")
    assert permit["compliance_status"] == "SHORTFALL", permit
    assert permit["enforcement_flag"] is False, permit


def test_reverification_failure_revokes_the_project_and_invalidates_its_batch(api):
    """The gravest field finding folds every pound of the batch into the void.

    "every credit batch of this project whose `status` is `ISSUED` or `LISTED`
    transitions to `INVALIDATED`, processed in `created_at` ascending order, with
    its whole unencumbered and encumbered balance folded into the void"

    Design: Difficulty/transitive_cascade/reverification_fail_cascade_project_to_batch_to_transaction_to_permit_violation
    """
    world = _settled_trade_world(api)

    event = fx.reverify(api, world["project_id"], "FAIL")

    assert event["resulting_project_status"] == "REVOKED", event
    assert event["inspector_user_id"] == "verifier-3", event
    assert_instant_equals(event["observed_at"], CLOCK_BASE, "observed_at")

    project = get_success_data(api.get_practice_project(world["project_id"], REGISTRY))
    assert project["status"] == "REVOKED", project

    batch = get_success_data(api.get_credit_batch(world["batch_id"], REGISTRY))
    assert batch["status"] == "INVALIDATED", batch
    assert_batch_buckets(batch, available=0.00, reserved=0.00, retired=0.00, invalidated=4000.00)
    assert_integer(batch["issued_lbs"], 4000, "issued_lbs is never restated")


def test_reverification_failure_drives_the_buyer_permit_into_violation(api):
    """A credit that never existed is an enforcement matter, not a shortfall.

    "`compliance_status` moves to `VIOLATION` — from `RESOLVED` when the
    recomputed gap comes out above 0.00, and from `SHORTFALL` unconditionally —
    `enforcement_flag` becomes true, and the permit's `version` increments by 1."

    Design: Difficulty/transitive_cascade/reverification_fail_cascade_project_to_batch_to_transaction_to_permit_violation
    """
    world = _settled_trade_world(api)

    fx.reverify(api, world["project_id"], "FAIL")

    txn = get_success_data(api.get_credit_transaction(world["txn_id"], REGISTRY))
    assert txn["status"] == "VOIDED", txn
    assert txn["void_reason"] == "BATCH_INVALIDATED", txn
    assert_instant_equals(txn["voided_at"], CLOCK_BASE, "voided_at")

    permit = validate_success(api.get_permit(world["permit_id"], PERMITTEE_1))
    assert_load(permit["credit_applied_lbs"], 0.00, "credit_applied_lbs")
    assert_load(permit["compliance_gap_lbs"], 1084.00, "compliance_gap_lbs")
    assert permit["compliance_status"] == "VIOLATION", permit
    assert permit["enforcement_flag"] is True, permit

    # The revocation cascade is not a market suspension: the program stays open.
    watershed = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_trading_gate(watershed, "ACTIVE")
    assert_load(watershed["reserve_pool_lbs"], 2400.00, "reserve_pool_lbs")
