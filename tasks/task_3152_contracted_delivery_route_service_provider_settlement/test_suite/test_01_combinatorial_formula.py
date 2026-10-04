"""Tests translated from the depth Test Targeting Index (queue A) — rule
combinatorial_formula (depth reasoning: combinatorial_formula).

Each test reproduces an indexed scenario and asserts the indexed outcome.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    run_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

AM = TEST_USERS["account_manager_headers"]
SA = TEST_USERS["settlement_analyst_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ═══════════════════════════════════════════════════════════════════════
# Instance: tiered_stop_rate_cliff_boundary
# ═══════════════════════════════════════════════════════════════════════

_TIER_CLIFF_RECORD = {
    "setup_api_calls": [
        {"call": "POST /route-settlement/service-providers",
         "payload": {"legal_name": "Acme Route Services LLC", "tax_id": "27-1000001"},
         "as": "AccountManager", "captures": {"prov_a_id": "$.data.id"}},
        {"call": "POST /route-settlement/service-areas",
         "payload": {"area_code": "TR11", "state_code": "TN", "zip_prefix_low": "372",
                     "zip_prefix_high": "374", "stop_capacity_weekly": 1001},
         "as": "AccountManager", "captures": {"area_a1_id": "$.data.id"}},
        {"call": "POST /route-settlement/insurance-policies",
         "payload": {"provider_id": "${prov_a_id}", "policy_type": "AUTO_LIABILITY",
                     "coverage_cents": 1000000, "expires_at": "2027-01-01T00:00:00Z"},
         "as": "ServiceProvider", "as_user_id": "${prov_a_id}",
         "captures": {"pol_a_id": "$.data.id"}},
        {"call": "POST /route-settlement/insurance-policies/${pol_a_id}/verify",
         "payload": {}, "as": "ComplianceOfficer"},
        {"call": "POST /route-settlement/vehicles",
         "payload": {"provider_id": "${prov_a_id}", "service_area_id": "${area_a1_id}",
                     "vehicle_class": "BOX_TRUCK", "gvwr_pounds": 26000, "is_temporary": False},
         "as": "AccountManager", "captures": {"veh_a_id": "$.data.id"}},
        {"call": "POST /route-settlement/vehicles/${veh_a_id}/activate",
         "payload": {}, "as": "AccountManager"},
        {"call": "POST /route-settlement/drivers",
         "payload": {"provider_id": "${prov_a_id}", "service_area_id": "${area_a1_id}",
                     "full_name": "Dana Cruz", "license_class": "CLASS_B",
                     "qualification_status": "QUALIFIED", "is_temporary": False},
         "as": "AccountManager", "captures": {"drv_a_id": "$.data.id"}},
        {"call": "POST /route-settlement/drivers/${drv_a_id}/qualify",
         "payload": {"qualification_status": "QUALIFIED"}, "as": "ComplianceOfficer"},
        {"call": "POST /route-settlement/service-providers/${prov_a_id}/approve",
         "payload": {}, "as": "AccountManager"},
        {"call": "POST /route-settlement/agreements",
         "payload": {"provider_id": "${prov_a_id}", "service_area_id": "${area_a1_id}",
                     "base_rate_cents_per_stop": 22, "package_rate_cents": 8,
                     "peak_surcharge_cents": 150, "insurance_coverage_cents": 500000,
                     "negotiated_by": "am_001"},
         "as": "AccountManager", "captures": {"agr_a1_id": "$.data.id"}},
        {"call": "POST /route-settlement/agreements/${agr_a1_id}/submit",
         "payload": {}, "as": "ServiceProvider", "as_user_id": "${prov_a_id}"},
        {"call": "POST /route-settlement/agreements/${agr_a1_id}/sign",
         "payload": {}, "as": "AccountManager"},
        {"call": "GET /route-settlement/service-areas/${area_a1_id}",
         "payload": {}, "as": "AccountManager", "captures": {"area_a1_id_pre": "$.data.version"}},
        {"call": "POST /route-settlement/route-assignments",
         "payload": {"service_area_id": "${area_a1_id}", "provider_id": "${prov_a_id}",
                     "effective_date": "2026-09-03T00:00:00Z", "transfer_price_cents": 0,
                     "expected_service_area_version": "${area_a1_id_pre}"},
         "as": "AccountManager", "captures": {"asg_a1_id": "$.data.id"}},
        {"call": "POST /route-settlement/route-assignments/${asg_a1_id}/activate",
         "payload": {}, "as": "AccountManager"},
        {"call": "GET /route-settlement/service-providers/${prov_a_id}",
         "payload": {}, "as": "AccountManager", "captures": {"prov_a1_id_pre": "$.data.version"}},
        {"call": "POST /route-settlement/settlement-periods",
         "payload": {"provider_id": "${prov_a_id}", "service_area_id": "${area_a1_id}",
                     "week_start_at": "2026-09-07T00:00:00Z", "is_peak_week": False,
                     "fuel_rate_cents_per_mile": 3,
                     "expected_provider_version": "${prov_a1_id_pre}"},
         "as": "SettlementAnalyst", "captures": {"per_w1_id": "$.data.id"}},
        {"call": "POST /route-settlement/settlement-periods/${per_w1_id}/stop-observations",
         "payload": {"observed_date": "2026-09-08T00:00:00Z",
                     "recorded_at": "2026-09-08T18:00:00Z", "stops_count": 1000,
                     "packages_count": 800, "miles_driven": 0, "accessorial_cents": 0},
         "as": "SettlementAnalyst"},
        {"call": "POST /route-settlement/settlement-periods/${per_w1_id}/deductions",
         "payload": {"deduction_type": "MAINTENANCE", "amount_cents": 20000,
                     "performance_factor_eligible": True},
         "as": "SettlementAnalyst"},
        {"call": "POST /route-settlement/settlement-periods/${per_w1_id}/deductions",
         "payload": {"deduction_type": "ACCESSORIAL", "amount_cents": 34000,
                     "performance_factor_eligible": True},
         "as": "SettlementAnalyst"},
        {"call": "POST /route-settlement/_clock/set_current_utc",
         "payload": {"to_iso8601": "2026-09-15T00:00:00Z"}, "as": "PlatformAdmin"},
    ],
    "trigger": [
        {"call": "POST /route-settlement/settlement-periods/${per_w1_id}/close-accrual",
         "payload": {}, "as": "SettlementAnalyst", "captures": {"w1": "$.data"}},
    ],
}


def test_stop_tier_cliff_at_1000_stops_closes_on_1001_capacity(api):
    """PRD §3.7: "When the capped stop count is 1000 or fewer, the tier rate
    equals the agreement's `base_rate_cents_per_stop`."
    PRD §3.7: "The stop gross is then the capped stop count multiplied by the
    tier rate."
    PRD §3.7: "The close enforces the capacity boundary — the week's summed
    `stops_count` may not exceed the governing area's `stop_capacity_weekly`"

    Design: Difficulty/combinatorial_formula/tiered_stop_rate_cliff_boundary
    """
    captures, trigger = run_scenario(_TIER_CLIFF_RECORD)
    period = validate_success(trigger[0][1], 200)
    # 1000 stops x 22 + 800 packages x 8 = 22000 + 6400 = 28400 base gross.
    assert period["base_gross_cents"] == 28400
    summary = validate_success(
        api.get_period_summary(captures["per_w1_id"], SA), 200)
    assert summary["stops_gross_cents"] == 22000


def test_stop_tier_cliff_applies_rate_to_all_stops_at_1001(api):
    """PRD §3.7: "When it is between 1001 and 2500 inclusive, the tier rate
    equals the base rate plus the tier increment of 3 cents."
    PRD §3.7: "Once the high tier is reached, that single tier rate applies to
    *every* stop in the week, not merely to the stops above the boundary; this
    is a cliff, and it is the pinned reading."
    PRD §3.7: "The close enforces the capacity boundary — the week's summed
    `stops_count` may not exceed the governing area's `stop_capacity_weekly`"

    Design: Difficulty/combinatorial_formula/tiered_stop_rate_cliff_boundary
    """
    import test_helpers.fixtures as fx
    from test_helpers import (
        create_area, create_provider, create_route_assignment_payload,
        draft_and_sign_agreement, get_success_data, open_week,
        setup_provider_compliance, set_clock, CLOCK_PAST_WEEK,
    )

    provider = create_provider()
    area = create_area(stop_capacity=1001)
    setup_provider_compliance(provider["id"], area["id"])
    draft_and_sign_agreement(provider["id"], area["id"])
    area_now = get_success_data(api.get_service_area(area["id"], AM))
    assignment = get_success_data(api.create_route_assignment(
        create_route_assignment_payload(area["id"], provider["id"], area_now["version"]), AM))
    get_success_data(api.activate_route_assignment(assignment["id"], AM))
    period = open_week(provider["id"], area["id"])
    fx.add_observation(period["id"], stops_count=1000, packages_count=0,
                       accessorial_cents=0)
    fx.add_observation(period["id"], observed_date="2026-09-09T00:00:00Z",
                       recorded_at="2026-09-09T18:00:00Z", stops_count=1,
                       packages_count=0, accessorial_cents=0)
    set_clock(CLOCK_PAST_WEEK)
    closed = get_success_data(api.close_accrual(period["id"], SA))
    assert closed["status"] == "ACCRUAL_CLOSED"
    summary = validate_success(api.get_period_summary(period["id"], SA), 200)
    # 1001 stops sit in the 1001..2500 tier at 22 + 3 = 25 cents per stop,
    # applied to every stop — 25025 rather than the 22000 the lower tier yields.
    assert summary["stops_gross_cents"] == 25025

# ═══════════════════════════════════════════════════════════════════════
# Instance: stop_tier_and_capacity_boundaries
# ═══════════════════════════════════════════════════════════════════════

_CAPACITY_RECORD = {
    "setup_api_calls": [
        {"call": "POST /route-settlement/service-providers",
         "payload": {"legal_name": "Acme Route Services LLC", "tax_id": "27-1000001"},
         "as": "AccountManager", "captures": {"prov_a_id": "$.data.id"}},
        {"call": "POST /route-settlement/service-areas",
         "payload": {"area_code": "TR11", "state_code": "TN", "zip_prefix_low": "372",
                     "zip_prefix_high": "374", "stop_capacity_weekly": 2000},
         "as": "AccountManager", "captures": {"area_a1_id": "$.data.id"}},
        {"call": "POST /route-settlement/insurance-policies",
         "payload": {"provider_id": "${prov_a_id}", "policy_type": "AUTO_LIABILITY",
                     "coverage_cents": 1000000, "expires_at": "2027-01-01T00:00:00Z"},
         "as": "ServiceProvider", "as_user_id": "${prov_a_id}",
         "captures": {"pol_a_id": "$.data.id"}},
        {"call": "POST /route-settlement/insurance-policies/${pol_a_id}/verify",
         "payload": {}, "as": "ComplianceOfficer"},
        {"call": "POST /route-settlement/vehicles",
         "payload": {"provider_id": "${prov_a_id}", "service_area_id": "${area_a1_id}",
                     "vehicle_class": "BOX_TRUCK", "gvwr_pounds": 26000, "is_temporary": False},
         "as": "AccountManager", "captures": {"veh_a_id": "$.data.id"}},
        {"call": "POST /route-settlement/vehicles/${veh_a_id}/activate",
         "payload": {}, "as": "AccountManager"},
        {"call": "POST /route-settlement/drivers",
         "payload": {"provider_id": "${prov_a_id}", "service_area_id": "${area_a1_id}",
                     "full_name": "Dana Cruz", "license_class": "CLASS_B",
                     "qualification_status": "QUALIFIED", "is_temporary": False},
         "as": "AccountManager", "captures": {"drv_a_id": "$.data.id"}},
        {"call": "POST /route-settlement/drivers/${drv_a_id}/qualify",
         "payload": {"qualification_status": "QUALIFIED"}, "as": "ComplianceOfficer"},
        {"call": "POST /route-settlement/service-providers/${prov_a_id}/approve",
         "payload": {}, "as": "AccountManager"},
        {"call": "POST /route-settlement/agreements",
         "payload": {"provider_id": "${prov_a_id}", "service_area_id": "${area_a1_id}",
                     "base_rate_cents_per_stop": 22, "package_rate_cents": 8,
                     "peak_surcharge_cents": 150, "insurance_coverage_cents": 500000,
                     "negotiated_by": "am_001"},
         "as": "AccountManager", "captures": {"agr_a1_id": "$.data.id"}},
        {"call": "POST /route-settlement/agreements/${agr_a1_id}/submit",
         "payload": {}, "as": "ServiceProvider", "as_user_id": "${prov_a_id}"},
        {"call": "POST /route-settlement/agreements/${agr_a1_id}/sign",
         "payload": {}, "as": "AccountManager"},
        {"call": "GET /route-settlement/service-areas/${area_a1_id}",
         "payload": {}, "as": "AccountManager", "captures": {"area_occ_v": "$.data.version"}},
        {"call": "POST /route-settlement/route-assignments",
         "payload": {"service_area_id": "${area_a1_id}", "provider_id": "${prov_a_id}",
                     "effective_date": "2026-09-03T00:00:00Z", "transfer_price_cents": 0,
                     "expected_service_area_version": "${area_occ_v}"},
         "as": "AccountManager", "captures": {"asg_a1_id": "$.data.id"}},
        {"call": "POST /route-settlement/route-assignments/${asg_a1_id}/activate",
         "payload": {}, "as": "AccountManager"},
        {"call": "GET /route-settlement/service-providers/${prov_a_id}",
         "payload": {}, "as": "SettlementAnalyst", "captures": {"prov_pre": "$.data.version"}},
        {"call": "POST /route-settlement/settlement-periods",
         "payload": {"provider_id": "${prov_a_id}", "service_area_id": "${area_a1_id}",
                     "week_start_at": "2026-09-07T00:00:00Z", "is_peak_week": False,
                     "fuel_rate_cents_per_mile": 3, "expected_provider_version": "${prov_pre}"},
         "as": "SettlementAnalyst", "captures": {"per_w1_id": "$.data.id"}},
        {"call": "POST /route-settlement/settlement-periods/${per_w1_id}/stop-observations",
         "payload": {"observed_date": "2026-09-08T00:00:00Z",
                     "recorded_at": "2026-09-08T18:00:00Z", "stops_count": 1000,
                     "packages_count": 0, "miles_driven": 0, "accessorial_cents": 0},
         "as": "SettlementAnalyst"},
        {"call": "POST /route-settlement/settlement-periods/${per_w1_id}/stop-observations",
         "payload": {"observed_date": "2026-09-09T00:00:00Z",
                     "recorded_at": "2026-09-09T18:00:00Z", "stops_count": 1000,
                     "packages_count": 0, "miles_driven": 0, "accessorial_cents": 0},
         "as": "SettlementAnalyst"},
        {"call": "POST /route-settlement/settlement-periods/${per_w1_id}/stop-observations",
         "payload": {"observed_date": "2026-09-10T00:00:00Z",
                     "recorded_at": "2026-09-10T18:00:00Z", "stops_count": 1,
                     "packages_count": 0, "miles_driven": 0, "accessorial_cents": 0},
         "as": "SettlementAnalyst"},
        {"call": "POST /route-settlement/_clock/set_current_utc",
         "payload": {"to_iso8601": "2026-09-15T00:00:00Z"}, "as": "PlatformAdmin"},
    ],
    "trigger": [
        {"call": "POST /route-settlement/settlement-periods/${per_w1_id}/close-accrual",
         "payload": {}, "as": "SettlementAnalyst", "captures": {"err_cap": "$.data.error_id"}},
    ],
}


def test_weekly_stops_above_capacity_refused_at_close(api):
    """PRD §3.7: "A week whose frozen stops exceed capacity is refused with
    `ERR_STOP_CAPACITY_EXCEEDED` (HTTP 422)."
    PRD §3.7: "The close enforces the capacity boundary — the week's summed
    `stops_count` may not exceed the governing area's `stop_capacity_weekly`"

    Design: Difficulty/boundary_precision_check/stop_tier_and_capacity_boundaries
    """
    captures, trigger = run_scenario(_CAPACITY_RECORD)
    err = validate_error(trigger[0][1], "ERR_STOP_CAPACITY_EXCEEDED", expected_status=422)
    assert err["error_id"] == "ERR_STOP_CAPACITY_EXCEEDED"


def test_weekly_stops_exactly_at_capacity_close_succeeds(api):
    """PRD §3.7: "the week's summed `stops_count` may not exceed the governing
    area's `stop_capacity_weekly`"
    PRD §3.7: "When the capped stop count is 1000 or fewer, the tier rate
    equals the agreement's `base_rate_cents_per_stop`."

    Design: Difficulty/boundary_precision_check/stop_tier_and_capacity_boundaries
    """
    from test_helpers import (
        CLOCK_PAST_WEEK, create_area, create_provider, create_route_assignment_payload,
        draft_and_sign_agreement, get_success_data, open_week,
        setup_provider_compliance, set_clock,
    )
    import test_helpers.fixtures as fx

    provider = create_provider()
    area = create_area(stop_capacity=2000)
    setup_provider_compliance(provider["id"], area["id"])
    draft_and_sign_agreement(provider["id"], area["id"])
    area_now = get_success_data(api.get_service_area(area["id"], AM))
    assignment = get_success_data(api.create_route_assignment(
        create_route_assignment_payload(area["id"], provider["id"], area_now["version"]), AM))
    get_success_data(api.activate_route_assignment(assignment["id"], AM))
    period = open_week(provider["id"], area["id"])
    fx.add_observation(period["id"], stops_count=1000, packages_count=0, accessorial_cents=0)
    fx.add_observation(period["id"], recorded_at="2026-09-09T18:00:00Z",
                       observed_date="2026-09-09T00:00:00Z", stops_count=1000,
                       packages_count=0, accessorial_cents=0)
    set_clock(CLOCK_PAST_WEEK)
    closed = get_success_data(api.close_accrual(period["id"], SA))
    assert closed["status"] == "ACCRUAL_CLOSED"
    summary = validate_success(api.get_period_summary(period["id"], SA), 200)
    # 2000 stops sit in the 1001..2500 tier at 22 + 3 = 25 cents per stop.
    assert summary["stops_gross_cents"] == 50000


# ═══════════════════════════════════════════════════════════════════════
# Instance: late_accrual_recut_evaluation_order
# ═══════════════════════════════════════════════════════════════════════

def test_peak_surcharge_and_tier_evaluation_order(api):
    """PRD §3.7: "The peak gross is the total stops across the week multiplied
    by the agreement's `peak_surcharge_cents`, but only when the week is flagged
    `is_peak_week`; otherwise the peak gross is exactly zero."
    PRD §3.7: "The week's `base_gross_cents` is the sum of the stop gross, the
    package gross, the peak gross and the accessorial gross."

    Design: Difficulty/combinatorial_formula/late_accrual_recut_evaluation_order
    """
    from test_helpers import (
        CLOCK_PAST_WEEK, create_area, create_provider, create_route_assignment_payload,
        draft_and_sign_agreement, get_success_data, open_week,
        setup_provider_compliance, set_clock,
    )
    import test_helpers.fixtures as fx

    provider = create_provider(legal_name="Brightway Ground Contractors Inc", tax_id="27-1000002")
    area = create_area(area_code="TR12", state_code="GA", zip_low="300", zip_high="302",
                       stop_capacity=1200)
    setup_provider_compliance(provider["id"], area["id"])
    draft_and_sign_agreement(provider["id"], area["id"])
    area_now = get_success_data(api.get_service_area(area["id"], AM))
    assignment = get_success_data(api.create_route_assignment(
        create_route_assignment_payload(area["id"], provider["id"], area_now["version"]), AM))
    get_success_data(api.activate_route_assignment(assignment["id"], AM))
    period = open_week(provider["id"], area["id"], week_start="2026-09-14T00:00:00Z",
                       is_peak_week=True)
    fx.add_observation(period["id"], observed_date="2026-09-15T00:00:00Z",
                       recorded_at="2026-09-16T18:00:00Z", stops_count=300,
                       packages_count=250, accessorial_cents=2000)
    set_clock("2026-09-22T00:00:00Z")
    closed = get_success_data(api.close_accrual(period["id"], SA))
    assert closed["status"] == "ACCRUAL_CLOSED"
    summary = validate_success(api.get_period_summary(period["id"], SA), 200)
    # stops gross 300 x 22 = 6600, packages 250 x 8 = 2000, peak 300 x 150 = 45000,
    # accessorial 2000 -> base gross 55600.
    assert summary["stops_gross_cents"] == 6600
    assert summary["peak_gross_cents"] == 45000
    assert summary["base_gross_cents"] == 55600


def test_non_peak_week_contributes_zero_peak_gross(api):
    """PRD §3.7: "The peak gross is the total stops across the week multiplied
    by the agreement's `peak_surcharge_cents`, but only when the week is flagged
    `is_peak_week`; otherwise the peak gross is exactly zero."

    Design: Difficulty/combinatorial_formula/late_accrual_recut_evaluation_order
    """
    from test_helpers import (
        CLOCK_PAST_WEEK, create_area, create_provider, create_route_assignment_payload,
        draft_and_sign_agreement, get_success_data, open_week,
        setup_provider_compliance, set_clock,
    )
    import test_helpers.fixtures as fx

    provider = create_provider(legal_name="Brightway Ground Contractors Inc", tax_id="27-1000002")
    area = create_area(area_code="TR12", state_code="GA", zip_low="300", zip_high="302",
                       stop_capacity=1200)
    setup_provider_compliance(provider["id"], area["id"])
    draft_and_sign_agreement(provider["id"], area["id"])
    area_now = get_success_data(api.get_service_area(area["id"], AM))
    assignment = get_success_data(api.create_route_assignment(
        create_route_assignment_payload(area["id"], provider["id"], area_now["version"]), AM))
    get_success_data(api.activate_route_assignment(assignment["id"], AM))
    period = open_week(provider["id"], area["id"], week_start="2026-09-14T00:00:00Z",
                       is_peak_week=False)
    fx.add_observation(period["id"], observed_date="2026-09-15T00:00:00Z",
                       recorded_at="2026-09-16T18:00:00Z", stops_count=300,
                       packages_count=250, accessorial_cents=2000)
    set_clock("2026-09-22T00:00:00Z")
    get_success_data(api.close_accrual(period["id"], SA))
    summary = validate_success(api.get_period_summary(period["id"], SA), 200)
    assert summary["peak_gross_cents"] == 0
    assert summary["base_gross_cents"] == 10600


# ═══════════════════════════════════════════════════════════════════════
# Instance: nonexistent_area_precedes_occupied_area
# ═══════════════════════════════════════════════════════════════════════

def test_nonexistent_area_reference_beats_occupied_area(api):
    """PRD §3.4: "a request that fails more than one gate must surface the
    earlier one."
    PRD §2.9: "The first identifier in the path that does not resolve to a row
    terminates the request immediately with the `404` error belonging to that
    resource type, before any later identifier is even read."

    Design: Difficulty/priority_pair_validation_conflict/nonexistent_area_precedes_occupied_area
    """
    from test_helpers import (
        create_area, create_provider, create_route_assignment_payload,
        draft_and_sign_agreement, get_success_data, setup_provider_compliance,
    )

    provider = create_provider()
    area = create_area()
    setup_provider_compliance(provider["id"], area["id"])
    draft_and_sign_agreement(provider["id"], area["id"])
    area_now = get_success_data(api.get_service_area(area["id"], AM))
    assignment = get_success_data(api.create_route_assignment(
        create_route_assignment_payload(area["id"], provider["id"], area_now["version"]), AM))
    get_success_data(api.activate_route_assignment(assignment["id"], AM))

    res = api.create_route_assignment({
        "service_area_id": "00000000-0000-4000-8000-000000000999",
        "provider_id": provider["id"],
        "effective_date": "2026-09-03T00:00:00Z",
        "transfer_price_cents": 0,
        "expected_service_area_version": area_now["version"],
    }, AM)
    validate_error(res, "ERR_SERVICE_AREA_NOT_FOUND", expected_status=404)


def test_failed_area_reference_creates_no_title(api):
    """PRD §3.4: "the named provider must resolve (`ERR_PROVIDER_NOT_FOUND`,
    HTTP 404) and the named area must resolve (`ERR_SERVICE_AREA_NOT_FOUND`,
    HTTP 404)"

    Design: Difficulty/priority_pair_validation_conflict/nonexistent_area_precedes_occupied_area
    """
    from test_helpers import (
        create_area, create_provider, create_route_assignment_payload,
        draft_and_sign_agreement, get_success_data, setup_provider_compliance,
    )

    provider = create_provider()
    area = create_area()
    setup_provider_compliance(provider["id"], area["id"])
    draft_and_sign_agreement(provider["id"], area["id"])
    area_now = get_success_data(api.get_service_area(area["id"], AM))
    assignment = get_success_data(api.create_route_assignment(
        create_route_assignment_payload(area["id"], provider["id"], area_now["version"]), AM))
    get_success_data(api.activate_route_assignment(assignment["id"], AM))

    api.create_route_assignment({
        "service_area_id": "00000000-0000-4000-8000-000000000999",
        "provider_id": provider["id"],
        "effective_date": "2026-09-03T00:00:00Z",
        "transfer_price_cents": 0,
        "expected_service_area_version": area_now["version"],
    }, AM)

    data, meta = validate_paginated(api.list_area_route_assignments(area["id"], AM))
    assert meta["total_count"] == 1


# ═══════════════════════════════════════════════════════════════════════
# Instance: terminal_agreement_precedes_branding_gate
# ═══════════════════════════════════════════════════════════════════════

def test_terminating_a_renegotiating_agreement_closes_its_draft_titles(api):
    """PRD §3.3: "Terminating an agreement in `RE_NEGOTIATION` closes only its
    draft titles: every `RouteAssignment` on the agreement's area that is still
    in `DRAFT` is set to `TERMINATED`."
    PRD §2.9: "any request against a resource that has already reached a
    terminal state is refused with `ERR_ALREADY_TERMINAL` (HTTP 409)", and "the
    already-terminal check is evaluated before the legality check".

    Design: Difficulty/priority_pair_validation_conflict/terminal_agreement_precedes_branding_gate
    """
    from test_helpers import (
        create_area, create_provider, create_route_assignment_payload,
        get_success_data, make_service_provider_headers, setup_provider_compliance,
    )
    from test_helpers.factories import create_agreement_payload

    provider = create_provider()
    area = create_area()
    _, vehicle, _ = setup_provider_compliance(provider["id"], area["id"])
    agreement = get_success_data(api.create_agreement(
        create_agreement_payload(provider["id"], area["id"]), AM))
    get_success_data(api.submit_agreement(
        agreement["id"], make_service_provider_headers(provider["id"])))
    get_success_data(api.renegotiate_agreement(agreement["id"], AM))
    area_now = get_success_data(api.get_service_area(area["id"], AM))
    assignment = get_success_data(api.create_route_assignment(
        create_route_assignment_payload(area["id"], provider["id"], area_now["version"]), AM))

    terminated = validate_success(api.terminate_agreement(agreement["id"], AM), 200)
    assert terminated["status"] == "TERMINATED"
    # The cascade closes the draft title, which is then terminal for any later
    # request regardless of the branding gate the activation would also fail.
    closed = validate_success(api.get_route_assignment(assignment["id"], AM), 200)
    assert closed["status"] == "TERMINATED"

    res = api.activate_route_assignment(assignment["id"], AM)
    validate_error(res, "ERR_ALREADY_TERMINAL", expected_status=409)


def test_branding_noninspection_lowers_provider_percentage(api):
    """PRD §3.1: "the percentage is the count of active-fleet vehicles whose
    `branding_compliance` is `PASSED`, divided by the total count of the active
    fleet, multiplied by one hundred, and rounded half up to two decimal places."

    Design: Difficulty/priority_pair_validation_conflict/terminal_agreement_precedes_branding_gate
    """
    from test_helpers import (
        create_area, create_provider, create_route_assignment_payload,
        get_success_data, make_service_provider_headers as _mk_sp_headers,
        setup_provider_compliance,
    )
    from test_helpers.factories import create_agreement_payload

    provider = create_provider()
    area = create_area()
    _, vehicle, _ = setup_provider_compliance(provider["id"], area["id"])
    agreement = get_success_data(api.create_agreement(
        create_agreement_payload(provider["id"], area["id"]), AM))
    get_success_data(api.submit_agreement(
        agreement["id"], _mk_sp_headers(provider["id"])))
    get_success_data(api.renegotiate_agreement(agreement["id"], AM))
    area_now = get_success_data(api.get_service_area(area["id"], AM))
    get_success_data(api.create_route_assignment(
        create_route_assignment_payload(area["id"], provider["id"], area_now["version"]), AM))
    get_success_data(api.branding_check(vehicle["id"], {"branding_compliance": "FAILED"}, CO))

    provider_now = validate_success(api.get_service_provider(provider["id"], AM), 200)
    assert provider_now["brand_compliance_pct"] == 0.00
