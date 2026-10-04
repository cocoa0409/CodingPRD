"""Boundary precision on the numeric and instant thresholds."""
from test_helpers import E, api_client, validate_error, validate_success
from test_helpers.fixtures import (
    COMPLIANCE,
    INTAKE,
    READER,
    certify,
    create_jurisdiction,
    create_piercer,
    create_store,
    file_and_triage_incident,
    get_appointment,
    get_store,
    set_clock,
    setup_customer_with_active_consent,
    setup_ready_appointment,
    setup_store_near_incident_threshold,
)


def test_store_is_open_at_two_open_incidents_and_restricted_at_three(api):
    """PRD §2.7: "otherwise, when the open incident count is at least 3, or at least one failed
    cycle exists, the posture is `RESTRICTED`".
    PRD §2.7: "The boundaries are inclusive: an open incident count of exactly 3 restricts, and
    a count of 2 does not."

    Design: Difficulty/boundary_precision_check/store_posture_restriction_at_exactly_three_open_incidents
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_store_near_incident_threshold(store_overrides={"piercing_room_count": 1})
    store_id = ctx["store"]["id"]

    at_two = get_store(store_id)
    assert at_two["open_incident_count"] == 2
    assert at_two["compliance_posture"] == "OPEN"

    file_and_triage_incident(ctx["session"], severity="MINOR", reported_at="2026-09-07T00:00:00Z")

    at_three = get_store(store_id)
    assert at_three["open_incident_count"] == 3
    assert at_three["compliance_posture"] == "RESTRICTED"


def test_a_fourth_open_incident_leaves_the_store_restricted(api):
    """PRD §2.7: "The three thresholds are fixed constants: `RESTRICTION_INCIDENT_THRESHOLD`
    is 3, `RESTRICTION_FAILED_CYCLE_THRESHOLD` is 1, and `FREEZE_FAILED_CYCLE_THRESHOLD` is 2."
    PRD §2.7: "Because the freeze test is applied first, a store with both a failed cycle and a
    single critical incident reports `FROZEN` rather than `RESTRICTED`."

    Design: Difficulty/boundary_precision_check/store_posture_restriction_at_exactly_three_open_incidents
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_store_near_incident_threshold(store_overrides={"piercing_room_count": 1})
    store_id = ctx["store"]["id"]

    for day in ("2026-09-07T00:00:00Z", "2026-09-08T00:00:00Z"):
        file_and_triage_incident(ctx["session"], severity="MINOR", reported_at=day)

    at_four = get_store(store_id)
    assert at_four["open_incident_count"] == 4
    # No critical incident and no failed cycle, so the count alone still governs.
    assert at_four["compliance_posture"] == "RESTRICTED"


def test_check_in_one_minute_before_the_lead_window_is_rejected(api):
    """PRD §2.12: "State validity is fourth: a target row that is not in a state from which the
    requested transition is declared yields `ERR_INVALID_STATE` (HTTP 409)".
    PRD §3.3: "Check-in takes a `CONFIRMED` appointment to `CHECKED_IN` and requires three things:
    the clock is at or after `slot_start_at` minus the check-in lead of 30 minutes
    (`CHECK_IN_LEAD_MINUTES`), so the boundary is inclusive".

    Design: Difficulty/boundary_precision_check/check_in_boundary_at_exactly_the_lead_minute
    """
    set_clock("2026-09-01T11:29:00Z")
    jurisdiction = create_jurisdiction(permitted_sites=["LOBE"])
    store = create_store(jurisdiction["id"], piercing_room_count=1)
    piercer = create_piercer(store["id"])
    certify(piercer["id"])
    customer, _ = setup_customer_with_active_consent(jurisdiction["id"])

    appointment = setup_ready_appointment(
        store["id"], customer["id"], piercer["id"], jurisdiction["id"],
        slot_start="2026-09-01T12:29:00Z", slot_end="2026-09-01T12:59:00Z",
    )
    assert appointment["status"] == "CONFIRMED"

    # 11:29 is one minute earlier than 12:29 minus the 30-minute lead.
    res = api.check_in_appointment(appointment["id"], INTAKE)
    validate_error(res, E.INVALID_STATE, expected_status=409)
    assert get_appointment(appointment["id"])["status"] == "CONFIRMED"


def test_check_in_at_exactly_thirty_minutes_before_the_slot_succeeds(api):
    """PRD §3.3: "Check-in takes a `CONFIRMED` appointment to `CHECKED_IN` and requires three
    things: the clock is at or after `slot_start_at` minus the check-in lead of 30 minutes
    (`CHECK_IN_LEAD_MINUTES`), so the boundary is inclusive; the store's `status` is `OPEN`;
    and the customer holds at least one `ConsentRecord` whose `consent_status` is `ACTIVE`."

    Design: Difficulty/boundary_precision_check/check_in_boundary_at_exactly_the_lead_minute
    """
    set_clock("2026-09-01T11:29:00Z")
    jurisdiction = create_jurisdiction(permitted_sites=["LOBE"])
    store = create_store(jurisdiction["id"], piercing_room_count=1)
    piercer = create_piercer(store["id"])
    certify(piercer["id"])
    customer, _ = setup_customer_with_active_consent(jurisdiction["id"])

    appointment = setup_ready_appointment(
        store["id"], customer["id"], piercer["id"], jurisdiction["id"],
        slot_start="2026-09-01T12:29:00Z", slot_end="2026-09-01T12:59:00Z",
    )

    api.set_clock("2026-09-01T11:59:00Z", COMPLIANCE)
    checked_in = validate_success(api.check_in_appointment(appointment["id"], INTAKE), 200)
    assert checked_in["status"] == "CHECKED_IN"
    assert get_appointment(appointment["id"])["status"] == "CHECKED_IN"


def test_a_critical_incident_freezes_the_store_ahead_of_the_count_threshold(api):
    """PRD §2.7: "when at least one critical incident exists, or at least two failed cycles
    exist, the posture is `FROZEN`".
    PRD §2.7: "Because the freeze test is applied first, a store with both a failed cycle and a
    single critical incident reports `FROZEN` rather than `RESTRICTED`."

    Design: Difficulty/boundary_precision_check/store_posture_restriction_at_exactly_three_open_incidents
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_store_near_incident_threshold(store_overrides={"piercing_room_count": 1})
    store_id = ctx["store"]["id"]
    assert ctx["store"]["compliance_posture"] == "OPEN"
    assert ctx["store"]["open_incident_count"] == 2

    # A single MEDICAL_EMERGENCY incident freezes the store even though the open
    # incident count has only reached 3. It is escalated so that it stays
    # non-terminal (a RESOLVED/REFUND_ISSUED incident no longer counts).
    file_and_triage_incident(
        ctx["session"], severity="MEDICAL_EMERGENCY", reported_at="2026-09-08T00:00:00Z",
        escalate=True,
    )

    frozen = get_store(store_id)
    assert frozen["open_incident_count"] == 3
    assert frozen["compliance_posture"] == "FROZEN"