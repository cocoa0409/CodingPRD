"""Tests translated from the breadth Coverage Index (queue B) — sections
calculations, endpoints and errors.
"""
import pytest

from test_helpers import (
    CLOCK_PAST_WEEK,
    TEST_USERS,
    api_client,
    create_area,
    create_deduction_payload,
    create_peak_declaration_payload,
    create_provider,
    create_route_assignment_payload,
    create_vehicle_payload,
    file_and_verify_policy,
    get_success_data,
    make_service_provider_headers,
    open_week,
    setup_active_provider,
    setup_reconciled_week,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
import test_helpers.fixtures as fx

AM = TEST_USERS["account_manager_headers"]
SA = TEST_USERS["settlement_analyst_headers"]
CO = TEST_USERS["compliance_officer_headers"]
PA = TEST_USERS["platform_admin_headers"]


# ═══════════════════════════════════════════════════════════════════════
# calculations: chargeback_escalation_threshold_exact_boundary
# ═══════════════════════════════════════════════════════════════════════

def test_chargeback_escalation_boundary_at_exactly_200000_cents(api):
    """PRD §3.10: "When that prior-year-to-date total has reached or exceeded
    200000 cents, the net figure is multiplied by one plus ten hundredths — a ten
    percent escalation — and rounded half up to a whole cent."

    Design: Corner/calculations/chargeback_escalation_threshold_exact_boundary
    """
    ctx = setup_active_provider()
    provider, area = ctx["provider"], ctx["area"]
    period = open_week(provider["id"], area["id"])

    def _approve(amount_cents):
        claim = get_success_data(api.create_chargeback_claim({
            "provider_id": provider["id"], "settlement_period_id": period["id"],
            "claim_type": "DAMAGE", "amount_cents": amount_cents,
            "recovery_rate_pct": 0}, AM))
        return validate_success(api.approve_chargeback_claim(claim["id"], AM), 200)

    _approve(150000)   # prior total 0 -> un-escalated
    _approve(49999)    # prior total 150000 -> un-escalated; running total 199999

    third = _approve(30000)   # prior total 199999 < 200000 -> un-escalated
    assert third["net_of_recovery_cents"] == 30000
    outstanding_after_3 = validate_success(
        api.get_service_provider(provider["id"], SA), 200)["chargeback_outstanding_cents"]
    assert outstanding_after_3 == 229999

    fourth = _approve(100)    # prior total 229999 >= 200000 -> 100 x 1.10 = 110
    assert fourth["net_of_recovery_cents"] == 110
    provider_after = validate_success(api.get_service_provider(provider["id"], SA), 200)
    assert provider_after["chargeback_outstanding_cents"] == 230109


# ═══════════════════════════════════════════════════════════════════════
# calculations: composite_score_rounding_precision
# ═══════════════════════════════════════════════════════════════════════

def test_composite_score_rounds_half_up_not_half_even(api):
    """PRD §3.9: "The raw composite is five tenths of the `service_score`, plus
    three tenths of the `safety_score`, plus two tenths of the
    `customer_experience_score`, rounded half up to two decimal places."
    PRD §2.10: "where a rule states a score or a percentage that is itself
    stored, it is rounded half up to two decimal places."

    Design: Corner/calculations/composite_score_rounding_precision
    """
    provider = create_provider()
    file_and_verify_policy(provider["id"])
    get_success_data(api.approve_service_provider(provider["id"], AM))

    metric = get_success_data(api.create_performance_metric({
        "provider_id": provider["id"], "service_score": 91.005,
        "safety_score": 90.005, "customer_experience_score": 90.005}, SA))
    composed = validate_success(api.compose_performance_metric(metric["id"], SA), 200)
    # raw = 0.5*91.005 + 0.3*90.005 + 0.2*90.005 = 90.505 -> half up -> 90.51
    assert composed["composite_score"] == 90.51


# ═══════════════════════════════════════════════════════════════════════
# calculations: gross_settlement_tier_cliff_input_set_filtering
# ═══════════════════════════════════════════════════════════════════════

def test_out_of_window_observation_does_not_move_the_tier(api):
    """PRD §3.7: "The close freezes the window: every observation whose
    `recorded_at` falls inside the half-open week is fixed into the accrual, and
    any observation recorded later is ignored by the arithmetic regardless of
    what its `observed_date` says."

    Design: Corner/calculations/gross_settlement_tier_cliff_input_set_filtering
    """
    ctx = setup_active_provider()
    period = open_week(ctx["provider"]["id"], ctx["area"]["id"],
                       week_start="2026-09-07T00:00:00Z")
    fx.add_observation(period["id"], observed_date="2026-09-08T00:00:00Z",
                       recorded_at="2026-09-08T18:00:00Z", stops_count=900,
                       packages_count=500, accessorial_cents=0)
    # recorded_at 2026-09-14T12:00:00Z is one instant past the exclusive week end.
    fx.add_observation(period["id"], observed_date="2026-09-13T00:00:00Z",
                       recorded_at="2026-09-14T12:00:00Z", stops_count=1500,
                       packages_count=0, accessorial_cents=0)
    set_clock(CLOCK_PAST_WEEK)
    validate_success(api.close_accrual(period["id"], SA), 200)

    summary = validate_success(api.get_period_summary(period["id"], SA), 200)
    assert summary["stops_gross_cents"] == 19800
    assert summary["base_gross_cents"] == 23800


# ═══════════════════════════════════════════════════════════════════════
# endpoints: summary_read_reports_exact_segment_decomposition
# ═══════════════════════════════════════════════════════════════════════

def test_summary_read_decomposes_a_reconciled_week(api):
    """PRD §3.7: "The week's arithmetic is exposed in decomposed form by a
    computed read that reports the week's `settlement_period_id`, its
    `stops_gross_cents`, `package_gross_cents`, `peak_gross_cents` and
    `accessorial_gross_cents`, its resulting `base_gross_cents`, its applied
    `performance_multiplier`, its `capped_deduction_cents`, its
    `uncapped_deduction_cents`, and its `net_amount_cents`, so that a provider
    can see exactly which segment moved its payout."

    Design: Corner/endpoints/summary_read_reports_exact_segment_decomposition
    """
    ctx = setup_reconciled_week(
        observation_overrides={"stops_count": 300, "packages_count": 250,
                               "accessorial_cents": 2000},
        deductions=[{"deduction_type": "MAINTENANCE", "amount_cents": 15000,
                     "performance_factor_eligible": True},
                    {"deduction_type": "FUEL", "amount_cents": 3000,
                     "performance_factor_eligible": False}],
        metric_scores=(72, 70, 62))

    summary = validate_success(api.get_period_summary(ctx["period"]["id"], SA), 200)
    assert summary["stops_gross_cents"] == 6600
    assert summary["package_gross_cents"] == 2000
    assert summary["accessorial_gross_cents"] == 2000
    assert summary["base_gross_cents"] == 10600
    assert summary["performance_multiplier"] == 0.90
    assert summary["capped_deduction_cents"] == 13500
    assert summary["uncapped_deduction_cents"] == 3000
    assert summary["net_amount_cents"] == 10600 - 13500 - 3000


# ═══════════════════════════════════════════════════════════════════════
# endpoints: obligation_endpoints_reject_dangling_vehicle_reference
# ═══════════════════════════════════════════════════════════════════════

def test_vehicle_registration_rejects_a_dangling_area_reference(api):
    """PRD §2.9: "Body-declared foreign keys — `service_area_id`, `provider_id`,
    `acquiring_provider_id`, `settlement_period_id`, `vehicle_id` and
    `fuel_index_rate_id` — are resolved at a single point rather than lazily at
    the moment they are used, so a dangling body reference fails as a
    missing-or-invalid-request condition promptly rather than surfacing later as
    an unrelated failure."
    PRD §2.9: "a service area yields `ERR_SERVICE_AREA_NOT_FOUND`"

    The body carries a well-formed `service_area_id` that names no row, so the
    dangling-reference rule (not the UUID-format rule) is the gate under test.

    Design: Corner/endpoints/obligation_endpoints_reject_dangling_vehicle_reference
    """
    provider = create_provider()
    area = create_area()
    get_success_data(api.approve_service_provider(provider["id"], AM))

    res = api.create_vehicle(create_vehicle_payload(
        provider["id"], "00000000-0000-4000-8000-000000000777",
        vehicle_class="TRACTOR_TRAILER", gvwr_pounds=80000), AM)
    validate_error(res, "ERR_SERVICE_AREA_NOT_FOUND", expected_status=404)

    data, _meta = validate_paginated(
        api.list_vehicles(AM, {"service_area_id": area["id"]}))
    assert data == []


# ═══════════════════════════════════════════════════════════════════════
# errors: peak_capacity_exceeded_on_missing_active_declaration
# ═══════════════════════════════════════════════════════════════════════

def test_temporary_driver_refused_without_a_covering_active_declaration(api):
    """PRD §3.2: "a temporary unit can only be added while an `ACTIVE`
    `PeakSeasonDeclaration` covers the requested instant and the fleet's
    temporary count remains within `authorized_vehicles`, and a violation returns
    `ERR_PEAK_CAPACITY_EXCEEDED` (HTTP 422)."
    PRD §3.6: "Only a declaration in `ACTIVE` status lets temporary assets
    satisfy the qualification gates at all"

    Design: Corner/errors/peak_capacity_exceeded_on_missing_active_declaration
    """
    provider = create_provider()
    area = create_area()
    get_success_data(api.approve_service_provider(provider["id"], AM))
    get_success_data(api.create_peak_declaration(create_peak_declaration_payload(
        area["id"], starts_on="2026-11-01T00:00:00Z",
        ends_on="2026-12-31T00:00:00Z"), AM))

    res = api.create_driver({
        "provider_id": provider["id"], "service_area_id": area["id"],
        "full_name": "Peak Hire One", "license_class": "CLASS_B",
        "qualification_status": "QUALIFIED", "is_temporary": True}, AM)
    validate_error(res, "ERR_PEAK_CAPACITY_EXCEEDED", expected_status=422)

def test_temporary_driver_accepted_once_declaration_is_active(api):
    """PRD §3.2: "a temporary unit can only be added while an `ACTIVE`
    `PeakSeasonDeclaration` covers the requested instant and the fleet's
    temporary count remains within `authorized_vehicles`"
    PRD §3.6: "The requested instant must fall inside the window — the
    declaration is activated only while `starts_on` has arrived and `ends_on`
    has not"

    Design: Corner/errors/peak_capacity_exceeded_on_missing_active_declaration
    """
    provider = create_provider()
    area = create_area()
    get_success_data(api.approve_service_provider(provider["id"], AM))
    declaration = get_success_data(api.create_peak_declaration(create_peak_declaration_payload(
        area["id"], starts_on="2026-11-01T00:00:00Z",
        ends_on="2026-12-31T00:00:00Z"), AM))
    get_success_data(api.set_current_utc("2026-11-15T00:00:00Z", PA))
    validate_success(api.activate_peak_declaration(declaration["id"], AM), 200)

    created = validate_success(api.create_driver({
        "provider_id": provider["id"], "service_area_id": area["id"],
        "full_name": "Peak Hire One", "license_class": "CLASS_B",
        "qualification_status": "QUALIFIED", "is_temporary": True}, AM), 201)
    assert created["is_temporary"] is True


# ═══════════════════════════════════════════════════════════════════════
# errors: charges_error_stale_version_on_settlement_create
# ═══════════════════════════════════════════════════════════════════════

def test_stale_provider_version_refuses_settlement_create(api):
    """PRD §3.7: "it must carry `expected_provider_version`, and a value that no
    longer matches the provider's current `version` is refused with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/charges_error_stale_version_on_settlement_create
    """
    ctx = setup_reconciled_week()
    provider, area = ctx["provider"], ctx["area"]

    res = api.create_settlement_period({
        "provider_id": provider["id"], "service_area_id": area["id"],
        "week_start_at": "2026-09-14T00:00:00Z", "is_peak_week": False,
        "fuel_rate_cents_per_mile": 3,
        "expected_provider_version": ctx["provider"]["version"]}, SA)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_fresh_provider_version_allows_settlement_create(api):
    """PRD §3.7: "it must carry `expected_provider_version`, and a value that no
    longer matches the provider's current `version` is refused with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.7: "A new week begins in `OPEN` and advances the provider's `version`
    by one."

    Design: Corner/errors/charges_error_stale_version_on_settlement_create
    """
    ctx = setup_reconciled_week()
    provider, area = ctx["provider"], ctx["area"]
    provider_now = get_success_data(api.get_service_provider(provider["id"], SA))

    created = validate_success(api.create_settlement_period({
        "provider_id": provider["id"], "service_area_id": area["id"],
        "week_start_at": "2026-09-14T00:00:00Z", "is_peak_week": False,
        "fuel_rate_cents_per_mile": 3,
        "expected_provider_version": provider_now["version"]}, SA), 201)
    assert created["status"] == "OPEN"


# ═══════════════════════════════════════════════════════════════════════
# errors: step_van_refused_on_large_service_area
# ═══════════════════════════════════════════════════════════════════════

def test_step_van_refused_above_the_stop_capacity_ceiling(api):
    """PRD §2.7: "A `STEP_VAN` is refused on any service area whose
    `stop_capacity_weekly` exceeds the `STEP_VAN_STOP_CEILING` of 1500, while
    `BOX_TRUCK` and `TRACTOR_TRAILER` are accepted on every area without
    exception."

    Design: Corner/errors/step_van_refused_on_large_service_area
    """
    provider = create_provider()
    large_area = create_area(area_code="TR11", zip_low="372", zip_high="374",
                             stop_capacity=2000)
    get_success_data(api.approve_service_provider(provider["id"], AM))

    res = api.create_vehicle(create_vehicle_payload(
        provider["id"], large_area["id"], vehicle_class="STEP_VAN", gvwr_pounds=10000), AM)
    validate_error(res, "ERR_VEHICLE_INELIGIBLE", expected_status=422)


def test_step_van_accepted_at_exactly_the_ceiling_and_tractor_trailer_always(api):
    """PRD §2.7: "A `STEP_VAN` is refused on any service area whose
    `stop_capacity_weekly` exceeds the `STEP_VAN_STOP_CEILING` of 1500, while
    `BOX_TRUCK` and `TRACTOR_TRAILER` are accepted on every area without
    exception."

    Design: Corner/errors/step_van_refused_on_large_service_area
    """
    provider = create_provider()
    boundary_area = create_area(area_code="TR12", zip_low="375", zip_high="377",
                                stop_capacity=1500)
    large_area = create_area(area_code="TR13", zip_low="378", zip_high="380",
                             stop_capacity=2000)
    get_success_data(api.approve_service_provider(provider["id"], AM))

    at_ceiling = validate_success(api.create_vehicle(create_vehicle_payload(
        provider["id"], boundary_area["id"], vehicle_class="STEP_VAN", gvwr_pounds=10000), AM), 201)
    assert at_ceiling["status"] == "PENDING"
    tractor = validate_success(api.create_vehicle(create_vehicle_payload(
        provider["id"], large_area["id"], vehicle_class="TRACTOR_TRAILER", gvwr_pounds=80000), AM), 201)
    assert tractor["vehicle_class"] == "TRACTOR_TRAILER"


# ═══════════════════════════════════════════════════════════════════════
# errors: unqualified_driver_blocks_agreement_signature
# ═══════════════════════════════════════════════════════════════════════

def test_class_c_driver_blocks_the_agreement_signature(api):
    """PRD §3.3: "Before the signature is accepted, every driver whose
    `service_area_id` is the agreement's area must report `qualification_status`
    of `QUALIFIED`, and a single unqualified driver stops the signature with
    `ERR_DRIVER_NOT_QUALIFIED` (HTTP 422)."

    Design: Corner/errors/unqualified_driver_blocks_agreement_signature
    """
    from test_helpers import create_agreement_payload, setup_provider_compliance

    provider = create_provider()
    area = create_area()
    setup_provider_compliance(provider["id"], area["id"])
    agreement = get_success_data(api.create_agreement(
        create_agreement_payload(provider["id"], area["id"]), AM))
    get_success_data(api.submit_agreement(
        agreement["id"], make_service_provider_headers(provider["id"])))
    get_success_data(api.create_driver({
        "provider_id": provider["id"], "service_area_id": area["id"],
        "full_name": "Lee Novak", "license_class": "CLASS_C",
        "qualification_status": "UNQUALIFIED", "is_temporary": False}, AM))

    res = api.sign_agreement(agreement["id"], AM)
    validate_error(res, "ERR_DRIVER_NOT_QUALIFIED", expected_status=422)
    assert validate_success(api.get_agreement(agreement["id"], AM), 200)["status"] == "PENDING_REVIEW"


def test_signature_succeeds_with_a_qualified_roster(api):
    """PRD §3.3: "Before the signature is accepted, every driver whose
    `service_area_id` is the agreement's area must report `qualification_status`
    of `QUALIFIED`"
    PRD §3.3: "When both gates pass, the agreement becomes `ACTIVE`, and its
    `renewal_due_at` is stamped as the activation instant plus 365 days."

    Design: Corner/errors/unqualified_driver_blocks_agreement_signature
    """
    from test_helpers import create_agreement_payload, setup_provider_compliance

    provider = create_provider()
    area = create_area()
    setup_provider_compliance(provider["id"], area["id"])
    agreement = get_success_data(api.create_agreement(
        create_agreement_payload(provider["id"], area["id"]), AM))
    get_success_data(api.submit_agreement(
        agreement["id"], make_service_provider_headers(provider["id"])))

    signed = validate_success(api.sign_agreement(agreement["id"], AM), 200)
    assert signed["status"] == "ACTIVE"
    assert signed["renewal_due_at"] is not None


# ═══════════════════════════════════════════════════════════════════════
# errors: underinsured_provider_blocked_from_acquiring_title
# ═══════════════════════════════════════════════════════════════════════

def test_underinsured_provider_blocked_from_acquiring_title(api):
    """PRD §3.4: "the provider's auto liability coverage must clear the governing
    agreement's floor and must not be expired (`ERR_INSURANCE_INSUFFICIENT`,
    HTTP 422)."
    PRD §3.3: "every `AUTO_LIABILITY` policy of the provider must carry
    `coverage_cents` at or above the agreement's `insurance_coverage_cents` floor
    and must not have expired, or the signature stops with
    `ERR_INSURANCE_INSUFFICIENT` (HTTP 422)."

    The signature gate and the acquisition gate read the same floor, so a
    governing agreement can only ever be ACTIVE while the provider's coverage
    clears it. The acquisition gate is therefore reached with coverage that was
    adequate when the agreement was signed and has since lapsed past
    `expires_at`, which the identical §3.4 sentence forbids.

    Design: Corner/errors/underinsured_provider_blocked_from_acquiring_title
    """
    from test_helpers import create_agreement_payload, setup_provider_compliance

    provider = create_provider()
    area = create_area()
    setup_provider_compliance(provider["id"], area["id"], coverage_cents=1000000,
                              expires_at="2026-09-05T00:00:00Z")
    agreement = get_success_data(api.create_agreement(create_agreement_payload(
        provider["id"], area["id"], insurance_coverage_cents=1000000), AM))
    get_success_data(api.submit_agreement(
        agreement["id"], make_service_provider_headers(provider["id"])))
    get_success_data(api.sign_agreement(agreement["id"], AM))
    # The logical clock moves past the certificate's expires_at instant.
    get_success_data(api.set_current_utc("2026-10-01T00:00:00Z", PA))
    area_now = get_success_data(api.get_service_area(area["id"], AM))

    res = api.create_route_assignment(create_route_assignment_payload(
        area["id"], provider["id"], area_now["version"]), AM)
    validate_error(res, "ERR_INSURANCE_INSUFFICIENT", expected_status=422)


def test_matching_coverage_permits_title_acquisition(api):
    """PRD §3.4: "the provider's auto liability coverage must clear the governing
    agreement's floor and must not be expired"
    PRD §3.4: "A new title begins in `DRAFT`, and the create advances the area's
    `version` by one."

    Design: Corner/errors/underinsured_provider_blocked_from_acquiring_title
    """
    from test_helpers import create_agreement_payload, setup_provider_compliance

    provider = create_provider()
    area = create_area()
    setup_provider_compliance(provider["id"], area["id"], coverage_cents=1000000)
    agreement = get_success_data(api.create_agreement(create_agreement_payload(
        provider["id"], area["id"], insurance_coverage_cents=500000), AM))
    get_success_data(api.submit_agreement(
        agreement["id"], make_service_provider_headers(provider["id"])))
    get_success_data(api.sign_agreement(agreement["id"], AM))
    area_now = get_success_data(api.get_service_area(area["id"], AM))

    created = validate_success(api.create_route_assignment(
        create_route_assignment_payload(area["id"], provider["id"], area_now["version"]), AM), 201)
    assert created["status"] == "DRAFT"


# ═══════════════════════════════════════════════════════════════════════
# errors: deductions_above_cap_require_over_cap_flag
# ═══════════════════════════════════════════════════════════════════════

def _accrual_closed_week_with_capped_segments():
    ctx = setup_active_provider()
    period = open_week(ctx["provider"]["id"], ctx["area"]["id"])
    fx.add_observation(period["id"], stops_count=300, packages_count=250,
                       accessorial_cents=2000)
    fx.add_deduction(period["id"], "MAINTENANCE", 40000, performance_factor_eligible=True)
    fx.add_deduction(period["id"], "ACCESSORIAL", 20000, performance_factor_eligible=True)
    set_clock(CLOCK_PAST_WEEK)
    validate_success(api_client.close_accrual(period["id"], SA), 200)
    return ctx, period


def test_reconcile_refused_when_capped_segments_exceed_the_cap(api):
    """PRD §3.8: "Priority 26 of the global rule set states that when the summed
    non-`CHARGEBACK` deduction segments exceed the cap of 50000 cents, the
    reconcile is refused with `ERR_DEDUCTION_CAP_EXCEEDED` (HTTP 422) — unless the
    reconcile request sets `allow_over_cap` to true, in which case the cap is
    bypassed."

    Design: Corner/errors/deductions_above_cap_require_over_cap_flag
    """
    _ctx, period = _accrual_closed_week_with_capped_segments()
    res = api.reconcile_period(period["id"], {"deduction_order": "MAINTENANCE_FIRST"}, SA)
    validate_error(res, "ERR_DEDUCTION_CAP_EXCEEDED", expected_status=422)
    assert validate_success(api.get_settlement_period(period["id"], SA), 200)["status"] == "ACCRUAL_CLOSED"


def test_over_cap_flag_allows_reconcile_and_waterfall_still_caps(api):
    """PRD §3.8: "In the ordinary order, `MAINTENANCE` is filled to its full
    requested amount before any `ACCESSORIAL` cents are allocated, so a week
    carrying both segments large enough to straddle the cap loses all of its
    `ACCESSORIAL` allocation first — this is the maintenance-first reading."

    Design: Corner/errors/deductions_above_cap_require_over_cap_flag
    """
    _ctx, period = _accrual_closed_week_with_capped_segments()
    reconciled = validate_success(api.reconcile_period(
        period["id"], {"deduction_order": "MAINTENANCE_FIRST", "allow_over_cap": True}, SA), 200)
    assert reconciled["status"] == "RECONCILED"

    summary = validate_success(api.get_period_summary(period["id"], SA), 200)
    assert summary["capped_deduction_cents"] == 50000


# ═══════════════════════════════════════════════════════════════════════
# errors: dispute_filed_outside_window_refused
# ═══════════════════════════════════════════════════════════════════════

def test_dispute_filed_at_the_window_deadline_is_refused(api):
    """PRD §3.11: "it may only be filed while the logical clock is still inside
    the filing window — strictly before `week_start_at` plus seven days plus 90
    days. A filing at or after that instant is refused with
    `ERR_DISPUTE_WINDOW_EXPIRED` (HTTP 422)."

    Design: Corner/errors/dispute_filed_outside_window_refused
    """
    ctx = setup_reconciled_week()
    get_success_data(api.set_current_utc("2026-12-14T00:00:00Z", PA))
    res = api.dispute_period(ctx["period"]["id"],
                             {"reason_code": "DEDUCTION", "disputed_amount_cents": 3000},
                             make_service_provider_headers(ctx["provider"]["id"]))
    validate_error(res, "ERR_DISPUTE_WINDOW_EXPIRED", expected_status=422)


def test_dispute_filed_one_day_inside_the_window_is_accepted(api):
    """PRD §3.11: "it may only be filed while the logical clock is still inside
    the filing window — strictly before `week_start_at` plus seven days plus 90
    days."
    PRD §3.11: "It is born in `OPEN`, its `opened_at` is the current logical
    instant, its `expires_at` is that instant plus 90 days"

    The settled week opens at week_start_at 2026-09-07, so the filing window runs
    to strictly before 2026-09-07 + 7 + 90 days = 2026-12-13.

    Design: Corner/errors/dispute_filed_outside_window_refused
    """
    ctx = setup_reconciled_week()
    get_success_data(api.set_current_utc("2026-12-12T00:00:00Z", PA))
    dispute = validate_success(api.dispute_period(
        ctx["period"]["id"],
        {"reason_code": "DEDUCTION", "disputed_amount_cents": 3000},
        make_service_provider_headers(ctx["provider"]["id"])), 201)
    assert dispute["status"] == "OPEN"
    assert dispute["opened_at"] == "2026-12-12T00:00:00.000Z"
    assert dispute["expires_at"] == "2027-03-12T00:00:00.000Z"


# ═══════════════════════════════════════════════════════════════════════
# errors: chargeback_outstanding_blocks_route_transfer
# ═══════════════════════════════════════════════════════════════════════

def test_chargeback_outstanding_blocks_a_route_transfer(api):
    """PRD §3.5: "First, the transferring provider's `chargeback_outstanding_cents`
    must be exactly zero; a provider carrying any unsettled charge-back balance
    may not move a route title at all, and the refusal is
    `ERR_CHARGEBACK_OUTSTANDING` (HTTP 422)."

    Design: Corner/errors/chargeback_outstanding_blocks_route_transfer
    """
    from test_helpers import setup_two_approved_providers

    ctx = setup_two_approved_providers()
    provider, area, asg, provider_b = ctx["provider"], ctx["area"], ctx["assignment"], ctx["provider_b"]
    from test_helpers import open_week
    period = open_week(provider["id"], area["id"])
    claim = get_success_data(api.create_chargeback_claim({
        "provider_id": provider["id"], "settlement_period_id": period["id"],
        "claim_type": "DAMAGE", "amount_cents": 20000, "recovery_rate_pct": 0}, AM))
    validate_success(api.approve_chargeback_claim(claim["id"], AM), 200)

    res = api.request_transfer(
        asg["id"], {"acquiring_provider_id": provider_b["id"], "transfer_price_cents": 4500000},
        make_service_provider_headers(provider["id"]))
    validate_error(res, "ERR_CHARGEBACK_OUTSTANDING", expected_status=422)


def test_chargeback_outstanding_zeros_only_after_release(api):
    """PRD §2.4: "it falls when a settlement week carrying charge-back segments
    is released."
    PRD §3.11: "Every `CHARGEBACK` deduction on the week reduces the provider's
    `chargeback_outstanding_cents` by its `amount_cents`"

    Design: Corner/errors/chargeback_outstanding_blocks_route_transfer
    """
    from test_helpers import setup_two_approved_providers

    ctx = setup_two_approved_providers()
    provider, area = ctx["provider"], ctx["area"]
    period = open_week(provider["id"], area["id"])
    fx.add_deduction(period["id"], "MAINTENANCE", 5000, performance_factor_eligible=True)
    set_clock(CLOCK_PAST_WEEK)
    validate_success(api.close_accrual(period["id"], SA), 200)
    validate_success(api.reconcile_period(period["id"], {}, SA), 200)
    claim = get_success_data(api.create_chargeback_claim({
        "provider_id": provider["id"], "settlement_period_id": period["id"],
        "claim_type": "DAMAGE", "amount_cents": 20000, "recovery_rate_pct": 0}, AM))
    validate_success(api.approve_chargeback_claim(claim["id"], AM), 200)
    assert validate_success(api.get_service_provider(provider["id"], SA), 200)[
        "chargeback_outstanding_cents"] == 20000

    validate_success(api.release_period(period["id"], AM), 200)
    assert validate_success(api.get_service_provider(provider["id"], SA), 200)[
        "chargeback_outstanding_cents"] == 0


# ═══════════════════════════════════════════════════════════════════════
# errors: path_id_not_found_family_rejections
# ═══════════════════════════════════════════════════════════════════════

def test_each_resource_family_reports_its_own_not_found_error(api):
    """PRD §2.9: "The identifier-to-error mapping is fixed: a provider path id
    that does not resolve yields `ERR_PROVIDER_NOT_FOUND`; a service area yields
    `ERR_SERVICE_AREA_NOT_FOUND`; an agreement yields `ERR_AGREEMENT_NOT_FOUND`;
    a settlement period yields `ERR_SETTLEMENT_PERIOD_NOT_FOUND`; a route
    assignment yields `ERR_ASSIGNMENT_NOT_FOUND`; a vehicle yields
    `ERR_VEHICLE_NOT_FOUND`; a driver yields `ERR_DRIVER_NOT_FOUND`; a charge-back
    claim yields `ERR_CHARGEBACK_CLAIM_NOT_FOUND`; a dispute yields
    `ERR_DISPUTE_NOT_FOUND`; and a peak-season declaration yields
    `ERR_PEAK_DECLARATION_NOT_FOUND`."

    Design: Corner/errors/path_id_not_found_family_rejections
    """
    missing = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
    validate_error(api.submit_agreement(missing, make_service_provider_headers(
        "9f8e7d6c-5b4a-4392-8170-6f5e4d3c2b1a")),
        "ERR_AGREEMENT_NOT_FOUND", expected_status=404)
    validate_error(api.close_accrual(missing, SA),
                   "ERR_SETTLEMENT_PERIOD_NOT_FOUND", expected_status=404)
    validate_error(api.activate_route_assignment(missing, AM),
                   "ERR_ASSIGNMENT_NOT_FOUND", expected_status=404)
    validate_error(api.activate_vehicle(missing, AM),
                   "ERR_VEHICLE_NOT_FOUND", expected_status=404)
    validate_error(api.suspend_driver(missing, CO),
                   "ERR_DRIVER_NOT_FOUND", expected_status=404)
    validate_error(api.approve_chargeback_claim(missing, AM),
                   "ERR_CHARGEBACK_CLAIM_NOT_FOUND", expected_status=404)
    validate_error(api.counter_dispute(missing, {"counter_amount_cents": 1000}, SA),
                   "ERR_DISPUTE_NOT_FOUND", expected_status=404)
    validate_error(api.activate_peak_declaration(missing, AM),
                   "ERR_PEAK_DECLARATION_NOT_FOUND", expected_status=404)
