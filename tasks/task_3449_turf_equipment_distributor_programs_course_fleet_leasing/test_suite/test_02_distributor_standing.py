"""Distributor standing: compliance reviews, the fill-rate boundary, and the
standing cascade that reverts in-flight lease reviews (PRD §3.1 and §2.9).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    create_and_receive_order,
    create_appraisal_for,
    create_catalog_model,
    create_course_for,
    create_distributor_active,
    create_lease_for,
    create_order_for,
    create_part_for,
    get_success_data,
    make_distributor_manager_headers,
    submit_lease,
    submit_order,
    cancel_order,
    validate_error,
    validate_success,
)

BOUNDARY_DISTRIBUTOR = {
    "name": "Boundary Bros",
    "territory_codes": ["OR"],
    "min_parts_stock_value_cents": 0,
    "labor_rate_cents": 12000,
    "annual_claim_cap_cents": 10000000,
}

SIERRA_FAILING_STOCK = {
    "name": "Sierra Turf Supply",
    "territory_codes": ["AZ"],
    "min_parts_stock_value_cents": 500000,
    "labor_rate_cents": 13500,
    "annual_claim_cap_cents": 30000000,
}

GM_1200 = {
    "model_code": "GM-1200",
    "category": "MOWER",
    "tier": "STANDARD",
    "list_price_cents": 4200000,
    "eligible_turf_types": ["BERMUDA", "MIXED"],
    "warranty_labor_hourly_cap_cents": 8000,
    "parts_support_years": 8,
}

DESERT_WILLOW = {
    "name": "Desert Willow GC",
    "turf_profile": "BERMUDA",
    "cut_quality_standard": "MAINTENANCE",
    "credit_limit_cents": 30000000,
}


def _setup_sierra_with_lease():
    """ACTIVE distributor with a 500,000-cent stocking obligation (no received
    orders), a course, the STANDARD model, and one DRAFT lease."""
    distributor, _tech = create_distributor_active(**SIERRA_FAILING_STOCK)
    course = create_course_for(distributor, **DESERT_WILLOW)
    model = create_catalog_model(**GM_1200)
    lease = create_lease_for(
        distributor,
        course,
        [{"model_id": model["id"], "qty": 2}],
        cycle_months=24,
        start_date="2027-01-04",
    )
    return distributor, course, model, lease


def test_fill_rate_exactly_at_threshold_passes(api, corporate_admin_headers):
    """PRD §3.1: "The review passes when the fill rate is at least 0.92 — the
    boundary is inclusive — and `stock_value_trailing_cents` is at least the
    distributor's `min_parts_stock_value_cents`; failing either leg fails the
    review."
    PRD §3.1: "A distributor in `ACTIVE` that passes stays `ACTIVE`; one that
    fails drops to `PROBATION`."

    Design: Difficulty/boundary_precision_check/fill_rate_exactly_at_threshold_passes
    """
    distributor, _tech = create_distributor_active(**BOUNDARY_DISTRIBUTOR)
    model = create_catalog_model()
    part = create_part_for(model)
    create_and_receive_order(distributor, part, 100, 92)

    reviewed = validate_success(
        api.run_compliance_review(distributor["id"], corporate_admin_headers)
    )
    assert reviewed["status"] == "ACTIVE", (
        f"fill_rate 92/100 == 0.92 is exactly the inclusive boundary; "
        f"expected ACTIVE, got {reviewed['status']!r}"
    )
    assert reviewed["fill_rate"] == pytest.approx(0.92)


def test_fill_rate_below_threshold_drops_to_probation(api, corporate_admin_headers):
    """PRD §3.1: "otherwise `fill_rate` is the sum of `received_units` divided
    by the sum of `ordered_units` across the window."
    PRD §3.1: "A distributor in `ACTIVE` that passes stays `ACTIVE`; one that
    fails drops to `PROBATION`."

    Design: Difficulty/boundary_precision_check/fill_rate_exactly_at_threshold_passes
    """
    distributor, _tech = create_distributor_active(**BOUNDARY_DISTRIBUTOR)
    model = create_catalog_model()
    part = create_part_for(model)
    create_and_receive_order(distributor, part, 100, 92)
    create_and_receive_order(distributor, part, 100, 91)

    reviewed = validate_success(
        api.run_compliance_review(distributor["id"], corporate_admin_headers)
    )
    # 183/200 = 0.915 < 0.92: the inclusive boundary no longer met.
    assert reviewed["status"] == "PROBATION", (
        f"fill_rate 183/200 = 0.915 must fail the review; got {reviewed['status']!r}"
    )
    assert reviewed["fill_rate"] == pytest.approx(0.915)


def test_fill_rate_excludes_cancelled_and_inflight_orders(api, corporate_admin_headers):
    """PRD §3.1: "considering only the distributor's own parts orders in
    `RECEIVED` status; cancelled and in-flight orders never enter the window."

    Design: Corner/calculations/fill_rate_excludes_cancelled_and_inflight_orders
    """
    distributor, _tech = create_distributor_active(**BOUNDARY_DISTRIBUTOR)
    model = create_catalog_model()
    part = create_part_for(model)
    create_and_receive_order(distributor, part, 100, 92)

    cancelled = create_order_for(distributor, [{"part_id": part["id"], "qty": 50}])
    cancelled = submit_order(cancelled)
    cancel_order(cancelled)

    inflight = create_order_for(distributor, [{"part_id": part["id"], "qty": 50}])
    submit_order(inflight)

    reviewed = validate_success(
        api.run_compliance_review(distributor["id"], corporate_admin_headers)
    )
    assert reviewed["fill_rate"] == pytest.approx(0.92), (
        "only the RECEIVED 92/100 order may enter the window; the CANCELLED and "
        f"in-flight SUBMITTED orders must be ignored, got {reviewed['fill_rate']!r}"
    )
    assert reviewed["status"] == "ACTIVE"


def test_failing_review_drops_to_probation_and_reverts_lease(api, corporate_admin_headers):
    """PRD §2.9: "When a distributor falls from `ACTIVE` to `PROBATION`, or
    from `PROBATION` to `SUSPENDED`, the second link reverts every FleetLease
    of that distributor sitting in `SPEC_REVIEW` back to `DRAFT`, incrementing
    each reverted lease's `version` by 1"
    PRD §3.1: "A distributor in `ACTIVE` that passes stays `ACTIVE`; one that
    fails drops to `PROBATION`."

    Design: Difficulty/transitive_cascade/compliance_probation_reverts_lease_and_voids_appraisals
    """
    distributor, _course, _model, lease = _setup_sierra_with_lease()
    create_appraisal_for(
        lease, _model, external_serial="OLD-777", hours=900,
        condition_grade="A", policy="BOOK",
    )
    lease = submit_lease(lease)

    reviewed = validate_success(
        api.run_compliance_review(distributor["id"], corporate_admin_headers)
    )
    assert reviewed["status"] == "PROBATION", (
        f"stock_value 0 < min_parts_stock_value_cents 500000 must fail the "
        f"review, got {reviewed['status']!r}"
    )
    reverted = validate_success(api.get_lease(lease["id"], corporate_admin_headers))
    assert reverted["status"] == "DRAFT", (
        f"SPEC_REVIEW lease must be reverted to DRAFT by the standing cascade, "
        f"got {reverted['status']!r}"
    )
    assert reverted["version"] == 3, (
        "create 1, submit 2, cascade revert 3 (a newly created FleetLease starts "
        f"with version set to 1 and cascade mutations increment it), got {reverted['version']}"
    )


def test_lease_revert_voids_valued_appraisal(api, corporate_admin_headers):
    """PRD §2.9: "the third link then voids each reverted lease's appraisals in
    `VALUED` or `DISPUTED` and walks each appraisal in `ACCEPTED` back to
    `VALUED`."

    Design: Difficulty/transitive_cascade/compliance_probation_reverts_lease_and_voids_appraisals
    """
    distributor, _course, model, lease = _setup_sierra_with_lease()
    appraisal = create_appraisal_for(
        lease, model, external_serial="OLD-777", hours=900,
        condition_grade="A", policy="BOOK",
    )
    lease = submit_lease(lease)

    reviewed = validate_success(
        api.run_compliance_review(distributor["id"], corporate_admin_headers)
    )
    assert reviewed["status"] == "PROBATION"
    reverted = validate_success(api.get_lease(lease["id"], corporate_admin_headers))
    assert reverted["status"] == "DRAFT" and reverted["version"] == 3
    voided = validate_success(api.get_appraisal(appraisal["id"], corporate_admin_headers))
    assert voided["status"] == "VOIDED", (
        f"the lease revert must void its VALUED appraisal, got {voided['status']!r}"
    )


def test_probation_reverts_only_spec_review_leases(api, corporate_admin_headers):
    """PRD §2.9: "the second link reverts every FleetLease of that distributor
    sitting in `SPEC_REVIEW` back to `DRAFT`, incrementing each reverted
    lease's `version` by 1"

    Design: Corner/state_machines/probation_reverts_only_spec_review_leases
    """
    distributor, course, model, _lease = _setup_sierra_with_lease()
    l_draft = _lease  # never submitted
    l_sr = create_lease_for(
        distributor,
        course,
        [{"model_id": model["id"], "qty": 1}],
        cycle_months=24,
        start_date="2028-02-01",
    )
    l_sr = submit_lease(l_sr)

    reviewed = validate_success(
        api.run_compliance_review(distributor["id"], corporate_admin_headers)
    )
    assert reviewed["status"] == "PROBATION"

    sr_after = validate_success(api.get_lease(l_sr["id"], corporate_admin_headers))
    assert sr_after["status"] == "DRAFT" and sr_after["version"] == 3, (
        f"SPEC_REVIEW lease must revert (version 1 -> 3); got "
        f"{sr_after['status']!r} v{sr_after['version']}"
    )
    draft_after = validate_success(api.get_lease(l_draft["id"], corporate_admin_headers))
    assert draft_after["status"] == "DRAFT" and draft_after["version"] == 1, (
        f"the conditional cascade must skip leases not in SPEC_REVIEW; got "
        f"{draft_after['status']!r} v{draft_after['version']}"
    )


def test_submit_after_probation_rejected_not_active(api, corporate_admin_headers):
    """PRD §3.4: "This is the owning `DistributorManager`'s act: the acting
    distributor must own the lease and operate the equipment channel
    (`ERR_WRONG_CHANNEL`), its standing must be `ACTIVE`
    (`ERR_DISTRIBUTOR_NOT_ACTIVE`), and the OCC guard of §2.7 applies
    (`ERR_STALE_LEASE_VERSION`)."

    Design: Difficulty/cross_entity_state_dependency/lease_submit_requires_distributor_active
    """
    distributor, _course, _model, lease = _setup_sierra_with_lease()
    reviewed = validate_success(
        api.run_compliance_review(distributor["id"], corporate_admin_headers)
    )
    assert reviewed["status"] == "PROBATION"

    resp = api.transition_lease(
        lease["id"],
        "SPEC_REVIEW",
        lease["version"],
        make_distributor_manager_headers(distributor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DISTRIBUTOR_NOT_ACTIVE.value)


def test_rejected_submit_leaves_lease_draft(api, corporate_admin_headers):
    """PRD §3.4: "its standing must be `ACTIVE` (`ERR_DISTRIBUTOR_NOT_ACTIVE`)"
    PRD §3.4: "The lease opens in `DRAFT` with `version` 1"

    Design: Difficulty/cross_entity_state_dependency/lease_submit_requires_distributor_active
    """
    distributor, _course, _model, lease = _setup_sierra_with_lease()
    reviewed = validate_success(
        api.run_compliance_review(distributor["id"], corporate_admin_headers)
    )
    assert reviewed["status"] == "PROBATION"

    resp = api.transition_lease(
        lease["id"],
        "SPEC_REVIEW",
        lease["version"],
        make_distributor_manager_headers(distributor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DISTRIBUTOR_NOT_ACTIVE.value)
    after = validate_success(api.get_lease(lease["id"], corporate_admin_headers))
    assert after["status"] == "DRAFT" and after["version"] == 1, (
        f"the rejected submit must leave the lease untouched; got "
        f"{after['status']!r} v{after['version']}"
    )
