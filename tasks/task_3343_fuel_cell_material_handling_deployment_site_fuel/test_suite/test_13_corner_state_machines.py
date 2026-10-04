"""Corner coverage — state machine edges: terminal lockdowns, invalid
transitions, clock-driven transitions, and conditional cascades
(PRD §2.5, §3.1, §3.3, §3.4, §3.6, §3.8).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    set_clock, create_site, create_technician,
    create_approved_assessment, create_scheduled_plan, create_event,
    start_event, complete_event, tech_headers,
    create_draft_invoice, create_planned_station,
    create_training_record_payload, create_conversion_plan_payload,
    MANAGER, SAFETY, COMPLIANCE, BILLING,
)


def test_assessment_terminal_approved_rejects_further_transitions(api):
    """PRD §3.1: "`APPROVED` is terminal for the assessment."
    PRD §2.10: "Fourth, transition legality: the target resource must be in a
    valid from-state for the requested action (`ERR_INVALID_STATE`, HTTP 409)."

    Design: Corner/state_machines/assessment_terminal_approved_rejects_further_transitions
    """
    site = create_site(code="S-SM1")
    ass = create_approved_assessment(
        site["id"], forklift_count=2, duty_cycle_hours_per_day=4.0,
        peak_shift_hours=6)
    resp = api.revise_assessment(site["id"], ass["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_event_start_from_in_progress_rejected(api):
    """PRD §3.4: "Starting an event moves it `SCHEDULED` to `IN_PROGRESS`"
    PRD §2.10: "Fourth, transition legality: the target resource must be in a
    valid from-state for the requested action (`ERR_INVALID_STATE`, HTTP 409)."

    Design: Corner/state_machines/event_start_from_in_progress_rejected_idempotency
    """
    site = create_site(code="S-SM2")
    tech = create_technician(name="Tech SM", certification_level="BASIC")
    create_approved_assessment(
        site["id"], forklift_count=2, duty_cycle_hours_per_day=4.0,
        peak_shift_hours=6)
    plan = create_scheduled_plan(
        site["id"], name="Wave SM", target_forklift_count=1,
        baseline_productivity_units_per_hour=40.0,
        expected_productivity_gain_pct=5)
    ev = create_event(plan["id"], tech["id"], forklift_id="FL-SM",
                      scheduled_start="2026-10-02T08:00:00Z",
                      scheduled_end="2026-10-02T10:00:00Z")
    started = start_event(plan["id"], ev["id"], tech["id"])
    assert started["status"] == "IN_PROGRESS"
    resp = api.start_event(plan["id"], ev["id"], tech_headers(tech["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_success_data(api.get_conversion_event(ev["id"], MANAGER))
    assert after["status"] == "IN_PROGRESS", "the rejected second start changes nothing"


def test_plan_cancel_cascades_only_non_terminal_events(api):
    """PRD §3.4: "A whole plan can be cancelled while `IN_PROGRESS`: the plan
    moves to `CANCELLED` and every event of the plan still in `SCHEDULED` or
    `IN_PROGRESS` cascades down to `CANCELLED` with it. `COMPLETED` and
    `CANCELLED` are terminal for both plans and events."

    Design: Corner/state_machines/plan_cancel_cascades_only_non_terminal_events
    """
    site = create_site(code="S-SM3")
    tech = create_technician(name="Tech CC")
    create_approved_assessment(
        site["id"], forklift_count=3, duty_cycle_hours_per_day=4.0,
        peak_shift_hours=6)
    plan = create_scheduled_plan(
        site["id"], name="Wave CC", target_forklift_count=2,
        transition_mode="PARALLEL", start_date="2026-10-01",
        end_date="2026-10-20", baseline_productivity_units_per_hour=40.0,
        expected_productivity_gain_pct=5)
    eva = create_event(plan["id"], tech["id"], forklift_id="FL-CA",
                       scheduled_start="2026-10-02T08:00:00Z",
                       scheduled_end="2026-10-02T10:00:00Z")
    evb = create_event(plan["id"], tech["id"], forklift_id="FL-CB",
                       scheduled_start="2026-10-03T08:00:00Z",
                       scheduled_end="2026-10-03T10:00:00Z")
    start_event(plan["id"], eva["id"], tech["id"])
    complete_event(plan["id"], eva["id"], tech["id"])
    start_event(plan["id"], evb["id"], tech["id"])
    cancelled = validate_success(api.cancel_plan(site["id"], plan["id"], MANAGER))
    assert cancelled["status"] == "CANCELLED"
    eva_after = get_success_data(api.get_conversion_event(eva["id"], MANAGER))
    evb_after = get_success_data(api.get_conversion_event(evb["id"], MANAGER))
    assert eva_after["status"] == "COMPLETED", "terminal events are untouched"
    assert evb_after["status"] == "CANCELLED", "non-terminal events cascade down"


def test_plan_revert_from_draft_rejected(api):
    """PRD §3.4: "Scheduling is reversible only while nothing has finished:
    reverting returns `SCHEDULED` to `DRAFT`, but only when no conversion event
    of the plan has reached `COMPLETED`."
    PRD §2.10: "Fourth, transition legality: the target resource must be in a
    valid from-state for the requested action (`ERR_INVALID_STATE`, HTTP 409)."

    Design: Corner/state_machines/plan_revert_blocked_after_completed_event
    """
    site = create_site(code="S-SM4")
    plan = get_success_data(api.create_conversion_plan(
        site["id"], create_conversion_plan_payload(
            name="Wave RV", baseline_productivity_units_per_hour=40.0,
            expected_productivity_gain_pct=5), MANAGER))
    resp = api.revert_plan(site["id"], plan["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_invoice_pay_from_draft_rejected(api):
    """PRD §3.6: "an `ISSUED` invoice may be paid (moving to `PAID`, terminal)
    by a `BillingOperator`, or disputed by the customer-side `SiteManager`,
    moving it to `DISPUTED`"
    PRD §2.10: "Fourth, transition legality: the target resource must be in a
    valid from-state for the requested action (`ERR_INVALID_STATE`, HTTP 409)."

    Design: Corner/state_machines/invoice_pay_from_draft_rejected
    """
    site = create_site(code="S-SM5")
    contract = get_success_data(api.create_supply_contract(
        site["id"], {"supply_mode": "PIPELINE", "start_date": "2026-10-01",
                     "end_date": "2026-12-31", "base_price_per_kg": 2.5,
                     "reliability_sla_pct": 99.0, "committed_monthly_kg": 10},
        MANAGER))
    invoice = create_draft_invoice(site["id"], contract["id"])
    resp = api.pay_invoice(invoice["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_training_record_clock_driven_expiry(api):
    """PRD §2.5: "A training record in `VALID` whose `expires_at` is before the
    current date moves to `EXPIRED`."
    PRD §3.8: "A record is born `VALID` and stays so until the logical clock
    passes `expires_at`, at which point it transitions automatically to the
    terminal `EXPIRED` status."

    Design: Corner/state_machines/training_record_clock_driven_expiry
    """
    site = create_site(code="S-SM6")
    record = get_success_data(api.create_training_record(
        site["id"], create_training_record_payload(
            trainee_employee_id="EMP-1", course_code="H2_BASIC",
            completed_at="2026-09-01", expires_at="2026-10-10"), MANAGER))
    assert record["status"] == "VALID"
    set_clock("2026-10-11T00:00:00Z")
    after = get_success_data(api.get_training_record(record["id"], SAFETY))
    assert after["status"] == "EXPIRED"


def test_station_permitted_cascade_requires_both_permits(api):
    """PRD §3.3: "Construction and fire approvals work as a pair: the moment
    the second of a `PLANNED` station's `CONSTRUCTION` and `FIRE` permits
    reaches `ISSUED`, the station cascades from `PLANNED` to `PERMITTED`."

    Design: Corner/state_machines/station_permitted_cascade_requires_both_permits
    """
    site = create_site(code="S-SM7")
    station = create_planned_station(
        site["id"], station_code="ST-S7", capacity_kg_per_day=100,
        storage_capacity_kg=300, construction_start="2026-10-01",
        construction_end="2026-11-01")
    construction = get_success_data(api.create_permit(
        station["id"], {"permit_type": "CONSTRUCTION",
                        "issued_date": "2026-10-01", "expiry_date": "2027-01-01"},
        MANAGER))
    fire = get_success_data(api.create_permit(
        station["id"], {"permit_type": "FIRE",
                        "issued_date": "2026-10-01", "expiry_date": "2027-01-01"},
        MANAGER))
    validate_success(api.issue_permit(station["id"], construction["id"], COMPLIANCE))
    mid = get_success_data(api.get_station(station["id"], COMPLIANCE))
    assert mid["construction_status"] == "PLANNED", (
        "one issued permit of the pair leaves the station PLANNED")
    validate_success(api.issue_permit(station["id"], fire["id"], COMPLIANCE))
    after = get_success_data(api.get_station(station["id"], COMPLIANCE))
    assert after["construction_status"] == "PERMITTED", (
        "the second issued permit of the pair flips the station to PERMITTED")
