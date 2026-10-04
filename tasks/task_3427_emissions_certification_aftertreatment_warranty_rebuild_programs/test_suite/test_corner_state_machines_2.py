"""Corner coverage — state machines, part 2 (PRD §3.4 unit decommission
gates, §3.7 claim terminal states and the neglect-denial fleet cascade,
§3.8 campaign announce/closure cascades, §3.9 reman terminal states).

The runner restarts the server before every test, so each test builds its own
environment from an empty database through PRD-declared endpoints only.
"""
from test_helpers import (
    ApiErrorId,
    adjudicate,
    adjudicate_claim_payload,
    cancel_work_order,
    complete_work_order,
    create_warranty_claim_payload,
    declare_campaign,
    file_claim,
    get_family,
    get_unit,
    grade_core,
    make_fleet_manager_headers,
    make_service_advisor_headers,
    make_warranty_adjudicator_headers,
    schedule_work_order,
    set_logical_clock,
    setup_campaign_in_progress,
    setup_engine_unit,
    setup_full_environment,
    setup_reman_order_awaiting_core,
    setup_reman_order_core_received,
    stamp_family_non_conforming,
    start_claim_review,
    start_work_order,
    validate_error,
    validate_success,
    verify_work_order,
    ADJUDICATOR_USER_ID,
)


def test_announce_cascades_family_hold_and_unit_flags(api, officer_headers):
    """PRD §3.8: "On success, three things happen in the same request. First, the family itself transitions to `COMPLIANCE_HOLD`, with the family's `version` incrementing. Second, every engine unit of the family whose `lifecycle` is `IN_SERVICE` and whose `campaign_compliance` is not already `CAMPAIGN_OPEN` transitions to `CAMPAIGN_OPEN`, each such unit's `version` incrementing — this is the fleet notification, and it re-opens units that a prior campaign had left `REMEDIED`. Third, the campaign stamps `announced_at` from the logical clock and records `notified_unit_count` as the number of units flagged."

    One announce call produces three declared side effects at once: family to
    COMPLIANCE_HOLD with a bumped version, the in-service unit flagged
    CAMPAIGN_OPEN, and announced_at stamped on the ANNOUNCED campaign.

    Design: Corner/state_machines/announce_cascades_family_hold_and_unit_flags
    """
    env = setup_full_environment()
    unit = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-101")
    stamp_family_non_conforming(env["family"]["id"], test_period_label="2027-MY-Q1")
    campaign = declare_campaign(env["family"]["id"], campaign_code="CMP-C2")
    family_pre = get_family(env["family"]["id"])

    announced = validate_success(api.announce_campaign(campaign["id"], officer_headers))
    assert announced["status"] == "ANNOUNCED"
    assert announced["announced_at"] is not None

    family_post = get_family(env["family"]["id"])
    assert family_post["certification_status"] == "COMPLIANCE_HOLD", (
        f"announce places the family on hold, got {family_post['certification_status']}"
    )
    assert family_post["version"] > family_pre["version"], (
        "the family hop is a mutation: version must advance "
        f"({family_pre['version']} -> {family_post['version']})"
    )

    unit_now = get_unit(unit["id"])
    assert unit_now["campaign_compliance"] == "CAMPAIGN_OPEN", (
        f"the in-service unit is flagged, got {unit_now['campaign_compliance']}"
    )


def test_announce_skips_units_already_decommissioned(api, admin_headers, officer_headers):
    """PRD §3.8: "Second, every engine unit of the family whose `lifecycle` is `IN_SERVICE` and whose `campaign_compliance` is not already `CAMPAIGN_OPEN` transitions to `CAMPAIGN_OPEN`"
    PRD §3.8: "A campaign announced against a family whose units are all decommissioned or already open therefore records a `notified_unit_count` of 0."

    A unit decommissioned before announce is not flagged, and
    notified_unit_count counts only the two IN_SERVICE units.

    Design: Corner/state_machines/announce_skips_units_already_decommissioned
    """
    env = setup_full_environment()
    setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-101")
    setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-102")
    unit_c = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-103")
    retired = validate_success(api.decommission_unit(unit_c["id"], admin_headers))
    assert retired["lifecycle"] == "DECOMMISSIONED"

    stamp_family_non_conforming(env["family"]["id"], test_period_label="2027-MY-Q1")
    campaign = declare_campaign(env["family"]["id"], campaign_code="CMP-C3")

    announced = validate_success(api.announce_campaign(campaign["id"], officer_headers))
    assert announced["notified_unit_count"] == 2, (
        f"the decommissioned unit is not counted, got {announced['notified_unit_count']}"
    )

    unit_c_now = get_unit(unit_c["id"])
    assert unit_c_now["lifecycle"] == "DECOMMISSIONED"
    assert unit_c_now["campaign_compliance"] == "CLEAR", (
        f"the cascade is conditional on IN_SERVICE, got {unit_c_now['campaign_compliance']}"
    )


def test_paid_claim_is_terminal(api, admin_headers):
    """PRD §3.7: "Payment is the terminal act for approved claims: a `PlatformAdmin` pays a claim in `APPROVED_FULL` or `APPROVED_PARTIAL`, moving it to `PAID` and stamping `paid_at` from the logical clock. `PAID` and `DENIED_NEGLECT` are both terminal; a denied claim is never paid."
    PRD §2.8: "State gates: the generic `ERR_INVALID_STATE_TRANSITION`, plus the specific state errors"

    A PAID claim accepts no further transitions: a second adjudicate returns
    409 ERR_INVALID_STATE_TRANSITION.

    Design: Corner/state_machines/paid_claim_is_terminal
    """
    env = setup_full_environment()
    unit = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-101")
    set_logical_clock("2026-12-01T00:00:00Z")
    claim = file_claim(
        unit, env["center"],
        failed_component_class="ENGINE_BASE",
        failure_code="FC-pay",
        claimed_amount_cents=40000,
    )
    start_claim_review(claim["id"])
    adjudicate(claim["id"], "APPROVE_FULL")

    paid = validate_success(api.pay_claim(claim["id"], admin_headers))
    assert paid["status"] == "PAID"
    assert paid["paid_at"] is not None and paid["paid_at"].startswith("2026-12-01T00:00:00"), (
        f"paid_at is stamped from the logical clock, got {paid['paid_at']}"
    )

    refused = api.adjudicate_claim(
        claim["id"],
        adjudicate_claim_payload("APPROVE_FULL"),
        make_warranty_adjudicator_headers(ADJUDICATOR_USER_ID),
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


def test_closed_campaign_is_terminal(api, officer_headers):
    """PRD §3.8: "Closure itself is the system transition from `COMPLETION_REVIEW` to `CLOSED`: in addition to the campaign's own `version` increment, if no other campaign of the same family sits in `ANNOUNCED`, `IN_PROGRESS`, or `COMPLETION_REVIEW`, the family exits `COMPLIANCE_HOLD` — to `IN_PRODUCTION` when `production_entered` is true, otherwise to `CERTIFIED`. `CLOSED` is terminal."
    PRD §2.8: "State gates: the generic `ERR_INVALID_STATE_TRANSITION`, plus the specific state errors"

    A campaign verified to completion_rate 1.0 closes inside the
    completion-review request; resume-execution on CLOSED then returns 409
    ERR_INVALID_STATE_TRANSITION.

    Design: Corner/state_machines/closed_campaign_is_terminal
    """
    env = setup_full_environment()
    center_id = env["center"]["id"]
    unit = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-101")
    stamp_family_non_conforming(env["family"]["id"], test_period_label="2027-MY-Q1")
    campaign = setup_campaign_in_progress(env["family"]["id"], campaign_code="CMP-C6")
    work_order = schedule_work_order(
        campaign["id"], unit["id"], center_id, env["technician"]["id"]
    )
    start_work_order(work_order["id"], center_id)
    complete_work_order(work_order["id"], center_id)
    verify_work_order(work_order["id"])

    closed = validate_success(api.campaign_completion_review(campaign["id"], officer_headers))
    assert closed["status"] == "CLOSED", (
        f"rate 1.0 meets the 0.95 default threshold, got {closed['status']}"
    )

    refused = api.resume_campaign_execution(campaign["id"], officer_headers)
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


def test_decommission_blocked_by_scheduled_work_order(api, admin_headers):
    """PRD §3.4: "Decommissioning retires a unit: a `PlatformAdmin` moves it from `IN_SERVICE` to `DECOMMISSIONED`, which is terminal. The transition is blocked while any campaign work order for the unit sits in `SCHEDULED` or `IN_BAY` (`ERR_WORK_ORDERS_OUTSTANDING`, HTTP 409) and while any reman order for the unit sits in `QUOTED`, `AWAITING_CORE`, or `CORE_RECEIVED` (`ERR_REMAN_ORDER_OPEN`, HTTP 409)."
    PRD §3.8: "Cancellation is available from `SCHEDULED`, moves the order to `CANCELLED`, and releases its occupied bay-days, restoring the capacity invariant."

    A unit with a SCHEDULED work order cannot be decommissioned; after the
    work order is cancelled the identical decommission succeeds.

    Design: Corner/state_machines/decommission_blocked_by_scheduled_work_order
    """
    env = setup_full_environment()
    center_id = env["center"]["id"]
    unit = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-101")
    stamp_family_non_conforming(env["family"]["id"], test_period_label="2027-MY-Q1")
    campaign = setup_campaign_in_progress(env["family"]["id"], campaign_code="CMP-C7")
    work_order = schedule_work_order(
        campaign["id"], unit["id"], center_id, env["technician"]["id"]
    )

    refused = api.decommission_unit(unit["id"], admin_headers)
    validate_error(refused, ApiErrorId.ERR_WORK_ORDERS_OUTSTANDING)

    cancel_work_order(work_order["id"], center_id)
    retired = validate_success(api.decommission_unit(unit["id"], admin_headers))
    assert retired["lifecycle"] == "DECOMMISSIONED", (
        f"once the order is cancelled the decommission succeeds, got {retired['lifecycle']}"
    )


def test_decommission_blocked_by_open_reman_order(api, admin_headers):
    """PRD §3.4: "The transition is blocked while any campaign work order for the unit sits in `SCHEDULED` or `IN_BAY` (`ERR_WORK_ORDERS_OUTSTANDING`, HTTP 409) and while any reman order for the unit sits in `QUOTED`, `AWAITING_CORE`, or `CORE_RECEIVED` (`ERR_REMAN_ORDER_OPEN`, HTTP 409)."

    A unit with a reman order confirmed to AWAITING_CORE cannot be
    decommissioned; the unit remains IN_SERVICE.

    Design: Corner/state_machines/decommission_blocked_by_open_reman_order
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
    assert order["status"] == "AWAITING_CORE"

    refused = api.decommission_unit(unit["id"], admin_headers)
    validate_error(refused, ApiErrorId.ERR_REMAN_ORDER_OPEN)

    unit_now = get_unit(unit["id"])
    assert unit_now["lifecycle"] == "IN_SERVICE", (
        f"the unit must not move, got {unit_now['lifecycle']}"
    )


def test_reman_core_rejected_is_terminal(api):
    """PRD §3.9: "A grade of `REJECT` — defined as a 0.0 grade percentage — takes a different branch: the order moves to `CORE_REJECTED`, `final_core_credit_cents` is set to 0, the center's balance decreases by the full provisional credit, and the center's `core_reversal_count` increments by 1, all center mutations."
    PRD §3.9: "`CLOSED`, `CORE_REJECTED`, and `CORE_FORFEIT` are all terminal."

    A CORE_REJECTED order accepts no further lifecycle calls: a later close
    attempt returns 409 ERR_INVALID_STATE_TRANSITION.

    Design: Corner/state_machines/reman_core_rejected_is_terminal
    """
    env = setup_full_environment()
    unit = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-101")
    set_logical_clock("2026-12-01T00:00:00Z")
    order = setup_reman_order_core_received(
        unit["id"], env["center"]["id"],
        reman_scope="COMPONENT", component_type="DPF", spec_level="STANDARD",
        quoted_price_cents=200000, quoted_core_value_cents=80000,
        expected_core_return_by="2027-03-01T00:00:00Z",
    )
    rejected = grade_core(order["id"], "REJECT")
    assert rejected["status"] == "CORE_REJECTED"
    assert rejected["final_core_credit_cents"] == 0

    refused = api.close_reman_order(
        order["id"], make_service_advisor_headers(env["center"]["id"])
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


def test_fleet_suspended_at_third_neglect_denial_blocks_claims_until_reinstated(
    api, admin_headers
):
    """PRD §3.7: "A denial for neglect cascades beyond the claim. The unit's fleet has its `neglect_denial_count` incremented by 1 — a mutation of the fleet that increments the fleet's `version` — and when that count reaches 3, the fleet transitions from `ACTIVE` to `SUSPENDED`, a second fleet mutation within the same adjudication request. A `SUSPENDED` fleet's `FleetManager` can no longer file claims or append maintenance records until a `PlatformAdmin` reinstates the fleet."
    PRD §3.7: "the filing fleet must be `ACTIVE` (`ERR_FLEET_SUSPENDED`)"
    PRD §3.4: "a `PlatformAdmin` may reinstate a suspended fleet, returning it to `ACTIVE` and resetting `neglect_denial_count` to 0."

    Three DENIED_NEGLECT adjudications on one fleet's units flip the fleet to
    SUSPENDED; the fourth filing fails ERR_FLEET_SUSPENDED, and after a
    PlatformAdmin reinstate (count reset to 0) the identical filing succeeds.

    Design: Corner/state_machines/fleet_suspended_at_third_neglect_denial_blocks_claims_until_reinstated
    """
    env = setup_full_environment()
    family_id, fleet_id, center_id = (
        env["family"]["id"], env["fleet"]["id"], env["center"]["id"],
    )
    units = [
        setup_engine_unit(family_id, fleet_id, serial_number=f"UN-10{i}")
        for i in (1, 2, 3, 4)
    ]
    for unit in units:
        # 35000 miles / 0 oil changes -> 2 missed intervals x 25; one bad DEF
        # service x 15 -> neglect score 65, squarely in the DENY_NEGLECT band.
        resp = api.create_telematics_snapshot(
            unit["id"],
            {
                "recorded_at": "2026-11-10T00:00:00Z",
                "odometer_miles": 35000,
                "engine_hours": 700,
                "fault_codes": [],
                "def_consumption_gal": 70.0,
                "nox_sensor_drift_ppm": 3,
            },
            admin_headers,
        )
        validate_success(resp, 201)
        resp = api.create_maintenance_record(
            unit["id"],
            {
                "performed_at": "2026-11-12T00:00:00Z",
                "maintenance_type": "DEF_SERVICE",
                "odometer_at_service": 34000,
                "def_quality_ok": False,
            },
            make_fleet_manager_headers(fleet_id),
        )
        validate_success(resp, 201)

    set_logical_clock("2026-12-01T00:00:00Z")
    fleet_headers = make_fleet_manager_headers(fleet_id)
    for unit in units[:3]:
        claim = file_claim(
            unit, env["center"],
            failed_component_class="AFTERTREATMENT_SCR",
            failure_code=f"FC-n{unit['serial_number']}",
            claimed_amount_cents=30000,
        )
        start_claim_review(claim["id"])
        denied = adjudicate(claim["id"], "DENY_NEGLECT")
        assert denied["status"] == "DENIED_NEGLECT"
        assert denied["neglect_score"] == 65

    fleet_now = validate_success(api.get_fleet(fleet_id, admin_headers))
    assert fleet_now["status"] == "SUSPENDED", (
        f"the third denial suspends the fleet, got {fleet_now['status']}"
    )
    assert fleet_now["neglect_denial_count"] == 3

    blocked = api.create_warranty_claim(
        create_warranty_claim_payload(
            engine_unit_id=units[3]["id"],
            service_center_id=center_id,
            failed_component_class="AFTERTREATMENT_SCR",
            failure_code="FC-n4",
            claimed_amount_cents=30000,
        ),
        fleet_headers,
    )
    validate_error(blocked, ApiErrorId.ERR_FLEET_SUSPENDED)

    reinstated = validate_success(api.reinstate_fleet(fleet_id, admin_headers))
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["neglect_denial_count"] == 0, (
        f"reinstate resets the counter, got {reinstated['neglect_denial_count']}"
    )

    resp = api.create_warranty_claim(
        create_warranty_claim_payload(
            engine_unit_id=units[3]["id"],
            service_center_id=center_id,
            failed_component_class="AFTERTREATMENT_SCR",
            failure_code="FC-n5",
            claimed_amount_cents=30000,
        ),
        fleet_headers,
    )
    claim_after = validate_success(resp, 201)
    assert claim_after["status"] == "SUBMITTED"
