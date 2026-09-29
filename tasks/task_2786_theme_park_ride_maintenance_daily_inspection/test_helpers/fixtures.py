"""Composite setup fixtures.

Every helper here drives the API exactly as a client would, using only the
endpoints the PRD declares. The harness resets the database before each test, so
each helper builds its preconditions from nothing.

Server-authored rows are never present in a create response, so the helpers that
need them re-read them from the list endpoint the PRD nominates: item results by
`inspection_id`, fleet actions by `bulletin_id`, auto-opened downtime rows by
`attraction_id`.
"""

import math
from typing import Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .constants import CLOCK_START_DATE, CLOCK_START_INSTANT, NDT
from .test_users import (
    ADMIN,
    INSPECTOR,
    MANAGER,
    OPERATOR,
    SAFETY_OFFICER,
    TECHNICIAN,
    make_maintenance_technician_headers,
    make_qualified_inspector_headers,
)

DEFAULT_TECHNICIAN_BADGE = "tech-1"
DEFAULT_INSPECTOR_BADGE = "insp-1"


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str, headers: Dict = ADMIN) -> dict:
    """Move the logical clock and return the reported instant."""
    return get_success_data(
        api_client.set_clock(factories.set_clock_payload(to_iso8601), headers)
    )


# ---------------------------------------------------------------------------
# Tier 1 — single rows in their initial state
# ---------------------------------------------------------------------------
def create_attraction(headers: Dict = ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_attraction(
            factories.create_attraction_payload(**overrides), headers
        )
    )


def read_attraction(attraction_id: str, headers: Dict = ADMIN) -> dict:
    return get_success_data(api_client.get_attraction(attraction_id, headers))


def log_cycles(
    attraction_id: str,
    cycles_added: int,
    service_date: str = CLOCK_START_DATE,
    headers: Dict = TECHNICIAN,
) -> dict:
    return get_success_data(
        api_client.log_cycles(
            attraction_id,
            factories.log_cycles_payload(service_date, cycles_added),
            headers,
        )
    )


def create_component(attraction_id: str, headers: Dict = ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_component(
            factories.create_component_payload(attraction_id, **overrides), headers
        )
    )


def read_component(component_id: str, headers: Dict = ADMIN) -> dict:
    return get_success_data(api_client.get_component(component_id, headers))


def record_ndt(
    component_id: str,
    ndt_method: str = "ULTRASONIC",
    result: str = "PASS",
    headers: Dict = INSPECTOR,
) -> dict:
    return get_success_data(
        api_client.record_ndt(
            component_id, factories.record_ndt_payload(ndt_method, result), headers
        )
    )


def create_shop_bay(
    name: str = "Bay 1", concurrent_slot_capacity: int = 1, headers: Dict = ADMIN
) -> dict:
    return get_success_data(
        api_client.create_shop_bay(
            factories.create_shop_bay_payload(name, concurrent_slot_capacity), headers
        )
    )


def read_shop_bay(shop_bay_id: str, headers: Dict = MANAGER) -> dict:
    return get_success_data(api_client.get_shop_bay(shop_bay_id, headers))


def create_certification(
    attraction_id: str, headers: Dict = MANAGER, **overrides
) -> dict:
    return get_success_data(
        api_client.create_operator_certification(
            factories.create_operator_certification_payload(attraction_id, **overrides),
            headers,
        )
    )


def create_certifications_with_restraint_scores(
    attraction_id: str,
    restraint_scores: Sequence[int],
    dispatch_procedure_score: int = 90,
    effective_from: str = CLOCK_START_INSTANT,
    expires_at: str = "2026-12-31T00:00:00.000Z",
) -> List[dict]:
    """One certification per supplied restraint score, each on its own badge."""
    created = []
    for index, score in enumerate(restraint_scores, start=1):
        created.append(
            create_certification(
                attraction_id,
                operator_user_id=f"op-{index}",
                effective_from=effective_from,
                expires_at=expires_at,
                restraint_verification_score=score,
                dispatch_procedure_score=dispatch_procedure_score,
            )
        )
    return created


def create_incident(attraction_id: str, headers: Dict = SAFETY_OFFICER, **overrides) -> dict:
    return get_success_data(
        api_client.create_incident(
            factories.create_incident_payload(attraction_id, **overrides), headers
        )
    )


def create_bulletin(
    bulletin_ref: str = "SB-2026-001", headers: Dict = ADMIN, **overrides
) -> dict:
    return get_success_data(
        api_client.create_bulletin(
            factories.create_bulletin_payload(bulletin_ref, **overrides), headers
        )
    )


def create_requisition(attraction_id: str, headers: Dict = TECHNICIAN, **overrides) -> dict:
    return get_success_data(
        api_client.create_part_requisition(
            factories.create_part_requisition_payload(attraction_id, **overrides),
            headers,
        )
    )


# ---------------------------------------------------------------------------
# Tier 2 — templates and their checklist lines
# ---------------------------------------------------------------------------
def create_template(
    attraction_id: str,
    effective_from_date: str = "2026-07-01",
    headers: Dict = ADMIN,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_inspection_template(
            factories.create_inspection_template_payload(
                attraction_id, effective_from_date, **overrides
            ),
            headers,
        )
    )


def append_line(
    template_id: str,
    sequence_no: int,
    severity_class: str = "ADVISORY",
    description: Optional[str] = None,
    headers: Dict = ADMIN,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.append_checklist_item(
            template_id,
            factories.append_checklist_item_payload(
                sequence_no,
                description or f"Checklist line {sequence_no}",
                severity_class,
                **overrides,
            ),
            headers,
        )
    )


def activate_template(template_id: str, attraction_id: str, headers: Dict = ADMIN) -> dict:
    """Read the attraction's live version, then activate with it.

    PRD §2.7: "`POST /park-ops/inspection-templates/{id}/activate` requires
    `expected_attraction_version`, matched against the parent attraction's current
    `version`."
    """
    attraction = read_attraction(attraction_id, headers)
    return get_success_data(
        api_client.activate_inspection_template(
            template_id,
            factories.activate_inspection_template_payload(attraction["version"]),
            headers,
        )
    )


def attraction_with_active_template(
    line_severities: Sequence[str] = ("ESSENTIAL",),
    component_ids: Optional[Sequence[Optional[str]]] = None,
    requires_photo_flags: Optional[Sequence[bool]] = None,
    effective_from_date: str = "2026-07-01",
    attraction: Optional[dict] = None,
    **attraction_overrides,
) -> dict:
    """One attraction carrying an ACTIVE template with the requested lines.

    Returns ``{"attraction", "template", "items"}``; ``items`` is in sequence order.
    """
    if attraction is None:
        attraction = create_attraction(**attraction_overrides)
    template = create_template(
        attraction["id"], effective_from_date=effective_from_date
    )
    items = []
    for index, severity_class in enumerate(line_severities):
        line_overrides = {}
        if component_ids is not None and component_ids[index] is not None:
            line_overrides["component_id"] = component_ids[index]
        if requires_photo_flags is not None:
            line_overrides["requires_photo"] = requires_photo_flags[index]
        items.append(
            append_line(
                template["id"],
                sequence_no=index + 1,
                severity_class=severity_class,
                **line_overrides,
            )
        )
    activated = activate_template(template["id"], attraction["id"])
    return {
        "attraction": read_attraction(attraction["id"]),
        "template": activated,
        "items": items,
    }


# ---------------------------------------------------------------------------
# Tier 3 — inspections walked along their lifecycle
# ---------------------------------------------------------------------------
def open_inspection(
    attraction_id: str,
    service_date: str = CLOCK_START_DATE,
    technician_badge: str = DEFAULT_TECHNICIAN_BADGE,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_daily_inspection(
            factories.create_daily_inspection_payload(
                attraction_id, service_date, **overrides
            ),
            make_maintenance_technician_headers(technician_badge),
        )
    )


def list_item_results(inspection_id: str, headers: Dict = TECHNICIAN) -> List[dict]:
    """The fanned-out result rows, ordered by the sequence_no of the line each answers.

    PRD §3.2: "the way to discover them is the result list filtered by
    `inspection_id`".
    """
    return get_success_data(
        api_client.list_inspection_item_results(
            headers, params={"inspection_id": inspection_id, "limit": 100}
        )
    )


def record_result(
    result_id: str,
    outcome: str,
    note: Optional[str] = None,
    technician_badge: str = DEFAULT_TECHNICIAN_BADGE,
) -> dict:
    return get_success_data(
        api_client.record_inspection_item_result(
            result_id,
            factories.record_item_result_payload(outcome, note),
            make_maintenance_technician_headers(technician_badge),
        )
    )


def record_outcomes(
    results: Sequence[dict],
    outcomes: Sequence,
    technician_badge: str = DEFAULT_TECHNICIAN_BADGE,
) -> List[dict]:
    """Record one outcome per result row.

    Each entry is either an outcome string or an ``(outcome, note)`` pair.
    """
    recorded = []
    for result, outcome in zip(results, outcomes):
        if isinstance(outcome, (tuple, list)):
            recorded.append(
                record_result(result["id"], outcome[0], outcome[1], technician_badge)
            )
        else:
            recorded.append(record_result(result["id"], outcome, None, technician_badge))
    return recorded


def submit_inspection(
    inspection_id: str, technician_badge: str = DEFAULT_TECHNICIAN_BADGE
) -> dict:
    return get_success_data(
        api_client.submit_daily_inspection(
            inspection_id, make_maintenance_technician_headers(technician_badge)
        )
    )


def sign_off_inspection(
    inspection_id: str, inspector_badge: str = DEFAULT_INSPECTOR_BADGE
) -> dict:
    return get_success_data(
        api_client.sign_off_daily_inspection(
            inspection_id, make_qualified_inspector_headers(inspector_badge)
        )
    )


def reject_inspection(
    inspection_id: str,
    rejection_reason: str = "Rework required",
    inspector_badge: str = DEFAULT_INSPECTOR_BADGE,
) -> dict:
    return get_success_data(
        api_client.reject_daily_inspection(
            inspection_id,
            factories.reject_inspection_payload(rejection_reason),
            make_qualified_inspector_headers(inspector_badge),
        )
    )


def reopen_inspection(
    inspection_id: str, technician_badge: str = DEFAULT_TECHNICIAN_BADGE
) -> dict:
    return get_success_data(
        api_client.reopen_daily_inspection(
            inspection_id, make_maintenance_technician_headers(technician_badge)
        )
    )


def inspection_with_outcomes(
    line_severities: Sequence[str] = ("ESSENTIAL",),
    outcomes: Optional[Sequence] = None,
    service_date: str = CLOCK_START_DATE,
    technician_badge: str = DEFAULT_TECHNICIAN_BADGE,
    component_ids: Optional[Sequence[Optional[str]]] = None,
    effective_from_date: str = "2026-07-01",
    attraction: Optional[dict] = None,
    **attraction_overrides,
) -> dict:
    """Attraction + ACTIVE template + one open inspection with outcomes recorded.

    Returns ``{"attraction", "template", "items", "inspection", "results"}``.
    ``results`` is re-read after recording so it reflects the stored outcomes.
    """
    bundle = attraction_with_active_template(
        line_severities,
        component_ids=component_ids,
        effective_from_date=effective_from_date,
        attraction=attraction,
        **attraction_overrides,
    )
    inspection = open_inspection(
        bundle["attraction"]["id"], service_date, technician_badge
    )
    results = list_item_results(inspection["id"])
    if outcomes:
        record_outcomes(results, outcomes, technician_badge)
        results = list_item_results(inspection["id"])
    bundle["inspection"] = get_success_data(
        api_client.get_daily_inspection(inspection["id"], TECHNICIAN)
    )
    bundle["results"] = results
    bundle["attraction"] = read_attraction(bundle["attraction"]["id"])
    return bundle


def inspection_pending_sign_off(
    line_severities: Sequence[str] = ("ESSENTIAL",),
    outcomes: Optional[Sequence] = None,
    service_date: str = CLOCK_START_DATE,
    technician_badge: str = DEFAULT_TECHNICIAN_BADGE,
    **kwargs,
) -> dict:
    """An inspection with every line answered and then submitted."""
    resolved = outcomes or ["PASS"] * len(line_severities)
    bundle = inspection_with_outcomes(
        line_severities,
        resolved,
        service_date=service_date,
        technician_badge=technician_badge,
        **kwargs,
    )
    bundle["inspection"] = submit_inspection(
        bundle["inspection"]["id"], technician_badge
    )
    bundle["results"] = list_item_results(bundle["inspection"]["id"])
    return bundle


def inspection_signed_off(
    line_severities: Sequence[str] = ("ESSENTIAL",),
    outcomes: Optional[Sequence] = None,
    service_date: str = CLOCK_START_DATE,
    technician_badge: str = DEFAULT_TECHNICIAN_BADGE,
    inspector_badge: str = DEFAULT_INSPECTOR_BADGE,
    **kwargs,
) -> dict:
    bundle = inspection_pending_sign_off(
        line_severities,
        outcomes,
        service_date=service_date,
        technician_badge=technician_badge,
        **kwargs,
    )
    bundle["inspection"] = sign_off_inspection(
        bundle["inspection"]["id"], inspector_badge
    )
    bundle["attraction"] = read_attraction(bundle["attraction"]["id"])
    return bundle


def inspection_rejected(
    line_severities: Sequence[str] = ("ESSENTIAL",),
    outcomes: Optional[Sequence] = None,
    rejection_reason: str = "Rework required",
    technician_badge: str = DEFAULT_TECHNICIAN_BADGE,
    inspector_badge: str = DEFAULT_INSPECTOR_BADGE,
    **kwargs,
) -> dict:
    bundle = inspection_pending_sign_off(
        line_severities, outcomes, technician_badge=technician_badge, **kwargs
    )
    bundle["inspection"] = reject_inspection(
        bundle["inspection"]["id"], rejection_reason, inspector_badge
    )
    bundle["results"] = list_item_results(bundle["inspection"]["id"])
    return bundle


# ---------------------------------------------------------------------------
# Tier 4 — accumulation and threshold targeting
# ---------------------------------------------------------------------------
def ndt_overdue_cycle_ceiling(ndt_interval_cycles: int) -> int:
    """PRD §3.1: "the grace ceiling, which is `ndt_interval_cycles` multiplied by
    1.20 and rounded up to a whole cycle"."""
    return math.ceil(ndt_interval_cycles * NDT["GRACE_FACTOR"])


def component_driven_to_cycles_elapsed(
    cycles_elapsed: int,
    criticality: str = "SAFETY_CRITICAL",
    ndt_interval_cycles: int = 100,
    ndt_interval_days: int = 3650,
    service_date: str = CLOCK_START_DATE,
    attraction: Optional[dict] = None,
    **attraction_overrides,
) -> dict:
    """Attraction + component whose cycles-since-last-test lands on a chosen figure.

    The day interval defaults high so the day comparison can never be the trigger.
    Returns ``{"attraction", "component"}`` with both rows freshly re-read.
    """
    if attraction is None:
        attraction = create_attraction(**attraction_overrides)
    component = create_component(
        attraction["id"],
        criticality=criticality,
        ndt_interval_cycles=ndt_interval_cycles,
        ndt_interval_days=ndt_interval_days,
    )
    if cycles_elapsed:
        log_cycles(attraction["id"], cycles_elapsed, service_date)
    return {
        "attraction": read_attraction(attraction["id"]),
        "component": read_component(component["id"]),
    }


def committed_requisition(
    attraction_id: str,
    total_cost_cents: int,
    status: str = "RESERVED",
    part_number: str = "PN-COMMIT",
    expected_availability_date: str = "2026-09-01",
    **overrides,
) -> dict:
    """A requisition worth exactly ``total_cost_cents`` walked to a chosen status.

    PRD §3.5: "`total_cost_cents` is the `quantity` multiplied by the
    `unit_cost_cents`", so quantity 1 makes the committed figure exact.
    """
    requisition = create_requisition(
        attraction_id,
        quantity=1,
        unit_cost_cents=total_cost_cents,
        part_number=part_number,
        **overrides,
    )
    return walk_requisition_to(requisition, status, expected_availability_date)


def walk_requisition_to(
    requisition: dict,
    status: str,
    expected_availability_date: str = "2026-09-01",
    cancel_reason: str = "No longer required",
) -> dict:
    """Move a requisition on to RESERVED, BACKORDERED, RECEIVED or CANCELLED.

    The walk starts from whatever status the supplied row is already sitting in.
    PRD §3.5: "A requisition that is `RESERVED` or `BACKORDERED` moves to
    `RECEIVED`" — so a row handed in already committed is received directly
    rather than being reserved a second time.
    """
    requisition_id = requisition["id"]
    current = requisition.get("status", "REQUESTED")
    if status == current:
        return requisition
    if status == "REQUESTED":
        return requisition
    if status == "CANCELLED":
        return get_success_data(
            api_client.cancel_part_requisition(
                requisition_id,
                factories.cancel_requisition_payload(cancel_reason),
                MANAGER,
            )
        )
    if status == "BACKORDERED":
        return get_success_data(
            api_client.backorder_part_requisition(
                requisition_id,
                MANAGER,
                {"expected_availability_date": expected_availability_date},
            )
        )
    if status == "RECEIVED":
        if current == "REQUESTED":
            get_success_data(
                api_client.reserve_part_requisition(requisition_id, MANAGER)
            )
        return get_success_data(
            api_client.receive_part_requisition(requisition_id, TECHNICIAN)
        )
    if status == "RESERVED":
        return get_success_data(
            api_client.reserve_part_requisition(requisition_id, MANAGER)
        )
    raise ValueError(f"unsupported requisition status: {status}")


# ---------------------------------------------------------------------------
# Downtime lifecycles
# ---------------------------------------------------------------------------
def open_downtime(
    attraction_id: str,
    started_at: str = "2026-08-01T09:00:00.000Z",
    cause_category: str = "MECHANICAL",
    headers: Dict = TECHNICIAN,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_downtime_event(
            factories.create_downtime_event_payload(
                attraction_id, started_at, cause_category, **overrides
            ),
            headers,
        )
    )


def diagnose_downtime(
    event_id: str,
    root_cause_code: str = "RC-0001",
    failed_component_id: Optional[str] = None,
) -> dict:
    return get_success_data(
        api_client.diagnose_downtime_event(
            event_id,
            factories.diagnose_downtime_payload(root_cause_code, failed_component_id),
            TECHNICIAN,
        )
    )


def resolve_downtime(event_id: str, ended_at: str) -> dict:
    return get_success_data(
        api_client.resolve_downtime_event(
            event_id, factories.resolve_downtime_payload(ended_at), TECHNICIAN
        )
    )


def close_downtime(event_id: str) -> dict:
    return get_success_data(api_client.close_downtime_event(event_id, MANAGER))


def void_downtime(event_id: str, void_reason: str = "Logged in error") -> dict:
    return get_success_data(
        api_client.void_downtime_event(
            event_id, factories.void_downtime_payload(void_reason), MANAGER
        )
    )


def downtime_in_status(
    attraction_id: str,
    status: str,
    started_at: str = "2026-08-01T09:00:00.000Z",
    ended_at: str = "2026-08-01T10:00:00.000Z",
    cause_category: str = "MECHANICAL",
    root_cause_code: str = "RC-0001",
    failed_component_id: Optional[str] = None,
    void_reason: str = "Logged in error",
) -> dict:
    """Walk one downtime event to any of its declared states.

    AWAITING_PARTS is reached the way the PRD declares it: a requisition naming
    the DIAGNOSED event is backordered.
    """
    event = open_downtime(attraction_id, started_at, cause_category)
    if status == "OPEN":
        return event
    diagnosed = diagnose_downtime(event["id"], root_cause_code, failed_component_id)
    if status == "DIAGNOSED":
        return diagnosed
    if status == "AWAITING_PARTS":
        requisition = create_requisition(
            attraction_id, part_number="PN-PARK", downtime_event_id=event["id"]
        )
        walk_requisition_to(requisition, "BACKORDERED")
        return get_success_data(api_client.get_downtime_event(event["id"], TECHNICIAN))
    resolved = resolve_downtime(event["id"], ended_at)
    if status == "RESOLVED":
        return resolved
    closed = close_downtime(event["id"])
    if status == "CLOSED":
        return closed
    if status == "VOIDED":
        return void_downtime(event["id"], void_reason)
    raise ValueError(f"unsupported downtime status: {status}")


def closed_downtime_window(
    attraction_id: str, windows: Sequence[Tuple[str, str]]
) -> List[dict]:
    """One CLOSED downtime event per ``(started_at, ended_at)`` pair, in order."""
    events = []
    for started_at, ended_at in windows:
        event = open_downtime(attraction_id, started_at)
        diagnose_downtime(event["id"])
        resolve_downtime(event["id"], ended_at)
        events.append(close_downtime(event["id"]))
    return events


def auto_opened_downtime_events(attraction_id: str) -> List[dict]:
    """The system-authored downtime rows for an attraction.

    PRD §3.4: "Auto-opened rows are distinguishable from operator-logged rows by
    `auto_opened` reading true and `cause_category` reading `INSPECTION_FAIL`."
    """
    events = get_success_data(
        api_client.list_downtime_events(
            MANAGER, params={"attraction_id": attraction_id, "limit": 100}
        )
    )
    return [event for event in events if event["auto_opened"]]


# ---------------------------------------------------------------------------
# Bulletins and the fleet fan-out
# ---------------------------------------------------------------------------
def list_bulletin_actions(bulletin_id: str, headers: Dict = MANAGER) -> List[dict]:
    """The fanned-out fleet actions, in the attraction `created_at` order the PRD fixes."""
    return get_success_data(
        api_client.list_bulletin_actions(
            headers, params={"bulletin_id": bulletin_id, "limit": 100}
        )
    )


def acknowledge_bulletin(bulletin_id: str, manager_badge: str = "mgr-1") -> dict:
    from .test_users import make_maintenance_manager_headers

    return get_success_data(
        api_client.acknowledge_bulletin(
            bulletin_id, make_maintenance_manager_headers(manager_badge)
        )
    )


def acknowledged_bulletin_with_actions(
    bulletin_ref: str = "SB-2026-001",
    manufacturer: str = "Vekoma",
    model_code: str = "TA-1",
    severity: str = "MANDATORY",
    attraction_count: int = 1,
    ride_classes: Optional[Sequence[str]] = None,
    manager_badge: str = "mgr-1",
    attractions: Optional[Sequence[dict]] = None,
    **bulletin_overrides,
) -> dict:
    """Matching attractions + one acknowledged bulletin + its PENDING fleet actions.

    Returns ``{"bulletin", "actions", "attractions"}``. ``actions[i]`` answers
    ``attractions[i]`` because the fan-out follows attraction creation order.
    """
    if attractions is None:
        built = []
        for index in range(attraction_count):
            ride_class = (
                ride_classes[index] if ride_classes is not None else "THRILL"
            )
            built.append(
                create_attraction(
                    name=f"Fleet Attraction {index + 1}",
                    manufacturer=manufacturer,
                    model_code=model_code,
                    ride_class=ride_class,
                )
            )
        attractions = built
    bulletin = create_bulletin(
        bulletin_ref,
        manufacturer=manufacturer,
        model_code=model_code,
        severity=severity,
        **bulletin_overrides,
    )
    acknowledged = acknowledge_bulletin(bulletin["id"], manager_badge)
    return {
        "bulletin": acknowledged,
        "actions": list_bulletin_actions(bulletin["id"]),
        "attractions": list(attractions),
    }


def start_action(action_id: str) -> dict:
    return get_success_data(api_client.start_bulletin_action(action_id, TECHNICIAN))


def verify_action(action_id: str, inspector_badge: str = DEFAULT_INSPECTOR_BADGE) -> dict:
    return get_success_data(
        api_client.verify_bulletin_action(
            action_id, make_qualified_inspector_headers(inspector_badge)
        )
    )


def defer_action(
    action_id: str,
    deferral_reason: str = "Awaiting factory kit",
    deferred_until_date: str = "2026-09-01",
) -> dict:
    return get_success_data(
        api_client.defer_bulletin_action(
            action_id,
            factories.defer_bulletin_action_payload(
                deferral_reason, deferred_until_date
            ),
            MANAGER,
        )
    )


# ---------------------------------------------------------------------------
# Incidents and the regulatory hold
# ---------------------------------------------------------------------------
def held_incident(
    attraction_id: str, injury_severity: str = "MINOR", **overrides
) -> dict:
    """An incident sitting in RIDE_HELD, so the attraction carries the hold.

    A NONE or MINOR incident opens in REPORTED and needs the explicit escalation;
    a SERIOUS or FATAL one is already held at creation.
    """
    incident = create_incident(
        attraction_id, injury_severity=injury_severity, **overrides
    )
    if incident["status"] == "RIDE_HELD":
        return incident
    return get_success_data(api_client.hold_ride(incident["id"], SAFETY_OFFICER))


def clear_incident_internally(
    incident_id: str, regulator_clearance_ref: Optional[str] = None
) -> dict:
    """Take the internal-review branch and clear, releasing the hold."""
    get_success_data(api_client.investigate_incident(incident_id, SAFETY_OFFICER))
    get_success_data(api_client.close_internal_review(incident_id, SAFETY_OFFICER))
    return get_success_data(
        api_client.clear_incident(
            incident_id, SAFETY_OFFICER, factories.clear_incident_payload(regulator_clearance_ref)
        )
    )


# ---------------------------------------------------------------------------
# Tier 5 — shop bays, overhaul bookings and terminal phases
# ---------------------------------------------------------------------------
def book_work_order(
    attraction_id: str,
    component_id: str,
    shop_bay: Optional[dict] = None,
    bay_name: str = "Bay 1",
    concurrent_slot_capacity: int = 1,
    **overrides,
) -> dict:
    """One SCHEDULED work order plus the bay it occupies.

    Returns ``{"work_order", "shop_bay"}``; the bay is re-read after the booking so
    its `version` and `booked_order_count` are current.
    """
    if shop_bay is None:
        shop_bay = create_shop_bay(bay_name, concurrent_slot_capacity)
    work_order = get_success_data(
        api_client.create_overhaul_work_order(
            factories.create_overhaul_work_order_payload(
                attraction_id,
                component_id,
                shop_bay["id"],
                shop_bay["version"],
                **overrides,
            ),
            MANAGER,
        )
    )
    return {"work_order": work_order, "shop_bay": read_shop_bay(shop_bay["id"])}


def advance_work_order(work_order_id: str, target_phase: str) -> dict:
    return get_success_data(
        api_client.advance_overhaul_work_order(
            work_order_id, factories.advance_work_order_payload(target_phase), MANAGER
        )
    )


def work_order_at_phase(
    attraction_id: str,
    component_id: str,
    target_phase: str,
    shop_bay: Optional[dict] = None,
    **overrides,
) -> dict:
    """Book a work order and walk it down the pipeline to a chosen phase.

    PRD §3.9: the pipeline is "SCHEDULED -> TEARDOWN -> INSPECTION -> REBUILD ->
    RECOMMISSIONED", so each hop is taken in turn.
    """
    booked = book_work_order(attraction_id, component_id, shop_bay=shop_bay, **overrides)
    pipeline = ["TEARDOWN", "INSPECTION", "REBUILD", "RECOMMISSIONED"]
    work_order = booked["work_order"]
    if target_phase != "SCHEDULED":
        for phase in pipeline:
            work_order = advance_work_order(work_order["id"], phase)
            if phase == target_phase:
                break
    return {"work_order": work_order, "shop_bay": read_shop_bay(booked["shop_bay"]["id"])}


# ---------------------------------------------------------------------------
# Cross-entity composites
# ---------------------------------------------------------------------------
def blocked_inspection_from_safety_critical_failure(
    service_date: str = CLOCK_START_DATE,
    technician_badge: str = DEFAULT_TECHNICIAN_BADGE,
    ndt_interval_cycles: int = 60000,
    **attraction_overrides,
) -> dict:
    """An attraction whose current inspection is BLOCKED by a SAFETY_CRITICAL failure.

    Returns ``{"attraction", "component", "template", "items", "inspection",
    "results", "auto_downtime"}``.
    """
    attraction = create_attraction(**attraction_overrides)
    component = create_component(
        attraction["id"],
        criticality="SAFETY_CRITICAL",
        ndt_interval_cycles=ndt_interval_cycles,
        ndt_interval_days=3650,
    )
    bundle = inspection_with_outcomes(
        line_severities=("SAFETY_CRITICAL", "ADVISORY"),
        outcomes=[("FAIL", "Below the declared minimum"), "PASS"],
        service_date=service_date,
        technician_badge=technician_badge,
        component_ids=(component["id"], None),
        attraction=attraction,
    )
    bundle["component"] = read_component(component["id"])
    auto_events = auto_opened_downtime_events(attraction["id"])
    bundle["auto_downtime"] = auto_events[0] if auto_events else None
    return bundle


def attraction_open_for_service(
    line_severities: Sequence[str] = ("ESSENTIAL",),
    restraint_scores: Sequence[int] = (90,),
    min_operators_required: int = 1,
    service_date: str = CLOCK_START_DATE,
    **attraction_overrides,
) -> dict:
    """An attraction whose posture derives OPEN: signed off today, no downtime, no hold.

    Certifications are added before the sign-off so the readiness read has an input
    set. Returns ``{"attraction", "template", "items", "inspection", "results",
    "certifications"}``.
    """
    attraction = create_attraction(
        min_operators_required=min_operators_required, **attraction_overrides
    )
    certifications = create_certifications_with_restraint_scores(
        attraction["id"], restraint_scores
    )
    bundle = inspection_signed_off(
        line_severities,
        outcomes=["PASS"] * len(line_severities),
        service_date=service_date,
        attraction=attraction,
    )
    bundle["certifications"] = certifications
    return bundle
