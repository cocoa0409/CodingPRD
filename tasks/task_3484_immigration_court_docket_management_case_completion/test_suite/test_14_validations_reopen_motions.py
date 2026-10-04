"""Validation probes: motions to reopen an in absentia order.

Filing is gated by the case's IN_ABSENTIA posture (before cross-entity
linkage), by decision linkage and rescindability, by the conditioned
NOTICE_DEFECTIVE basis, by the inclusive 180-day window on the
EXCEPTIONAL_CIRCUMSTANCES basis, and by a one-FILED-motion-per-case cap; a
decided motion is terminal.
"""

from test_helpers import (
    ApiErrorId,
    NOSHOW_CLOCK_ISO,
    NOSHOW_HEARING_START_ISO,
    assert_motion_to_reopen,
    assign_case_to_judge,
    create_case,
    decide_motion_to_reopen,
    decision_of_case,
    file_motion_to_reopen,
    get_success_data,
    make_judge_headers,
    make_motion_to_reopen_payload,
    make_ruling_payload,
    mark_notice_defective,
    read_case,
    read_decision,
    record_no_show,
    same_instant,
    schedule_hearing,
    scheduled_hearing_of,
    serve_notice,
    set_clock,
    setup_case_in_absentia,
    setup_docketed_case,
    setup_in_absentia_with_motion,
    validate_error,
    validate_success,
)


def test_motion_to_reopen_duplicate_pending_rejected(api, admin_headers):
    """PRD §3.5: "At most one motion to reopen may stand `FILED` for a case at a time (`ERR_MOTION_ALREADY_PENDING`)."

    Design: Corner/validations/motion_to_reopen_duplicate_pending_rejected
    """
    ctx = setup_in_absentia_with_motion()

    # A second filing while the first awaits the judge is rejected.
    resp = api.create_motion_to_reopen(
        make_motion_to_reopen_payload(
            ctx["case"]["id"], ctx["decision"]["id"], "EXCEPTIONAL_CIRCUMSTANCES"
        ),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_MOTION_ALREADY_PENDING)

    # The first motion is undisturbed.
    after = get_success_data(
        api.get_motion_to_reopen(ctx["motion"]["id"], headers=admin_headers)
    )
    assert after["status"] == "FILED"


def test_notice_defective_basis_requires_defective_notice(api, admin_headers):
    """PRD §3.5: "`NOTICE_DEFECTIVE` requires the source hearing's notice to be `DEFECTIVE` (otherwise `ERR_NOTICE_NOT_DEFECTIVE`) and is exempt from any filing window."
    PRD §3.5: "A motion begins `FILED` with its `filed_at` at the clock and its `decided_by_judge_id` and `decided_at` null."

    Design: Corner/validations/notice_defective_basis_without_defect_rejected
    """
    ctx = setup_case_in_absentia()
    set_clock("2026-09-06T00:00:00Z")

    # The notice on the no-show hearing is still SERVED, so the conditioned
    # basis fails.
    resp = api.create_motion_to_reopen(
        make_motion_to_reopen_payload(
            ctx["case"]["id"], ctx["decision"]["id"], "NOTICE_DEFECTIVE"
        ),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_NOTICE_NOT_DEFECTIVE)

    # The window-bound basis on the same order files cleanly.
    resp = api.create_motion_to_reopen(
        make_motion_to_reopen_payload(
            ctx["case"]["id"], ctx["decision"]["id"], "EXCEPTIONAL_CIRCUMSTANCES"
        ),
        headers=admin_headers,
    )
    data = validate_success(resp, expected_status=201)
    assert_motion_to_reopen(data)
    assert data["status"] == "FILED"


def test_reopen_window_inclusive_boundary_and_defective_exemption(api, admin_headers):
    """PRD §3.5: "`EXCEPTIONAL_CIRCUMSTANCES` is window-bound: the clock at filing must be at or before the decision's `reopen_deadline`, the boundary is inclusive, and a filing one second past it fails with `ERR_REOPEN_WINDOW_EXPIRED`."
    PRD §3.5: "`NOTICE_DEFECTIVE` requires the source hearing's notice to be `DEFECTIVE` (otherwise `ERR_NOTICE_NOT_DEFECTIVE`) and is exempt from any filing window."
    PRD §3.5: "whose `issued_at` is the clock, whose `appeal_deadline` falls exactly 30 days later, and whose `reopen_deadline` falls exactly 180 days later."

    Design: Corner/validations/reopen_window_three_way
    """
    ctx = setup_docketed_case()
    judge_id = ctx["judge"]["id"]
    case1_id = ctx["case"]["id"]
    hearing1 = schedule_hearing(
        ctx["case"], "MASTER_CALENDAR", NOSHOW_HEARING_START_ISO
    )
    notice1 = serve_notice(
        hearing1["id"], service_method="MAIL", served_at="2026-08-20T00:00:00Z"
    )
    # A second case on the same bench reaches IN_ABSENTIA from the same
    # morning's docket.
    case2 = assign_case_to_judge(create_case(ctx["court"]["id"])["id"], judge_id)
    hearing2 = schedule_hearing(case2, "MASTER_CALENDAR", "2026-09-05T10:30:00Z")
    serve_notice(
        hearing2["id"], service_method="ELECTRONIC", served_at="2026-08-21T00:00:00Z"
    )
    set_clock(NOSHOW_CLOCK_ISO)
    record_no_show(hearing1, judge_id=judge_id)
    record_no_show(hearing2, judge_id=judge_id)
    decision1 = decision_of_case(case1_id)
    decision2 = decision_of_case(case2["id"])
    # Both orders were issued at the no-show clock, so both reopen windows
    # close exactly 180 days later.
    assert same_instant(decision1["reopen_deadline"], "2027-03-04T11:00:00Z")
    assert same_instant(decision2["reopen_deadline"], "2027-03-04T11:00:00Z")

    # At exactly the deadline the window is inclusive: the filing succeeds.
    set_clock("2027-03-04T11:00:00Z")
    resp = api.create_motion_to_reopen(
        make_motion_to_reopen_payload(
            case1_id, decision1["id"], "EXCEPTIONAL_CIRCUMSTANCES"
        ),
        headers=admin_headers,
    )
    motion1 = validate_success(resp, expected_status=201)
    assert motion1["status"] == "FILED"
    motion1 = decide_motion_to_reopen(motion1, "DENIED", judge_id=judge_id)
    mark_notice_defective(notice1["id"])

    # One second past the deadline the same basis on the other case is expired.
    set_clock("2027-03-04T11:00:01Z")
    resp = api.create_motion_to_reopen(
        make_motion_to_reopen_payload(
            case2["id"], decision2["id"], "EXCEPTIONAL_CIRCUMSTANCES"
        ),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_REOPEN_WINDOW_EXPIRED)

    # Weeks past the deadline the NOTICE_DEFECTIVE basis still files: it is
    # window-exempt, the notice is DEFECTIVE, and the DENIED first motion
    # leaves no FILED motion standing.
    set_clock("2027-04-01T00:00:00Z")
    resp = api.create_motion_to_reopen(
        make_motion_to_reopen_payload(case1_id, decision1["id"], "NOTICE_DEFECTIVE"),
        headers=admin_headers,
    )
    motion2 = validate_success(resp, expected_status=201)
    assert_motion_to_reopen(motion2)
    assert motion2["status"] == "FILED"
    after1 = get_success_data(
        api.get_motion_to_reopen(motion1["id"], headers=admin_headers)
    )
    assert after1["status"] == "DENIED"


def test_motion_state_gate_precedes_decision_linkage_gate(api, admin_headers):
    """PRD §3.5: "Filing requires the case to be `IN_ABSENTIA` (otherwise `ERR_CASE_NOT_IN_ABSENTIA`); requires the named decision to belong to the named case (`ERR_DECISION_CASE_MISMATCH`); and requires the target decision to be rescindable — still `ISSUED`, and of outcome `IN_ABSENTIA_REMOVAL` — otherwise `ERR_DECISION_NOT_RESCINDABLE`."
    PRD §2.6: "A request that would fail several checks receives exactly one error: the check in the earliest tier below that fails. The eleven tiers are evaluated in this order, and the ordering is itself part of the contract."
    PRD §2.6: "6. **Cross-entity linkage (HTTP 409).** Referenced resources must belong together: `ERR_HEARING_CASE_MISMATCH` when a continuance's hearing belongs to a different case than the one named, `ERR_DECISION_CASE_MISMATCH` when a motion to reopen's decision belongs to a different case, `ERR_JUDGE_WRONG_COURT` when a docketing judge sits at a different court than the case's venue."

    Design: Corner/validations/motion_referential_and_state_guards
    """
    ctx = setup_docketed_case()
    judge_id = ctx["judge"]["id"]
    case1_id = ctx["case"]["id"]
    case2 = assign_case_to_judge(create_case(ctx["court"]["id"])["id"], judge_id)
    hearing2 = schedule_hearing(case2, "MASTER_CALENDAR", "2026-09-05T10:30:00Z")
    serve_notice(
        hearing2["id"], service_method="MAIL", served_at="2026-08-20T00:00:00Z"
    )
    hearing1 = schedule_hearing(
        ctx["case"], "MASTER_CALENDAR", NOSHOW_HEARING_START_ISO
    )
    serve_notice(
        hearing1["id"], service_method="MAIL", served_at="2026-08-20T00:00:00Z"
    )
    set_clock(NOSHOW_CLOCK_ISO)
    # Only case 1 reaches IN_ABSENTIA; case 2 remains CALENDAR.
    record_no_show(hearing1, judge_id=judge_id)
    decision1 = decision_of_case(case1_id)

    # The filing names a CALENDAR case and someone else's decision: the tier-5
    # state gate fires before the tier-6 linkage gate.
    resp = api.create_motion_to_reopen(
        make_motion_to_reopen_payload(
            case2["id"], decision1["id"], "EXCEPTIONAL_CIRCUMSTANCES"
        ),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_IN_ABSENTIA)

    # With both cases IN_ABSENTIA the state gate passes, and the cross-filed
    # decision surfaces the linkage error.
    record_no_show(hearing2, judge_id=judge_id)
    decision2 = decision_of_case(case2["id"])
    resp = api.create_motion_to_reopen(
        make_motion_to_reopen_payload(
            case1_id, decision2["id"], "EXCEPTIONAL_CIRCUMSTANCES"
        ),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DECISION_CASE_MISMATCH)

    # Both rejections wrote nothing: no motion rows exist for either case.
    for cid in (case1_id, case2["id"]):
        motions = get_success_data(
            api.list_motions_to_reopen(
                headers=admin_headers, params={"case_id": cid, "limit": 100}
            )
        )
        assert motions == [], "no motion may be created by a rejected filing"


def test_motion_decide_twice_rejected(api, admin_headers):
    """PRD §3.5: "The assigned judge then rules, supplying a `decision` of `GRANTED` or `DENIED`; the motion must still be `FILED` (otherwise `ERR_MOTION_NOT_PENDING`) and the caller must be the case's assigned judge (`ERR_NOT_ASSIGNED_JUDGE`), and either ruling stamps `decided_by_judge_id` and `decided_at`."
    PRD §3.5: "A denial leaves the decision and the case untouched."

    Design: Corner/validations/motion_decide_twice_rejected
    """
    ctx = setup_in_absentia_with_motion()
    motion = decide_motion_to_reopen(
        ctx["motion"], "DENIED", judge_id=ctx["judge"]["id"]
    )
    assert motion["status"] == "DENIED"

    # A decided motion is terminal: the second ruling is rejected.
    resp = api.decide_motion_to_reopen(
        motion["id"],
        make_ruling_payload("GRANTED"),
        headers=make_judge_headers(ctx["judge"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MOTION_NOT_PENDING)

    # The in absentia order stands.
    after = get_success_data(
        api.get_motion_to_reopen(motion["id"], headers=admin_headers)
    )
    assert after["status"] == "DENIED"
    assert read_decision(ctx["decision"]["id"])["status"] == "ISSUED"
    assert read_case(ctx["case"]["id"])["status"] == "IN_ABSENTIA"


def test_motion_against_rescinded_decision_rejected(api, admin_headers):
    """PRD §3.5: "requires the target decision to be rescindable — still `ISSUED`, and of outcome `IN_ABSENTIA_REMOVAL` — otherwise `ERR_DECISION_NOT_RESCINDABLE`. Per §2.6, that rescindability check needs the decision loaded, so it runs immediately after the linkage check rather than inside the case's own state tier."
    PRD §3.5: "A grant unwinds the removal: the decision becomes `RESCINDED`, the case returns `IN_ABSENTIA → CALENDAR`, its `version` increments by 1, and the system auto-creates a fresh `MASTER_CALENDAR` hearing 21 days out from the clock — `auto_created` true, the case's retained `assigned_judge_id` presiding, the interpreter re-selected, and the candidate slot advanced one calendar day at a time until every applicable scheduling check of §3.3 passes."
    PRD §3.5: "whose `issued_at` is the clock, whose `appeal_deadline` falls exactly 30 days later, and whose `reopen_deadline` falls exactly 180 days later."

    Design: Corner/validations/motion_against_rescinded_decision_rejected
    """
    ctx = setup_case_in_absentia()
    judge_id = ctx["judge"]["id"]
    case_id = ctx["case"]["id"]
    decision1 = ctx["decision"]

    # The notice proves defective and the NOTICE_DEFECTIVE motion is granted:
    # decision1 is RESCINDED and the case returns to CALENDAR with an
    # auto-created master hearing 21 days out (2026-09-26T11:00 at this clock).
    mark_notice_defective(ctx["notice"]["id"])
    motion = file_motion_to_reopen(case_id, decision1["id"], "NOTICE_DEFECTIVE")
    motion = decide_motion_to_reopen(motion, "GRANTED", judge_id=judge_id)
    assert read_decision(decision1["id"])["status"] == "RESCINDED"

    # The case reaches IN_ABSENTIA a second time via a no-show at the reopen
    # hearing, producing a fresh ISSUED decision at the no-show clock.
    set_clock("2026-09-26T11:30:00Z")
    reopen_hearing = scheduled_hearing_of(case_id)
    assert reopen_hearing is not None, "the grant auto-created a reopen hearing"
    serve_notice(
        reopen_hearing["id"], service_method="MAIL", served_at="2026-09-06T00:00:00Z"
    )
    record_no_show(reopen_hearing, judge_id=judge_id)

    # A motion naming the RESCINDED decision fails the rescindability check;
    # the linkage holds (the decision does belong to this case), so only that
    # gate fires.
    resp = api.create_motion_to_reopen(
        make_motion_to_reopen_payload(case_id, decision1["id"], "NOTICE_DEFECTIVE"),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DECISION_NOT_RESCINDABLE)

    # The fresh decision stands ISSUED; only the granted motion exists.
    decision2 = decision_of_case(case_id, status="ISSUED")
    assert decision2 is not None
    assert decision2["id"] != decision1["id"]
    assert same_instant(decision2["issued_at"], "2026-09-26T11:30:00Z")
    assert read_case(case_id)["status"] == "IN_ABSENTIA"
    motions = get_success_data(
        api.list_motions_to_reopen(
            headers=admin_headers, params={"case_id": case_id, "limit": 100}
        )
    )
    assert [m["id"] for m in motions] == [motion["id"]]
