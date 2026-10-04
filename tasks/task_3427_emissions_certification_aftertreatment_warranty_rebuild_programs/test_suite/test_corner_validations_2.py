"""Corner coverage — validations, part 2 (PRD §3.9 forfeit timing, §3.4
in-use sample rules, §3.8 campaign gates, §3.2 phase-out gate, and the
uniqueness scopes of §3.1/§3.2/§3.4/§3.6/§3.8).

The runner restarts the server before every test, so each test builds its own
environment from an empty database through PRD-declared endpoints only.
"""
from test_helpers import (
    ApiErrorId,
    add_diagnostic_tool,
    add_technician,
    complete_work_order,
    compute_provisional_core_credit,
    create_campaign_work_order_payload,
    create_engine_family_payload,
    create_field_campaign_payload,
    create_in_use_result_payload,
    create_regulation_standard_payload,
    create_service_center,
    create_technician_payload,
    create_diagnostic_tool_payload,
    declare_campaign,
    get_family,
    get_unit,
    make_service_advisor_headers,
    schedule_work_order,
    set_logical_clock,
    setup_campaign_in_progress,
    setup_engine_unit,
    setup_family_certified,
    setup_family_in_production,
    setup_fleet,
    setup_full_environment,
    setup_reman_order_awaiting_core,
    stamp_family_non_conforming,
    start_work_order,
    validate_error,
    validate_paginated,
    validate_success,
    verify_work_order,
)


def test_forfeit_core_before_due_date_rejected(api, admin_headers):
    """PRD §3.9: "From `AWAITING_CORE`, a `ServiceAdvisor` (own center) or a `RemanPlanner` may forfeit the core, but only when the logical clock is strictly after `expected_core_return_by`; on or before the deadline the attempt is rejected with `ERR_CORE_NOT_YET_LATE` (HTTP 409)."
    PRD §3.9: "Confirmation moves the order from `QUOTED` to `AWAITING_CORE` and posts the provisional credit: the center's `core_credit_balance_cents` increases by `provisional_core_credit_cents`, a center mutation that increments the center's `version`."

    forfeit-core at 2026-12-01 with the return window open until 2027-03-01
    fails 409 ERR_CORE_NOT_YET_LATE; the order stays AWAITING_CORE and the
    center ledger keeps the 120000 provisional credit.

    Design: Corner/validations/forfeit_core_before_due_date_rejected
    """
    env = setup_full_environment()
    unit = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-101")
    set_logical_clock("2026-12-01T00:00:00Z")
    order = setup_reman_order_awaiting_core(
        unit["id"], env["center"]["id"],
        reman_scope="ENGINE", spec_level="STANDARD",
        quoted_price_cents=500000, quoted_core_value_cents=200000,
        expected_core_return_by="2027-03-01T00:00:00Z",
    )

    refused = api.forfeit_core(
        order["id"], make_service_advisor_headers(env["center"]["id"])
    )
    validate_error(refused, ApiErrorId.ERR_CORE_NOT_YET_LATE)

    order_now = validate_success(api.get_reman_order(order["id"], admin_headers))
    assert order_now["status"] == "AWAITING_CORE"
    center_now = validate_success(api.get_service_center(env["center"]["id"], admin_headers))
    assert center_now["core_credit_balance_cents"] == compute_provisional_core_credit(200000) == 120000, (
        "the provisional credit stays posted while forfeiture is refused, "
        f"got {center_now['core_credit_balance_cents']}"
    )


def test_in_use_sample_floor_and_passing_cap_enforced(api, officer_headers):
    """PRD §3.4: "The `sample_size` must be at least 5 — a smaller sample is rejected with `ERR_SAMPLE_SIZE_TOO_SMALL` (HTTP 422) — while `passing_units` must be at least 0 and no greater than `sample_size`, with violations caught earlier as shape errors under `ERR_INVALID_REQUEST`."
    PRD §2.8: "Request shape: required fields present, enum values within their declared sets, integer ranges respected (`bay_days` at least 1, `claimed_amount_cents` greater than 0, `sample_size` at least 1, `passing_units` at least 0 and no greater than `sample_size`..."

    sample_size 4 is below the regulatory minimum 5 (422
    ERR_SAMPLE_SIZE_TOO_SMALL), passing_units greater than sample_size is a
    shape error (400 ERR_INVALID_REQUEST), and sample_size exactly 5 is
    accepted.

    Design: Corner/validations/in_use_sample_floor_and_passing_cap_enforced
    """
    env = setup_family_in_production()
    family_id = env["family"]["id"]
    set_logical_clock("2027-06-01T00:00:00Z")

    too_small = api.create_in_use_result(
        family_id,
        create_in_use_result_payload(
            test_period_label="2027-MY-Q2a", sample_size=4, passing_units=4,
        ),
        officer_headers,
    )
    validate_error(too_small, ApiErrorId.ERR_SAMPLE_SIZE_TOO_SMALL)

    over_cap = api.create_in_use_result(
        family_id,
        create_in_use_result_payload(
            test_period_label="2027-MY-Q2b", sample_size=6, passing_units=7,
        ),
        officer_headers,
    )
    validate_error(over_cap, ApiErrorId.ERR_INVALID_REQUEST)

    at_floor = validate_success(
        api.create_in_use_result(
            family_id,
            create_in_use_result_payload(
                test_period_label="2027-MY-Q2c", sample_size=5, passing_units=5,
            ),
            officer_headers,
        ),
        201,
    )
    assert at_floor["conformity_ratio"] == 1.0, (
        f"5/5 at the floor gives ratio 1.0, got {at_floor['conformity_ratio']}"
    )


def test_recall_announce_requires_non_conforming_family(api, officer_headers):
    """PRD §3.8: "The family must at that moment be in `CERTIFIED` or `IN_PRODUCTION` — announcement from any other family state fails as `ERR_INVALID_STATE_TRANSITION` — and a `RECALL` campaign additionally requires the family's `in_use_compliance_status` to be `NON_CONFORMING`, otherwise the announce is rejected with `ERR_RECALL_REQUIRES_NON_CONFORMANCE` (HTTP 409)."

    A RECALL campaign cannot be announced while the family's in-use status is
    NOT_TESTED; a SERVICE_CAMPAIGN on the same family announces fine and still
    cascades — the gate is type-conditional.

    Design: Corner/validations/recall_announce_requires_non_conforming_family
    """
    env = setup_family_in_production()
    fleet = setup_fleet()
    unit = setup_engine_unit(env["family"]["id"], fleet["id"], serial_number="UN-101")
    recall = declare_campaign(
        env["family"]["id"], campaign_code="CMP-R", campaign_type="RECALL",
        defect_summary="NOx exceedance", remedy_description="Recalibrate dosing",
        remedy_bay_days=1,
    )
    service = declare_campaign(
        env["family"]["id"], campaign_code="CMP-S", campaign_type="SERVICE_CAMPAIGN",
        defect_summary="Preventive doser inspection", remedy_description="Inspect doser",
        remedy_bay_days=1,
    )

    refused = api.announce_campaign(recall["id"], officer_headers)
    validate_error(refused, ApiErrorId.ERR_RECALL_REQUIRES_NON_CONFORMANCE)

    announced = validate_success(api.announce_campaign(service["id"], officer_headers))
    assert announced["status"] == "ANNOUNCED", (
        f"the SERVICE_CAMPAIGN is not gated by in-use status, got {announced['status']}"
    )
    family_now = get_family(env["family"]["id"])
    assert family_now["certification_status"] == "COMPLIANCE_HOLD"
    assert get_unit(unit["id"])["campaign_compliance"] == "CAMPAIGN_OPEN"


def test_begin_execution_with_zero_notified_units_rejected(api, officer_headers):
    """PRD §3.8: "Execution begins when a `RegulatoryOfficer` moves the campaign from `ANNOUNCED` to `IN_PROGRESS`, which requires `notified_unit_count` to be greater than 0; announcing into an empty fleet leaves the campaign unable to begin, and the attempt is rejected with `ERR_CAMPAIGN_HAS_NO_UNITS` (HTTP 409)."
    PRD §3.8: "A campaign announced against a family whose units are all decommissioned or already open therefore records a `notified_unit_count` of 0."

    A campaign announced over a family with zero IN_SERVICE units records
    notified_unit_count 0 and cannot begin execution.

    Design: Corner/validations/begin_execution_with_zero_notified_units_rejected
    """
    env = setup_family_in_production()
    stamp_family_non_conforming(env["family"]["id"], test_period_label="2027-MY-Q1")
    campaign = declare_campaign(env["family"]["id"], campaign_code="CMP-Z")

    announced = validate_success(api.announce_campaign(campaign["id"], officer_headers))
    assert announced["notified_unit_count"] == 0, (
        f"no units were ever registered, got {announced['notified_unit_count']}"
    )

    refused = api.begin_campaign_execution(campaign["id"], officer_headers)
    validate_error(refused, ApiErrorId.ERR_CAMPAIGN_HAS_NO_UNITS)


def test_phase_out_blocked_while_campaign_open(api, officer_headers):
    """PRD §3.2: "A `RegulatoryOfficer` may phase out a family from either `IN_PRODUCTION` or `COMPLIANCE_HOLD`, moving it to `PHASED_OUT`, but only while no field campaign of the family sits in `ANNOUNCED`, `IN_PROGRESS`, or `COMPLETION_REVIEW`; an open campaign blocks the transition with `ERR_CAMPAIGN_STILL_OPEN` (HTTP 409)."

    Phase-out is refused while the campaign is IN_PROGRESS; after the campaign
    CLOSES (releasing the hold) the identical phase-out succeeds — the gate
    reads sibling-campaign state.

    Design: Corner/validations/phase_out_blocked_while_campaign_open
    """
    env = setup_full_environment()
    center_id = env["center"]["id"]
    unit = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-101")
    stamp_family_non_conforming(env["family"]["id"], test_period_label="2027-MY-Q1")
    campaign = setup_campaign_in_progress(env["family"]["id"], campaign_code="CMP-C9")
    work_order = schedule_work_order(
        campaign["id"], unit["id"], center_id, env["technician"]["id"]
    )
    start_work_order(work_order["id"], center_id)
    complete_work_order(work_order["id"], center_id)
    verify_work_order(work_order["id"])

    refused = api.phase_out_family(env["family"]["id"], officer_headers)
    validate_error(refused, ApiErrorId.ERR_CAMPAIGN_STILL_OPEN)

    closed = validate_success(api.campaign_completion_review(campaign["id"], officer_headers))
    assert closed["status"] == "CLOSED", (
        f"rate 1.0 meets the 0.95 default threshold, got {closed['status']}"
    )

    phased = validate_success(api.phase_out_family(env["family"]["id"], officer_headers))
    assert phased["certification_status"] == "PHASED_OUT", (
        f"with no open campaign the phase-out succeeds, got {phased['certification_status']}"
    )


def test_work_order_for_unit_not_flagged_by_campaign_rejected(api):
    """PRD §3.8: "Scheduling passes through five gates beyond the standard checks: the campaign must be `IN_PROGRESS` (`ERR_CAMPAIGN_NOT_IN_PROGRESS`, HTTP 409); the unit's `campaign_compliance` must be `CAMPAIGN_OPEN` (`ERR_UNIT_CAMPAIGN_NOT_OPEN`, HTTP 409); the executing center must be `AUTHORIZED` (`ERR_CENTER_NOT_AUTHORIZED`); the assigned technician must belong to the named center, must be `CERT_ACTIVE` at the current logical clock, must be `emissions_endorsed`"
    PRD §3.8: "On success the order moves to `VERIFIED` — terminal — and stamps `verified_at`; then, in the same request: the unit transitions from `CAMPAIGN_OPEN` to `REMEDIED` (unit `version` increments)"

    A unit whose campaign_compliance is not CAMPAIGN_OPEN cannot be scheduled
    under the campaign: after the unit's first remedy is verified (REMEDIED),
    a second work order for the same unit fails ERR_UNIT_CAMPAIGN_NOT_OPEN.

    Design: Corner/validations/work_order_for_unit_not_flagged_by_campaign_rejected
    """
    env = setup_full_environment()
    center_id = env["center"]["id"]
    unit_a = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-101")
    setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-102")
    stamp_family_non_conforming(env["family"]["id"], test_period_label="2027-MY-Q1")
    campaign = setup_campaign_in_progress(env["family"]["id"], campaign_code="CMP-CA")
    first = schedule_work_order(
        campaign["id"], unit_a["id"], center_id, env["technician"]["id"]
    )
    start_work_order(first["id"], center_id)
    complete_work_order(first["id"], center_id)
    verify_work_order(first["id"])
    assert get_unit(unit_a["id"])["campaign_compliance"] == "REMEDIED"

    refused = api.create_campaign_work_order(
        campaign["id"],
        create_campaign_work_order_payload(
            engine_unit_id=unit_a["id"],
            service_center_id=center_id,
            assigned_technician_id=env["technician"]["id"],
        ),
        make_service_advisor_headers(center_id),
    )
    validate_error(refused, ApiErrorId.ERR_UNIT_CAMPAIGN_NOT_OPEN)


def test_work_order_in_announced_but_not_started_campaign_rejected(api, officer_headers):
    """PRD §3.8: "Scheduling passes through five gates beyond the standard checks: the campaign must be `IN_PROGRESS` (`ERR_CAMPAIGN_NOT_IN_PROGRESS`, HTTP 409); the unit's `campaign_compliance` must be `CAMPAIGN_OPEN` (`ERR_UNIT_CAMPAIGN_NOT_OPEN`, HTTP 409)"

    An ANNOUNCED campaign has notified units but is not yet executing:
    work-order creation fails ERR_CAMPAIGN_NOT_IN_PROGRESS until
    begin-execution runs.

    Design: Corner/validations/work_order_in_announced_but_not_started_campaign_rejected
    """
    env = setup_full_environment()
    center_id = env["center"]["id"]
    unit = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-101")
    stamp_family_non_conforming(env["family"]["id"], test_period_label="2027-MY-Q1")
    campaign = declare_campaign(env["family"]["id"], campaign_code="CMP-CB")
    announced = validate_success(api.announce_campaign(campaign["id"], officer_headers))
    assert announced["status"] == "ANNOUNCED" and announced["notified_unit_count"] == 1

    refused = api.create_campaign_work_order(
        campaign["id"],
        create_campaign_work_order_payload(
            engine_unit_id=unit["id"],
            service_center_id=center_id,
            assigned_technician_id=env["technician"]["id"],
        ),
        make_service_advisor_headers(center_id),
    )
    validate_error(refused, ApiErrorId.ERR_CAMPAIGN_NOT_IN_PROGRESS)


def test_uniqueness_scopes_enforced_per_declared_scope(
    api, admin_headers, engineer_headers, officer_headers
):
    """PRD §3.1: "its `code` — unique across the entire program, so a duplicate submission is rejected with `ERR_DUPLICATE_STANDARD_CODE` (HTTP 409)"
    PRD §3.2: "the `family_code` must be unique among families of the same `model_year` (`ERR_DUPLICATE_FAMILY_CODE`)"
    PRD §3.4: "a `serial_number` unique within the family (`ERR_DUPLICATE_SERIAL_NUMBER`, HTTP 409)"
    PRD §3.6: "a `badge_id` unique within that center (`ERR_DUPLICATE_BADGE_ID`, HTTP 409)"
    PRD §3.6: "Issuing a tool to a center records its `tool_serial` — unique program-wide, so a duplicate is rejected with `ERR_DUPLICATE_TOOL_SERIAL` (HTTP 409)"
    PRD §3.8: "a `campaign_code` unique within the family (`ERR_DUPLICATE_CAMPAIGN_CODE`, HTTP 409)"

    Each uniqueness rule fires inside its declared scope and not outside it:
    family_code collides only within the same model_year, badge_id only within
    one center, tool_serial program-wide, campaign_code only within one
    family, standard code program-wide.

    Design: Corner/validations/uniqueness_scopes_enforced_per_declared_scope
    """
    env = setup_family_certified(
        standard_overrides={"code": "STD-UQ-1"},
        family_overrides={"family_code": "F-UQ"},
    )
    standard_id, family_id = env["standard"]["id"], env["family"]["id"]
    center = create_service_center()
    add_technician(center["id"], full_name="Tess Adey", badge_id="T-01")
    add_diagnostic_tool(center["id"], tool_serial="DT-9001")
    declare_campaign(
        family_id, campaign_code="CMP-D", campaign_type="SERVICE_CAMPAIGN",
        defect_summary="Inspection", remedy_description="Inspect", remedy_bay_days=1,
    )

    dup_family = api.create_engine_family(
        create_engine_family_payload(
            regulation_standard_id=standard_id, family_code="F-UQ", model_year=2027,
        ),
        engineer_headers,
    )
    validate_error(dup_family, ApiErrorId.ERR_DUPLICATE_FAMILY_CODE)

    other_year = validate_success(
        api.create_engine_family(
            create_engine_family_payload(
                regulation_standard_id=standard_id, family_code="F-UQ", model_year=2028,
            ),
            engineer_headers,
        ),
        201,
    )
    assert other_year["family_code"] == "F-UQ", (
        "the scope is (family_code, model_year): the same code in another "
        "model year is a different family"
    )

    dup_badge = api.create_technician(
        center["id"],
        create_technician_payload(
            full_name="Other Tech", badge_id="T-01",
            certification_level="LEVEL_1", emissions_endorsed=False,
        ),
        admin_headers,
    )
    validate_error(dup_badge, ApiErrorId.ERR_DUPLICATE_BADGE_ID)

    dup_tool = api.create_diagnostic_tool(
        center["id"],
        create_diagnostic_tool_payload(tool_serial="DT-9001", software_version="8.0.0"),
        admin_headers,
    )
    validate_error(dup_tool, ApiErrorId.ERR_DUPLICATE_TOOL_SERIAL)

    dup_campaign = api.create_field_campaign(
        create_field_campaign_payload(
            engine_family_id=family_id, campaign_code="CMP-D",
            campaign_type="SERVICE_CAMPAIGN", defect_summary="Inspection 2",
            remedy_description="Inspect", remedy_bay_days=1,
        ),
        officer_headers,
    )
    validate_error(dup_campaign, ApiErrorId.ERR_DUPLICATE_CAMPAIGN_CODE)

    dup_standard = api.create_regulation_standard(
        create_regulation_standard_payload(
            code="STD-UQ-1",
            effective_model_year_first=2024, effective_model_year_last=2026,
        ),
        admin_headers,
    )
    validate_error(dup_standard, ApiErrorId.ERR_DUPLICATE_STANDARD_CODE)
