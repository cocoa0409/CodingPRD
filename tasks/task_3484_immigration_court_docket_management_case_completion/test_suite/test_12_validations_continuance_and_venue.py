"""Validation probes: continuance filing/ruling gates and venue-motion gates.

Continuance filings carry a pro-se-only reason code, a 24-hour lead time with
a first-request attorney carve-out, a same-case hearing linkage rule, and a
one-pending-per-hearing cardinality cap; a decided request is terminal.  A
venue motion must name a different court, stands alone while PENDING, and is
terminal once decided.
"""

from test_helpers import (
    ApiErrorId,
    assert_continuance_request,
    assign_case_to_judge,
    create_case,
    create_court,
    decide_continuance,
    decide_venue_motion,
    file_continuance,
    get_success_data,
    list_case_hearings,
    make_continuance_payload,
    make_judge_headers,
    make_ruling_payload,
    make_venue_motion_payload,
    read_case,
    schedule_hearing,
    set_clock,
    setup_docketed_case,
    setup_venue_motion_pending,
    validate_error,
    validate_success,
)


def test_attorney_continuance_requires_pro_se_case(api, admin_headers):
    """PRD §3.4: "First, an `ATTORNEY_REPRESENTATION` request is meaningful only for the unrepresented: the case must be `PRO_SE`, otherwise `ERR_REASON_REQUIRES_PRO_SE` (HTTP 422)."
    PRD §3.4: "A filed request is `PENDING`, with `decided_by_judge_id` and `decided_at` both null."

    Design: Corner/validations/attorney_continuance_on_represented_case_rejected
    """
    ctx = setup_docketed_case(representation_status="COUNSEL_RETAINED")
    case_id = ctx["case"]["id"]
    hearing = schedule_hearing(ctx["case"], "MASTER_CALENDAR", "2026-09-10T10:00:00Z")

    # The represented case may not plead attorney representation.
    resp = api.create_continuance_request(
        make_continuance_payload(case_id, hearing["id"], "ATTORNEY_REPRESENTATION"),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_REASON_REQUIRES_PRO_SE)

    # A neutral reason on the same case files cleanly.
    resp = api.create_continuance_request(
        make_continuance_payload(case_id, hearing["id"], "EVIDENCE_GATHERING"),
        headers=admin_headers,
    )
    data = validate_success(resp, expected_status=201)
    assert_continuance_request(data)
    assert data["status"] == "PENDING"


def test_continuance_lead_time_with_first_attorney_carve_out(api, admin_headers):
    """PRD §3.4: "Third, a continuance must be filed no later than 24 hours before the hearing's `scheduled_start`; a later filing fails with `ERR_CONTINUANCE_TOO_LATE`, with a single carve-out — the case's first-ever continuance request, when its `reason_code` is `ATTORNEY_REPRESENTATION`, is exempt from the lead-time rule, so an unrepresented respondent always gets one late chance to seek counsel."
    PRD §3.4: "The system records that first-request fact on the request itself as `is_first_for_case`, true only when no prior continuance request of any status exists for the case."

    Design: Corner/validations/continuance_lead_time_and_attorney_carve_out
    """
    ctx = setup_docketed_case()
    case_id = ctx["case"]["id"]
    hearing = schedule_hearing(ctx["case"], "MASTER_CALENDAR", "2026-09-02T10:00:00Z")
    # 22 hours before the start: inside the 24-hour lead-time window.
    set_clock("2026-09-01T12:00:00Z")

    # A late EVIDENCE_GATHERING filing is rejected.
    resp = api.create_continuance_request(
        make_continuance_payload(case_id, hearing["id"], "EVIDENCE_GATHERING"),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CONTINUANCE_TOO_LATE)

    # The same late filing succeeds as the case's first-ever request when the
    # reason is ATTORNEY_REPRESENTATION (the case is PRO_SE, so the reason
    # gate passes) — and the rejection above wrote no request row.
    resp = api.create_continuance_request(
        make_continuance_payload(case_id, hearing["id"], "ATTORNEY_REPRESENTATION"),
        headers=admin_headers,
    )
    data = validate_success(resp, expected_status=201)
    assert_continuance_request(data)
    assert data["is_first_for_case"] is True
    assert data["status"] == "PENDING"


def test_continuance_with_hearing_from_other_case_rejected(api, admin_headers):
    """PRD §3.4: "Beyond the generic tiers, filing validates that the targeted hearing belongs to the named case (`ERR_HEARING_CASE_MISMATCH`) and that no other `PENDING` continuance already targets that hearing (`ERR_CONTINUANCE_ALREADY_PENDING`)."
    PRD §3.4: "A filed request is `PENDING`, with `decided_by_judge_id` and `decided_at` both null."

    Design: Corner/validations/continuance_with_hearing_from_other_case_rejected
    """
    ctx = setup_docketed_case()
    case_id = ctx["case"]["id"]
    own_hearing = schedule_hearing(
        ctx["case"], "MASTER_CALENDAR", "2026-09-10T10:00:00Z"
    )
    # A second case on the same bench with its own SCHEDULED hearing.
    case2 = assign_case_to_judge(
        create_case(ctx["court"]["id"])["id"], ctx["judge"]["id"]
    )
    other_hearing = schedule_hearing(case2, "MASTER_CALENDAR", "2026-09-10T11:00:00Z")

    # Naming the other case's hearing is a cross-entity linkage failure.
    resp = api.create_continuance_request(
        make_continuance_payload(case_id, other_hearing["id"], "EVIDENCE_GATHERING"),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_HEARING_CASE_MISMATCH)

    # The correctly paired filing succeeds.
    resp = api.create_continuance_request(
        make_continuance_payload(case_id, own_hearing["id"], "EVIDENCE_GATHERING"),
        headers=admin_headers,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "PENDING"
    assert data["hearing_id"] == own_hearing["id"]


def test_second_pending_continuance_same_hearing_rejected(api, admin_headers):
    """PRD §3.4: "Beyond the generic tiers, filing validates that the targeted hearing belongs to the named case (`ERR_HEARING_CASE_MISMATCH`) and that no other `PENDING` continuance already targets that hearing (`ERR_CONTINUANCE_ALREADY_PENDING`)."

    Design: Corner/validations/second_pending_continuance_same_hearing_rejected
    """
    ctx = setup_docketed_case()
    case_id = ctx["case"]["id"]
    hearing = schedule_hearing(ctx["case"], "MASTER_CALENDAR", "2026-09-10T10:00:00Z")
    first = file_continuance(case_id, hearing["id"], "EVIDENCE_GATHERING")

    # A second filing against the same hearing while the first is PENDING.
    resp = api.create_continuance_request(
        make_continuance_payload(case_id, hearing["id"], "OTHER"),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CONTINUANCE_ALREADY_PENDING)

    # The rejection writes nothing: the first request stands PENDING.
    after = get_success_data(
        api.get_continuance_request(first["id"], headers=admin_headers)
    )
    assert after["status"] == "PENDING"


def test_continuance_decide_twice_rejected(api, admin_headers):
    """PRD §3.4: "The request must still be `PENDING` (otherwise `ERR_CONTINUANCE_NOT_PENDING`) and the caller must be the case's assigned judge (`ERR_NOT_ASSIGNED_JUDGE`); either ruling stamps `decided_by_judge_id` with the acting judge and `decided_at` with the clock."
    PRD §3.4: "For any `reason_code` other than `PENDING_APPLICATION`, the targeted hearing becomes `CONTINUED` and the system auto-creates its replacement: the same case, hearing type, judge, and `is_remote` flag; `auto_created` true; `supersedes_hearing_id` pointing at the continued hearing; and a `scheduled_start` 7 days after the continued hearing's start for a detained case, or 28 days after for a non-detained one — with the candidate slot then advanced one calendar day at a time until the judge-overlap, judge daily-minutes, detained-capacity, and interpreter-selection checks of §3.3 all pass, a deterministic forward search."

    Design: Corner/validations/continuance_decide_twice_rejected
    """
    ctx = setup_docketed_case()
    case_id = ctx["case"]["id"]
    hearing = schedule_hearing(ctx["case"], "MASTER_CALENDAR", "2026-09-10T10:00:00Z")
    request = file_continuance(case_id, hearing["id"], "EVIDENCE_GATHERING")
    request = decide_continuance(
        request, "GRANTED", judge_id=ctx["judge"]["id"]
    )
    assert request["status"] == "GRANTED"

    # A decided request is terminal: re-deciding is rejected.
    resp = api.decide_continuance_request(
        request["id"],
        make_ruling_payload("DENIED"),
        headers=make_judge_headers(ctx["judge"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CONTINUANCE_NOT_PENDING)

    # The grant already replaced the hearing (CONTINUED + SCHEDULED successor);
    # the rejected re-decision created nothing further.
    hearings = list_case_hearings(case_id)
    assert len(hearings) == 2
    statuses = sorted(h["status"] for h in hearings)
    assert statuses == ["CONTINUED", "SCHEDULED"]


def test_venue_motion_duplicate_pending_rejected(api, admin_headers):
    """PRD §3.7: "The destination must differ from the case's current court (otherwise `ERR_DESTINATION_COURT_IS_CURRENT`, HTTP 422), and at most one such motion may stand `PENDING` for a case at a time (`ERR_VENUE_MOTION_ALREADY_PENDING`)."

    Design: Corner/validations/venue_motion_duplicate_pending_rejected
    """
    ctx = setup_venue_motion_pending()
    case_id = ctx["case"]["id"]
    third_court = create_court()

    # A second filing while the first motion is still PENDING is rejected,
    # even though it names a different (valid) destination.
    resp = api.create_venue_motion(
        make_venue_motion_payload(case_id, third_court["id"], "counsel preference"),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VENUE_MOTION_ALREADY_PENDING)

    # The first motion is undisturbed.
    motion = get_success_data(api.get_venue_motion(ctx["motion"]["id"], headers=admin_headers))
    assert motion["status"] == "PENDING"
    assert motion["destination_court_id"] == ctx["dest_court"]["id"]


def test_venue_motion_to_current_court_rejected(api, admin_headers):
    """PRD §3.7: "The destination must differ from the case's current court (otherwise `ERR_DESTINATION_COURT_IS_CURRENT`, HTTP 422), and at most one such motion may stand `PENDING` for a case at a time (`ERR_VENUE_MOTION_ALREADY_PENDING`)."

    Design: Corner/validations/venue_motion_to_current_court_rejected
    """
    ctx = setup_docketed_case()
    case_id = ctx["case"]["id"]

    # The destination equals the case's current court: the motion would change
    # nothing, so it is a semantic rejection.
    resp = api.create_venue_motion(
        make_venue_motion_payload(case_id, ctx["court"]["id"], "no move"),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DESTINATION_COURT_IS_CURRENT)

    motions = get_success_data(
        api.list_venue_motions(
            headers=admin_headers, params={"case_id": case_id, "limit": 100}
        )
    )
    assert motions == [], "the rejected filing created no motion rows"


def test_venue_motion_decide_twice_rejected(api, admin_headers):
    """PRD §3.7: "The motion is `PENDING`, with `decided_by_judge_id` and `decided_at` null, until the assigned judge rules with a `decision` of `GRANTED` or `DENIED`, subject to the usual pair of gates — the motion must still be `PENDING` (`ERR_VENUE_MOTION_NOT_PENDING`) and the caller must be the case's assigned judge (`ERR_NOT_ASSIGNED_JUDGE`) — and either ruling stamps `decided_by_judge_id` and `decided_at`."
    PRD §3.7: "A denial ends the matter."

    Design: Corner/validations/venue_motion_decide_twice_rejected
    """
    ctx = setup_venue_motion_pending()
    motion = decide_venue_motion(
        ctx["motion"], "DENIED", judge_id=ctx["judge"]["id"]
    )
    assert motion["status"] == "DENIED"

    # A decided motion is terminal: the second ruling is rejected.
    resp = api.decide_venue_motion(
        motion["id"],
        make_ruling_payload("GRANTED"),
        headers=make_judge_headers(ctx["judge"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VENUE_MOTION_NOT_PENDING)

    # Nothing moved: the motion stays DENIED and the case keeps its venue.
    after = get_success_data(api.get_venue_motion(motion["id"], headers=admin_headers))
    assert after["status"] == "DENIED"
    assert read_case(ctx["case"]["id"])["court_id"] == ctx["court"]["id"]
