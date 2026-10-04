"""Corner coverage — calculations, part 2 (PRD §3.4/§3.7 coverage windows,
§3.7 neglect score cap and proration cap, §3.8 completion-rate closure).

The runner restarts the server before every test, so each test builds its own
environment from an empty database through PRD-declared endpoints only.
"""
from test_helpers import (
    ApiErrorId,
    SUBMITTER_USER_ID,
    add_accepted_test_run,
    add_maintenance_record,
    add_spec_version,
    adjudicate,
    assert_claim_financials_balance,
    begin_family_testing,
    certify_family,
    complete_work_order,
    compute_completion_rate,
    compute_neglect_score,
    compute_partial_proration,
    create_family,
    create_published_standard,
    create_warranty_claim_payload,
    declare_campaign,
    fault_code,
    file_claim,
    get_family,
    ingest_snapshot,
    make_certification_engineer_headers,
    make_fleet_manager_headers,
    schedule_work_order,
    set_logical_clock,
    setup_engine_unit,
    setup_family_in_production,
    setup_fleet,
    setup_full_environment,
    setup_service_center,
    stamp_family_non_conforming,
    start_claim_review,
    start_work_order,
    validate_error,
    validate_success,
    verify_work_order,
)


def test_neglect_score_caps_at_100(api, officer_headers):
    """PRD §3.7: "Expected oil changes are the unit's `accumulated_miles` divided by the 15,000-mile maintenance interval, floored to a whole number; missed oil changes are that expectation minus the count of the unit's `OIL_CHANGE` records, and never less than zero. Each missed oil change contributes 25 points. Each `DEF_SERVICE` record with `def_quality_ok` set false contributes 15 points. Each telematics snapshot whose `fault_codes` contain at least one `CRITICAL` entry contributes 20 points. The score is the sum, capped at 100."
    PRD §3.7: "On `DENY_NEGLECT` the claim moves to `DENIED_NEGLECT` with `approved_amount_cents` set to 0 and `customer_share_cents` equal to the full `claimed_amount_cents`."

    The raw demerit sum is 375 (13 missed intervals x 25 + 2 bad DEF x 15 + 1
    critical snapshot x 20); the stamped neglect_score is exactly 100 — the
    cap binds, not the raw sum.

    Design: Corner/calculations/neglect_score_caps_at_100
    """
    standard = create_published_standard(
        code="HD-EXT-2031",
        useful_life_miles=500000, useful_life_hours=30000, useful_life_years=10,
        base_warranty_years=2, base_warranty_miles=500000,
        effective_model_year_first=2031, effective_model_year_last=2034,
    )
    family = create_family(
        standard["id"], family_code="Z9-2031", model_year=2031, displacement_liters=12.0,
    )
    add_spec_version(family, calibrate_overrides={"observed_def_consumption_g_per_kwh": 6.1})
    begin_family_testing(family["id"])
    for test_type in ("FTP", "RMC", "SET"):
        add_accepted_test_run(family["id"], test_type)
    validate_success(
        api.submit_review(family["id"], make_certification_engineer_headers(SUBMITTER_USER_ID))
    )
    certify_family(family["id"])
    validate_success(api.enter_production(family["id"], officer_headers))

    fleet = setup_fleet()
    network = setup_service_center(with_tool=False)
    unit = setup_engine_unit(family["id"], fleet["id"], serial_number="UN-CAP")
    ingest_snapshot(
        unit["id"],
        recorded_at="2026-11-10T00:00:00Z", odometer_miles=200000, engine_hours=2500,
        fault_codes=[fault_code("P2201", "CRITICAL")],
        def_consumption_gal=90.0, nox_sensor_drift_ppm=3,
    )
    add_maintenance_record(
        unit["id"], fleet_id=fleet["id"],
        performed_at="2026-11-11T00:00:00Z", maintenance_type="DEF_SERVICE",
        odometer_at_service=190000, def_quality_ok=False,
    )
    add_maintenance_record(
        unit["id"], fleet_id=fleet["id"],
        performed_at="2026-11-20T00:00:00Z", maintenance_type="DEF_SERVICE",
        odometer_at_service=195000, def_quality_ok=False,
    )

    set_logical_clock("2026-12-01T00:00:00Z")
    claim = file_claim(
        unit, network["center"],
        failed_component_class="ENGINE_BASE", failure_code="FC-cap",
        claimed_amount_cents=80000,
    )
    start_claim_review(claim["id"])
    decided = adjudicate(claim["id"], "DENY_NEGLECT")

    assert decided["neglect_score"] == compute_neglect_score(200000, 0, 2, 1) == 100, (
        f"the uncapped sum would be 375; the cap must bind at 100, got {decided['neglect_score']}"
    )
    assert decided["status"] == "DENIED_NEGLECT"
    assert decided["approved_amount_cents"] == 0
    assert decided["customer_share_cents"] == 80000
    assert_claim_financials_balance(decided)


def test_completion_rate_equality_with_custom_threshold_closes(api, officer_headers):
    """PRD §3.8: "A `RegulatoryOfficer` may move an `IN_PROGRESS` campaign to `COMPLETION_REVIEW`; the request recomputes the campaign's `completion_rate` — 0 while `notified_unit_count` is 0, otherwise the verified count divided by the notified count, rounded half-up to 4 decimal places — and, when `notified_unit_count` is greater than 0 and the rate is at least the campaign's `completion_threshold` (the boundary is inclusive), the campaign advances all the way to `CLOSED` within the same request."

    A campaign created with completion_threshold 0.5 closes at completion_rate
    exactly 0.5 (1 of 2 verified) — the >= comparison is boundary-inclusive
    against the per-campaign override — and the family exits the hold to
    IN_PRODUCTION.

    Design: Corner/calculations/completion_rate_equality_with_custom_threshold_closes
    """
    env = setup_full_environment()
    center_id = env["center"]["id"]
    unit_a = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-101")
    setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-102")
    stamp_family_non_conforming(env["family"]["id"], test_period_label="2027-MY-Q1")
    campaign = declare_campaign(
        env["family"]["id"], campaign_code="CMP-C8", completion_threshold=0.5,
    )
    validate_success(api.announce_campaign(campaign["id"], officer_headers))
    validate_success(api.begin_campaign_execution(campaign["id"], officer_headers))
    work_order = schedule_work_order(
        campaign["id"], unit_a["id"], center_id, env["technician"]["id"]
    )
    start_work_order(work_order["id"], center_id)
    complete_work_order(work_order["id"], center_id)
    verify_work_order(work_order["id"])

    closed = validate_success(api.campaign_completion_review(campaign["id"], officer_headers))
    assert closed["completion_rate"] == compute_completion_rate(1, 2) == 0.5, (
        f"1 verified of 2 notified, got {closed['completion_rate']}"
    )
    assert closed["status"] == "CLOSED", (
        f"0.5 >= 0.5 closes in the same request, got {closed['status']}"
    )
    family_now = get_family(env["family"]["id"])
    assert family_now["certification_status"] == "IN_PRODUCTION", (
        "production_entered is true, so the hold releases to IN_PRODUCTION, "
        f"got {family_now['certification_status']}"
    )


def test_coverage_miles_exactly_at_base_limit_expires(api):
    """PRD §3.7: "The base warranty window is open when the logical clock is strictly earlier than the unit's `in_service_date` plus the standard's `base_warranty_years` calendar years, and the unit's `accumulated_miles` is strictly less than the standard's `base_warranty_miles`; engine hours play no part in the base window."
    PRD §3.7: "Every window comparison is strict: a unit sitting exactly on a limit is not covered by that window."

    At 49999 accumulated miles the base window is open; at exactly 50000 (the
    limit) base_covered flips false while extended_covered (limit 100000)
    stays true — the two windows diverge on the same unit.

    Design: Corner/calculations/coverage_miles_exactly_at_base_limit_expires
    """
    env = setup_family_in_production()
    fleet = setup_fleet()
    unit = setup_engine_unit(env["family"]["id"], fleet["id"], serial_number="UN-101")
    ingest_snapshot(
        unit["id"],
        recorded_at="2026-11-15T00:00:00Z", odometer_miles=49999, engine_hours=400,
        fault_codes=[], def_consumption_gal=100.0, nox_sensor_drift_ppm=2,
    )
    set_logical_clock("2026-12-01T00:00:00Z")
    fleet_headers = make_fleet_manager_headers(fleet["id"])

    cov_49k = validate_success(api.get_unit_coverage(unit["id"], fleet_headers))
    assert cov_49k["base_covered"] is True, "49999 < 50000 keeps the base window open"
    assert cov_49k["extended_covered"] is True

    ingest_snapshot(
        unit["id"],
        recorded_at="2026-12-01T00:00:00Z", odometer_miles=50000, engine_hours=401,
        fault_codes=[], def_consumption_gal=1.0, nox_sensor_drift_ppm=2,
    )
    cov_50k = validate_success(api.get_unit_coverage(unit["id"], fleet_headers))
    assert cov_50k["base_covered"] is False, (
        "the mileage comparison is strict: exactly 50000 is not covered"
    )
    assert cov_50k["extended_covered"] is True, (
        "50000 < min(100000, 435000) and 401 < min(3000, 22000): the extended "
        "window stays open"
    )


def test_proration_customer_share_capped_at_fifty_percent(api):
    """PRD §3.7: "Under the `BASE_WARRANTY` variant the proration is time-based: the term in days is the standard's `base_warranty_years` multiplied by 365; the elapsed days are the whole days from the unit's `in_service_date` to the claim's submission instant, never negative; the daily rate is the `claimed_amount_cents` divided by the term in days, rounded half-up to whole cents; and the raw customer share is that rounded daily rate multiplied by the elapsed days."
    PRD §3.7: "Under both variants the share is then capped: the cap is half of `claimed_amount_cents` rounded half-up to whole cents, `customer_share_cents` is the smaller of the raw share and the cap, and `approved_amount_cents` is the remainder of the claim after the customer share."

    365 elapsed days at the 137-cent daily rate give a raw share of 50005, but
    the customer share is capped at round_half_up(100000 x 0.5) = 50000.

    Design: Corner/calculations/proration_customer_share_capped_at_fifty_percent
    """
    env = setup_full_environment()
    unit = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-101")
    ingest_snapshot(
        unit["id"],
        recorded_at="2026-10-15T00:00:00Z", odometer_miles=15000, engine_hours=400,
        fault_codes=[], def_consumption_gal=40.0, nox_sensor_drift_ppm=2,
    )
    add_maintenance_record(
        unit["id"], fleet_id=env["fleet"]["id"],
        performed_at="2026-10-20T00:00:00Z", maintenance_type="DEF_SERVICE",
        odometer_at_service=14000, def_quality_ok=False,
    )
    # 15000 // 15000 = 1 missed oil change (25) + one bad DEF (15) = 40 ->
    # the APPROVE_PARTIAL band [30, 60).
    set_logical_clock("2027-09-01T00:00:00Z")  # 365 whole days after in-service
    claim = file_claim(
        unit, env["center"],
        failed_component_class="ENGINE_BASE", failure_code="FC-cap2",
        claimed_amount_cents=100000,
    )
    assert claim["coverage_variant"] == "BASE_WARRANTY"
    start_claim_review(claim["id"])
    decided = adjudicate(claim["id"], "APPROVE_PARTIAL")

    expected_share, expected_approved = compute_partial_proration(
        "BASE_WARRANTY", 100000, base_warranty_years=2, elapsed_days=365,
    )
    assert (expected_share, expected_approved) == (50000, 50000)
    assert decided["neglect_score"] == 40
    assert decided["customer_share_cents"] == expected_share == 50000, (
        "the 50-percent cap binds over the raw 50005 (137 x 365), "
        f"got {decided['customer_share_cents']}"
    )
    assert decided["approved_amount_cents"] == expected_approved == 50000
    assert decided["status"] == "APPROVED_PARTIAL"
    assert_claim_financials_balance(decided)


def test_extended_window_capped_by_useful_life_definition(api, officer_headers):
    """PRD §3.7: "The extended emissions window uses per-axis minimums of program constants against the standard's useful-life obligations: the extended years term is the smaller of 5 years and the standard's `useful_life_years`, the extended mileage term is the smaller of 100,000 miles and the standard's `useful_life_miles`, and the extended hours term is the smaller of 3,000 hours and the standard's `useful_life_hours`."
    PRD §3.7: "When the extended window is open the claim is stamped `EXTENDED_EMISSIONS`; otherwise, when the base window is open, it is stamped `BASE_WARRANTY`; when neither window is open the filing is rejected with `ERR_COVERAGE_EXPIRED` (HTTP 409)."

    A standard with useful_life_miles 80000 caps extended coverage at 80000
    (not 100000): a DPF claim at 75000 miles stamps EXTENDED_EMISSIONS while
    the same claim at 85000 miles fails ERR_COVERAGE_EXPIRED.

    Design: Corner/calculations/extended_window_capped_by_useful_life_definition
    """
    standard = create_published_standard(
        code="UL-LOW-2031",
        useful_life_miles=80000, useful_life_hours=22000, useful_life_years=10,
        base_warranty_years=2, base_warranty_miles=50000,
        effective_model_year_first=2031, effective_model_year_last=2034,
    )
    family = create_family(
        standard["id"], family_code="UL-2031", model_year=2031, displacement_liters=12.0,
    )
    add_spec_version(family, calibrate_overrides={"observed_def_consumption_g_per_kwh": 6.1})
    begin_family_testing(family["id"])
    for test_type in ("FTP", "RMC", "SET"):
        add_accepted_test_run(family["id"], test_type)
    validate_success(
        api.submit_review(family["id"], make_certification_engineer_headers(SUBMITTER_USER_ID))
    )
    certify_family(family["id"])
    validate_success(api.enter_production(family["id"], officer_headers))

    fleet = setup_fleet()
    network = setup_service_center(with_tool=False)
    unit = setup_engine_unit(family["id"], fleet["id"], serial_number="UN-UL1")
    ingest_snapshot(
        unit["id"],
        recorded_at="2026-11-15T00:00:00Z", odometer_miles=75000, engine_hours=800,
        fault_codes=[], def_consumption_gal=150.0, nox_sensor_drift_ppm=2,
    )
    set_logical_clock("2026-12-01T00:00:00Z")

    claim = file_claim(
        unit, network["center"],
        failed_component_class="AFTERTREATMENT_DPF", failure_code="FC-dpf",
        claimed_amount_cents=60000,
    )
    assert claim["coverage_variant"] == "EXTENDED_EMISSIONS", (
        "base is closed at 75000 >= 50000, but 75000 < min(100000, 80000) = 80000 "
        f"keeps the extended window open, got {claim['coverage_variant']}"
    )

    ingest_snapshot(
        unit["id"],
        recorded_at="2026-12-01T01:00:00Z", odometer_miles=85000, engine_hours=900,
        fault_codes=[], def_consumption_gal=20.0, nox_sensor_drift_ppm=2,
    )
    refused = api.create_warranty_claim(
        create_warranty_claim_payload(
            engine_unit_id=unit["id"],
            service_center_id=network["center"]["id"],
            failed_component_class="AFTERTREATMENT_DPF",
            failure_code="FC-dpf2",
            claimed_amount_cents=60000,
        ),
        make_fleet_manager_headers(fleet["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_COVERAGE_EXPIRED)
