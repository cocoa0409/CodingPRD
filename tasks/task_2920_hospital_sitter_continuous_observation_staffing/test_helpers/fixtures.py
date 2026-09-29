"""
Composite setup builders.

The harness restarts the API server before every individual test, so every test
begins against an empty database. Nothing here assumes seeded data: each builder
constructs its preconditions from scratch through the PRD-declared endpoints only,
and uses ``get_success_data`` so a failed setup step reports the server's own
``error_id`` instead of a bare KeyError.

Ownership discipline: after creating a ``Staff`` row, any ownership-gated call is
issued with ``make_sitter_headers(staff["id"])`` or
``make_remote_observer_headers(staff["id"])`` — never with a shared identity —
because PRD 2.1 compares an entity-backed caller's ``X-User-ID`` to the resource's
own ``Staff`` reference.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .api_client import canonical_instant, instant
from .constants import (
    CLOCK_START,
    COMPETENCY_ADVANCED,
    MODALITY_ONE_TO_ONE_SITTER,
    MODALITY_VIDEO_MONITORING,
    POOL_INTERNAL_FLOAT,
    RISK_FALL,
)
from .test_users import (
    ADMIN,
    COORDINATOR,
    MANAGER,
    OFFICER_1,
    PROVIDER_1,
    make_remote_observer_headers,
    make_sitter_headers,
)

_OMIT = f._OMIT


# ─── Tier 0: single-entity creates ────────────────────

def make_unit(
    api,
    unit_code: str = "UNIT-1",
    budget_cents: int = 100000,
    video_monitoring_enabled: Any = _OMIT,
    name: str = "Medical Observation Unit",
) -> Dict[str, Any]:
    """Register a nursing unit as the ``NurseManager`` of PRD 3.1."""
    return get_success_data(
        api.create_unit(
            f.unit_payload(
                unit_code=unit_code,
                name=name,
                observation_cost_budget_cents=budget_cents,
                video_monitoring_enabled=video_monitoring_enabled,
            ),
            MANAGER,
        )
    )


def make_patient(
    api,
    unit_id: str,
    mrn: str = "MRN-1000",
    age_years: int = 60,
    full_name: str = "Observation Patient",
) -> Dict[str, Any]:
    """Admit a patient to a unit as the ``NurseManager`` of PRD 3.1."""
    return get_success_data(
        api.create_patient(
            f.patient_payload(unit_id, mrn=mrn, full_name=full_name, age_years=age_years),
            MANAGER,
        )
    )


def make_staff(
    api,
    home_unit_id: str,
    full_name: str = "Observation Sitter",
    source_pool: str = POOL_INTERNAL_FLOAT,
    hourly_rate_cents: int = 2000,
    competency_level: str = COMPETENCY_ADVANCED,
    deescalation_cert_expires_on: str = "2027-01-01T00:00:00Z",
) -> Dict[str, Any]:
    """Register an observer as the ``StaffingCoordinator`` of PRD 3.1."""
    return get_success_data(
        api.create_staff(
            f.staff_payload(
                home_unit_id,
                full_name=full_name,
                source_pool=source_pool,
                hourly_rate_cents=hourly_rate_cents,
                competency_level=competency_level,
                deescalation_cert_expires_on=deescalation_cert_expires_on,
            ),
            COORDINATOR,
        )
    )


def make_order(
    api,
    patient_id: str,
    provider_headers=PROVIDER_1,
    ordering_provider_user_id: Optional[str] = None,
    risk_categories: Optional[List[str]] = None,
    required_modality: str = MODALITY_ONE_TO_ONE_SITTER,
    clinical_rationale: str = "Continuous observation indicated by bedside assessment.",
) -> Dict[str, Any]:
    """Write an observation order as the ``AttendingProvider`` of PRD 3.2."""
    provider_id = ordering_provider_user_id or provider_headers["X-User-ID"]
    return get_success_data(
        api.create_order(
            f.order_payload(
                patient_id,
                provider_id,
                risk_categories=[RISK_FALL] if risk_categories is None else risk_categories,
                required_modality=required_modality,
                clinical_rationale=clinical_rationale,
            ),
            provider_headers,
        )
    )


def make_station(
    api,
    observer_staff_id: str,
    station_label: str = "CONSOLE-1",
    declared_max_span: int = 3,
) -> Dict[str, Any]:
    """Open a remote-observation console as the ``StaffingCoordinator`` of PRD 3.7."""
    return get_success_data(
        api.create_station(
            f.station_payload(
                observer_staff_id,
                station_label=station_label,
                declared_max_span=declared_max_span,
            ),
            COORDINATOR,
        )
    )


def make_assignment(
    api,
    order_id: str,
    staff_id: str,
    shift_start_at: str,
    shift_end_at: str,
    expected_order_version: Optional[int] = None,
    float_authorization_code: Any = _OMIT,
) -> Dict[str, Any]:
    """
    Schedule a watch as the ``StaffingCoordinator`` of PRD 3.4.

    When ``expected_order_version`` is omitted the order is re-read first, which is
    exactly what PRD 2.8 demands: "The check forces the coordinator to re-read the
    order before spending money on it."
    """
    version = (
        expected_order_version
        if expected_order_version is not None
        else read_order(api, order_id)["version"]
    )
    return get_success_data(
        api.create_assignment(
            f.assignment_payload(
                order_id,
                staff_id,
                shift_start_at,
                shift_end_at,
                version,
                float_authorization_code=float_authorization_code,
            ),
            COORDINATOR,
        )
    )


def make_feed(
    api,
    station_id: str,
    order_id: str,
    monitor_start_at: str,
    monitor_end_at: str,
    observer_staff_id: str,
) -> Dict[str, Any]:
    """Admit an order onto a console as its own ``RemoteObserver`` (PRD 3.7)."""
    return get_success_data(
        api.create_feed(
            f.feed_payload(station_id, order_id, monitor_start_at, monitor_end_at),
            make_remote_observer_headers(observer_staff_id),
        )
    )


def make_safety_event(
    api,
    order_id: str,
    event_kind: str,
    reporter_staff_id: str,
    narrative: str = "Observed and documented at the bedside.",
    assignment_id: Any = _OMIT,
    as_remote_observer: bool = False,
) -> Dict[str, Any]:
    """
    Report a safety event as PRD 3.8's only permitted reporters.

    Reporting "is the one write reserved to ``Sitter`` and ``RemoteObserver`` with
    no administrative substitute", so setup can never shortcut this through an
    admin identity.
    """
    headers = (
        make_remote_observer_headers(reporter_staff_id)
        if as_remote_observer
        else make_sitter_headers(reporter_staff_id)
    )
    return get_success_data(
        api.create_safety_event(
            f.safety_event_payload(
                order_id,
                event_kind,
                narrative=narrative,
                assignment_id=assignment_id,
            ),
            headers,
        )
    )


def make_reassessment(
    api,
    order_id: str,
    risk_categories_after: List[str],
    provider_headers=PROVIDER_1,
) -> Dict[str, Any]:
    """Record a reassessment as the ``AttendingProvider`` of PRD 3.3."""
    return get_success_data(
        api.create_reassessment(
            order_id, f.reassessment_payload(risk_categories_after), provider_headers
        )
    )


def make_handoff(
    api,
    outgoing_assignment_id: str,
    incoming_assignment_id: str,
    outgoing_staff_id: str,
    behavior_summary: str = "Patient calm, redirected twice, no attempts to rise.",
    interventions_used: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Draft handoff documentation as the outgoing watch's own ``Sitter`` (PRD 3.6)."""
    return get_success_data(
        api.create_handoff(
            f.handoff_payload(
                outgoing_assignment_id,
                incoming_assignment_id,
                behavior_summary=behavior_summary,
                interventions_used=interventions_used,
            ),
            make_sitter_headers(outgoing_staff_id),
        )
    )


def advance_clock(api, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock as the ``SystemAdmin`` of PRD 2.4 and run the sweep."""
    return get_success_data(api.set_clock(f.clock_payload(current_utc), ADMIN))


# ─── Read helpers ─────────────────────────────────────

def read_unit(api, unit_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_unit(unit_id, MANAGER))


def read_patient(api, patient_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_patient(patient_id, MANAGER))


def read_staff(api, staff_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_staff(staff_id, COORDINATOR))


def read_order(api, order_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_order(order_id, PROVIDER_1))


def read_assignment(api, assignment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_assignment(assignment_id, COORDINATOR))


def read_station(api, station_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_station(station_id, COORDINATOR))


def read_feed(api, feed_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_feed(feed_id, COORDINATOR))


def read_event(api, event_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_safety_event(event_id, OFFICER_1))


def read_handoff(api, handoff_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_handoff(handoff_id, COORDINATOR))


def read_reassessment(api, reassessment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_reassessment(reassessment_id, PROVIDER_1))


def _all_rows(response) -> List[Dict[str, Any]]:
    rows, _meta = validate_paginated(response)
    return rows


def unit_cost_entries(api, unit_id: str, params: Optional[Dict] = None) -> List[Dict[str, Any]]:
    query = {"limit": 100}
    if params:
        query.update(params)
    return _all_rows(api.list_unit_cost_entries(unit_id, MANAGER, query))


def assignment_cost_entries(api, assignment_id: str) -> List[Dict[str, Any]]:
    return _all_rows(api.list_assignment_cost_entries(assignment_id, COORDINATOR, {"limit": 100}))


def order_assignments(api, order_id: str) -> List[Dict[str, Any]]:
    return _all_rows(api.list_order_assignments(order_id, COORDINATOR, {"limit": 100}))


def order_feeds(api, order_id: str) -> List[Dict[str, Any]]:
    return _all_rows(api.list_order_feeds(order_id, COORDINATOR, {"limit": 100}))


def order_reassessments(api, order_id: str) -> List[Dict[str, Any]]:
    return _all_rows(api.list_order_reassessments(order_id, PROVIDER_1, {"limit": 100}))


def order_safety_events(api, order_id: str) -> List[Dict[str, Any]]:
    return _all_rows(api.list_order_safety_events(order_id, OFFICER_1, {"limit": 100}))


def station_feeds(api, station_id: str) -> List[Dict[str, Any]]:
    return _all_rows(api.list_station_feeds(station_id, COORDINATOR, {"limit": 100}))


def staff_stations(api, staff_id: str) -> List[Dict[str, Any]]:
    return _all_rows(api.list_staff_stations(staff_id, COORDINATOR, {"limit": 100}))


def staff_assignments(api, staff_id: str) -> List[Dict[str, Any]]:
    return _all_rows(api.list_staff_assignments(staff_id, COORDINATOR, {"limit": 100}))


def assignment_handoffs(api, assignment_id: str) -> List[Dict[str, Any]]:
    return _all_rows(api.list_assignment_handoffs(assignment_id, COORDINATOR, {"limit": 100}))


def patient_orders(api, patient_id: str) -> List[Dict[str, Any]]:
    return _all_rows(api.list_patient_orders(patient_id, PROVIDER_1, {"limit": 100}))


def unit_head(api, unit_id: str) -> int:
    """The unit's recomputed ledger head, PRD 2.10's conserved quantity."""
    return read_unit(api, unit_id)["observed_cost_to_date_cents"]


# ─── Tier 1: unit + patient + order ───────────────────

def unit_patient_order(
    api,
    unit_code: str = "UNIT-1",
    mrn: str = "MRN-1000",
    budget_cents: int = 100000,
    video_monitoring_enabled: Any = _OMIT,
    age_years: int = 60,
    risk_categories: Optional[List[str]] = None,
    required_modality: str = MODALITY_ONE_TO_ONE_SITTER,
    provider_headers=PROVIDER_1,
) -> Dict[str, Any]:
    """A registered unit with one admitted patient carrying one ACTIVE order."""
    unit = make_unit(
        api,
        unit_code=unit_code,
        budget_cents=budget_cents,
        video_monitoring_enabled=video_monitoring_enabled,
    )
    patient = make_patient(api, unit["id"], mrn=mrn, age_years=age_years)
    order = make_order(
        api,
        patient["id"],
        provider_headers=provider_headers,
        risk_categories=risk_categories,
        required_modality=required_modality,
    )
    return {"unit": unit, "patient": patient, "order": order}


# ─── Tier 2: a scheduled watch on that order ──────────

def scheduled_watch(
    api,
    unit_code: str = "UNIT-1",
    mrn: str = "MRN-1000",
    budget_cents: int = 100000,
    age_years: int = 60,
    risk_categories: Optional[List[str]] = None,
    shift_start_at: str = "2026-08-01T08:00:00Z",
    shift_end_at: str = "2026-08-01T16:00:00Z",
    hourly_rate_cents: int = 2000,
    source_pool: str = POOL_INTERNAL_FLOAT,
    competency_level: str = COMPETENCY_ADVANCED,
    deescalation_cert_expires_on: str = "2027-01-01T00:00:00Z",
    staff_name: str = "Observation Sitter",
) -> Dict[str, Any]:
    """
    A unit, patient, ACTIVE order, registered observer and one SCHEDULED watch with
    its PROVISIONAL ledger row already posted (PRD 3.4).
    """
    world = unit_patient_order(
        api,
        unit_code=unit_code,
        mrn=mrn,
        budget_cents=budget_cents,
        age_years=age_years,
        risk_categories=risk_categories,
    )
    staff = make_staff(
        api,
        world["unit"]["id"],
        full_name=staff_name,
        source_pool=source_pool,
        hourly_rate_cents=hourly_rate_cents,
        competency_level=competency_level,
        deescalation_cert_expires_on=deescalation_cert_expires_on,
    )
    assignment = make_assignment(
        api, world["order"]["id"], staff["id"], shift_start_at, shift_end_at
    )
    world.update({"staff": staff, "assignment": assignment})
    return world


# ─── Tier 3: the watch already running ────────────────

def start_watch_at(api, assignment_id: str, staff_id: str, clock_instant: str) -> Dict[str, Any]:
    """Advance the clock into the start window and begin the watch (PRD 3.5)."""
    advance_clock(api, clock_instant)
    return get_success_data(api.start_watch(assignment_id, make_sitter_headers(staff_id)))


def watch_in_progress(
    api,
    shift_start_at: str = "2026-08-01T08:00:00Z",
    shift_end_at: str = "2026-08-01T16:00:00Z",
    start_clock_at: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """A watch already advanced SCHEDULED -> ON_WATCH with its first segment open."""
    world = scheduled_watch(
        api, shift_start_at=shift_start_at, shift_end_at=shift_end_at, **kwargs
    )
    world["assignment"] = start_watch_at(
        api,
        world["assignment"]["id"],
        world["staff"]["id"],
        start_clock_at or shift_start_at,
    )
    return world


# ─── Tier 3: a console carrying one ACTIVE feed ───────

def console_with_active_feed(
    api,
    unit_code: str = "UNIT-1",
    mrn: str = "MRN-1000",
    budget_cents: int = 500000,
    age_years: int = 60,
    risk_categories: Optional[List[str]] = None,
    declared_max_span: int = 3,
    station_label: str = "CONSOLE-1",
    monitor_start_at: str = "2026-08-01T08:00:00Z",
    monitor_end_at: str = "2026-08-01T12:00:00Z",
    observer_rate_cents: int = 2000,
) -> Dict[str, Any]:
    """
    A video-enabled unit with a VIDEO_MONITORING order, a console and one ACTIVE
    feed, so the console sits in ACTIVE_MONITORING and its observer ON_ASSIGNMENT.
    """
    world = unit_patient_order(
        api,
        unit_code=unit_code,
        mrn=mrn,
        budget_cents=budget_cents,
        video_monitoring_enabled=True,
        age_years=age_years,
        risk_categories=risk_categories,
        required_modality=MODALITY_VIDEO_MONITORING,
    )
    observer = make_staff(
        api,
        world["unit"]["id"],
        full_name="Remote Observer",
        hourly_rate_cents=observer_rate_cents,
    )
    station = make_station(
        api,
        observer["id"],
        station_label=station_label,
        declared_max_span=declared_max_span,
    )
    feed = make_feed(
        api,
        station["id"],
        world["order"]["id"],
        monitor_start_at,
        monitor_end_at,
        observer["id"],
    )
    world.update({"observer": observer, "station": station, "feed": feed})
    return world


# ─── Tier 4: threshold / accumulation targeting ───────

def close_event_on_order(
    api,
    order_id: str,
    event_kind: str,
    reporter_staff_id: str,
    resolution: str,
    assignment_id: Any = _OMIT,
    review_findings: Any = _OMIT,
    opener_headers=OFFICER_1,
    closer_headers=None,
    as_remote_observer: bool = False,
) -> Dict[str, Any]:
    """
    Walk a safety event all the way to CLOSED through whichever branch its
    ``event_kind`` allows, honouring PRD 3.8's requirement that the closer's
    ``X-User-ID`` differ from ``review_opened_by_user_id``.
    """
    from .constants import ESCALATION_BRANCH_KINDS
    from .test_users import OFFICER_2

    event = make_safety_event(
        api,
        order_id,
        event_kind,
        reporter_staff_id,
        assignment_id=assignment_id,
        as_remote_observer=as_remote_observer,
    )
    if event_kind in ESCALATION_BRANCH_KINDS:
        get_success_data(
            api.escalate_response(
                event["id"],
                f.escalate_response_payload(["VERBAL_REDIRECTION"]),
                opener_headers,
            )
        )
        closer = closer_headers or opener_headers
        findings = review_findings
    else:
        get_success_data(api.open_incident_review(event["id"], opener_headers))
        closer = closer_headers or OFFICER_2
        findings = (
            review_findings
            if review_findings is not _OMIT
            else "Reviewed; retraining scheduled."
        )
    return get_success_data(
        api.close_safety_event(
            event["id"], f.close_event_payload(resolution, review_findings=findings), closer
        )
    )


def order_with_one_reassessment(
    api,
    unit_code: str = "UNIT-1",
    mrn: str = "MRN-1000",
    risk_categories: Optional[List[str]] = None,
    age_years: int = 60,
    budget_cents: int = 100000,
    provider_headers=PROVIDER_1,
) -> Dict[str, Any]:
    """
    An ACTIVE order whose ``reassessment_count`` is 1, which PRD 3.9 makes the
    precondition for opening a discontinuation review.
    """
    world = unit_patient_order(
        api,
        unit_code=unit_code,
        mrn=mrn,
        budget_cents=budget_cents,
        age_years=age_years,
        risk_categories=risk_categories,
        provider_headers=provider_headers,
    )
    categories = risk_categories or [RISK_FALL]
    world["reassessment"] = make_reassessment(
        api, world["order"]["id"], categories, provider_headers=provider_headers
    )
    world["order"] = read_order(api, world["order"]["id"])
    return world


def order_in_discontinuation_review(
    api,
    recommendation: str = "DISCONTINUE",
    opener_headers=PROVIDER_1,
    **kwargs,
) -> Dict[str, Any]:
    """An order walked ACTIVE -> DISCONTINUATION_REVIEW, immune to the clock sweep."""
    world = order_with_one_reassessment(api, **kwargs)
    get_success_data(
        api.open_discontinuation_review(
            world["order"]["id"],
            f.discontinuation_review_payload(recommendation),
            opener_headers,
        )
    )
    world["order"] = read_order(api, world["order"]["id"])
    return world


def restricted_unit_via_lapse(
    api,
    unit_code: str = "UNIT-1",
    mrn: str = "MRN-1000",
    budget_cents: int = 100000,
) -> Dict[str, Any]:
    """
    Drive a unit to RESTRICTED / OBSERVATION_ORDER_LAPSED with a ledger head of 0,
    which takes the two separate clock advances PRD 3.3 requires: one to reach
    REASSESSMENT_DUE and a second to lapse.
    """
    world = unit_patient_order(
        api, unit_code=unit_code, mrn=mrn, budget_cents=budget_cents
    )
    due_at = read_order(api, world["order"]["id"])["next_reassessment_due_at"]
    advance_clock(api, canonical_instant(due_at))
    advance_clock(api, instant(due_at, hours=6))
    world["order"] = read_order(api, world["order"]["id"])
    world["unit"] = read_unit(api, world["unit"]["id"])
    return world


# ─── Tier 5: terminal / finalisation shortcuts ────────

def completed_watch(
    api,
    completion_reason: str,
    complete_at: str,
    **kwargs,
) -> Dict[str, Any]:
    """A watch taken all the way to COMPLETED with its finals posted (PRD 3.5)."""
    world = watch_in_progress(api, **kwargs)
    advance_clock(api, complete_at)
    world["assignment"] = get_success_data(
        api.complete_watch(
            world["assignment"]["id"],
            f.completion_payload(completion_reason),
            make_sitter_headers(world["staff"]["id"]),
        )
    )
    world["unit"] = read_unit(api, world["unit"]["id"])
    return world


def suspended_sitter_via_incident_review(
    api,
    unit_code: str = "UNIT-1",
    mrn: str = "MRN-1000",
    budget_cents: int = 500000,
    risk_categories: Optional[List[str]] = None,
    event_kind: str = "FALL_WITH_INJURY",
    opener_headers=OFFICER_1,
) -> Dict[str, Any]:
    """
    An ON_WATCH sitter driven to SUSPENDED / INCIDENT_REVIEW_OPENED, which PRD 3.8
    applies "strictly **after** all four cascade hops" of the incident review.
    """
    world = watch_in_progress(
        api,
        unit_code=unit_code,
        mrn=mrn,
        budget_cents=budget_cents,
        risk_categories=risk_categories,
    )
    world["event"] = make_safety_event(
        api,
        world["order"]["id"],
        event_kind,
        world["staff"]["id"],
        assignment_id=world["assignment"]["id"],
    )
    get_success_data(api.open_incident_review(world["event"]["id"], opener_headers))
    world["event"] = read_event(api, world["event"]["id"])
    world["staff"] = read_staff(api, world["staff"]["id"])
    world["order"] = read_order(api, world["order"]["id"])
    return world
