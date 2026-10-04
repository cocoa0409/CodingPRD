"""State-machine probes: docket-review lapse processing and appeal outcomes.

The checkpoint run finalizes a DECIDED case whose appeal window has lapsed,
finalizes an IN_ABSENTIA case only once its 180-day reopen window has lapsed,
and skips the in-absentia case while a FILED motion to reopen stands. An in
absentia order is itself appealable inside its 30-day window, and a DISMISSED
ruling closes the case exactly like an affirmation.
"""

from test_helpers import (
    MERITS_HEARING_CLOCK_ISO,
    assert_appeal,
    assert_docket_review,
    get_success_data,
    make_appeal_payload,
    make_appeal_ruling_payload,
    read_case,
    read_decision,
    run_docket_review,
    same_instant,
    set_clock,
    setup_appealed_case,
    setup_case_in_absentia,
    setup_decided_case,
    setup_in_absentia_with_motion,
    validate_success,
)


def test_docket_review_lapse_finalizes_expired_decision():
    """PRD §3.8: "Any `DECIDED` case of the court whose latest decision is still `ISSUED` while the clock has moved strictly past that decision's `appeal_deadline` is finalized on the spot: the decision becomes `FINAL`, the case becomes `COMPLETED` with `completed_at` set to the clock, and the case's `version` increments by 1."
    PRD §3.8: "The snapshot's `cases_finalized_by_lapse` records how many cases that particular run moved to `COMPLETED` across both lapse branches, so each checkpoint doubles as an audit of what the sweep did."

    Design: Corner/state_machines/docket_review_lapse_finalizes_expired_decision
    """
    # Decision issued 2026-09-04T12:00:00Z -> appeal deadline 2026-10-04T12:00:00Z;
    # no appeal filed. The run at 2026-10-05 is strictly past the deadline.
    ctx = setup_decided_case()
    set_clock("2026-10-05T00:00:00Z")

    review = run_docket_review(ctx["court"]["id"])
    assert_docket_review(review)
    assert review["cases_finalized_by_lapse"] == 1
    # The snapshot's completions_ytd / pending_case_count are deliberately not
    # asserted here: §3.8 freezes the live metrics "exactly as they stand at
    # run time" while the lapse sweep "acts in the same breath as the
    # snapshot", which does not uniquely derive whether the frozen metrics
    # observe this run's own lapse effects.  The lapse effects themselves
    # (below) are verbatim in §3.8 and are asserted.

    assert read_decision(ctx["decision"]["id"])["status"] == "FINAL"
    case = read_case(ctx["case"]["id"])
    assert case["status"] == "COMPLETED"
    assert same_instant(case["completed_at"], "2026-10-05T00:00:00Z")


def test_docket_review_lapse_finalizes_in_absentia_after_reopen_window():
    """PRD §3.8: "Likewise, any `IN_ABSENTIA` case whose in absentia decision is still `ISSUED`, whose `reopen_deadline` the clock has moved strictly past, and against which no `FILED` motion to reopen stands is finalized the same way."
    PRD §3.5: "whose `issued_at` is the clock, whose `appeal_deadline` falls exactly 30 days later, and whose `reopen_deadline` falls exactly 180 days later."

    Design: Corner/state_machines/docket_review_lapse_finalizes_in_absentia_after_reopen_window
    """
    # In-absentia order issued 2026-09-05T11:00:00Z -> reopen deadline
    # 2027-03-04T11:00:00Z; the run at 2027-03-05 is strictly past it.
    ctx = setup_case_in_absentia()
    set_clock("2027-03-05T00:00:00Z")

    review = run_docket_review(ctx["court"]["id"])
    assert_docket_review(review)
    assert review["cases_finalized_by_lapse"] == 1

    assert read_decision(ctx["decision"]["id"])["status"] == "FINAL"
    case = read_case(ctx["case"]["id"])
    assert case["status"] == "COMPLETED"
    assert same_instant(case["completed_at"], "2027-03-05T00:00:00Z")


def test_docket_review_lapse_skips_case_with_filed_motion(api, admin_headers):
    """PRD §3.8: "Likewise, any `IN_ABSENTIA` case whose in absentia decision is still `ISSUED`, whose `reopen_deadline` the clock has moved strictly past, and against which no `FILED` motion to reopen stands is finalized the same way."
    PRD §3.5: "At most one motion to reopen may stand `FILED` for a case at a time (`ERR_MOTION_ALREADY_PENDING`)."

    Design: Corner/state_machines/docket_review_lapse_skips_case_with_filed_motion
    """
    # The motion is filed 2026-09-06, inside the 180-day window, and left
    # FILED; the checkpoint runs past the reopen deadline.
    ctx = setup_in_absentia_with_motion(basis="EXCEPTIONAL_CIRCUMSTANCES")
    set_clock("2027-03-05T00:00:00Z")

    review = run_docket_review(ctx["court"]["id"])
    assert_docket_review(review)
    assert review["cases_finalized_by_lapse"] == 0

    # The standing FILED motion blocks the lapse: everything is untouched.
    assert read_case(ctx["case"]["id"])["status"] == "IN_ABSENTIA"
    assert read_decision(ctx["decision"]["id"])["status"] == "ISSUED"
    motion = get_success_data(
        api.get_motion_to_reopen(ctx["motion"]["id"], headers=admin_headers)
    )
    assert motion["status"] == "FILED"


def test_in_absentia_decision_is_appealable(api, admin_headers):
    """PRD §3.6: "Either decided posture — `DECIDED` or `IN_ABSENTIA` — can be appealed to the review board. A `CourtAdministrator` files the appeal with the `decision_id` and an optional free-text `grounds`. The decision must still be `ISSUED` (otherwise `ERR_DECISION_NOT_APPEALABLE`), and the clock must be at or before the decision's `appeal_deadline`: the 30-day window is inclusive, so a filing at exactly the deadline succeeds while one a second later fails with `ERR_APPEAL_WINDOW_EXPIRED`. A filed appeal copies its `case_id` from the decision, records its `filed_at` at the clock, starts `FILED` with `decided_by_board_member_id` and `decided_at` null, moves the decision from `ISSUED` to `APPEAL_PENDING`, moves the case from its `DECIDED` or `IN_ABSENTIA` posture to `APPEALED`, and increments the case's `version` by 1."

    Design: Corner/state_machines/in_absentia_decision_is_appealable
    """
    # In-absentia order issued 2026-09-05T11:00:00Z; the appeal is filed the
    # next day, inside the 30-day appeal window.
    ctx = setup_case_in_absentia()
    set_clock("2026-09-06T00:00:00Z")

    resp = api.create_appeal(
        make_appeal_payload(ctx["decision"]["id"], grounds="lack of notice"),
        headers=admin_headers,
    )
    appeal = validate_success(resp, expected_status=201)
    assert_appeal(appeal)
    assert appeal["status"] == "FILED"
    assert appeal["case_id"] == ctx["case"]["id"]

    assert read_case(ctx["case"]["id"])["status"] == "APPEALED"
    assert read_decision(ctx["decision"]["id"])["status"] == "APPEAL_PENDING"


def test_appeal_dismissed_completes_case(api, board_headers):
    """PRD §3.6: "The appeal must still be `FILED` — ruling twice is `ERR_APPEAL_ALREADY_DECIDED` — and the ruling stamps `decided_by_board_member_id` with the acting member's `X-User-ID` and `decided_at` with the clock. The three rulings diverge sharply. `AFFIRMED` and `DISMISSED` are symmetrical endings: the decision becomes `FINAL`, the case becomes `COMPLETED` with `completed_at` set to the clock, and the case's `version` increments by 1."

    Design: Corner/state_machines/appeal_dismissed_completes_case
    """
    # Case APPEALED with the appeal FILED; the ruling clock is the merits
    # completion instant 2026-09-04T12:00:00Z.
    ctx = setup_appealed_case()

    resp = api.decide_appeal(
        ctx["appeal"]["id"],
        make_appeal_ruling_payload("DISMISSED"),
        headers=board_headers,
    )
    appeal = validate_success(resp, expected_status=200)
    assert appeal["status"] == "DISMISSED"

    assert read_decision(ctx["decision"]["id"])["status"] == "FINAL"
    case = read_case(ctx["case"]["id"])
    assert case["status"] == "COMPLETED"
    assert same_instant(case["completed_at"], MERITS_HEARING_CLOCK_ISO)
