"""State-machine probes: administrative closure, recalendar, venue motions,
and the two continuance ruling branches.

The ADMIN_CLOSED cascade cancels only SCHEDULED hearings; recalendar returns
the case to MERITS so the closure loop closes cleanly; a granted venue motion
moves the venue and resets the docket while a denial touches nothing; a
PENDING_APPLICATION continuance grant closes the case with no replacement
hearing while a denial leaves the hearing standing.
"""

from test_helpers import (
    CONTINUANCE_HEARING_START_ISO,
    MASTER_HEARING_START_ISO,
    advance_case_to_merits,
    assert_backlog_flag,
    case_version,
    close_case_administratively,
    create_court,
    decide_continuance,
    decide_venue_motion,
    file_continuance,
    file_venue_motion,
    list_case_hearings,
    make_hearing_payload,
    make_judge_headers,
    read_case,
    read_court,
    read_hearing,
    same_instant,
    schedule_hearing,
    setup_docketed_case,
    validate_success,
    CLOCK_DEFAULT_ISO,
)


def test_administrative_closure_cancels_only_scheduled_hearings():
    """PRD §3.4: "Whichever path delivers a case into `ADMIN_CLOSED`, the same conditional cascade fires: every `SCHEDULED` hearing of the case becomes `CANCELLED`, while hearings already completed, continued, or otherwise resolved are untouched, and the case's `version` increments by 1."
    PRD §3.4: "The direct administrative-closure operation takes a `closure_reason` and requires the case to be `CALENDAR` or `MERITS` (otherwise `ERR_CASE_STATE_FORBIDS_CLOSURE`) and the caller to be the assigned judge (`ERR_NOT_ASSIGNED_JUDGE`)."

    Design: Corner/state_machines/administrative_closure_cancels_only_scheduled_hearings
    """
    ctx = setup_docketed_case()
    # Master hearing completed (case MERITS); a merits hearing stands SCHEDULED.
    m = advance_case_to_merits(ctx["case"], judge_id=ctx["judge"]["id"])
    merits = schedule_hearing(m["case"], "INDIVIDUAL_MERITS", "2026-09-04T10:00:00Z")

    closed = close_case_administratively(
        m["case"], "PENDING_APPLICATION", judge_id=ctx["judge"]["id"]
    )
    assert closed["status"] == "ADMIN_CLOSED"

    # Conditional cascade: the SCHEDULED merits hearing is cancelled...
    assert read_hearing(merits["id"])["status"] == "CANCELLED"
    # ...while the COMPLETED master hearing is untouched.
    assert read_hearing(m["master_hearing"]["id"])["status"] == "COMPLETED"
    assert list_case_hearings(ctx["case"]["id"], status="SCHEDULED") == []


def test_recalendar_returns_admin_closed_case_to_merits(api, admin_headers):
    """PRD §3.4: "The assigned judge may later recalendar the case, an operation that requires the case to be `ADMIN_CLOSED` (otherwise `ERR_CASE_NOT_ADMIN_CLOSED`), requires the same ownership binding, and returns the case `ADMIN_CLOSED → MERITS`, incrementing `version` once more."
    PRD §3.3: "The case must be in `CALENDAR` or `MERITS` — any other posture is rejected with `ERR_CASE_STATE_FORBIDS_HEARING`."

    Design: Corner/state_machines/recalendar_returns_admin_closed_case_to_merits
    """
    ctx = setup_docketed_case()
    m = advance_case_to_merits(ctx["case"], judge_id=ctx["judge"]["id"])
    schedule_hearing(m["case"], "INDIVIDUAL_MERITS", "2026-09-04T10:00:00Z")
    close_case_administratively(
        m["case"], "PENDING_APPLICATION", judge_id=ctx["judge"]["id"]
    )
    case_id = ctx["case"]["id"]

    # Recalendar: 200, case back on the merits docket.
    resp = api.recalendar_case(case_id, headers=make_judge_headers(ctx["judge"]["id"]))
    case = validate_success(resp, expected_status=200)
    assert case["status"] == "MERITS"

    # The closure loop closes cleanly: a new merits hearing schedules at once.
    resp = api.create_hearing(
        make_hearing_payload(
            case_id, "INDIVIDUAL_MERITS", "2026-09-08T10:00:00Z", case_version(case_id)
        ),
        headers=admin_headers,
    )
    hearing = validate_success(resp, expected_status=201)
    assert hearing["status"] == "SCHEDULED"


def test_venue_motion_grant_moves_venue_and_resets_docket():
    """PRD §3.7: "A grant moves the case: its `court_id` becomes the destination court, its `assigned_judge_id` is cleared to null, every `SCHEDULED` hearing of the case is `CANCELLED`, and the case's `status` returns to `FILED` — from any of `FILED`, `CALENDAR`, or `MERITS` — so the new court re-dockets it to one of its own judges through the §3.2 gate, with the case's `version` incremented by 1."
    PRD §3.7: "until the assigned judge rules with a `decision` of `GRANTED` or `DENIED`, subject to the usual pair of gates — the motion must still be `PENDING` (`ERR_VENUE_MOTION_NOT_PENDING`) and the caller must be the case's assigned judge (`ERR_NOT_ASSIGNED_JUDGE`) — and either ruling stamps `decided_by_judge_id` and `decided_at`."

    Design: Corner/state_machines/venue_motion_grant_moves_venue_and_resets_docket
    """
    ctx = setup_docketed_case()
    master = schedule_hearing(ctx["case"], "MASTER_CALENDAR", MASTER_HEARING_START_ISO)
    dest = create_court()
    motion = file_venue_motion(ctx["case"]["id"], dest["id"], "respondent moved")

    decided = decide_venue_motion(motion, "GRANTED", judge_id=ctx["judge"]["id"])
    assert decided["status"] == "GRANTED"
    assert decided["decided_by_judge_id"] == ctx["judge"]["id"]

    # The grant rewrites venue, clears the judge, and resets the case.
    case = read_case(ctx["case"]["id"])
    assert case["court_id"] == dest["id"]
    assert case["assigned_judge_id"] is None
    assert case["status"] == "FILED"
    assert read_hearing(master["id"])["status"] == "CANCELLED"

    # Pending volume moves with the case: source 1 -> 0, destination 0 -> 1.
    assert_backlog_flag(read_court(ctx["court"]["id"]), 0, False)
    assert_backlog_flag(read_court(dest["id"]), 1, False)


def test_venue_motion_deny_keeps_case_and_hearing():
    """PRD §3.7: "A denial ends the matter. A grant moves the case: its `court_id` becomes the destination court, its `assigned_judge_id` is cleared to null, every `SCHEDULED` hearing of the case is `CANCELLED`, and the case's `status` returns to `FILED` — from any of `FILED`, `CALENDAR`, or `MERITS` — so the new court re-dockets it to one of its own judges through the §3.2 gate, with the case's `version` incremented by 1."

    Design: Corner/state_machines/venue_motion_deny_keeps_case_and_hearing
    """
    ctx = setup_docketed_case()
    master = schedule_hearing(ctx["case"], "MASTER_CALENDAR", MASTER_HEARING_START_ISO)
    dest = create_court()
    motion = file_venue_motion(ctx["case"]["id"], dest["id"], "respondent moved")

    decided = decide_venue_motion(motion, "DENIED", judge_id=ctx["judge"]["id"])
    assert decided["status"] == "DENIED"

    # The DENIED branch performs no cascade: venue, judge, case state, and
    # the scheduled hearing are all unchanged.
    case = read_case(ctx["case"]["id"])
    assert case["court_id"] == ctx["court"]["id"]
    assert case["assigned_judge_id"] == ctx["judge"]["id"]
    assert case["status"] == "CALENDAR"
    assert read_hearing(master["id"])["status"] == "SCHEDULED"


def test_pending_application_grant_closes_case_without_replacement():
    """PRD §3.4: "A grant on `PENDING_APPLICATION` means something different entirely: the respondent is pursuing an application elsewhere, so the targeted hearing becomes `CANCELLED`, no replacement is created, and the case moves from `CALENDAR` or `MERITS` to `ADMIN_CLOSED`, again incrementing `version` by 1."
    PRD §3.4: "Third, a continuance must be filed no later than 24 hours before the hearing's `scheduled_start`; a later filing fails with `ERR_CONTINUANCE_TOO_LATE`, with a single carve-out — the case's first-ever continuance request, when its `reason_code` is `ATTORNEY_REPRESENTATION`, is exempt from the lead-time rule, so an unrepresented respondent always gets one late chance to seek counsel."

    Design: Corner/state_machines/pending_application_grant_closes_case_without_replacement
    """
    ctx = setup_docketed_case()
    m = advance_case_to_merits(ctx["case"], judge_id=ctx["judge"]["id"])
    # Filed at the 2026-09-03T10:30Z post-completion clock, so the merits
    # hearing must start at least 24h later to clear the lead-time rule.
    merits = schedule_hearing(m["case"], "INDIVIDUAL_MERITS", "2026-09-05T10:00:00Z")
    request = file_continuance(ctx["case"]["id"], merits["id"], "PENDING_APPLICATION")

    granted = decide_continuance(request, "GRANTED", judge_id=ctx["judge"]["id"])
    assert granted["status"] == "GRANTED"

    case = read_case(ctx["case"]["id"])
    assert case["status"] == "ADMIN_CLOSED"
    assert case["continuance_count"] == 1
    # The targeted hearing is CANCELLED — not CONTINUED — and no superseding
    # replacement was created: exactly the master (COMPLETED) plus this one.
    assert read_hearing(merits["id"])["status"] == "CANCELLED"
    hearings = list_case_hearings(ctx["case"]["id"])
    assert len(hearings) == 2
    assert sorted(h["status"] for h in hearings) == ["CANCELLED", "COMPLETED"]


def test_continuance_deny_leaves_hearing_scheduled():
    """PRD §3.4: "The request must still be `PENDING` (otherwise `ERR_CONTINUANCE_NOT_PENDING`) and the caller must be the case's assigned judge (`ERR_NOT_ASSIGNED_JUDGE`); either ruling stamps `decided_by_judge_id` with the acting judge and `decided_at` with the clock. A denial touches nothing else — the targeted hearing stands."

    Design: Corner/state_machines/continuance_deny_leaves_hearing_scheduled
    """
    ctx = setup_docketed_case()
    hearing = schedule_hearing(
        ctx["case"], "MASTER_CALENDAR", CONTINUANCE_HEARING_START_ISO
    )
    request = file_continuance(ctx["case"]["id"], hearing["id"], "EVIDENCE_GATHERING")

    denied = decide_continuance(request, "DENIED", judge_id=ctx["judge"]["id"])
    assert denied["status"] == "DENIED"
    assert denied["decided_by_judge_id"] == ctx["judge"]["id"]
    # The clock never moved off its 2026-09-01T00:00:00Z default in this flow.
    assert same_instant(denied["decided_at"], CLOCK_DEFAULT_ISO)

    # The denial touched nothing else: hearing stands, case unchanged.
    assert read_hearing(hearing["id"])["status"] == "SCHEDULED"
    case = read_case(ctx["case"]["id"])
    assert case["status"] == "CALENDAR"
    assert case["continuance_count"] == 0
