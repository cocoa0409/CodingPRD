"""Composite setup helpers for the accident-investigation domain.

The test harness restarts the API server before every individual test, so each
test starts against an empty database and the logical clock reads
2026-09-01T00:00:00Z (PRD §2.4). Every helper builds its preconditions from
scratch through PRD-declared endpoints, and every composite chain pins the
clock explicitly first so timestamps are deterministic.

Ownership threading (PRD §2.1): IIC calls use make_iic_headers(iic_user_id),
GroupChairman calls use make_group_chairman_headers(chairman_user_id),
AddresseeContact calls use make_addressee_contact_headers(org_id), and
BoardMember votes use make_board_member_headers(member_id). The launch SoD
pair is md-1 (proposer) / md-2 (adopter) (PRD §3.2).

Composite fixtures return dicts with documented keys; single-resource helpers
return the resource's data payload (the full resource in its post-call state).
All helpers use get_success_data so a broken setup fails fast with a clear
"Setup step failed" message.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import (
    DEFAULT_BENCH_ID,
    DEFAULT_CHAIRMAN_USER_ID,
    DEFAULT_IIC_USER_ID,
    DEFAULT_MEETING_WINDOW_END,
    DEFAULT_MEETING_WINDOW_START,
    DEFAULT_ROOM_ID,
    DEFAULT_SESSION_WINDOW_END,
    DEFAULT_SESSION_WINDOW_START,
    INITIAL_CLOCK_UTC,
    UNACCEPTABLE_STREAK_FOR_CLOSE,
)
from .factories import (
    adopt_launch_decision_payload,
    advance_phase_payload,
    classify_response_payload,
    close_recommendation_payload,
    conduct_violation_payload,
    create_accident_case_payload,
    create_board_meeting_payload,
    create_group_payload,
    create_party_designation_payload,
    create_party_organization_payload,
    create_recorder_payload,
    create_safety_recommendation_payload,
    create_seat_payload,
    expel_party_designation_payload,
    factual_report_payload,
    propose_launch_decision_payload,
    readout_session_payload,
    recommendation_response_payload,
    reconsider_launch_decision_payload,
    vote_payload,
)
from .test_users import (
    TEST_USERS,
    make_addressee_contact_headers,
    make_board_member_headers,
    make_group_chairman_headers,
    make_iic_headers,
)

DUTY_OFFICER = TEST_USERS["duty_officer_headers"]
MD_PROPOSER = TEST_USERS["md_proposer_headers"]
MD_ADOPTER = TEST_USERS["md_adopter_headers"]
PARTY_COORDINATOR = TEST_USERS["party_coordinator_headers"]
RECORDER_CUSTODIAN = TEST_USERS["recorder_custodian_headers"]
DOCKET_OFFICER = TEST_USERS["docket_officer_headers"]
BOARD_ADMIN = TEST_USERS["board_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock, single-resource creates, reads, and embedded-record finders
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=INITIAL_CLOCK_UTC) -> dict:
    """Move the server logical clock (BoardAdmin). Returns {current_utc}."""
    return get_success_data(api.set_clock(to_iso8601, BOARD_ADMIN))


def create_case(**overrides) -> dict:
    """Register an accident notification (DutyOfficer, 201). Returns AccidentCase
    with computed statutory_score / risk_adjusted_score / suggested_mode."""
    return get_success_data(
        api.create_accident_case(create_accident_case_payload(**overrides), DUTY_OFFICER)
    )


def get_case(case_id) -> dict:
    return get_success_data(api.get_accident_case(case_id, DUTY_OFFICER))


def find_decision(case: dict, decision_id) -> dict:
    for decision in case["launch_decisions"]:
        if decision["decision_id"] == decision_id:
            return decision
    raise AssertionError(f"decision {decision_id} not found in case {case['id']}")


def get_proposed_decision(case: dict) -> dict:
    """The single PROPOSED embedded decision (at most one exists per case)."""
    proposed = [d for d in case["launch_decisions"] if d["status"] == "PROPOSED"]
    assert len(proposed) == 1, (
        f"expected exactly one PROPOSED decision on case {case['id']}, "
        f"found {len(proposed)}"
    )
    return proposed[0]


def get_investigation(investigation_id) -> dict:
    return get_success_data(api.get_investigation(investigation_id, DUTY_OFFICER))


def get_investigation_for_case(case_id) -> dict:
    """The investigation cascade-created by a FULL_GO_TEAM adoption. At most one
    investigation ever exists per accident case (PRD §3.2)."""
    rows = get_success_data(
        api.list_investigations(DUTY_OFFICER, params={"accident_case_id": case_id})
    )
    assert isinstance(rows, list) and len(rows) == 1, (
        f"expected exactly one investigation for case {case_id}, got {len(rows)}"
    )
    return rows[0]


def create_org(**overrides) -> dict:
    """Register a party organization (PartyCoordinator, 201)."""
    return get_success_data(
        api.create_party_organization(
            create_party_organization_payload(**overrides), PARTY_COORDINATOR
        )
    )


def get_org(organization_id) -> dict:
    return get_success_data(api.get_party_organization(organization_id, DUTY_OFFICER))


def create_designation(investigation_id, organization_id, **overrides) -> dict:
    """Designate an organization as a party to an investigation (201, ACTIVE)."""
    return get_success_data(
        api.create_party_designation(
            create_party_designation_payload(investigation_id, organization_id, **overrides),
            PARTY_COORDINATOR,
        )
    )


def get_designation(designation_id) -> dict:
    return get_success_data(api.get_party_designation(designation_id, DUTY_OFFICER))


def find_seat(designation: dict, group_id=None, seat_id=None) -> dict:
    """Locate an embedded GroupSeat. With group_id, returns the (first) seat on
    that group; with seat_id, the matching seat; with neither, the most recently
    appended seat."""
    seats = designation["group_seats"]
    if seat_id is not None:
        for seat in seats:
            if seat["seat_id"] == seat_id:
                return seat
        raise AssertionError(f"seat {seat_id} not found in designation {designation['id']}")
    if group_id is not None:
        for seat in seats:
            if seat["group_id"] == group_id:
                return seat
        raise AssertionError(
            f"no seat on group {group_id} in designation {designation['id']}"
        )
    assert seats, f"designation {designation['id']} has no group_seats"
    return seats[-1]


def create_group(
    investigation_id,
    iic_user_id=DEFAULT_IIC_USER_ID,
    specialty="OPERATIONS",
    chairman_user_id=DEFAULT_CHAIRMAN_USER_ID,
    **overrides,
) -> dict:
    """Form an investigative group (IIC, 201, ACTIVE, seated_count 0)."""
    return get_success_data(
        api.create_group(
            create_group_payload(
                investigation_id, specialty, chairman_user_id, **overrides
            ),
            make_iic_headers(iic_user_id),
        )
    )


def get_group(group_id) -> dict:
    return get_success_data(api.get_group(group_id, DUTY_OFFICER))


def find_report(group: dict, report_id=None) -> dict:
    """Locate an embedded FactualReport by id; with report_id=None, the most
    recently appended report."""
    reports = group["factual_reports"]
    if report_id is not None:
        for report in reports:
            if report["report_id"] == report_id:
                return report
        raise AssertionError(f"report {report_id} not found in group {group['id']}")
    assert reports, f"group {group['id']} has no factual_reports"
    return reports[-1]


def create_recorder(investigation_id, **overrides) -> dict:
    """Register a recorder package (RecorderCustodian, 201, SECURED)."""
    return get_success_data(
        api.create_recorder(
            create_recorder_payload(investigation_id, **overrides), RECORDER_CUSTODIAN
        )
    )


def get_recorder(recorder_id) -> dict:
    return get_success_data(api.get_recorder(recorder_id, RECORDER_CUSTODIAN))


def find_session(recorder: dict, session_id=None) -> dict:
    """Locate an embedded ReadoutSession by id; with session_id=None, the most
    recently appended session."""
    sessions = recorder["readout_sessions"]
    if session_id is not None:
        for session in sessions:
            if session["session_id"] == session_id:
                return session
        raise AssertionError(f"session {session_id} not found in recorder {recorder['id']}")
    assert sessions, f"recorder {recorder['id']} has no readout_sessions"
    return sessions[-1]


def get_recommendation(recommendation_id) -> dict:
    return get_success_data(api.get_safety_recommendation(recommendation_id, DUTY_OFFICER))


def get_meeting(meeting_id) -> dict:
    return get_success_data(api.get_board_meeting(meeting_id, DUTY_OFFICER))


# ---------------------------------------------------------------------------
# Tier 1: launch pipeline (case -> propose -> adopt) (PRD §3.1, §3.2)
# ---------------------------------------------------------------------------

def propose_launch_decision(case, mode="FULL_GO_TEAM", proposer_headers=None, **overrides) -> dict:
    """Propose a launch decision as ManagingDirector (md-1 by default), carrying
    the case's current version for OCC. `case` is an AccidentCase data dict.
    Returns the updated AccidentCase (201)."""
    payload = propose_launch_decision_payload(mode, case["version"], **overrides)
    return get_success_data(
        api.propose_launch_decision(case["id"], payload, proposer_headers or MD_PROPOSER)
    )


def adopt_launch_decision(
    case_id,
    decision_id,
    iic_user_id=DEFAULT_IIC_USER_ID,
    adopter_headers=None,
) -> dict:
    """Adopt a PROPOSED decision as a different ManagingDirector (md-2 by
    default; PRD §3.2 bars the proposer). Pass iic_user_id=None for
    LIMITED/DECLINED modes (the field must be absent). Returns AccidentCase."""
    payload = adopt_launch_decision_payload(iic_user_id)
    return get_success_data(
        api.adopt_launch_decision(case_id, decision_id, payload, adopter_headers or MD_ADOPTER)
    )


def reconsider_launch_decision(case_id, decision_id, md_headers=None, **overrides) -> dict:
    """Reopen an ADOPTED decision (LIMITED_TRACK/DECLINED cases only).
    Overrides may carry rationale and/or severity fields. Returns AccidentCase."""
    return get_success_data(
        api.reconsider_launch_decision(
            case_id,
            decision_id,
            reconsider_launch_decision_payload(**overrides),
            md_headers or MD_PROPOSER,
        )
    )


def setup_case_with_adopted_decision(mode="LIMITED", iic_user_id=None, **case_overrides) -> dict:
    """Clock + case + propose + adopt for one launch mode.

    Keys: case (post-adoption AccidentCase), decision_id.
    For LIMITED the case moves to LIMITED_TRACK; DECLINED to DECLINED;
    FULL_GO_TEAM launches (iic_user_id is then required and defaults to the
    canonical iic-1) — but callers wanting the investigation should prefer
    setup_launched_investigation().
    """
    if mode == "FULL_GO_TEAM" and iic_user_id is None:
        iic_user_id = DEFAULT_IIC_USER_ID
    set_clock()
    case = create_case(**case_overrides)
    case = propose_launch_decision(case, mode=mode)
    decision = get_proposed_decision(case)
    case = adopt_launch_decision(
        case["id"], decision["decision_id"], iic_user_id=iic_user_id
    )
    return {"case": case, "decision_id": decision["decision_id"]}


def setup_launched_investigation(iic_user_id=DEFAULT_IIC_USER_ID, **case_overrides) -> dict:
    """Clock + case + propose FULL_GO_TEAM (md-1) + adopt (md-2): the case is
    LAUNCHED and its investigation exists in GO_TEAM_ASSEMBLED / docket SEALED.

    Keys: case, decision_id, investigation, iic_user_id.
    """
    set_clock()
    case = create_case(**case_overrides)
    case = propose_launch_decision(case, mode="FULL_GO_TEAM")
    decision = get_proposed_decision(case)
    case = adopt_launch_decision(
        case["id"], decision["decision_id"], iic_user_id=iic_user_id
    )
    investigation = get_investigation_for_case(case["id"])
    return {
        "case": case,
        "decision_id": decision["decision_id"],
        "investigation": investigation,
        "iic_user_id": iic_user_id,
    }


# ---------------------------------------------------------------------------
# Tier 2: party hierarchy and investigation phases (PRD §3.3, §3.5)
# ---------------------------------------------------------------------------

def advance_phase(investigation_id, to_phase, iic_user_id=DEFAULT_IIC_USER_ID) -> dict:
    """Advance the investigation one declared hop (IIC-scoped). Returns the
    updated Investigation."""
    return get_success_data(
        api.advance_phase(
            investigation_id, advance_phase_payload(to_phase), make_iic_headers(iic_user_id)
        )
    )


def reopen_factual(investigation_id, iic_user_id=DEFAULT_IIC_USER_ID) -> dict:
    """Revert ANALYSIS -> FACTUAL (COMPLETE groups revert to ACTIVE; an OPEN
    docket stays OPEN). Returns the updated Investigation."""
    return get_success_data(
        api.reopen_factual(investigation_id, make_iic_headers(iic_user_id))
    )


def release_docket(investigation_id) -> dict:
    """Release the public docket (DocketOfficer): VERIFIED reports -> DOCKETED,
    completed recorders -> RELEASED, docket SEALED -> OPEN. Returns the
    updated Investigation."""
    return get_success_data(api.release_docket(investigation_id, DOCKET_OFFICER))


def create_seat(designation_id, group_id, iic_user_id=DEFAULT_IIC_USER_ID) -> dict:
    """Seat a designated party on a group (IIC, 201). Returns the updated
    PartyDesignation including the new embedded seat."""
    return get_success_data(
        api.create_seat(
            designation_id, create_seat_payload(group_id), make_iic_headers(iic_user_id)
        )
    )


def setup_on_scene(
    iic_user_id=DEFAULT_IIC_USER_ID,
    chairman_user_id=DEFAULT_CHAIRMAN_USER_ID,
    org_overrides=None,
    case_overrides=None,
) -> dict:
    """Launched investigation + one ACTIVE group + advance to ON_SCENE + one
    OPERATOR organization + ACTIVE designation + one SEATED seat on the group.

    Keys: case, decision_id, investigation, iic_user_id, group,
    chairman_user_id, org, designation, seat_id.
    """
    base = setup_launched_investigation(iic_user_id=iic_user_id, **(case_overrides or {}))
    inv_id = base["investigation"]["id"]
    group = create_group(
        inv_id, iic_user_id=iic_user_id, chairman_user_id=chairman_user_id
    )
    investigation = advance_phase(inv_id, "ON_SCENE", iic_user_id=iic_user_id)
    org = create_org(**(org_overrides or {}))
    designation = create_designation(inv_id, org["id"])
    designation = create_seat(designation["id"], group["id"], iic_user_id=iic_user_id)
    return {
        **base,
        "investigation": investigation,
        # Re-read post-seat: seated_count is recomputed on seat creation
        # (PRD §3.3), so the creation-time snapshot would report 0.
        "group": get_group(group["id"]),
        "chairman_user_id": chairman_user_id,
        "org": org,
        "designation": designation,
        "seat_id": find_seat(designation, group_id=group["id"])["seat_id"],
    }


def create_factual_report(
    group_id,
    chairman_user_id=DEFAULT_CHAIRMAN_USER_ID,
    report_kind="GROUP_FACTUAL",
    content="Factual record: brake system teardown results.",
    recorder_id=None,
    **overrides,
) -> dict:
    """Author a factual report (GroupChairman, 201, SUBMITTED). Returns the
    updated InvestigativeGroup including the new embedded report."""
    return get_success_data(
        api.create_factual_report(
            group_id,
            factual_report_payload(report_kind, content, recorder_id, **overrides),
            make_group_chairman_headers(chairman_user_id),
        )
    )


def verify_report(group_id, report_id, iic_user_id=DEFAULT_IIC_USER_ID) -> dict:
    """IIC verifies a SUBMITTED report. Returns the updated InvestigativeGroup."""
    return get_success_data(
        api.verify_factual_report(group_id, report_id, make_iic_headers(iic_user_id))
    )


def complete_group(group_id, chairman_user_id=DEFAULT_CHAIRMAN_USER_ID) -> dict:
    """Chairman marks the group COMPLETE. Returns the updated InvestigativeGroup."""
    return get_success_data(
        api.complete_group(group_id, make_group_chairman_headers(chairman_user_id))
    )


def setup_factual(
    iic_user_id=DEFAULT_IIC_USER_ID,
    chairman_user_id=DEFAULT_CHAIRMAN_USER_ID,
    org_overrides=None,
    case_overrides=None,
    report_overrides=None,
) -> dict:
    """On-scene chain + advance to FACTUAL + one SUBMITTED GROUP_FACTUAL report.

    Keys: setup_on_scene keys + report_id (group refreshed post-report).
    """
    ctx = setup_on_scene(
        iic_user_id=iic_user_id,
        chairman_user_id=chairman_user_id,
        org_overrides=org_overrides,
        case_overrides=case_overrides,
    )
    inv_id = ctx["investigation"]["id"]
    ctx["investigation"] = advance_phase(inv_id, "FACTUAL", iic_user_id=iic_user_id)
    ctx["group"] = create_factual_report(
        ctx["group"]["id"], chairman_user_id=chairman_user_id, **(report_overrides or {})
    )
    ctx["report_id"] = find_report(ctx["group"])["report_id"]
    return ctx


def setup_group_completed(**kwargs) -> dict:
    """Factual chain + verify + complete: the group is COMPLETE with one
    VERIFIED report and one SEATED seat. Keys: setup_factual keys (group and
    investigation refreshed)."""
    ctx = setup_factual(**kwargs)
    ctx["group"] = verify_report(
        ctx["group"]["id"], ctx["report_id"], iic_user_id=ctx["iic_user_id"]
    )
    ctx["group"] = complete_group(
        ctx["group"]["id"], chairman_user_id=ctx["chairman_user_id"]
    )
    ctx["investigation"] = get_investigation(ctx["investigation"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: docket, analysis, recommendations, board lifecycle (PRD §3.5–§3.8)
# ---------------------------------------------------------------------------

def setup_docket_released(**kwargs) -> dict:
    """Group-completed chain + release-docket: docket OPEN, the report
    DOCKETED, docket_completeness_pct 100. Keys: setup_group_completed keys
    (investigation and group refreshed)."""
    ctx = setup_group_completed(**kwargs)
    ctx["investigation"] = release_docket(ctx["investigation"]["id"])
    ctx["group"] = get_group(ctx["group"]["id"])
    return ctx


def setup_analysis(**kwargs) -> dict:
    """Docket-released chain + advance to ANALYSIS. Keys: setup_docket_released
    keys (investigation refreshed)."""
    ctx = setup_docket_released(**kwargs)
    ctx["investigation"] = advance_phase(
        ctx["investigation"]["id"], "ANALYSIS", iic_user_id=ctx["iic_user_id"]
    )
    return ctx


def issue_recommendation(
    investigation_id,
    addressee_org_id,
    iic_user_id=DEFAULT_IIC_USER_ID,
    **overrides,
) -> dict:
    """Issue a safety recommendation (IIC, 201, OPEN_AWAITING_RESPONSE).
    Requires the investigation to be in ANALYSIS or BOARD_REVIEW (PRD §3.7)."""
    return get_success_data(
        api.create_safety_recommendation(
            create_safety_recommendation_payload(
                investigation_id, addressee_org_id, **overrides
            ),
            make_iic_headers(iic_user_id),
        )
    )


def setup_analysis_with_recommendation(**kwargs) -> dict:
    """Analysis chain + one recommendation addressed to the chain's operator
    organization. Keys: setup_analysis keys + recommendation."""
    ctx = setup_analysis(**kwargs)
    ctx["recommendation"] = issue_recommendation(
        ctx["investigation"]["id"], ctx["org"]["id"], iic_user_id=ctx["iic_user_id"]
    )
    return ctx


def submit_response(recommendation_id, org_id, response_text="We will implement the recommendation.") -> dict:
    """Addressee organization responds (entity-backed: X-User-ID is the org id).
    Moves the recommendation to OPEN_UNCLASSIFIED. Returns the updated
    SafetyRecommendation."""
    return get_success_data(
        api.submit_response(
            recommendation_id,
            recommendation_response_payload(response_text),
            make_addressee_contact_headers(org_id),
        )
    )


def classify_pending_response(recommendation_id, classification, md_headers=None) -> dict:
    """ManagingDirector classifies the pending response (OPEN_UNCLASSIFIED ->
    OPEN_ACCEPTABLE / OPEN_UNACCEPTABLE). Returns the updated SafetyRecommendation."""
    return get_success_data(
        api.classify_response(
            recommendation_id,
            classify_response_payload(classification),
            md_headers or MD_PROPOSER,
        )
    )


def respond_and_classify(
    recommendation_id,
    org_id,
    classification,
    response_text="Response to the safety recommendation.",
) -> dict:
    """One full respond + classify cycle. Returns the post-classification
    SafetyRecommendation."""
    submit_response(recommendation_id, org_id, response_text=response_text)
    return classify_pending_response(recommendation_id, classification)


def close_recommendation(recommendation_id, outcome, md_headers=None) -> dict:
    """Close a recommendation (CLOSED_ACCEPTABLE / CLOSED_EXCEEDS from
    OPEN_ACCEPTABLE; CLOSED_UNACCEPTABLE from OPEN_UNACCEPTABLE with streak
    >= 2). Returns the updated SafetyRecommendation."""
    return get_success_data(
        api.close_recommendation(
            recommendation_id,
            close_recommendation_payload(outcome),
            md_headers or MD_PROPOSER,
        )
    )


def build_unacceptable_streak(recommendation_id, org_id, count=UNACCEPTABLE_STREAK_FOR_CLOSE) -> dict:
    """Run `count` respond+classify-UNACCEPTABLE cycles so unacceptable_streak
    reaches `count`. Returns the final SafetyRecommendation (OPEN_UNACCEPTABLE)."""
    recommendation = None
    for _ in range(count):
        recommendation = respond_and_classify(
            recommendation_id, org_id, "UNACCEPTABLE"
        )
    return recommendation


def schedule_board_meeting(investigation_id, **overrides) -> dict:
    """Schedule a board meeting (BoardAdmin, 201, SCHEDULED). Default window is
    2026-09-02T09:00–10:00Z on room-1 with members bm-1/bm-2/bm-3 — strictly
    after the initial clock, satisfying quorum."""
    return get_success_data(
        api.create_board_meeting(
            create_board_meeting_payload(investigation_id, **overrides), BOARD_ADMIN
        )
    )


def setup_board_review(meeting_overrides=None, **kwargs) -> dict:
    """Analysis chain + one SCHEDULED board meeting + advance to BOARD_REVIEW.
    Keys: setup_analysis keys + meeting."""
    ctx = setup_analysis(**kwargs)
    ctx["meeting"] = schedule_board_meeting(
        ctx["investigation"]["id"], **(meeting_overrides or {})
    )
    ctx["investigation"] = advance_phase(
        ctx["investigation"]["id"], "BOARD_REVIEW", iic_user_id=ctx["iic_user_id"]
    )
    return ctx


def setup_meeting_in_session(meeting_overrides=None, **kwargs) -> dict:
    """Board-review chain, then the clock is moved to the meeting's
    window_start_utc so the meeting is effectively IN_SESSION (lazy evaluation,
    PRD §2.4). Keys: setup_board_review keys (meeting re-read after the clock
    move). NOTE: the logical clock now reads the meeting's window start — any
    later windowed scheduling must start strictly after it."""
    ctx = setup_board_review(meeting_overrides=meeting_overrides, **kwargs)
    set_clock(ctx["meeting"]["window_start_utc"])
    ctx["meeting"] = get_meeting(ctx["meeting"]["id"])
    return ctx


def cast_vote(meeting, member_user_id, position, dissent_text=None) -> dict:
    """Cast/change/retract one sitting member's vote with OCC: `meeting` is a
    BoardMeeting data dict whose current version is carried as
    expected_meeting_version. Returns the updated BoardMeeting."""
    payload = vote_payload(position, meeting["version"], dissent_text=dissent_text)
    return get_success_data(
        api.cast_vote(meeting["id"], payload, make_board_member_headers(member_user_id))
    )


def cast_votes(meeting, votes) -> dict:
    """Cast several votes in sequence, chaining the OCC version across calls.
    `votes` entries are (member_user_id, position) or
    (member_user_id, position, dissent_text). Returns the final BoardMeeting."""
    current = meeting
    for entry in votes:
        current = cast_vote(current, *entry)
    return current


def close_meeting(meeting_id) -> dict:
    """Close an in-session meeting (BoardAdmin): outcome computed, cascade to
    the investigation and the case executed. Returns the updated BoardMeeting."""
    return get_success_data(api.close_board_meeting(meeting_id, BOARD_ADMIN))


# ---------------------------------------------------------------------------
# Tier 4: conduct accumulation, recorder readouts (PRD §3.4, §3.6)
# ---------------------------------------------------------------------------

def record_conduct_violation(
    designation_id,
    seat_id,
    iic_user_id=DEFAULT_IIC_USER_ID,
    violation_kind="PREMATURE_PUBLIC_STATEMENT",
    detail="Conduct violation recorded by the IIC.",
) -> dict:
    """Record one conduct violation against a SEATED seat (IIC, 201). The
    second strike auto-suspends the seat. Returns the updated PartyDesignation."""
    return get_success_data(
        api.record_conduct_violation(
            designation_id,
            seat_id,
            conduct_violation_payload(violation_kind, detail),
            make_iic_headers(iic_user_id),
        )
    )


def record_violations(
    designation_id,
    seat_id,
    count,
    iic_user_id=DEFAULT_IIC_USER_ID,
    violation_kinds=None,
) -> dict:
    """Record `count` violations in sequence (cycling violation_kinds if
    given). NOTE: the seat auto-suspends at 2 strikes, so count > 2 fails on a
    still-SEATED precondition. Returns the final PartyDesignation."""
    kinds = violation_kinds or ["PREMATURE_PUBLIC_STATEMENT"]
    designation = None
    for i in range(count):
        designation = record_conduct_violation(
            designation_id,
            seat_id,
            iic_user_id=iic_user_id,
            violation_kind=kinds[i % len(kinds)],
            detail=f"Violation {i + 1}.",
        )
    return designation


def expel_designation(designation_id, md_headers=None, **overrides) -> dict:
    """Expel a party (ManagingDirector) — requires a qualifying
    PREMATURE_PUBLIC_STATEMENT violation on the designation's seats. Returns
    the updated PartyDesignation (EXPELLED)."""
    return get_success_data(
        api.expel_party_designation(
            designation_id, expel_party_designation_payload(**overrides), md_headers or MD_PROPOSER
        )
    )


def schedule_readout_session(
    recorder_id,
    bench_id=DEFAULT_BENCH_ID,
    window_start_utc=DEFAULT_SESSION_WINDOW_START,
    window_end_utc=DEFAULT_SESSION_WINDOW_END,
    **overrides,
) -> dict:
    """Schedule a lab-bench readout session (RecorderCustodian, 201). The first
    session moves the recorder SECURED -> IN_READOUT. Returns the updated
    RecorderPackage."""
    return get_success_data(
        api.create_readout_session(
            recorder_id,
            readout_session_payload(bench_id, window_start_utc, window_end_utc, **overrides),
            RECORDER_CUSTODIAN,
        )
    )


def setup_recorder_with_pending_session(
    investigation_id,
    bench_id=DEFAULT_BENCH_ID,
    window_start_utc="2026-09-03T10:00:00Z",
    window_end_utc="2026-09-03T12:00:00Z",
    **recorder_overrides,
) -> dict:
    """One recorder with a single session whose window is still in the future
    relative to the initial clock (2026-09-01T00:00:00Z) — the state needed to
    exercise ERR_RECORDER_READOUT_INCOMPLETE gates. Returns the RecorderPackage
    (IN_READOUT)."""
    recorder = create_recorder(investigation_id, **recorder_overrides)
    return schedule_readout_session(
        recorder["id"],
        bench_id=bench_id,
        window_start_utc=window_start_utc,
        window_end_utc=window_end_utc,
    )


def complete_readout(recorder) -> dict:
    """Advance the logical clock to the recorder's latest session end so lazy
    evaluation flips sessions COMPLETE and the recorder READOUT_COMPLETE on the
    re-read (PRD §2.4). Returns the re-read RecorderPackage."""
    sessions = recorder["readout_sessions"]
    assert sessions, "complete_readout requires at least one scheduled session"
    set_clock(max(s["window_end_utc"] for s in sessions))
    return get_recorder(recorder["id"])


# ---------------------------------------------------------------------------
# Tier 5: terminal state (full adoption cascade) (PRD §3.8, §2.10)
# ---------------------------------------------------------------------------

def setup_adopted_case(meeting_overrides=None, votes=None, **kwargs) -> dict:
    """Meeting-in-session chain + votes + close with an ADOPTED outcome:
    meeting COMPLETED, investigation ADOPTED with docket FINAL and groups
    DISBANDED, case CLOSED_ADOPTED. Default votes are bm-1 ADOPT, bm-2 ADOPT,
    bm-3 REJECT-with-dissent (2 > 1). Keys: setup_meeting_in_session keys with
    meeting, investigation, group, and case refreshed to their post-cascade
    state."""
    ctx = setup_meeting_in_session(meeting_overrides=meeting_overrides, **kwargs)
    if votes is None:
        votes = [
            ("bm-1", "ADOPT"),
            ("bm-2", "ADOPT"),
            ("bm-3", "REJECT", "The probable cause underweights maintenance culture."),
        ]
    ctx["meeting"] = cast_votes(ctx["meeting"], votes)
    ctx["meeting"] = close_meeting(ctx["meeting"]["id"])
    ctx["investigation"] = get_investigation(ctx["investigation"]["id"])
    ctx["group"] = get_group(ctx["group"]["id"])
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


__all__ = [
    # Tier 0
    "set_clock",
    "create_case",
    "get_case",
    "find_decision",
    "get_proposed_decision",
    "get_investigation",
    "get_investigation_for_case",
    "create_org",
    "get_org",
    "create_designation",
    "get_designation",
    "find_seat",
    "create_group",
    "get_group",
    "find_report",
    "create_recorder",
    "get_recorder",
    "find_session",
    "get_recommendation",
    "get_meeting",
    # Tier 1
    "propose_launch_decision",
    "adopt_launch_decision",
    "reconsider_launch_decision",
    "setup_case_with_adopted_decision",
    "setup_launched_investigation",
    # Tier 2
    "advance_phase",
    "reopen_factual",
    "release_docket",
    "create_seat",
    "setup_on_scene",
    "create_factual_report",
    "verify_report",
    "complete_group",
    "setup_factual",
    "setup_group_completed",
    # Tier 3
    "setup_docket_released",
    "setup_analysis",
    "issue_recommendation",
    "setup_analysis_with_recommendation",
    "submit_response",
    "classify_pending_response",
    "respond_and_classify",
    "close_recommendation",
    "build_unacceptable_streak",
    "schedule_board_meeting",
    "setup_board_review",
    "setup_meeting_in_session",
    "cast_vote",
    "cast_votes",
    "close_meeting",
    # Tier 4
    "record_conduct_violation",
    "record_violations",
    "expel_designation",
    "schedule_readout_session",
    "setup_recorder_with_pending_session",
    "complete_readout",
    # Tier 5
    "setup_adopted_case",
]
