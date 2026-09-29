"""Composite setup helpers.

The harness restarts the server before every individual test, so each test
starts against an empty store and must build every precondition through the
PRD's own endpoints.  These helpers are the shared spine.

Every helper returns already-unwrapped entity dicts (`get_success_data` hands
back `body["data"]`; nothing here unwraps a second time).  Composite `seed_*`
helpers return a mutable `world` dict whose documented keys are:

    clock            the instant the logical clock was last set to
    officer          IntegrityOfficer headers
    dean             AppealsDean headers
    registrar        RegistrarOfficer headers
    dept             Department row
    reporter         FacultyMember row (trained; also the offering instructor)
    reporter_h       FacultyReporter headers bound to `reporter["id"]`
    student          Student row
    student_h        Student headers bound to `student["id"]`
    offering          CourseOffering row
    report            IntegrityReport row (state depends on the helper)
    evidence          list of EvidenceItem rows attached to `report`
    case              Case row (present from `seed_case` onward)
    notice            the ALLEGATION_NOTICE Notification row, when sent
    room              HearingRoom row, when created
    chair             FacultyMember row acting as PanelChair, when created
    chair_h           PanelChair headers bound to `chair["id"]`
    panelists         list of FacultyMember rows on the panel
    session           HearingSession row, when scheduled
    votes             list of PanelVote rows
    sanction          the most recently created Sanction row
    appeal            Appeal row, when filed

Distinct owners always get distinct `X-User-ID` values: `reporter_h` carries
the reporter's own id, `chair_h` the chair's, `student_h` the student's.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient, api_client
from .constants import DEFAULT_CLOCK_UTC, TEST_DEFAULTS
from .test_users import (
    make_chair_headers,
    make_dean_headers,
    make_officer_headers,
    make_registrar_headers,
    make_reporter_headers,
    make_student_headers,
)

# ---------------------------------------------------------------------------
# Canonical timeline.
#
# Clock starts 2026-08-01T00:00:00Z.  An allegation notice sent then has a
# 7-day default window closing 2026-08-08T00:00:00Z, and the 10-day hearing
# notice period opens 2026-08-11T00:00:00Z.  The canonical session therefore
# sits at 2026-08-20T10:00:00Z–11:30:00Z: 90 whole minutes, plus twice a
# 30-minute room buffer, is 150 minutes on the room ledger.
# ---------------------------------------------------------------------------

CLOCK_T0 = DEFAULT_CLOCK_UTC                     # 2026-08-01T00:00:00Z
MEETING_START = "2026-08-05T09:00:00Z"
MEETING_END = "2026-08-05T10:00:00Z"
SESSION_START = "2026-08-20T10:00:00Z"
SESSION_END = "2026-08-20T11:30:00Z"
SESSION_MINUTES = 90
SESSION_LEDGER_MINUTES = 150                     # 90 + 2 * 30 buffer
CLOCK_AT_SESSION = SESSION_START
DECIDED_AT = SESSION_START


def _d(response, expected_status: Optional[int] = None) -> Any:
    """Unwrap a setup response once, with a readable failure message."""
    return get_success_data(response, expected_status)


# ---------------------------------------------------------------------------
# Primitive steps
# ---------------------------------------------------------------------------


def set_clock(
    instant: str, headers: Optional[Dict[str, str]] = None, client: ApiClient = api_client
) -> str:
    """Move the logical clock (PRD §2.4).  Available to all six roles."""
    _d(client.set_clock(instant, headers or make_officer_headers()))
    return instant


def create_department(
    headers: Optional[Dict[str, str]] = None,
    client: ApiClient = api_client,
    **overrides,
) -> Dict[str, Any]:
    return _d(
        client.create_department(
            f.department_payload(**overrides), headers or make_officer_headers()
        ),
        201,
    )


def create_unique_department(
    headers: Optional[Dict[str, str]] = None,
    client: ApiClient = api_client,
    **overrides,
) -> Dict[str, Any]:
    return _d(
        client.create_department(
            f.unique_department_payload(**overrides), headers or make_officer_headers()
        ),
        201,
    )


def create_faculty(
    department_id: str,
    trained: bool = True,
    completed_at: str = TEST_DEFAULTS["TRAINING_COMPLETED_AT"],
    module_code: str = TEST_DEFAULTS["TRAINING_MODULE_CODE"],
    headers: Optional[Dict[str, str]] = None,
    client: ApiClient = api_client,
    **overrides,
) -> Dict[str, Any]:
    """Create a faculty member, optionally recording one training completion.

    A member with no completion is `LAPSED`; a completion at or within 730 days
    of the clock makes them `CURRENT` (PRD §3.1).
    """
    acting = headers or make_officer_headers()
    member = _d(
        client.create_faculty_member(
            f.faculty_member_payload(department_id, **overrides), acting
        ),
        201,
    )
    if not trained:
        return member
    # No explicit status here: a training completion is not one of the PRD's
    # declared entities, so §4's "new distinct resource in a collection -> 201"
    # and "derived-field recomputation -> 200" rules both plausibly apply.  A
    # setup helper must not assert an outcome the PRD does not uniquely derive.
    _d(
        client.create_training_completion(
            member["id"],
            f.training_completion_payload(
                module_code=module_code, completed_at=completed_at
            ),
            acting,
        ),
    )
    # Re-read so the caller sees the re-derived training fields.
    return _d(client.get_faculty_member(member["id"], acting))


def create_student(
    headers: Optional[Dict[str, str]] = None,
    client: ApiClient = api_client,
    **overrides,
) -> Dict[str, Any]:
    return _d(
        client.create_student(
            f.student_payload(**overrides), headers or make_officer_headers()
        ),
        201,
    )


def create_offering(
    department_id: str,
    instructor_id: str,
    headers: Optional[Dict[str, str]] = None,
    client: ApiClient = api_client,
    unique: bool = False,
    **overrides,
) -> Dict[str, Any]:
    payload = (
        f.unique_course_offering_payload(department_id, instructor_id, **overrides)
        if unique
        else f.course_offering_payload(department_id, instructor_id, **overrides)
    )
    return _d(
        client.create_course_offering(payload, headers or make_officer_headers()), 201
    )


def create_room(
    headers: Optional[Dict[str, str]] = None,
    client: ApiClient = api_client,
    **overrides,
) -> Dict[str, Any]:
    return _d(
        client.create_hearing_room(
            f.hearing_room_payload(**overrides), headers or make_officer_headers()
        ),
        201,
    )


def create_report(
    offering_id: str,
    student_id: str,
    reporter_headers: Dict[str, str],
    client: ApiClient = api_client,
    **overrides,
) -> Dict[str, Any]:
    """Create a DRAFT report.  `reporter_id` comes from the acting header."""
    return _d(
        client.create_report(
            f.report_payload(offering_id, student_id, **overrides), reporter_headers
        ),
        201,
    )


def attach_similarity_evidence(
    report_id: str,
    reporter_headers: Dict[str, str],
    client: ApiClient = api_client,
    **overrides,
) -> Dict[str, Any]:
    """SEED-A exhibit: SIMILARITY_REPORT, similarity_pct 45.00, 4 pages -> 60.00."""
    return _d(
        client.create_evidence_item(
            f.similarity_evidence_payload(report_id, **overrides), reporter_headers
        ),
        201,
    )


def attach_proctor_log(
    report_id: str,
    reporter_headers: Dict[str, str],
    client: ApiClient = api_client,
    **overrides,
) -> Dict[str, Any]:
    """SEED-B second exhibit: PROCTOR_LOG, 1 page -> lifts the score to 81.50."""
    return _d(
        client.create_evidence_item(
            f.proctor_log_payload(report_id, **overrides), reporter_headers
        ),
        201,
    )


def submit_report(
    report_id: str, reporter_headers: Dict[str, str], client: ApiClient = api_client
) -> Dict[str, Any]:
    return _d(client.submit_report(report_id, reporter_headers))


def triage_report(
    report_id: str,
    decision: str = "ACCEPT",
    triage_note: str = "Evidence sufficient for a case.",
    headers: Optional[Dict[str, str]] = None,
    client: ApiClient = api_client,
) -> Dict[str, Any]:
    return _d(
        client.triage_report(
            report_id,
            f.triage_payload(decision, triage_note=triage_note),
            headers or make_officer_headers(),
        )
    )


def open_case(
    report_id: str,
    headers: Optional[Dict[str, str]] = None,
    client: ApiClient = api_client,
) -> Dict[str, Any]:
    return _d(
        client.create_case(f.case_payload(report_id), headers or make_officer_headers()),
        201,
    )


def read_case(
    case_id: str,
    headers: Optional[Dict[str, str]] = None,
    client: ApiClient = api_client,
) -> Dict[str, Any]:
    """Re-read a case; the returned `version` is what the OCC writes require."""
    return _d(client.get_case(case_id, headers or make_officer_headers()))


def case_version(
    case_id: str,
    headers: Optional[Dict[str, str]] = None,
    client: ApiClient = api_client,
) -> int:
    return read_case(case_id, headers, client)["version"]


# ---------------------------------------------------------------------------
# The canonical baseline world.
#
# One ENGL department (2000 enrolled / 5 headcount), one trained reporter who
# is also the offering's instructor, one student, one ENGL-201/2026FA offering
# with the four-component gradebook, and one PLAGIARISM report.
#
# The helper is phased: `seed_draft_report` stops at DRAFT so a caller can add
# more evidence, and each later helper advances the same world in place, so no
# helper's last hop ever invalidates its own first hop on reuse.
# ---------------------------------------------------------------------------


def seed_actors(
    clock: str = CLOCK_T0,
    training_completed_at: str = TEST_DEFAULTS["TRAINING_COMPLETED_AT"],
    reporter_trained: bool = True,
    client: ApiClient = api_client,
    **department_overrides,
) -> Dict[str, Any]:
    """Clock, department, trained reporter, student and offering."""
    officer = make_officer_headers()
    set_clock(clock, officer, client)
    dept = create_department(officer, client, **department_overrides)
    reporter = create_faculty(
        dept["id"],
        trained=reporter_trained,
        completed_at=training_completed_at,
        headers=officer,
        client=client,
    )
    student = create_student(officer, client)
    offering = create_offering(dept["id"], reporter["id"], officer, client)
    return {
        "clock": clock,
        "officer": officer,
        "dean": make_dean_headers(),
        "registrar": make_registrar_headers(),
        "dept": dept,
        "reporter": reporter,
        "reporter_h": make_reporter_headers(reporter["id"]),
        "student": student,
        "student_h": make_student_headers(student["id"]),
        "offering": offering,
        "evidence": [],
        "votes": [],
        "panelists": [],
    }


def seed_draft_report(
    world: Optional[Dict[str, Any]] = None,
    with_evidence: bool = True,
    client: ApiClient = api_client,
    **report_overrides,
) -> Dict[str, Any]:
    """Extend the world with a DRAFT report and (by default) the SEED-A exhibit."""
    world = world if world is not None else seed_actors(client=client)
    report = create_report(
        world["offering"]["id"],
        world["student"]["id"],
        world["reporter_h"],
        client,
        **report_overrides,
    )
    world["report"] = report
    if with_evidence:
        world["evidence"].append(
            attach_similarity_evidence(report["id"], world["reporter_h"], client)
        )
        world["report"] = _d(client.get_report(report["id"], world["officer"]))
    return world


def seed_submitted_report(
    world: Optional[Dict[str, Any]] = None, client: ApiClient = api_client, **kwargs
) -> Dict[str, Any]:
    world = world if world is not None else seed_draft_report(client=client, **kwargs)
    world["report"] = submit_report(
        world["report"]["id"], world["reporter_h"], client
    )
    return world


def seed_accepted_report(
    world: Optional[Dict[str, Any]] = None, client: ApiClient = api_client, **kwargs
) -> Dict[str, Any]:
    world = world if world is not None else seed_submitted_report(client=client, **kwargs)
    world["report"] = triage_report(
        world["report"]["id"], "ACCEPT", headers=world["officer"], client=client
    )
    return world


def seed_case(
    world: Optional[Dict[str, Any]] = None, client: ApiClient = api_client, **kwargs
) -> Dict[str, Any]:
    """A case in INTAKE_REVIEW: evidence 60.00, severity 44.00, recommended rank 3."""
    world = world if world is not None else seed_accepted_report(client=client, **kwargs)
    world["case"] = open_case(world["report"]["id"], world["officer"], client)
    return world


# ---------------------------------------------------------------------------
# Notice, pathway and the informal branch
# ---------------------------------------------------------------------------


def send_allegation_notice(
    world: Dict[str, Any],
    response_window_days: Optional[int] = None,
    client: ApiClient = api_client,
) -> Dict[str, Any]:
    """Requires INTAKE_REVIEW; moves the case to NOTIFIED (PRD §3.5)."""
    world["notice"] = _d(
        client.create_case_notification(
            world["case"]["id"],
            f.notification_payload("ALLEGATION_NOTICE", response_window_days),
            world["officer"],
        ),
        201,
    )
    world["case"] = read_case(world["case"]["id"], world["officer"], client)
    return world


def set_pathway(
    world: Dict[str, Any], pathway: str, client: ApiClient = api_client
) -> Dict[str, Any]:
    world["case"] = _d(
        client.set_case_pathway(
            world["case"]["id"], f.pathway_payload(pathway), world["officer"]
        )
    )
    return world


def acknowledge_notice(
    world: Dict[str, Any], client: ApiClient = api_client
) -> Dict[str, Any]:
    world["notice"] = _d(
        client.acknowledge_notification(world["notice"]["id"], world["student_h"])
    )
    return world


def seed_notified_case(
    world: Optional[Dict[str, Any]] = None,
    response_window_days: Optional[int] = None,
    client: ApiClient = api_client,
    **kwargs,
) -> Dict[str, Any]:
    """A case in NOTIFIED with its ALLEGATION_NOTICE on record."""
    world = world if world is not None else seed_case(client=client, **kwargs)
    return send_allegation_notice(world, response_window_days, client)


def seed_informal_case(
    world: Optional[Dict[str, Any]] = None, client: ApiClient = api_client, **kwargs
) -> Dict[str, Any]:
    """NOTIFIED + pathway INFORMAL — ready for the instructor's proposal."""
    world = world if world is not None else seed_notified_case(client=client, **kwargs)
    return set_pathway(world, "INFORMAL", client)


def seed_formal_case(
    world: Optional[Dict[str, Any]] = None, client: ApiClient = api_client, **kwargs
) -> Dict[str, Any]:
    """NOTIFIED + pathway FORMAL — ready for hearing scheduling."""
    world = world if world is not None else seed_notified_case(client=client, **kwargs)
    return set_pathway(world, "FORMAL", client)


def propose_informal_resolution(
    world: Dict[str, Any],
    proposed_ladder_rank: int = 3,
    effective_from: Optional[str] = None,
    client: ApiClient = api_client,
    **overrides,
) -> Dict[str, Any]:
    """The instructor's proposal; the response body is the created Sanction."""
    case = read_case(world["case"]["id"], world["officer"], client)
    world["sanction"] = _d(
        client.create_informal_resolution(
            case["id"],
            f.informal_resolution_payload(
                case["version"],
                proposed_ladder_rank,
                effective_from or world["clock"],
                **overrides,
            ),
            world["reporter_h"],
        ),
        201,
    )
    world["case"] = read_case(case["id"], world["officer"], client)
    return world


def respond_informal(
    world: Dict[str, Any], response: str, client: ApiClient = api_client
) -> Dict[str, Any]:
    world["case"] = _d(
        client.create_informal_response(
            world["case"]["id"], f.informal_response_payload(response), world["student_h"]
        )
    )
    return world


def seed_informal_proposed_case(
    world: Optional[Dict[str, Any]] = None,
    proposed_ladder_rank: int = 3,
    client: ApiClient = api_client,
    **kwargs,
) -> Dict[str, Any]:
    world = world if world is not None else seed_informal_case(client=client, **kwargs)
    return propose_informal_resolution(
        world, proposed_ladder_rank, client=client
    )


def seed_informal_accepted_case(
    world: Optional[Dict[str, Any]] = None,
    proposed_ladder_rank: int = 3,
    client: ApiClient = api_client,
    **kwargs,
) -> Dict[str, Any]:
    """INFORMAL_ACCEPTED: an admission, so `decided_at` is the current clock."""
    world = (
        world
        if world is not None
        else seed_informal_proposed_case(
            proposed_ladder_rank=proposed_ladder_rank, client=client, **kwargs
        )
    )
    return respond_informal(world, "ACCEPT", client)


# ---------------------------------------------------------------------------
# Instructor meetings
# ---------------------------------------------------------------------------


def schedule_meeting(
    world: Dict[str, Any],
    start_at: str = MEETING_START,
    end_at: str = MEETING_END,
    headers: Optional[Dict[str, str]] = None,
    client: ApiClient = api_client,
    **overrides,
) -> Dict[str, Any]:
    world["meeting"] = _d(
        client.create_case_meeting(
            f.case_meeting_payload(
                world["case"]["id"],
                world["reporter"]["id"],
                start_at,
                end_at,
                **overrides,
            ),
            headers or world["officer"],
        ),
        201,
    )
    return world


def record_meeting_outcome(
    world: Dict[str, Any],
    outcome: str,
    headers: Optional[Dict[str, str]] = None,
    client: ApiClient = api_client,
) -> Dict[str, Any]:
    """`HELD`/`NO_SHOW` belong to the instructor; `CANCELLED` is an office act."""
    acting = headers or (
        world["officer"] if outcome == "CANCELLED" else world["reporter_h"]
    )
    world["meeting"] = _d(
        client.record_meeting_outcome(
            world["meeting"]["id"], f.meeting_outcome_payload(outcome), acting
        )
    )
    return world


# ---------------------------------------------------------------------------
# Advisor engagements
# ---------------------------------------------------------------------------


def request_advisor(
    world: Dict[str, Any],
    advisor_kind: str = "FACULTY_ADVISOR",
    client: ApiClient = api_client,
    **overrides,
) -> Dict[str, Any]:
    engagement = _d(
        client.create_advisor_engagement(
            f.advisor_engagement_payload(
                world["case"]["id"], advisor_kind=advisor_kind, **overrides
            ),
            world["student_h"],
        ),
        201,
    )
    world.setdefault("engagements", []).append(engagement)
    world["engagement"] = engagement
    return world


def review_advisor(
    world: Dict[str, Any],
    decision: str = "APPROVE",
    decision_reason: Optional[str] = None,
    engagement_id: Optional[str] = None,
    client: ApiClient = api_client,
) -> Dict[str, Any]:
    target = engagement_id or world["engagement"]["id"]
    world["engagement"] = _d(
        client.review_advisor_engagement(
            target,
            f.review_payload(decision, decision_reason),
            world["officer"],
        )
    )
    return world


# ---------------------------------------------------------------------------
# Formal hearings
# ---------------------------------------------------------------------------


def seed_panel(
    world: Dict[str, Any],
    panel_size: int = 3,
    chair_trained: bool = True,
    chair_completed_at: str = "2026-02-01T00:00:00Z",
    client: ApiClient = api_client,
) -> Dict[str, Any]:
    """Register a room, a trained chair and `panel_size` conflict-free panelists.

    Neither the chair nor any panelist may be the case's reporter or the
    offering's instructor (PRD §3.7), so all of them are fresh faculty rows.
    """
    if "room" not in world:
        world["room"] = create_room(world["officer"], client)
    world["chair"] = create_faculty(
        world["dept"]["id"],
        trained=chair_trained,
        completed_at=chair_completed_at,
        headers=world["officer"],
        client=client,
    )
    world["chair_h"] = make_chair_headers(world["chair"]["id"])
    world["panelists"] = [
        create_faculty(
            world["dept"]["id"], trained=False, headers=world["officer"], client=client
        )
        for _ in range(panel_size)
    ]
    return world


def schedule_hearing(
    world: Dict[str, Any],
    start_at: str = SESSION_START,
    end_at: str = SESSION_END,
    client: ApiClient = api_client,
    **overrides,
) -> Dict[str, Any]:
    payload_kwargs = {
        "case_id": world["case"]["id"],
        "room_id": world["room"]["id"],
        "chair_id": world["chair"]["id"],
        "panelist_ids": [p["id"] for p in world["panelists"]],
        "start_at": start_at,
        "end_at": end_at,
    }
    payload_kwargs.update(overrides)
    world["session"] = _d(
        client.create_hearing_session(
            f.hearing_session_payload(**payload_kwargs),
            world["officer"],
        ),
        201,
    )
    world["case"] = read_case(world["case"]["id"], world["officer"], client)
    return world


def seed_hearing_scheduled(
    world: Optional[Dict[str, Any]] = None,
    panel_size: int = 3,
    client: ApiClient = api_client,
    **kwargs,
) -> Dict[str, Any]:
    """HEARING_SCHEDULED, room ledger at 150 minutes, `hearing_round` at 1."""
    world = world if world is not None else seed_formal_case(client=client, **kwargs)
    seed_panel(world, panel_size=panel_size, client=client)
    return schedule_hearing(world, client=client)


def convene_hearing(
    world: Dict[str, Any], clock: str = CLOCK_AT_SESSION, client: ApiClient = api_client
) -> Dict[str, Any]:
    """Advance the clock to `start_at` and convene as the session's own chair."""
    world["clock"] = set_clock(clock, world["officer"], client)
    world["session"] = _d(
        client.convene_hearing_session(world["session"]["id"], world["chair_h"])
    )
    world["case"] = read_case(world["case"]["id"], world["officer"], client)
    return world


def seed_convened_session(
    world: Optional[Dict[str, Any]] = None,
    panel_size: int = 3,
    clock: str = CLOCK_AT_SESSION,
    client: ApiClient = api_client,
    **kwargs,
) -> Dict[str, Any]:
    world = (
        world
        if world is not None
        else seed_hearing_scheduled(panel_size=panel_size, client=client, **kwargs)
    )
    return convene_hearing(world, clock, client)


def cast_vote(
    world: Dict[str, Any],
    panelist_index: int,
    verdict: str,
    severity_recommendation: Optional[int] = None,
    client: ApiClient = api_client,
) -> Dict[str, Any]:
    """The chair records one panelist's ballot (PRD §3.7)."""
    vote = _d(
        client.create_panel_vote(
            f.panel_vote_payload(
                world["session"]["id"],
                world["panelists"][panelist_index]["id"],
                verdict,
                severity_recommendation,
            ),
            world["chair_h"],
        ),
        201,
    )
    world["votes"].append(vote)
    return world


def cast_responsible_majority(
    world: Dict[str, Any],
    panel_recommendation: int = 3,
    client: ApiClient = api_client,
) -> Dict[str, Any]:
    """Two RESPONSIBLE ballots at `panel_recommendation` plus one NOT_RESPONSIBLE.

    Three cast on a three-member panel meets the quorum of 2; two responsible
    out of three effective votes gives a RESPONSIBLE finding, and the median of
    two equal recommendations is that value.
    """
    cast_vote(world, 0, "RESPONSIBLE", panel_recommendation, client)
    cast_vote(world, 1, "RESPONSIBLE", panel_recommendation, client)
    cast_vote(world, 2, "NOT_RESPONSIBLE", None, client)
    return world


def decide_hearing(
    world: Dict[str, Any], client: ApiClient = api_client
) -> Dict[str, Any]:
    world["session"] = _d(
        client.decide_hearing_session(world["session"]["id"], world["chair_h"])
    )
    world["case"] = read_case(world["case"]["id"], world["officer"], client)
    return world


def adjourn_hearing(
    world: Dict[str, Any], client: ApiClient = api_client, **overrides
) -> Dict[str, Any]:
    world["session"] = _d(
        client.adjourn_hearing_session(
            world["session"]["id"], f.adjourn_payload(**overrides), world["chair_h"]
        )
    )
    world["case"] = read_case(world["case"]["id"], world["officer"], client)
    return world


def cancel_hearing(
    world: Dict[str, Any], client: ApiClient = api_client, **overrides
) -> Dict[str, Any]:
    world["session"] = _d(
        client.cancel_hearing_session(
            world["session"]["id"], f.cancel_payload(**overrides), world["officer"]
        )
    )
    world["case"] = read_case(world["case"]["id"], world["officer"], client)
    return world


def seed_decided_case(
    world: Optional[Dict[str, Any]] = None,
    panel_recommendation: int = 3,
    client: ApiClient = api_client,
    **kwargs,
) -> Dict[str, Any]:
    """DECIDED, RESPONSIBLE on a PANEL basis, `decided_at` = 2026-08-20T10:00:00Z.

    With the default recommendation of 3 the case's tier rank is also 3, so
    `recommended_ladder_rank` is 3 and the office band is the closed interval
    from 2 to 4 — which is the only route to the rank-4 sanction kind.
    """
    world = world if world is not None else seed_convened_session(client=client, **kwargs)
    cast_responsible_majority(world, panel_recommendation, client)
    return decide_hearing(world, client)


# ---------------------------------------------------------------------------
# Sanctions
# ---------------------------------------------------------------------------


def propose_sanction(
    world: Dict[str, Any],
    ladder_rank: int = 3,
    effective_from: Optional[str] = None,
    client: ApiClient = api_client,
    **overrides,
) -> Dict[str, Any]:
    """Office proposal; `expected_case_version` is re-read immediately before."""
    case = read_case(world["case"]["id"], world["officer"], client)
    world["sanction"] = _d(
        client.create_sanction(
            f.sanction_payload(
                case["id"],
                case["version"],
                ladder_rank,
                effective_from or case["decided_at"] or world["clock"],
                **overrides,
            ),
            world["officer"],
        ),
        201,
    )
    world["case"] = read_case(case["id"], world["officer"], client)
    return world


def impose_sanction(
    world: Dict[str, Any], sanction_id: Optional[str] = None, client: ApiClient = api_client
) -> Dict[str, Any]:
    """Head of the five-hop cascade (PRD §3.8)."""
    world["sanction"] = _d(
        client.impose_sanction(
            sanction_id or world["sanction"]["id"], world["officer"]
        )
    )
    world["case"] = read_case(world["case"]["id"], world["officer"], client)
    return world


def complete_sanction(
    world: Dict[str, Any], sanction_id: Optional[str] = None, client: ApiClient = api_client
) -> Dict[str, Any]:
    world["sanction"] = _d(
        client.complete_sanction(
            sanction_id or world["sanction"]["id"], world["officer"]
        )
    )
    world["case"] = read_case(world["case"]["id"], world["officer"], client)
    return world


def seed_case_with_proposed_sanction(
    world: Optional[Dict[str, Any]] = None,
    ladder_rank: int = 3,
    client: ApiClient = api_client,
    **kwargs,
) -> Dict[str, Any]:
    world = world if world is not None else seed_decided_case(client=client, **kwargs)
    return propose_sanction(world, ladder_rank, client=client)


def seed_case_with_imposed_sanction(
    world: Optional[Dict[str, Any]] = None,
    ladder_rank: int = 3,
    client: ApiClient = api_client,
    **kwargs,
) -> Dict[str, Any]:
    """SANCTION_IMPOSED; at rank 4 or above `notation_status` is PENDING_POSTING."""
    world = (
        world
        if world is not None
        else seed_case_with_proposed_sanction(
            ladder_rank=ladder_rank, client=client, **kwargs
        )
    )
    return impose_sanction(world, client=client)


def seed_case_with_posted_notation(
    world: Optional[Dict[str, Any]] = None,
    ladder_rank: int = 4,
    client: ApiClient = api_client,
    **kwargs,
) -> Dict[str, Any]:
    """notation_status POSTED while the adjudication dimension sits at
    SANCTION_IMPOSED — the two dimensions advance independently (PRD §2.10)."""
    world = (
        world
        if world is not None
        else seed_case_with_imposed_sanction(
            ladder_rank=ladder_rank, client=client, **kwargs
        )
    )
    world["case"] = _d(client.post_notation(world["case"]["id"], world["registrar"]))
    return world


def seed_closed_case_with_posted_notation(
    world: Optional[Dict[str, Any]] = None,
    ladder_rank: int = 4,
    client: ApiClient = api_client,
    **kwargs,
) -> Dict[str, Any]:
    """Posted notation, then completion, so `expungement_eligible_at` is set."""
    world = (
        world
        if world is not None
        else seed_case_with_posted_notation(
            ladder_rank=ladder_rank, client=client, **kwargs
        )
    )
    return complete_sanction(world, client=client)


def post_notation(world: Dict[str, Any], client: ApiClient = api_client) -> Dict[str, Any]:
    world["case"] = _d(client.post_notation(world["case"]["id"], world["registrar"]))
    return world


def request_expungement(
    world: Dict[str, Any], client: ApiClient = api_client, **overrides
) -> Dict[str, Any]:
    world["case"] = _d(
        client.request_expungement(
            world["case"]["id"],
            f.expungement_request_payload(**overrides),
            world["student_h"],
        )
    )
    return world


def decide_expungement(
    world: Dict[str, Any],
    decision: str,
    decision_reason: Optional[str] = None,
    client: ApiClient = api_client,
) -> Dict[str, Any]:
    world["case"] = _d(
        client.decide_expungement(
            world["case"]["id"],
            f.expungement_decision_payload(decision, decision_reason),
            world["registrar"],
        )
    )
    return world


# ---------------------------------------------------------------------------
# Appeals
# ---------------------------------------------------------------------------


def file_appeal(
    world: Dict[str, Any],
    grounds: str = "PROCEDURE",
    client: ApiClient = api_client,
    **overrides,
) -> Dict[str, Any]:
    world["appeal"] = _d(
        client.create_appeal(
            f.appeal_payload(world["case"]["id"], grounds=grounds, **overrides),
            world["student_h"],
        ),
        201,
    )
    return world


def screen_appeal(
    world: Dict[str, Any],
    decision: str = "ACCEPT_FOR_REVIEW",
    decision_reason: Optional[str] = None,
    client: ApiClient = api_client,
) -> Dict[str, Any]:
    world["appeal"] = _d(
        client.screen_appeal(
            world["appeal"]["id"],
            f.screen_payload(decision, decision_reason),
            world["dean"],
        )
    )
    world["case"] = read_case(world["case"]["id"], world["officer"], client)
    return world


def decide_appeal(
    world: Dict[str, Any],
    outcome: str,
    reduced_ladder_rank: Optional[int] = None,
    client: ApiClient = api_client,
    **overrides,
) -> Dict[str, Any]:
    world["appeal"] = _d(
        client.decide_appeal(
            world["appeal"]["id"],
            f.appeal_decision_payload(
                outcome, reduced_ladder_rank=reduced_ladder_rank, **overrides
            ),
            world["dean"],
        )
    )
    world["case"] = read_case(world["case"]["id"], world["officer"], client)
    return world


def seed_appeal_under_review(
    world: Optional[Dict[str, Any]] = None,
    grounds: str = "PROCEDURE",
    client: ApiClient = api_client,
    **kwargs,
) -> Dict[str, Any]:
    """APPEAL_UNDER_REVIEW with `pre_appeal_adjudication_status` recorded."""
    world = world if world is not None else seed_decided_case(client=client, **kwargs)
    file_appeal(world, grounds=grounds, client=client)
    return screen_appeal(world, "ACCEPT_FOR_REVIEW", client=client)


# ---------------------------------------------------------------------------
# Prior history (the legacy import)
# ---------------------------------------------------------------------------


def seed_legacy_prior_case(
    world: Dict[str, Any],
    decided_at: str = "2025-09-01T00:00:00Z",
    completed_at: str = "2025-12-01T00:00:00Z",
    imposed_ladder_rank: int = 5,
    responsibility_finding: str = "RESPONSIBLE",
    course_code: Optional[str] = None,
    client: ApiClient = api_client,
) -> Dict[str, Any]:
    """Backfill one closed prior case for the same student.

    A separate offering is created so the prior can carry a different
    `course_code`, which is what the cross-course pattern detector counts
    (PRD §3.4).  The report stays in DRAFT, as the import requires.
    """
    offering = create_offering(
        world["dept"]["id"],
        world["reporter"]["id"],
        world["officer"],
        client,
        unique=True,
        **({"course_code": course_code} if course_code else {}),
    )
    report = create_report(
        offering["id"], world["student"]["id"], world["reporter_h"], client
    )
    prior = _d(
        client.legacy_import_case(
            f.legacy_import_payload(
                report["id"],
                decided_at=decided_at,
                responsibility_finding=responsibility_finding,
                imposed_ladder_rank=imposed_ladder_rank,
                completed_at=completed_at,
            ),
            world["officer"],
        ),
        201,
    )
    world.setdefault("priors", []).append(prior)
    world.setdefault("prior_offerings", []).append(offering)
    world["prior"] = prior
    return world


# ---------------------------------------------------------------------------
# Sibling cases (for the cascade tests)
# ---------------------------------------------------------------------------


def seed_sibling_case(
    world: Dict[str, Any],
    client: ApiClient = api_client,
    course_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Open a second live case for the same student on a different offering."""
    offering = create_offering(
        world["dept"]["id"],
        world["reporter"]["id"],
        world["officer"],
        client,
        unique=True,
        **({"course_code": course_code} if course_code else {}),
    )
    report = create_report(
        offering["id"], world["student"]["id"], world["reporter_h"], client
    )
    attach_similarity_evidence(report["id"], world["reporter_h"], client)
    submit_report(report["id"], world["reporter_h"], client)
    triage_report(report["id"], "ACCEPT", headers=world["officer"], client=client)
    sibling = open_case(report["id"], world["officer"], client)
    world.setdefault("siblings", []).append(sibling)
    world.setdefault("sibling_offerings", []).append(offering)
    world["sibling"] = sibling
    world["sibling_report"] = report
    return world
