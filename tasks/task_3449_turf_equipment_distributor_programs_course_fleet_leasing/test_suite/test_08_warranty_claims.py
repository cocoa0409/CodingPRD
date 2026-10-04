"""Warranty claim adjudication: claimed vs factory variants, the dispute
re-review cycle, settlement into the service credit, the annual fiscal cap,
the certification and warranty-window gates, and claim OCC (PRD §3.8, §2.7).
"""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    certify_technician_payload,
    claim_to_approved,
    claim_to_disputed,
    claim_to_paid,
    claim_to_partial_approved,
    claim_to_under_review,
    create_catalog_model,
    create_course_for,
    create_distributor_payload,
    create_lease_for,
    create_technician_payload,
    create_warranty_claim_payload,
    deliver_unit,
    is_iso8601_timestamp,
    list_lease_units,
    make_distributor_manager_headers,
    put_unit_in_service,
    run_rollover,
    setup_active_lease_with_in_service_unit,
    setup_approved_claim,
    setup_submitted_claim,
    walk_lease_to,
    validate_error,
    validate_success,
)


def _setup_expiring_cert_scenario(api, corporate_admin_headers):
    """ACTIVE distributor whose technician's certification expires
    2027-01-01; an ACTIVE lease started 2026-09-01 with its unit IN_SERVICE.
    After the clock advances to 2027-02-01 and the rollover runs, the
    technician stands CERT_EXPIRED while the unit's 24-month warranty still
    runs."""
    distributor = validate_success(
        api.create_distributor(create_distributor_payload(), corporate_admin_headers), 201
    )
    mgr = make_distributor_manager_headers(distributor["id"])
    technician = validate_success(
        api.create_technician(create_technician_payload(), mgr), 201
    )
    validate_success(
        api.certify_technician(
            technician["id"],
            certify_technician_payload(expires_at="2027-01-01T00:00:00Z"),
            corporate_admin_headers,
        )
    )
    distributor = validate_success(
        api.run_compliance_review(distributor["id"], corporate_admin_headers)
    )
    assert distributor["status"] == "ACTIVE", "Setup failed: activation gate"
    course = create_course_for(distributor)
    model = create_catalog_model()
    lease = create_lease_for(
        distributor, course, [{"model_id": model["id"], "qty": 1}],
        cycle_months=36, start_date="2026-09-01",
    )
    lease = walk_lease_to(lease, "ACTIVE")
    unit = list_lease_units(lease)[0]
    unit = deliver_unit(unit, "SN-A1")
    unit = put_unit_in_service(unit, course)
    advance_clock("2027-02-01T00:00:00Z")
    run_rollover()
    return {
        "distributor": distributor,
        "technician": technician,
        "course": course,
        "model": model,
        "lease": lease,
        "unit": unit,
    }


def test_create_computes_both_variants(api):
    """PRD §3.8: "The claim opens in `SUBMITTED` with its `distributor_id`
    stamped from the acting identity, and two figures are computed immediately
    at creation and pinned there: `claimed_labor_cents`, the `labor_hours`
    priced at the distributor's `labor_rate_cents` — what the distributor bills
    — and `factory_allowance_cents`, the same `labor_hours` priced at the
    model's `warranty_labor_hourly_cap_cents` — what the factory allows."

    Design: Difficulty/dual_variant_calc/warranty_claimed_vs_factory_adjudication
    """
    ctx = setup_submitted_claim()
    claim = ctx["claim"]
    # 4 h x 14,000 (distributor rate) vs 4 h x 9,500 (factory cap).
    assert claim["claimed_labor_cents"] == 56000
    assert claim["factory_allowance_cents"] == 38000
    assert claim["status"] == "SUBMITTED"


def test_approval_adjudicates_min_variant(api):
    """PRD §3.8: "The adjudicated labor figure, `adjudicated_labor_cents`, is
    the smaller of two pricings of the effective hours: the effective hours at
    the distributor's `labor_rate_cents`, or the effective hours at the model's
    `warranty_labor_hourly_cap_cents` — the factory never pays more than its
    allowance, and never more than the distributor actually bills. Parts are
    reimbursed at cost plus a 10 percent handling allowance:
    `parts_reimbursed_cents` is `parts_cost_cents` multiplied by 1.10, rounded
    half-up to integer cents, and this is the only rounded step in claim
    adjudication. `payable_total_cents` is the sum of
    `adjudicated_labor_cents` and `parts_reimbursed_cents`."

    Design: Difficulty/dual_variant_calc/warranty_claimed_vs_factory_adjudication
    """
    ctx = setup_approved_claim()
    claim = ctx["claim"]
    assert claim["status"] == "APPROVED"
    assert claim["adjudicated_labor_cents"] == 38000, (
        "min(4 x 14000, 4 x 9500): the factory allowance is the smaller variant"
    )
    assert claim["claimed_labor_cents"] != claim["adjudicated_labor_cents"]
    # round_half_up(22,000 x 1.10) = 24,200.
    assert claim["parts_reimbursed_cents"] == 24200
    assert claim["payable_total_cents"] == 62200


def test_partial_then_dispute_reopens_review(api):
    """PRD §3.8: "Partial approval moves it to `PARTIAL_APPROVED` and requires
    an `approved_labor_hours` strictly greater than 0 and strictly less than
    the claimed `labor_hours`; the effective hours are then
    `approved_labor_hours`, recorded on the claim."
    PRD §3.8: "the owning `DistributorManager` moves a claim from `DENIED` or
    from `PARTIAL_APPROVED` to `DISPUTED`, and a `CorporateAdmin` returns a
    `DISPUTED` claim to `UNDER_REVIEW` for re-review — a deliberate cycle that
    lets a claim be re-adjudicated, re-denied or re-partially-approved, and
    disputed again."

    Design: Difficulty/non_linear_state_machine/warranty_claim_dispute_reopens_review_cycle
    """
    ctx = setup_submitted_claim()
    claim = claim_to_under_review(ctx["claim"])
    claim = claim_to_partial_approved(claim, 2)
    # Partial round: min(2 x 14000, 2 x 9500) = 19,000; parts 24,200.
    assert claim["payable_total_cents"] == 43200
    assert claim["approved_labor_hours"] == 2
    claim = claim_to_disputed(claim)
    assert claim["status"] == "DISPUTED"
    claim = claim_to_under_review(claim)
    assert claim["status"] == "UNDER_REVIEW", (
        "the dispute loop re-opens the review cycle"
    )


def test_full_cycle_ends_paid_on_full_hours(api, corporate_admin_headers):
    """PRD §3.8: "Full approval moves the claim to `APPROVED` and adjudicates
    with the claimed hours as the effective hours."
    PRD §3.8: "Every claim transition, client- or system-driven, increments the
    claim's `version` by 1."
    PRD §3.8: "`PAID` is the claim's terminal state."

    Design: Difficulty/non_linear_state_machine/warranty_claim_dispute_reopens_review_cycle
    """
    ctx = setup_submitted_claim()
    created_version = ctx["claim"]["version"]
    claim = claim_to_under_review(ctx["claim"])
    claim = claim_to_partial_approved(claim, 2)
    assert claim["payable_total_cents"] == 43200
    claim = claim_to_disputed(claim)
    claim = claim_to_under_review(claim)
    claim = claim_to_approved(claim)
    # Re-adjudication after the dispute loop runs on the full claimed hours:
    # min(4 x 14000, 4 x 9500) = 38,000 + 24,200 parts = 62,200.
    assert claim["payable_total_cents"] == 62200, (
        "re-approval on full hours erases the partial-round payable"
    )
    claim = claim_to_paid(claim)
    assert claim["status"] == "PAID"
    assert claim["version"] == created_version + 6, (
        f"six OCC-guarded transitions from creation; got version {claim['version']}"
    )


def test_claim_pay_credits_distributor_service_balance(api, corporate_admin_headers):
    """PRD §3.8: "On payment the claim's `paid_at` is stamped with the logical
    clock and the distributor's `service_credit_balance_cents` increases by
    `payable_total_cents`."

    Design: Corner/state_machines/claim_pay_credits_distributor_service_balance
    """
    ctx = setup_approved_claim()
    claim = claim_to_paid(ctx["claim"])
    assert claim["status"] == "PAID"
    assert claim.get("paid_at") is not None and is_iso8601_timestamp(claim["paid_at"])
    distributor = validate_success(
        api.get_distributor(ctx["distributor"]["id"], corporate_admin_headers)
    )
    assert distributor["service_credit_balance_cents"] == 62200, (
        f"payment credits exactly payable_total_cents; got "
        f"{distributor['service_credit_balance_cents']}"
    )


def test_claim_pay_over_annual_cap_rejected(api, corporate_admin_headers):
    """PRD §3.8: "Payment is subject to the distributor's annual fiscal
    ceiling: the distributor's `claims_paid_ytd_cents` — the sum of
    `payable_total_cents` over its own claims already paid with a `paid_at`
    inside the current calendar year of the logical clock — plus this claim's
    `payable_total_cents` must not exceed the distributor's
    `annual_claim_cap_cents`, else payment is rejected with
    `ERR_CLAIM_CAP_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/claim_pay_over_annual_cap_rejected
    """
    ctx = setup_approved_claim(distributor_overrides={"annual_claim_cap_cents": 50000})
    claim = ctx["claim"]  # payable 62,200 > cap 50,000
    resp = api.transition_warranty_claim(
        claim["id"], "PAID", claim["version"], corporate_admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_CAP_EXCEEDED.value)
    after = validate_success(api.get_warranty_claim(claim["id"], corporate_admin_headers))
    assert after["status"] == "APPROVED", (
        "the fiscal check fires at pay time; the claim stays APPROVED"
    )


def test_claim_with_expired_cert_rejected(api, corporate_admin_headers):
    """PRD §3.1: "A season rollover expires every certification whose
    `cert_expires_at` has fallen behind the logical clock, moving the
    technician to `CERT_EXPIRED`; claims already in `SUBMITTED` remain in
    place, but any new claim naming that technician is rejected with
    `ERR_TECHNICIAN_CERT_INVALID` (HTTP 409)."
    PRD §3.8: "Certification: the technician must currently hold `CERT_ACTIVE`
    standing, else `ERR_TECHNICIAN_CERT_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/claim_requires_active_technician_cert
    """
    ctx = _setup_expiring_cert_scenario(api, corporate_admin_headers)
    resp = api.create_warranty_claim(
        create_warranty_claim_payload(
            ctx["unit"]["id"], ctx["technician"]["id"],
            labor_hours=2, parts_cost_cents=5000,
        ),
        make_distributor_manager_headers(ctx["distributor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TECHNICIAN_CERT_INVALID.value)


def test_rollover_marks_technician_cert_expired(api, corporate_admin_headers):
    """PRD §3.1: "A season rollover expires every certification whose
    `cert_expires_at` has fallen behind the logical clock, moving the
    technician to `CERT_EXPIRED`"

    Design: Difficulty/cross_entity_state_dependency/claim_requires_active_technician_cert
    """
    ctx = _setup_expiring_cert_scenario(api, corporate_admin_headers)
    technician = validate_success(
        api.get_technician(ctx["technician"]["id"], corporate_admin_headers)
    )
    assert technician["cert_status"] == "CERT_EXPIRED", (
        f"cert expiring 2027-01-01 is expired by the rollover at 2027-02-01; "
        f"got {technician['cert_status']!r}"
    )
    resp = api.create_warranty_claim(
        create_warranty_claim_payload(
            ctx["unit"]["id"], ctx["technician"]["id"],
            labor_hours=2, parts_cost_cents=5000,
        ),
        make_distributor_manager_headers(ctx["distributor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TECHNICIAN_CERT_INVALID.value)


def test_claim_create_warranty_expired_rejected(api):
    """PRD §3.8: "Coverage: the unit's age, measured from its `delivered_at`,
    must lie within its model's `factory_warranty_months`, else
    `ERR_WARRANTY_EXPIRED` (HTTP 422)."

    Design: Corner/validations/claim_create_warranty_expired_rejected
    """
    ctx = setup_active_lease_with_in_service_unit()
    # Unit delivered 2026-09-01 under a 24-month warranty; 2028-10-01 is 25
    # months in. No rollover runs, so the technician's standing is untouched.
    advance_clock("2028-10-01T00:00:00Z")
    resp = api.create_warranty_claim(
        create_warranty_claim_payload(
            ctx["unit"]["id"], ctx["technician"]["id"],
            labor_hours=2, parts_cost_cents=5000,
        ),
        make_distributor_manager_headers(ctx["distributor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED.value)


def test_claim_transition_stale_version_returns_412(api, corporate_admin_headers):
    """PRD §2.7: "A mismatch with the claim's current `version` — because
    another adjudication step has already advanced the claim — is rejected with
    `ERR_STALE_CLAIM_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/claim_transition_stale_version_returns_412
    """
    ctx = setup_submitted_claim()
    claim = ctx["claim"]  # created version
    claim = claim_to_under_review(claim)  # advanced one version
    resp = api.transition_warranty_claim(
        claim["id"], "DENIED", ctx["claim"]["version"], corporate_admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_STALE_CLAIM_VERSION.value)
    after = validate_success(api.get_warranty_claim(claim["id"], corporate_admin_headers))
    assert after["status"] == "UNDER_REVIEW"
