"""Composite setup helpers.

Every test starts against an empty database, so each helper builds its
preconditions from scratch using only endpoints the PRD declares.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_circuit_payload, create_crew_assignment_payload, create_crew_payload,
    create_customer_notification_payload, create_hazard_tree_payload,
    create_herbicide_permit_payload, create_outage_record_payload,
    create_prescription_payload, create_production_entry_payload,
    create_storm_event_payload, create_work_order_payload, create_work_plan_payload,
)
from .test_users import (
    ARBORIST_A_ID, ARBORIST_B_ID, TEST_USERS, make_arborist_headers,
    make_crew_foreman_headers,
)

FORESTER = TEST_USERS["forester_headers"]
PLANNER = TEST_USERS["planner_headers"]
ADVOCATE = TEST_USERS["advocate_headers"]
ANALYST = TEST_USERS["analyst_headers"]
ADMIN = TEST_USERS["admin_headers"]
ARBORIST_A = TEST_USERS["arborist_headers"]
ARBORIST_B = TEST_USERS["arborist_b_headers"]


# =====================================================================
# Tier 1 — single-step builders
# =====================================================================

def new_prescription(activate=True, **overrides) -> dict:
    """Author a prescription and (by default) activate it."""
    presc = get_success_data(
        api_client.create_prescription(create_prescription_payload(**overrides), FORESTER))
    if activate:
        presc = get_success_data(api_client.activate_prescription(presc["id"], FORESTER))
    return presc


def new_circuit(**overrides) -> dict:
    return get_success_data(
        api_client.create_circuit(create_circuit_payload(**overrides), FORESTER))


def new_work_plan(circuit_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_work_plan(create_work_plan_payload(circuit_id, **overrides), FORESTER))


def new_work_order(work_plan_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_work_order(create_work_order_payload(work_plan_id, **overrides), PLANNER))


def map_span(work_order_id, clearance_radius_ft=12, **extra) -> dict:
    payload = {"clearance_radius_ft": clearance_radius_ft}
    payload.update(extra)
    return get_success_data(api_client.map_work_order(work_order_id, payload, PLANNER))


def release_plan(work_plan_id) -> dict:
    return get_success_data(api_client.release_work_plan(work_plan_id, PLANNER))


def release_span(work_order_id) -> dict:
    return get_success_data(api_client.release_work_order(work_order_id, PLANNER))


def start_span(work_order_id) -> dict:
    return get_success_data(api_client.start_work_order(work_order_id, PLANNER))


def complete_span(work_order_id) -> dict:
    return get_success_data(api_client.complete_work_order(work_order_id, PLANNER))


def new_crew(**overrides) -> dict:
    return get_success_data(api_client.create_crew(create_crew_payload(**overrides), PLANNER))


def new_booking(work_order_id, crew_id, **overrides) -> dict:
    return get_success_data(api_client.create_crew_assignment(
        create_crew_assignment_payload(work_order_id, crew_id, **overrides), PLANNER))


def file_production(crew_assignment_id, crew_id, **overrides) -> dict:
    """File one day of production as the CrewForeman of the booked crew."""
    return get_success_data(api_client.create_production_entry(
        create_production_entry_payload(crew_assignment_id, **overrides),
        make_crew_foreman_headers(crew_id)))


def new_storm(**overrides) -> dict:
    return get_success_data(
        api_client.create_storm_event(create_storm_event_payload(**overrides), FORESTER))


def new_active_storm(**overrides) -> dict:
    storm = new_storm(**overrides)
    return get_success_data(api_client.activate_storm_event(storm["id"], FORESTER))


def new_outage(circuit_id, **overrides) -> dict:
    return get_success_data(api_client.create_outage_record(
        create_outage_record_payload(circuit_id, **overrides), FORESTER))


def new_notification(work_order_id, **overrides) -> dict:
    return get_success_data(api_client.create_customer_notification(
        create_customer_notification_payload(work_order_id, **overrides), ADVOCATE))


def new_hazard_tree(circuit_id, identified_by=ARBORIST_A_ID, **overrides) -> dict:
    return get_success_data(api_client.create_hazard_tree(
        create_hazard_tree_payload(circuit_id, **overrides), make_arborist_headers(identified_by)))


def new_permit(circuit_id, **overrides) -> dict:
    return get_success_data(api_client.create_herbicide_permit(
        create_herbicide_permit_payload(circuit_id, **overrides), ARBORIST_A))


def approve_permit(permit_id) -> dict:
    return get_success_data(
        api_client.decide_herbicide_permit(permit_id, {"outcome": "APPROVE"}, FORESTER))


def set_clock(to_iso8601) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def current_version(work_order_id) -> int:
    """The span's live version, for the OCC guard on billing-line drafting."""
    return get_success_data(api_client.get_work_order(work_order_id, ANALYST))["version"]


def current_crew_version(crew_id) -> int:
    return get_success_data(api_client.get_crew(crew_id, PLANNER))["version"]


# =====================================================================
# Tier 2 — entity hierarchy
# =====================================================================

def setup_circuit(voltage_class="DISTRIBUTION_12KV", growth_zone="RAPID",
                  base_cycle_years=4, prescription_clearance_ft=10,
                  effective_from="2026-01-01", circuit_code="CKT-A",
                  customer_count=1200, last_trim_completed_on="2024-03-15",
                  **presc_overrides) -> dict:
    """One ACTIVE prescription plus a circuit resolved onto it.

    Returns {"prescription": ..., "circuit": ...}.
    """
    presc = new_prescription(
        voltage_class=voltage_class, growth_zone=growth_zone,
        base_cycle_years=base_cycle_years,
        clearance_radius_ft=prescription_clearance_ft,
        effective_from=effective_from, **presc_overrides)
    circuit = new_circuit(
        circuit_code=circuit_code, voltage_class=voltage_class,
        growth_zone=growth_zone, customer_count=customer_count,
        last_trim_completed_on=last_trim_completed_on)
    return {"prescription": presc, "circuit": circuit}


def setup_plan_with_mapped_span(budget_cents=5_000_000, span_miles=2.5,
                                billing_method="UNIT_PRICE", planned_unit_count=200,
                                span_clearance_ft=12, program_year=2026,
                                planned_span_miles=10, extra_spans=None,
                                **circuit_kwargs) -> dict:
    """ACTIVE prescription + circuit + DRAFT plan + one MAPPED span.

    `extra_spans` is a list of `new_work_order` keyword dicts for sibling spans
    that the test needs later in the plan's life. They are created and mapped
    here, while the plan is still in `DRAFT`, because the PRD only permits
    mapping "the owning plan to be in `DRAFT`, `RELEASED` or `IN_PROGRESS`" —
    a plan that has already reached `COMPLETED` (because every one of its spans
    completed) can no longer take a newly mapped span. Holding them at `MAPPED`
    also keeps the plan out of `COMPLETED` when the primary span completes.
    """
    world = setup_circuit(**circuit_kwargs)
    plan = new_work_plan(world["circuit"]["id"], program_year=program_year,
                         planned_span_miles=planned_span_miles, budget_cents=budget_cents)
    span = new_work_order(plan["id"], span_miles=span_miles,
                          billing_method=billing_method,
                          planned_unit_count=planned_unit_count)
    map_span(span["id"], span_clearance_ft)
    world["plan"] = plan
    world["span"] = span
    world["extra_spans"] = []
    for spec in (extra_spans or []):
        spec = dict(spec)
        clearance = spec.pop("span_clearance_ft", span_clearance_ft)
        sibling = new_work_order(plan["id"], **spec)
        world["extra_spans"].append(map_span(sibling["id"], clearance))
    return world


def setup_released_span(**kwargs) -> dict:
    """Plan RELEASED and the span RELEASED, ready to be booked and started."""
    world = setup_plan_with_mapped_span(**kwargs)
    world["plan"] = release_plan(world["plan"]["id"])
    world["span"] = release_span(world["span"]["id"])
    return world


def add_mapped_span(plan_id, span_miles=2.5, billing_method="UNIT_PRICE",
                    planned_unit_count=200, span_clearance_ft=12) -> dict:
    span = new_work_order(plan_id, span_miles=span_miles, billing_method=billing_method,
                          planned_unit_count=planned_unit_count)
    return map_span(span["id"], span_clearance_ft)


def setup_in_progress_span(crew_code="CRW-1", crew_type="BUCKET", headcount=3,
                           hourly_rate_cents=8533, home_district="NORTH",
                           start_at="2026-08-03T08:00:00Z", end_at="2026-08-03T16:00:00Z",
                           **kwargs) -> dict:
    """A RELEASED span with one booked crew, started so the span is IN_PROGRESS."""
    world = setup_released_span(**kwargs)
    crew = new_crew(crew_code=crew_code, crew_type=crew_type, headcount=headcount,
                    hourly_rate_cents=hourly_rate_cents, home_district=home_district)
    booking = new_booking(world["span"]["id"], crew["id"], start_at=start_at, end_at=end_at)
    world["crew"] = crew
    world["booking"] = booking
    world["span"] = start_span(world["span"]["id"])
    return world


def setup_completed_span(units_trimmed=180, labor_hours=8, equipment_hours=6,
                         disposal_tons=1, work_date="2026-08-03", **kwargs) -> dict:
    """A COMPLETED span carrying one production entry — the standard billing base."""
    world = setup_in_progress_span(**kwargs)
    world["entry"] = file_production(
        world["booking"]["id"], world["crew"]["id"], work_date=work_date,
        units_trimmed=units_trimmed, labor_hours=labor_hours,
        equipment_hours=equipment_hours, disposal_tons=disposal_tons)
    world["span"] = complete_span(world["span"]["id"])
    return world


# =====================================================================
# Tier 3 — full lifecycle shortcuts
# =====================================================================

def draft_billing_line(work_order_id, billing_method="UNIT_PRICE") -> dict:
    """Read the span's live version, then draft a line under the OCC guard."""
    version = current_version(work_order_id)
    return get_success_data(api_client.create_billing_line(
        work_order_id,
        {"billing_method": billing_method, "expected_work_order_version": version},
        ANALYST))


def submit_line(line_id) -> dict:
    return get_success_data(api_client.submit_billing_line(line_id, ANALYST))


def review_line(line_id, outcome, dispute_reason=None) -> dict:
    payload = {"outcome": outcome}
    if dispute_reason is not None:
        payload["dispute_reason"] = dispute_reason
    return get_success_data(api_client.review_billing_line(line_id, payload, FORESTER))


def resubmit_line(line_id) -> dict:
    return get_success_data(api_client.resubmit_billing_line(line_id, ANALYST))


def pay_line(line_id) -> dict:
    return get_success_data(api_client.pay_billing_line(line_id, FORESTER))


def setup_completed_span_with_draft_line(billing_method="UNIT_PRICE", **kwargs) -> dict:
    """A COMPLETED span whose only billing line sits in DRAFT."""
    world = setup_completed_span(billing_method=billing_method, **kwargs)
    world["line"] = draft_billing_line(world["span"]["id"], billing_method)
    return world


def setup_completed_span_with_submitted_line(billing_method="UNIT_PRICE", **kwargs) -> dict:
    world = setup_completed_span_with_draft_line(billing_method=billing_method, **kwargs)
    world["line"] = submit_line(world["line"]["id"])
    return world


def complete_prepared_span(span_id, crew_id, units_trimmed=180, labor_hours=8,
                           equipment_hours=6, disposal_tons=1, work_date="2026-08-04",
                           start_at="2026-08-04T08:00:00Z",
                           end_at="2026-08-04T16:00:00Z") -> dict:
    """Walk an already-MAPPED sibling span to COMPLETED.

    Release -> book -> start -> file production -> complete. The span must have
    been created and mapped while the plan was still open (see the `extra_spans`
    argument of `setup_plan_with_mapped_span`).

    Returns {"span": ..., "booking": ..., "entry": ...}.
    """
    span = release_span(span_id)
    booking = new_booking(span_id, crew_id, start_at=start_at, end_at=end_at)
    span = start_span(span_id)
    entry = file_production(booking["id"], crew_id, work_date=work_date,
                            units_trimmed=units_trimmed, labor_hours=labor_hours,
                            equipment_hours=equipment_hours, disposal_tons=disposal_tons)
    span = complete_span(span_id)
    return {"span": span, "booking": booking, "entry": entry}


def add_completed_span(plan_id, crew_id, span_miles=2.5, billing_method="UNIT_PRICE",
                       planned_unit_count=200, span_clearance_ft=12, **kwargs) -> dict:
    """A second (or third) COMPLETED span on a plan that is still open.

    Only valid while the owning plan is in DRAFT, RELEASED or IN_PROGRESS, since
    the new span has to be mapped. Where the plan may already have completed, the
    sibling must instead be pre-created via `extra_spans` and finished with
    `complete_prepared_span`.
    """
    span = new_work_order(plan_id, span_miles=span_miles, billing_method=billing_method,
                          planned_unit_count=planned_unit_count)
    map_span(span["id"], span_clearance_ft)
    return complete_prepared_span(span["id"], crew_id, **kwargs)


# =====================================================================
# Tier 4 — refusal-cycle and hazard-tree targeting
# =====================================================================

def notify(notification_id, contact_method=None) -> dict:
    payload = {} if contact_method is None else {"contact_method": contact_method}
    return get_success_data(
        api_client.notify_customer_notification(notification_id, ADVOCATE, payload))


def respond(notification_id, response) -> dict:
    return get_success_data(api_client.respond_customer_notification(
        notification_id, {"response": response}, ADVOCATE))


def escalate(notification_id) -> dict:
    return get_success_data(
        api_client.escalate_customer_notification(notification_id, ADVOCATE))


def setup_notification_in_state(work_order_id, target_state, premise_code="PRM-1",
                                unit_count_at_premise=30, contact_method="DOOR_HANGER",
                                rounds=2) -> dict:
    """Walk a premise notification to PENDING / NOTIFIED / ACKNOWLEDGED /
    REFUSED / ESCALATED. `rounds` is how many escalations ESCALATED needs."""
    record = new_notification(work_order_id, premise_code=premise_code,
                              contact_method=contact_method,
                              unit_count_at_premise=unit_count_at_premise)
    if target_state == "PENDING":
        return record
    record = notify(record["id"])
    if target_state == "NOTIFIED":
        return record
    if target_state == "ACKNOWLEDGED":
        return respond(record["id"], "ACKNOWLEDGED")
    record = respond(record["id"], "REFUSED")
    if target_state == "REFUSED":
        return record
    if target_state != "ESCALATED":
        raise ValueError(f"unsupported notification state {target_state}")
    record = escalate(record["id"])
    for _ in range(rounds - 1):
        record = notify(record["id"])
        record = respond(record["id"], "REFUSED")
        record = escalate(record["id"])
    return record


def setup_assessed_tree(circuit_id, identified_by=ARBORIST_A_ID,
                        assessed_by=ARBORIST_B_ID, assess_payload=None, **overrides) -> dict:
    """A hazard tree identified by one arborist and assessed by a second."""
    tree = new_hazard_tree(circuit_id, identified_by=identified_by, **overrides)
    return get_success_data(api_client.assess_hazard_tree(
        tree["id"], make_arborist_headers(assessed_by), assess_payload or {}))


# =====================================================================
# Tier 5 — storm preemption and demobilization
# =====================================================================

def reassign_crew_to_storm(storm_id, crew_id, expected_crew_version=None) -> dict:
    version = (current_crew_version(crew_id)
               if expected_crew_version is None else expected_crew_version)
    return get_success_data(api_client.create_storm_reassignment(
        storm_id, {"crew_id": crew_id, "expected_crew_version": version}, PLANNER))


def remainder_child_of(parent_work_order_id) -> dict:
    """The remainder child spawned when a span was storm-preempted."""
    body = api_client.list_work_orders(
        PLANNER, params={"parent_work_order_id": parent_work_order_id}).json()
    rows = body["data"]
    assert rows, f"expected a remainder child under span {parent_work_order_id}"
    return rows[0]


def setup_storm_preempted_span(units_trimmed=10, labor_hours=2, equipment_hours=1,
                               disposal_tons=0, work_date="2026-08-03",
                               event_code="STM-1", severity_level=4,
                               affected_district="NORTH", **kwargs) -> dict:
    """An IN_PROGRESS span whose only crew is pulled onto an ACTIVE storm.

    Returns the world dict plus "storm" and "child" (the remainder span).
    """
    world = setup_in_progress_span(home_district=affected_district, **kwargs)
    world["entry"] = file_production(
        world["booking"]["id"], world["crew"]["id"], work_date=work_date,
        units_trimmed=units_trimmed, labor_hours=labor_hours,
        equipment_hours=equipment_hours, disposal_tons=disposal_tons)
    world["storm"] = new_active_storm(event_code=event_code, severity_level=severity_level,
                                      affected_district=affected_district)
    world["storm"] = reassign_crew_to_storm(world["storm"]["id"], world["crew"]["id"])
    world["child"] = remainder_child_of(world["span"]["id"])
    return world


def setup_active_permit(circuit_id, chemical_code="GLYPHOSATE",
                        window_start="2026-08-01", window_end="2026-08-31",
                        buffer_ft=25, **overrides) -> dict:
    """Request, approve and activate a permit inside its open window."""
    permit = new_permit(circuit_id, chemical_code=chemical_code, buffer_ft=buffer_ft,
                        window_start=window_start, window_end=window_end, **overrides)
    approve_permit(permit["id"])
    return get_success_data(api_client.activate_herbicide_permit(permit["id"], ARBORIST_A))


# =====================================================================
# Read-back helpers — every cascade is settled by the time it responds
# =====================================================================

def read_circuit(circuit_id) -> dict:
    return get_success_data(api_client.get_circuit(circuit_id, FORESTER))


def read_plan(work_plan_id) -> dict:
    return get_success_data(api_client.get_work_plan(work_plan_id, FORESTER))


def read_span(work_order_id) -> dict:
    return get_success_data(api_client.get_work_order(work_order_id, PLANNER))


def read_crew(crew_id) -> dict:
    return get_success_data(api_client.get_crew(crew_id, PLANNER))


def read_booking(assignment_id) -> dict:
    return get_success_data(api_client.get_crew_assignment(assignment_id, PLANNER))


def read_line(line_id) -> dict:
    return get_success_data(api_client.get_billing_line(line_id, ANALYST))


def read_notification(notification_id) -> dict:
    return get_success_data(api_client.get_customer_notification(notification_id, ADVOCATE))


def read_tree(tree_id) -> dict:
    return get_success_data(api_client.get_hazard_tree(tree_id, ARBORIST_A))


def read_permit(permit_id) -> dict:
    return get_success_data(api_client.get_herbicide_permit(permit_id, ARBORIST_A))


def read_storm(storm_id) -> dict:
    return get_success_data(api_client.get_storm_event(storm_id, FORESTER))


def read_prescription(prescription_id) -> dict:
    return get_success_data(api_client.get_prescription(prescription_id, FORESTER))


def read_production_entry(entry_id) -> dict:
    return get_success_data(api_client.get_production_entry(entry_id, PLANNER))


def read_production_summary(work_plan_id) -> dict:
    return get_success_data(api_client.get_production_summary(work_plan_id, PLANNER))


def read_reliability(circuit_id) -> dict:
    return get_success_data(api_client.get_circuit_reliability(circuit_id, FORESTER))
