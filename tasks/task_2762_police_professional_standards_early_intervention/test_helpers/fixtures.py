"""Composite fixtures that walk the API to a wanted state.

Every test starts against an empty deployment, so each test has to build the
world it needs from scratch. These helpers do that walking through the public
API only - no direct data writes - and return the identifiers, headers and
observed versions the test then asserts against.

They are organised from the simplest to the most far-reaching:

  Tier 1  advancing the clock and seeding standing reference data
  Tier 2  building the complaint / allegation / investigation hierarchy
  Tier 3  shortcuts that run a whole case to findings, sustain, impose, appeal
  Tier 4  accumulating activity events and driving the early-intervention cycle
  Tier 5  finalization: closing, purging, overturning and reinstating

Setup calls use the lenient success reader, so a failure inside a fixture is
reported as a setup failure rather than as a mysterious assertion error.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import ApiClient
from . import factories as f
from .test_users import (
    APPEALS_OFFICER_HEADERS,
    COMPLAINANT_HEADERS,
    OFFICER_REPRESENTATIVE_HEADERS,
    RECORDS_CUSTODIAN_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    make_ia_commander_headers,
    make_investigator_headers,
    make_supervisor_headers,
)

# The instant the clock reports on a fresh deployment.
BASE_CLOCK = "2026-08-01T00:00:00Z"


# ═══ Tier 1: state progression ═════════════════════════════════════════════

def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock and return what the write reported."""
    return get_success_data(api.set_clock(f.clock_payload(current_utc), SYSTEM_ADMIN_HEADERS))


def create_unit(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_unit(f.unit_payload(**overrides), SYSTEM_ADMIN_HEADERS))


def create_internal_affairs_unit(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_unit(f.internal_affairs_unit_payload(**overrides), SYSTEM_ADMIN_HEADERS)
    )


def create_hearing_room(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_hearing_room(f.hearing_room_payload(**overrides), SYSTEM_ADMIN_HEADERS)
    )


def create_officer(api: ApiClient, unit_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_officer(f.officer_payload(unit_id, **overrides), SYSTEM_ADMIN_HEADERS)
    )


def create_investigator(api: ApiClient, unit_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_officer(f.investigator_payload(unit_id, **overrides), SYSTEM_ADMIN_HEADERS)
    )


def create_supervisor(api: ApiClient, unit_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_officer(f.supervisor_payload(unit_id, **overrides), SYSTEM_ADMIN_HEADERS)
    )


def create_commander(api: ApiClient, unit_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_officer(f.commander_payload(unit_id, **overrides), SYSTEM_ADMIN_HEADERS)
    )


def read_officer(api: ApiClient, officer_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api.get_officer(officer_id, headers))


def read_complaint(api: ApiClient, complaint_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api.get_complaint(complaint_id, headers))


def read_investigation(api: ApiClient, investigation_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api.get_investigation(investigation_id, headers))


def read_allegation(api: ApiClient, allegation_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api.get_allegation(allegation_id, headers))


def read_session(api: ApiClient, session_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api.get_interview_session(session_id, headers))


def read_discipline(api: ApiClient, discipline_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api.get_discipline(discipline_id, headers))


def read_alert(api: ApiClient, alert_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api.get_eis_alert(alert_id, headers))


def read_plan(api: ApiClient, plan_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api.get_intervention_plan(plan_id, headers))


def read_disclosure(api: ApiClient, disclosure_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api.get_credibility_disclosure(disclosure_id, headers))


def read_eis_profile(
    api: ApiClient, officer_id: str, headers: Dict[str, str], params: Optional[Dict] = None
) -> Dict[str, Any]:
    return get_success_data(api.get_eis_profile(officer_id, headers, params))


def rows(response) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Read a list response as (rows, meta)."""
    return validate_paginated(response)


def seed_reference_data(
    api: ApiClient,
    clock: str = BASE_CLOCK,
    investigator_max_case_load: int = 3,
    investigator_certification_level: int = 3,
    room_capacity: int = 1,
) -> Dict[str, Any]:
    """Seed the standing world every case needs.

    Internal Affairs is created first so that it is the earliest-created
    Internal Affairs unit, which is where classification routes files that must
    leave the subject's own command. The returned dictionary also carries the
    header set for each acting identity, so callers never rebuild them.
    """
    set_clock(api, clock)

    ia_unit = create_internal_affairs_unit(api)
    patrol_unit = create_unit(api, intake_enabled=True)

    commander = create_commander(api, ia_unit["id"])
    investigator = create_investigator(
        api,
        ia_unit["id"],
        certification_level=investigator_certification_level,
        max_case_load=investigator_max_case_load,
    )
    supervisor = create_supervisor(api, patrol_unit["id"])
    subject = create_officer(api, patrol_unit["id"])
    room = create_hearing_room(api, concurrent_capacity=room_capacity)

    return {
        "clock": clock,
        "ia_unit_id": ia_unit["id"],
        "patrol_unit_id": patrol_unit["id"],
        "cmdr_id": commander["id"],
        "inv_a_id": investigator["id"],
        "sup_id": supervisor["id"],
        "subj_id": subject["id"],
        "room1_id": room["id"],
        "admin_headers": SYSTEM_ADMIN_HEADERS,
        "cmdr_headers": make_ia_commander_headers(commander["id"]),
        "inv_a_headers": make_investigator_headers(investigator["id"]),
        "sup_headers": make_supervisor_headers(supervisor["id"]),
        "complainant_headers": COMPLAINANT_HEADERS,
        "appeals_headers": APPEALS_OFFICER_HEADERS,
        "rep_headers": OFFICER_REPRESENTATIVE_HEADERS,
        "custodian_headers": RECORDS_CUSTODIAN_HEADERS,
    }


# ═══ Tier 2: entity hierarchy ══════════════════════════════════════════════

def file_supervisor_complaint(
    api: ApiClient, world: Dict[str, Any], **overrides: Any
) -> Dict[str, Any]:
    """File a supervisor-channel complaint against the subject's own command."""
    subject_unit_id = overrides.pop("subject_unit_id", world["patrol_unit_id"])
    reporter_id = overrides.pop("reporting_supervisor_officer_id", world["sup_id"])
    payload = f.supervisor_complaint_payload(subject_unit_id, reporter_id, **overrides)
    return get_success_data(api.create_complaint(payload, world["sup_headers"]))


def file_public_complaint(api: ApiClient, world: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    subject_unit_id = overrides.pop("subject_unit_id", world["patrol_unit_id"])
    payload = f.public_complaint_payload(subject_unit_id, **overrides)
    return get_success_data(api.create_complaint(payload, world["complainant_headers"]))


def file_anonymous_complaint(api: ApiClient, world: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    subject_unit_id = overrides.pop("subject_unit_id", world["patrol_unit_id"])
    payload = f.anonymous_complaint_payload(subject_unit_id, **overrides)
    return get_success_data(api.create_complaint(payload, world["complainant_headers"]))


def attach_allegation(
    api: ApiClient,
    world: Dict[str, Any],
    complaint_id: str,
    subject_officer_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Attach one allegation to a complaint, which also raises its allegation count."""
    payload = f.allegation_payload(subject_officer_id or world["subj_id"], **overrides)
    return get_success_data(api.create_allegation(complaint_id, payload, world["cmdr_headers"]))


def open_investigation(api: ApiClient, world: Dict[str, Any], complaint_id: str) -> Dict[str, Any]:
    return get_success_data(api.open_investigation(complaint_id, {}, world["cmdr_headers"]))


def assign_investigation(
    api: ApiClient,
    world: Dict[str, Any],
    investigation_id: str,
    expected_version: int,
    investigator_officer_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload = f.assignment_payload(expected_version, investigator_officer_id)
    return get_success_data(
        api.assign_investigation(investigation_id, payload, world["cmdr_headers"])
    )


def world_with_complaint(
    api: ApiClient,
    clock: str = BASE_CLOCK,
    allegation_type: str = "NEGLECT_OF_DUTY",
    offense_class: str = "B",
    reported_allegation_types: Optional[List[str]] = None,
    complaint_overrides: Optional[Dict[str, Any]] = None,
    **seed_kwargs: Any,
) -> Dict[str, Any]:
    """Seed the world and file one classified complaint carrying one allegation."""
    world = seed_reference_data(api, clock=clock, **seed_kwargs)
    complaint = file_supervisor_complaint(
        api,
        world,
        reported_allegation_types=reported_allegation_types or [allegation_type],
        **(complaint_overrides or {}),
    )
    allegation = attach_allegation(
        api,
        world,
        complaint["id"],
        allegation_type=allegation_type,
        offense_class=offense_class,
    )
    world.update(
        {
            "c_id": complaint["id"],
            "complaint": complaint,
            "a1_id": allegation["id"],
            "allegation_ids": [allegation["id"]],
        }
    )
    return world


def world_with_investigation(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Take the world as far as an UNASSIGNED investigation."""
    world = world_with_complaint(api, **kwargs)
    investigation = open_investigation(api, world, world["c_id"])
    world.update(
        {
            "i1_id": investigation["id"],
            "i1_v0": investigation["version"],
            "investigation": investigation,
        }
    )
    return world


def world_assigned_investigation(
    api: ApiClient, investigator_officer_id: Optional[str] = None, **kwargs: Any
) -> Dict[str, Any]:
    """Take the world as far as an investigation assigned to the standing investigator."""
    world = world_with_investigation(api, **kwargs)
    assigned = assign_investigation(
        api,
        world,
        world["i1_id"],
        world["i1_v0"],
        investigator_officer_id or world["inv_a_id"],
    )
    world.update({"i1_v1": assigned["version"], "investigation": assigned})
    return world


# ═══ Tier 3: full lifecycle shortcuts ══════════════════════════════════════

def schedule_session(
    api: ApiClient,
    world: Dict[str, Any],
    investigation_id: str,
    subject_officer_id: Optional[str] = None,
    hearing_room_id: Optional[str] = None,
    investigator_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Book an interview for the subject, in the standing room, with ample notice."""
    payload = f.interview_session_payload(
        subject_officer_id or world["subj_id"],
        hearing_room_id or world["room1_id"],
        **overrides,
    )
    return get_success_data(
        api.schedule_interview_session(
            investigation_id, payload, investigator_headers or world["inv_a_headers"]
        )
    )


def hold_session(
    api: ApiClient,
    world: Dict[str, Any],
    session_id: str,
    investigator_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Record that an interview took place; the clock must already have reached its start."""
    return get_success_data(
        api.hold_interview_session(
            session_id, f.hold_payload(**overrides), investigator_headers or world["inv_a_headers"]
        )
    )


def submit_findings(
    api: ApiClient,
    world: Dict[str, Any],
    investigation_id: str,
    entries: Sequence[Dict[str, Any]],
    investigator_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Submit one findings entry per allegation on the owning complaint."""
    return get_success_data(
        api.submit_findings(
            investigation_id,
            f.findings_payload(list(entries)),
            investigator_headers or world["inv_a_headers"],
        )
    )


def dispose_allegation(
    api: ApiClient,
    world: Dict[str, Any],
    allegation_id: str,
    disposition: str,
    commander_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.dispose_allegation(
            allegation_id,
            f.disposition_payload(disposition, **overrides),
            commander_headers or world["cmdr_headers"],
        )
    )


def discipline_for_allegation(
    api: ApiClient, world: Dict[str, Any], allegation_id: str
) -> Dict[str, Any]:
    """Find the Discipline row a sustained disposition created."""
    listed, _ = rows(api.list_disciplines(world["cmdr_headers"], {"allegation_id": allegation_id}))
    assert listed, f"no Discipline row exists for allegation {allegation_id}"
    return listed[0]


def disclosure_for_allegation(
    api: ApiClient, world: Dict[str, Any], allegation_id: str
) -> Dict[str, Any]:
    """Find the CredibilityDisclosure a sustained untruthfulness finding created."""
    listed, _ = rows(
        api.list_credibility_disclosures(
            world["custodian_headers"], {"source_allegation_id": allegation_id}
        )
    )
    assert listed, f"no CredibilityDisclosure exists for allegation {allegation_id}"
    return listed[0]


def alert_for_officer(api: ApiClient, world: Dict[str, Any], officer_id: str) -> Dict[str, Any]:
    """Find the early-intervention alert raised against an officer."""
    listed, _ = rows(api.list_eis_alerts(world["cmdr_headers"], {"officer_id": officer_id}))
    assert listed, f"no EarlyInterventionAlert exists for officer {officer_id}"
    return listed[0]


def reinstatement_for_appeal(api: ApiClient, world: Dict[str, Any], appeal_id: str) -> Dict[str, Any]:
    """Find the Reinstatement a reversal created."""
    listed, _ = rows(api.list_appeal_reinstatements(appeal_id, world["appeals_headers"]))
    assert listed, f"no Reinstatement exists for appeal {appeal_id}"
    return listed[0]


def world_at_findings(
    api: ApiClient,
    evidence_weight_for: float = 60,
    evidence_weight_against: float = 40,
    policy_compliant: bool = False,
    session_start: str = "2026-08-05T09:00:00Z",
    session_end: str = "2026-08-05T10:30:00Z",
    notice_served_at: str = BASE_CLOCK,
    hold_at: str = "2026-08-05T09:00:00Z",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Run one case from intake to submitted findings.

    Books an interview with more than the minimum notice, moves the clock to the
    session start, records the interview as held and then submits findings, which
    leaves the investigation in PENDING_REVIEW and the complaint in ADJUDICATION.
    """
    world = world_assigned_investigation(api, **kwargs)
    session = schedule_session(
        api,
        world,
        world["i1_id"],
        scheduled_start=session_start,
        scheduled_end=session_end,
        notice_served_at=notice_served_at,
    )
    set_clock(api, hold_at)
    hold_session(api, world, session["id"])
    findings = submit_findings(
        api,
        world,
        world["i1_id"],
        [
            f.finding_entry(
                world["a1_id"],
                evidence_weight_for=evidence_weight_for,
                evidence_weight_against=evidence_weight_against,
                policy_compliant=policy_compliant,
            )
        ],
    )
    world.update(
        {
            "s1_id": session["id"],
            "session": session,
            "clock": hold_at,
            "investigation": findings,
        }
    )
    return world


def world_with_sustained_allegation(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Run one case to a sustained disposition, which also proposes discipline."""
    world = world_at_findings(api, **kwargs)
    disposed = dispose_allegation(api, world, world["a1_id"], "SUSTAINED")
    discipline = discipline_for_allegation(api, world, world["a1_id"])
    world.update({"a1": disposed, "d1_id": discipline["id"], "discipline": discipline})
    return world


def world_with_imposed_discipline(
    api: ApiClient, effective_date: str = "2026-08-10T00:00:00Z", **kwargs: Any
) -> Dict[str, Any]:
    """Run one case to imposed discipline, which starts the appeal window."""
    world = world_with_sustained_allegation(api, **kwargs)
    imposed = get_success_data(
        api.impose_discipline(
            world["d1_id"], f.imposition_payload(effective_date=effective_date), world["cmdr_headers"]
        )
    )
    world.update({"discipline": imposed})
    return world


def world_with_filed_appeal(api: ApiClient, forum: str = "ARBITRATION", **kwargs: Any) -> Dict[str, Any]:
    """Run one case to a filed appeal, which moves the discipline to APPEALED."""
    world = world_with_imposed_discipline(api, **kwargs)
    appeal = get_success_data(
        api.file_appeal(world["d1_id"], f.appeal_payload(forum), world["rep_headers"])
    )
    world.update({"ap1_id": appeal["id"], "appeal": appeal})
    return world


# ═══ Tier 4: accumulation and threshold targeting ══════════════════════════

# The event pattern that carries an officer's weighted total to 17.5 and, with
# both the force and the pursuit indicators breached, to a rolling score of
# 63.75 - comfortably inside the ALERT band.
FIVE_EVENT_ALERT_PATTERN: Tuple[Tuple[str, str, str, str], ...] = (
    ("USE_OF_FORCE", "LEVEL_2", "2026-06-01T00:00:00Z", "UOF-1"),
    ("USE_OF_FORCE", "LEVEL_1", "2026-06-15T00:00:00Z", "UOF-2"),
    ("USE_OF_FORCE", "LEVEL_3", "2026-07-01T00:00:00Z", "UOF-3"),
    ("PURSUIT", "NA", "2026-07-10T00:00:00Z", "PUR-1"),
    ("PURSUIT", "NA", "2026-07-20T00:00:00Z", "PUR-2"),
)

# Three level-three uses of force, which breach the force indicator and land the
# rolling score at 55.00.
THREE_FORCE_EVENT_PATTERN: Tuple[Tuple[str, str, str, str], ...] = (
    ("USE_OF_FORCE", "LEVEL_3", "2026-07-01T00:00:00Z", "UOF-1"),
    ("USE_OF_FORCE", "LEVEL_3", "2026-07-10T00:00:00Z", "UOF-2"),
    ("USE_OF_FORCE", "LEVEL_3", "2026-07-20T00:00:00Z", "UOF-3"),
)


def record_activity_event(
    api: ApiClient,
    officer_id: str,
    event_type: str,
    occurred_at: str,
    severity_code: Optional[str] = None,
    source_reference: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Append one activity event to an officer's history."""
    payload = f.activity_event_payload(
        event_type=event_type,
        occurred_at=occurred_at,
        severity_code=severity_code,
        source_reference=source_reference,
    )
    return get_success_data(
        api.create_activity_event(officer_id, payload, headers or SYSTEM_ADMIN_HEADERS)
    )


def ingest_event_pattern(
    api: ApiClient,
    officer_id: str,
    pattern: Sequence[Tuple[str, str, str, str]],
    headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Append a whole pattern of activity events, in the order given."""
    created = []
    for event_type, severity_code, occurred_at, reference in pattern:
        created.append(
            record_activity_event(
                api,
                officer_id,
                event_type,
                occurred_at,
                severity_code=severity_code,
                source_reference=reference,
                headers=headers,
            )
        )
    return created


def run_sweep(
    api: ApiClient,
    world: Dict[str, Any],
    officer_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Run the early-intervention sweep, optionally narrowed to one officer."""
    return get_success_data(
        api.run_eis_sweep(f.eis_run_payload(officer_id), headers or SYSTEM_ADMIN_HEADERS)
    )


def world_with_scored_officer(
    api: ApiClient,
    pattern: Sequence[Tuple[str, str, str, str]] = FIVE_EVENT_ALERT_PATTERN,
    clock: str = BASE_CLOCK,
    **seed_kwargs: Any,
) -> Dict[str, Any]:
    """Seed the world and accumulate an event history against the subject officer."""
    world = seed_reference_data(api, clock=clock, **seed_kwargs)
    world["events"] = ingest_event_pattern(api, world["subj_id"], pattern)
    return world


def world_with_promoted_alert(
    api: ApiClient,
    pattern: Sequence[Tuple[str, str, str, str]] = FIVE_EVENT_ALERT_PATTERN,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Accumulate events, then let the sweep refresh and promote the alert.

    Event ingest opens an alert as soon as the score crosses out of NONE, but
    never refreshes one that is already open; the sweep is what brings a stale
    open alert up to date and promotes it to PLAN_REQUIRED once the band reaches
    ALERT.
    """
    world = world_with_scored_officer(api, pattern=pattern, **kwargs)
    world["run1"] = run_sweep(api, world)
    alert = alert_for_officer(api, world, world["subj_id"])
    world.update({"al_id": alert["id"], "al_v": alert["version"], "alert": alert})
    return world


def world_with_draft_plan(
    api: ApiClient,
    required_checkin_count: int = 2,
    duration_days: int = 30,
    interventions: Optional[List[str]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Take the alert as far as a DRAFT intervention plan monitored by the sergeant."""
    world = world_with_promoted_alert(api, **kwargs)
    plan = get_success_data(
        api.create_intervention_plan(
            world["al_id"],
            f.intervention_plan_payload(
                world["al_v"],
                world["sup_id"],
                required_checkin_count=required_checkin_count,
                duration_days=duration_days,
                interventions=interventions,
            ),
            world["sup_headers"],
        )
    )
    world.update({"p1_id": plan["id"], "plan": plan})
    return world


def world_with_active_plan(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Activate the plan, which materialises its monitoring check-ins."""
    world = world_with_draft_plan(api, **kwargs)
    activated = get_success_data(
        api.activate_intervention_plan(world["p1_id"], {}, world["sup_headers"])
    )
    check_ins, _ = rows(api.list_plan_check_ins(world["p1_id"], world["sup_headers"]))
    world.update(
        {
            "plan": activated,
            "check_ins": check_ins,
            "check_in_ids": [row["id"] for row in check_ins],
        }
    )
    return world


def complete_check_in(
    api: ApiClient,
    world: Dict[str, Any],
    check_in_id: str,
    outcome: str = "SATISFACTORY",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.complete_check_in(
            check_in_id, f.check_in_completion_payload(outcome), headers or world["sup_headers"]
        )
    )


# ═══ Tier 5: finalization and terminal state ═══════════════════════════════

def close_investigation(
    api: ApiClient, world: Dict[str, Any], investigation_id: str, headers: Optional[Dict] = None
) -> Dict[str, Any]:
    """Close an investigation once every allegation on its complaint is disposed."""
    return get_success_data(
        api.close_investigation(investigation_id, {}, headers or world["cmdr_headers"])
    )


def withdraw_complaint(
    api: ApiClient,
    world: Dict[str, Any],
    complaint_id: str,
    intake_reference_code: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Withdraw a complaint, proving authority with its intake reference code."""
    return get_success_data(
        api.withdraw_complaint(
            complaint_id,
            f.withdrawal_payload(intake_reference_code, **overrides),
            headers or world["sup_headers"],
        )
    )


def hear_appeal(api: ApiClient, world: Dict[str, Any], appeal_id: str) -> Dict[str, Any]:
    return get_success_data(api.hear_appeal(appeal_id, {}, world["appeals_headers"]))


def decide_appeal(
    api: ApiClient,
    world: Dict[str, Any],
    appeal_id: str,
    outcome: str,
    modified_days: Optional[int] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.decide_appeal(
            appeal_id, f.appeal_decision_payload(outcome, modified_days), world["appeals_headers"]
        )
    )


def world_with_overturned_appeal(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Run one case all the way through a reversal on appeal.

    The reversal takes the discipline to OVERTURNED, subtracts the imposed days
    from the officer's ledger, sends the allegation to OVERTURNED_ON_APPEAL and
    raises a pending reinstatement for the full reversed span.
    """
    world = world_with_filed_appeal(api, **kwargs)
    hear_appeal(api, world, world["ap1_id"])
    decided = decide_appeal(api, world, world["ap1_id"], "OVERTURNED")
    reinstatement = reinstatement_for_appeal(api, world, world["ap1_id"])
    world.update(
        {
            "appeal": decided,
            "r1_id": reinstatement["id"],
            "reinstatement": reinstatement,
        }
    )
    return world


def finalize_reinstatement(
    api: ApiClient,
    world: Dict[str, Any],
    reinstatement_id: str,
    interim_earnings_cents: int = 0,
) -> Dict[str, Any]:
    """Finalize a reinstatement award, offsetting whatever the officer earned meanwhile."""
    return get_success_data(
        api.finalize_reinstatement(
            reinstatement_id,
            f.reinstatement_finalize_payload(interim_earnings_cents),
            world["appeals_headers"],
        )
    )


def world_with_closed_complaint(
    api: ApiClient, close_at: str = "2026-08-20T00:00:00Z", **kwargs: Any
) -> Dict[str, Any]:
    """Run one case to a closed complaint: sustained, then the investigation closed.

    Closing the investigation once every allegation is disposed carries the
    complaint to CLOSED as well, stamps its closing instant and sets the
    retention horizon from the governing disposition.
    """
    world = world_with_sustained_allegation(api, **kwargs)
    set_clock(api, close_at)
    closed_investigation = close_investigation(api, world, world["i1_id"])
    world.update(
        {
            "clock": close_at,
            "investigation": closed_investigation,
            "complaint": read_complaint(api, world["c_id"], world["cmdr_headers"]),
        }
    )
    return world


def world_with_purgeable_complaint(
    api: ApiClient,
    allegation_type: str = "NEGLECT_OF_DUTY",
    offense_class: str = "B",
    close_at: str = "2026-08-20T00:00:00Z",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Run one case to a closed complaint whose retention horizon the clock has passed.

    The allegation is deliberately not an untruthfulness finding, so no
    credibility record is created and nothing holds the file back from a purge.
    The clock is then moved past the retention horizon the closure computed.
    """
    world = world_with_closed_complaint(
        api,
        close_at=close_at,
        allegation_type=allegation_type,
        offense_class=offense_class,
        **kwargs,
    )
    retention_until = world["complaint"]["retention_until"]
    set_clock(api, retention_until)
    world["clock"] = retention_until
    world["retention_until"] = retention_until
    return world


def purge_complaint(
    api: ApiClient, world: Dict[str, Any], complaint_id: str, headers: Optional[Dict] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.purge_complaint(complaint_id, {}, headers or world["custodian_headers"])
    )


def release_disclosure(
    api: ApiClient,
    world: Dict[str, Any],
    disclosure_id: str,
    requesting_party: str = "County Prosecutor",
) -> Dict[str, Any]:
    return get_success_data(
        api.release_credibility_disclosure(
            disclosure_id, {"requesting_party": requesting_party}, world["custodian_headers"]
        )
    )


def separate_officer(api: ApiClient, officer_id: str, status: str = "SEPARATED") -> Dict[str, Any]:
    """Move an officer along the employment dimension."""
    return get_success_data(
        api.set_employment_status(
            officer_id, f.employment_status_payload(status), SYSTEM_ADMIN_HEADERS
        )
    )
