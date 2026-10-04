"""Priority-pair validation conflict tests (PRD §2.8 fixed evaluation order:
state gate vs temporal coverage gate, qualification gate vs capacity gate).

The runner restarts the server before every test, so each test builds its own
environment from an empty database through PRD-declared endpoints only.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_technician,
    assert_engine_unit,
    create_campaign_work_order_payload,
    create_warranty_claim_payload,
    get_unit,
    make_fleet_manager_headers,
    make_service_advisor_headers,
    schedule_work_order,
    set_logical_clock,
    setup_campaign_in_progress,
    setup_engine_unit,
    setup_family_in_production,
    setup_fleet,
    setup_full_environment,
    setup_service_center,
    stamp_family_non_conforming,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# state gate (priority 7) beats temporal coverage gate (priority 12)
# ---------------------------------------------------------------------------
def _environment_with_decommissioned_unit_past_base_window(api):
    """Unit UN-801 in service since 2026-09-01; the clock advances to
    2029-01-02 (the 2-year base window closed 2028-09-01) and the unit is then
    decommissioned, so a claim filing violates the unit-lifecycle state gate
    and coverage determination at the same time."""
    env = setup_full_environment()
    family, fleet = env["family"], env["fleet"]
    unit = setup_engine_unit(family["id"], fleet["id"], serial_number="UN-801")
    set_logical_clock("2029-01-02T00:00:00Z")
    decommissioned = validate_success(api.decommission_unit(unit["id"], ADMIN))
    return env, decommissioned


def _file_engine_base_claim(api, env, unit):
    payload = create_warranty_claim_payload(
        engine_unit_id=unit["id"], service_center_id=env["center"]["id"],
        failed_component_class="ENGINE_BASE", failure_code="FC-duo",
        claimed_amount_cents=50000,
    )
    return api.create_warranty_claim(payload, make_fleet_manager_headers(env["fleet"]["id"]))


def test_unit_state_gate_precedes_coverage_expiry_on_claim_filing(api, admin_headers):
    """PRD §3.7: "After shape, existence, and ownership, the filing passes through three state gates in this order: the unit's `lifecycle` must be `IN_SERVICE` (`ERR_UNIT_NOT_IN_SERVICE`), the filing fleet must be `ACTIVE` (`ERR_FLEET_SUSPENDED`), and the repairing center's `auth_status` must be `AUTHORIZED` (`ERR_CENTER_NOT_AUTHORIZED`); coverage determination runs last."
    PRD §2.8: "When several checks could reject the same request, the server evaluates them in a fixed order and reports only the first failure."

    The unit is DECOMMISSIONED and the base window has closed (ENGINE_BASE
    carries no extended eligibility), so both gates fail; the state gate is
    evaluated first and the filing is rejected ERR_UNIT_NOT_IN_SERVICE, never
    ERR_COVERAGE_EXPIRED.

    Design: Difficulty/priority_pair_validation_conflict/claim_state_gate_beats_coverage_temporal_gate
    """
    env, unit = _environment_with_decommissioned_unit_past_base_window(api)
    assert unit["lifecycle"] == "DECOMMISSIONED"

    resp = _file_engine_base_claim(api, env, unit)
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_IN_SERVICE)


def test_rejected_filing_leaves_no_claim_row(api, admin_headers):
    """PRD §3.7: "The claims list endpoint supports filtering by `engine_unit_id`, `service_center_id`, and `status`."
    PRD §2.8: "When several checks could reject the same request, the server evaluates them in a fixed order and reports only the first failure."
    PRD §3.4: "Decommissioning retires a unit: a `PlatformAdmin` moves it from `IN_SERVICE` to `DECOMMISSIONED`, which is terminal."

    The doubly-violating filing is rejected at the state gate, so no claim row
    exists for the unit afterwards and the unit stays DECOMMISSIONED.

    Design: Difficulty/priority_pair_validation_conflict/claim_state_gate_beats_coverage_temporal_gate
    """
    env, unit = _environment_with_decommissioned_unit_past_base_window(api)

    resp = _file_engine_base_claim(api, env, unit)
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_IN_SERVICE)

    claims, meta = validate_paginated(
        api.list_warranty_claims(admin_headers, params={"engine_unit_id": unit["id"]})
    )
    assert claims == [], f"no claim may be created through a rejected filing, got {claims}"
    assert meta["total_count"] == 0

    unit_now = get_unit(unit["id"])
    assert_engine_unit(unit_now)
    assert unit_now["lifecycle"] == "DECOMMISSIONED"


# ---------------------------------------------------------------------------
# qualification gate (priority 9) beats bay capacity gate (priority 13)
# ---------------------------------------------------------------------------
def _campaign_at_single_bay_two_tech_center():
    """Second center 'High Plains Truck' with bay_capacity_per_day 1, holding a
    LEVEL_2 endorsed technician and a LEVEL_1 endorsed technician; RECALL
    campaign CMP-3 (3-bay-day remedy) IN_PROGRESS over units UN-811/UN-812; a
    first work order with the LEVEL_2 technician fills the single bay on
    2027-02-01."""
    env = setup_family_in_production()
    family = env["family"]
    fleet = setup_fleet()
    network = setup_service_center(
        bay_capacity_per_day=1, name="High Plains Truck", region="NW",
    )
    center, tech_level2 = network["center"], network["technician"]
    tech_level1 = add_technician(
        center["id"], certification_level="LEVEL_1", emissions_endorsed=True,
    )
    unit_a = setup_engine_unit(family["id"], fleet["id"], serial_number="UN-811")
    unit_b = setup_engine_unit(family["id"], fleet["id"], serial_number="UN-812")
    stamp_family_non_conforming(
        family["id"], test_period_label="2027-MY-Q1", sample_size=10, passing_units=8,
    )
    set_logical_clock("2026-12-15T00:00:00Z")
    campaign = setup_campaign_in_progress(
        family["id"], campaign_code="CMP-3", campaign_type="RECALL",
        defect_summary="NOx sensor drift",
        remedy_description="Replace both NOx sensors and recalibrate", remedy_bay_days=3,
    )
    wo_a = schedule_work_order(
        campaign["id"], unit_a["id"], center["id"], tech_level2["id"],
        scheduled_start_day="2027-02-01T00:00:00Z", bay_days=1,
    )
    return env, fleet, center, tech_level2, tech_level1, unit_a, unit_b, campaign, wo_a


def _create_conflicting_order(api, campaign, unit, center, tech):
    payload = create_campaign_work_order_payload(
        engine_unit_id=unit["id"], service_center_id=center["id"],
        assigned_technician_id=tech["id"],
        scheduled_start_day="2027-02-01T00:00:00Z", bay_days=3,
    )
    return api.create_campaign_work_order(
        campaign["id"], payload, make_service_advisor_headers(center["id"])
    )


def test_technician_qualification_gate_precedes_bay_capacity(api, admin_headers):
    """PRD §3.8: "the assigned technician must belong to the named center, must be `CERT_ACTIVE` at the current logical clock, must be `emissions_endorsed`, and — for any work order occupying 3 or more bay days — must hold `LEVEL_2` or `LEVEL_3` certification, with any shortfall rejected as `ERR_TECHNICIAN_NOT_QUALIFIED` (HTTP 409)"
    PRD §2.8: "When several checks could reject the same request, the server evaluates them in a fixed order and reports only the first failure."
    PRD §2.8: "9. Qualification and scoring consistency (`ERR_TECHNICIAN_NOT_QUALIFIED`, `ERR_DECISION_INCONSISTENT_WITH_SCORE`, `ERR_NO_QUALIFIED_TECHNICIAN`)."
    PRD §2.8: "13. Shop bay capacity (`ERR_CAPACITY_EXCEEDED`)."

    The LEVEL_1 technician on a 3-bay-day order fails the qualification gate
    while the already-filled single bay on 2027-02-01 fails the capacity gate;
    the earlier qualification failure is the one reported.

    Design: Difficulty/priority_pair_validation_conflict/work_order_technician_safety_beats_capacity_fiscal
    """
    (env, fleet, center, tech_level2, tech_level1,
     unit_a, unit_b, campaign, wo_a) = _campaign_at_single_bay_two_tech_center()

    resp = _create_conflicting_order(api, campaign, unit_b, center, tech_level1)
    validate_error(resp, ApiErrorId.ERR_TECHNICIAN_NOT_QUALIFIED)


def test_qualified_work_order_survives_rejected_conflicting_pairing(api, admin_headers):
    """PRD §3.8: "the assigned technician must belong to the named center, must be `CERT_ACTIVE` at the current logical clock, must be `emissions_endorsed`, and — for any work order occupying 3 or more bay days — must hold `LEVEL_2` or `LEVEL_3` certification, with any shortfall rejected as `ERR_TECHNICIAN_NOT_QUALIFIED` (HTTP 409)"
    PRD §3.8: "The order records the parent campaign's `campaign_id` and starts in `SCHEDULED`."

    The first work order — LEVEL_2 technician, one bay-day — was valid when
    created and remains SCHEDULED after the doubly-violating second create is
    rejected at the qualification gate; the rejected pairing consumed nothing
    on UN-812.

    Design: Difficulty/priority_pair_validation_conflict/work_order_technician_safety_beats_capacity_fiscal
    """
    (env, fleet, center, tech_level2, tech_level1,
     unit_a, unit_b, campaign, wo_a) = _campaign_at_single_bay_two_tech_center()

    resp = _create_conflicting_order(api, campaign, unit_b, center, tech_level1)
    validate_error(resp, ApiErrorId.ERR_TECHNICIAN_NOT_QUALIFIED)

    wo_a_now = validate_success(api.get_campaign_work_order(wo_a["id"], admin_headers))
    assert wo_a_now["status"] == "SCHEDULED", (
        f"the qualifying order is unaffected, got {wo_a_now['status']}"
    )

    unit_b_now = get_unit(unit_b["id"])
    assert_engine_unit(unit_b_now)
    assert unit_b_now["campaign_compliance"] == "CAMPAIGN_OPEN", (
        "a rejected work-order create must not consume the unit's campaign state"
    )
