"""Cross-entity state dependency tests (PRD §3.7 claim filing gated by the
engine unit's lifecycle, §3.8 work-order scheduling gated by the service
center's authorization).

The runner restarts the server before every test, so each test builds its own
environment from an empty database through PRD-declared endpoints only.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_engine_unit,
    assert_service_center,
    assert_warranty_claim,
    create_campaign_work_order_payload,
    create_warranty_claim_payload,
    get_unit,
    make_fleet_manager_headers,
    make_service_advisor_headers,
    set_logical_clock,
    setup_campaign_in_progress,
    setup_engine_unit,
    setup_full_environment,
    stamp_family_non_conforming,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# WarrantyClaim filing gated by EngineUnit lifecycle
# ---------------------------------------------------------------------------
def _environment_with_unit(unit_serial):
    env = setup_full_environment()
    unit = setup_engine_unit(
        env["family"]["id"], env["fleet"]["id"], serial_number=unit_serial,
    )
    set_logical_clock("2026-12-01T00:00:00Z")
    return env, unit


def _file_scr_claim(api, env, unit):
    payload = create_warranty_claim_payload(
        engine_unit_id=unit["id"], service_center_id=env["center"]["id"],
        failed_component_class="AFTERTREATMENT_SCR", failure_code="FC-scr",
        claimed_amount_cents=80000,
    )
    return api.create_warranty_claim(payload, make_fleet_manager_headers(env["fleet"]["id"]))


def test_claim_filing_rejected_when_unit_decommissioned_despite_open_coverage(api, admin_headers):
    """PRD §3.7: "After shape, existence, and ownership, the filing passes through three state gates in this order: the unit's `lifecycle` must be `IN_SERVICE` (`ERR_UNIT_NOT_IN_SERVICE`), the filing fleet must be `ACTIVE` (`ERR_FLEET_SUSPENDED`), and the repairing center's `auth_status` must be `AUTHORIZED` (`ERR_CENTER_NOT_AUTHORIZED`); coverage determination runs last."
    PRD §3.7: "The extended window is open only when all of the following hold: the claim's `failed_component_class` is one of the five emissions component classes — `AFTERTREATMENT_SCR`, `AFTERTREATMENT_DPF`, `DOSING_SYSTEM`, `NOX_SENSOR`, or `EGR_SYSTEM` — and the clock is strictly before `in_service_date` plus the extended years term, and `accumulated_miles` is strictly below the extended mileage term, and `accumulated_hours` is strictly below the extended hours term."

    The extended window is fully open for this AFTERTREATMENT_SCR failure
    (clock 2026-12-01, zero miles and hours), yet the filing is rejected purely
    because the unit left IN_SERVICE.

    Design: Difficulty/cross_entity_state_dependency/claim_create_gated_by_engine_unit_lifecycle
    """
    env, unit = _environment_with_unit("UN-901")
    validate_success(api.decommission_unit(unit["id"], ADMIN))

    resp = _file_scr_claim(api, env, unit)
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_IN_SERVICE)

    unit_now = get_unit(unit["id"])
    assert_engine_unit(unit_now)
    assert unit_now["lifecycle"] == "DECOMMISSIONED"


def test_identical_filing_on_in_service_unit_succeeds(api, admin_headers):
    """PRD §3.7: "When the extended window is open the claim is stamped `EXTENDED_EMISSIONS`; otherwise, when the base window is open, it is stamped `BASE_WARRANTY`; when neither window is open the filing is rejected with `ERR_COVERAGE_EXPIRED` (HTTP 409)."
    PRD §3.7: "A filed claim starts in `SUBMITTED` with `review_round` 0, captures the filer's `submitted_by_role` and `submitted_by_user_id`, and leaves `neglect_score`, `approved_amount_cents`, `customer_share_cents`, `decided_by_user_id`, and `paid_at` unset."

    Control for the lifecycle gate: the identical AFTERTREATMENT_SCR filing
    against a sibling unit still IN_SERVICE is accepted and stamps
    EXTENDED_EMISSIONS, while the decommissioned unit's rejection created no
    claim row.

    Design: Difficulty/cross_entity_state_dependency/claim_create_gated_by_engine_unit_lifecycle
    """
    env, unit = _environment_with_unit("UN-901")
    sibling = setup_engine_unit(
        env["family"]["id"], env["fleet"]["id"], serial_number="UN-901B",
    )
    validate_success(api.decommission_unit(unit["id"], ADMIN))

    rejected = _file_scr_claim(api, env, unit)
    validate_error(rejected, ApiErrorId.ERR_UNIT_NOT_IN_SERVICE)

    accepted = validate_success(_file_scr_claim(api, env, sibling), 201)
    assert_warranty_claim(accepted)
    assert accepted["status"] == "SUBMITTED"
    assert accepted["coverage_variant"] == "EXTENDED_EMISSIONS", (
        "the extended window is open for the in-service sibling, proving the "
        f"rejection above was the lifecycle gate alone; got {accepted['coverage_variant']}"
    )

    claims, meta = validate_paginated(
        api.list_warranty_claims(ADMIN, params={"engine_unit_id": unit["id"]})
    )
    assert claims == [], f"the rejected filing left no claim row, got {claims}"


# ---------------------------------------------------------------------------
# CampaignWorkOrder scheduling gated by ServiceCenter authorization
# ---------------------------------------------------------------------------
def _campaign_ready_then_suspend_center(api):
    """RECALL campaign CMP-4 IN_PROGRESS over unit UN-902 at an authorized
    center; the center is then suspended before any work order is scheduled."""
    env = setup_full_environment()
    family, fleet, center, tech = (
        env["family"], env["fleet"], env["center"], env["technician"],
    )
    unit = setup_engine_unit(family["id"], fleet["id"], serial_number="UN-902")
    stamp_family_non_conforming(
        family["id"], test_period_label="2027-MY-Q1", sample_size=10, passing_units=7,
    )
    set_logical_clock("2026-12-15T00:00:00Z")
    campaign = setup_campaign_in_progress(
        family["id"], campaign_code="CMP-4", campaign_type="RECALL",
        defect_summary="DEF crystallization in doser",
        remedy_description="Replace doser", remedy_bay_days=1,
    )
    validate_success(api.suspend_service_center(center["id"], ADMIN))
    return env, unit, campaign, center, tech


def test_work_order_rejected_when_center_suspended(api, admin_headers):
    """PRD §3.8: "Scheduling passes through five gates beyond the standard checks: the campaign must be `IN_PROGRESS` (`ERR_CAMPAIGN_NOT_IN_PROGRESS`, HTTP 409); the unit's `campaign_compliance` must be `CAMPAIGN_OPEN` (`ERR_UNIT_CAMPAIGN_NOT_OPEN`, HTTP 409); the executing center must be `AUTHORIZED` (`ERR_CENTER_NOT_AUTHORIZED`); the assigned technician must belong to the named center, must be `CERT_ACTIVE` at the current logical clock, must be `emissions_endorsed`, and — for any work order occupying 3 or more bay days — must hold `LEVEL_2` or `LEVEL_3` certification, with any shortfall rejected as `ERR_TECHNICIAN_NOT_QUALIFIED` (HTTP 409); and the shop's bay capacity must absorb the booking."
    PRD §3.6: "Suspension moves an `AUTHORIZED` center to `SUSPENDED`, and it happens in two ways: a `PlatformAdmin` may suspend a center directly, or the system suspends it as a side effect of the remanufacturing core-reversal cascade when the center's `core_reversal_count` reaches 2 (§3.9)."

    Campaign, unit and technician are all valid; the freshly SUSPENDED center
    alone defeats the schedule.

    Design: Difficulty/cross_entity_state_dependency/work_order_gated_by_service_center_authorization
    """
    env, unit, campaign, center, tech = _campaign_ready_then_suspend_center(api)

    payload = create_campaign_work_order_payload(
        engine_unit_id=unit["id"], service_center_id=center["id"],
        assigned_technician_id=tech["id"],
        scheduled_start_day="2027-01-04T00:00:00Z", bay_days=1,
    )
    resp = api.create_campaign_work_order(
        campaign["id"], payload, make_service_advisor_headers(center["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CENTER_NOT_AUTHORIZED)


def test_rejected_work_order_leaves_unit_campaign_open(api, admin_headers):
    """PRD §3.8: "Second, every engine unit of the family whose `lifecycle` is `IN_SERVICE` and whose `campaign_compliance` is not already `CAMPAIGN_OPEN` transitions to `CAMPAIGN_OPEN`, each such unit's `version` incrementing — this is the fleet notification, and it re-opens units that a prior campaign had left `REMEDIED`."
    PRD §3.8: "the executing center must be `AUTHORIZED` (`ERR_CENTER_NOT_AUTHORIZED`)"

    The rejected schedule consumes nothing: the unit stays CAMPAIGN_OPEN and
    the center remains SUSPENDED.

    Design: Difficulty/cross_entity_state_dependency/work_order_gated_by_service_center_authorization
    """
    env, unit, campaign, center, tech = _campaign_ready_then_suspend_center(api)

    payload = create_campaign_work_order_payload(
        engine_unit_id=unit["id"], service_center_id=center["id"],
        assigned_technician_id=tech["id"],
        scheduled_start_day="2027-01-04T00:00:00Z", bay_days=1,
    )
    resp = api.create_campaign_work_order(
        campaign["id"], payload, make_service_advisor_headers(center["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CENTER_NOT_AUTHORIZED)

    unit_now = get_unit(unit["id"])
    assert_engine_unit(unit_now)
    assert unit_now["campaign_compliance"] == "CAMPAIGN_OPEN", (
        f"no work order consumed the unit, got {unit_now['campaign_compliance']}"
    )

    center_now = validate_success(api.get_service_center(center["id"], admin_headers))
    assert_service_center(center_now)
    assert center_now["auth_status"] == "SUSPENDED"
