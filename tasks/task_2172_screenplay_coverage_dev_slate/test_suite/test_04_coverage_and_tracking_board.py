"""Coverage scoring, the revision cycle, approval and the tracking board."""

from test_helpers import (
    EDITOR_APPROVE,
    EDITOR_ASSIGN,
    EXEC_ALPHA,
    ApiErrorId,
    assert_tracking_board_entry,
    approve_report,
    board_entries_for_property,
    fetch_property,
    fetch_reader,
    fetch_report,
    fetch_submission,
    fill_report,
    make_clear_property,
    make_reader_headers,
    reject_report,
    set_clock,
    setup_assigned_coverage,
    setup_submitted_coverage,
    submit_report,
    validate_error,
    validate_paginated,
    validate_success,
)


# ==========================================================================
# The two scores
# ==========================================================================


def _reader_with_calibration_bias():
    """Reader R1 finishes with an APPROVED 9.00 report, so calibration_bias is 3.50."""
    set_clock("2026-09-01T00:00:00Z")
    first = setup_submitted_coverage(
        genre="DRAMA",
        title="Ashfall County",
        scores=(9, 9, 9, 9, 9),
        recommendation="RECOMMEND",
        synopsis_word_count=400,
        reader_capacity=3,
    )
    approve_report(first["report"]["id"])

    second = setup_assigned_coverage(
        genre="DRAMA",
        title="The Longer Winter",
        reader=first["reader"],
        submitting_agency="WME",
        window_start="2026-09-10T00:00:00Z",
        window_due="2026-09-13T00:00:00Z",
    )
    fill_report(
        second["report"]["id"],
        first["reader"]["id"],
        logline_score=8,
        structure_score=7,
        character_score=9,
        dialogue_score=6,
        marketability_score=8,
        recommendation="RECOMMEND",
        synopsis_word_count=400,
    )
    return {"first": first, "second": second, "reader": first["reader"]}


def test_composite_and_normalized_scores_diverge_by_the_calibration_bias(api):
    """PRD 3.4: "Submitting computes a raw weighted score from the five craft scores,
    each multiplied by its departmental weight and the products added together:
    `logline_score` at one tenth (0.10), plus `structure_score` at three tenths
    (0.30), plus `character_score` at one quarter (0.25), plus `dialogue_score` at
    fifteen hundredths (0.15), plus `marketability_score` at one fifth (0.20)."
    PRD 3.4: "`normalized_score` is the raw value less the authoring analyst's
    `calibration_bias` as read at this very instant, then clamped so that it is at
    least 1.00 and at most 10.00, and only then rounded half up to two decimal places
    — the clamp is applied before the rounding, not after."

    Design: Difficulty/dual_variant_calc/coverage_normalized_vs_composite_score_diverge
    """
    ctx = _reader_with_calibration_bias()

    resp = api.submit_coverage_report(
        ctx["second"]["report"]["id"], make_reader_headers(ctx["reader"]["id"])
    )
    data = validate_success(resp, 200)

    assert data["composite_score"] == 7.65, (
        f"Expected the raw weighted score 7.65, got {data['composite_score']}"
    )
    assert data["normalized_score"] == 4.15, (
        f"Expected 7.65 less a 3.50 calibration bias, got {data['normalized_score']}"
    )
    assert round(data["composite_score"] - data["normalized_score"], 2) == 3.50


def test_calibration_bias_is_read_at_submit_and_never_restates_earlier_reports(api):
    """PRD 3.4: "`composite_score` is the raw value rounded half up to two decimal
    places, with no calibration adjustment and no clamping; it is the number that
    appears on the face of the coverage report and the number that later feeds the
    reader's own calibration."
    PRD 3.4: "Both numbers are recomputed from the current field values on every
    submission, including the second submission that closes a revision cycle;
    approving the report afterwards does not restate either of them."

    Design: Difficulty/dual_variant_calc/coverage_normalized_vs_composite_score_diverge
    """
    ctx = _reader_with_calibration_bias()
    submit_report(ctx["second"]["report"]["id"], ctx["reader"]["id"])

    reader = fetch_reader(ctx["reader"]["id"])
    assert reader["calibration_bias"] == 3.50
    assert reader["completed_report_count"] == 1

    first_report = fetch_report(ctx["first"]["report"]["id"])
    assert first_report["composite_score"] == 9.00
    assert first_report["normalized_score"] == 9.00, (
        "the first report was scored while the bias was still 0.00 and is never restated"
    )


def test_submit_coverage_with_short_synopsis_returns_coverage_incomplete(api):
    """PRD 3.4: "Submitting a report requires all five craft scores to be present
    integers in the 1-through-10 range, the `recommendation` to be present, and
    `synopsis_word_count` to be at least 250 words. A report that falls short of any
    part of that standard is refused with `ERR_COVERAGE_INCOMPLETE`."

    Design: Corner/errors/submit_coverage_with_short_synopsis_returns_coverage_incomplete
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_assigned_coverage(genre="DRAMA", title="One Word Short")
    fill_report(
        ctx["report"]["id"],
        ctx["reader"]["id"],
        logline_score=7,
        structure_score=7,
        character_score=7,
        dialogue_score=7,
        marketability_score=7,
        recommendation="CONSIDER",
        synopsis_word_count=249,
    )

    resp = api.submit_coverage_report(
        ctx["report"]["id"], make_reader_headers(ctx["reader"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_COVERAGE_INCOMPLETE, 422)

    stored = fetch_report(ctx["report"]["id"])
    assert stored["status"] == "DRAFT"
    assert stored["composite_score"] is None
    assert stored["normalized_score"] is None
    assert validate_success(
        api.get_coverage_assignment(ctx["assignment"]["id"], EDITOR_ASSIGN)
    )["status"] == "ASSIGNED"
    assert fetch_submission(ctx["submission"]["id"])["status"] == "READER_ASSIGNED"


# ==========================================================================
# The revision cycle
# ==========================================================================


def _report_returned_once_and_rescored():
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_submitted_coverage(
        genre="HORROR",
        title="The Quiet Floor",
        scores=(4, 4, 4, 4, 4),
        recommendation="CONSIDER",
        synopsis_word_count=300,
        submitting_agency="APA",
    )
    assert fetch_report(ctx["report"]["id"])["composite_score"] == 4.00
    return ctx


def test_revision_cycle_returns_the_report_to_submitted_with_new_scores(api):
    """PRD 3.4: "The report moves `SUBMITTED → REVISION_REQUESTED`, its
    `revision_round_count` increments by one, the note is stored, the assignment goes
    back to `IN_PROGRESS`, and the submission returns `COVERAGE_IN_REVIEW →
    READER_ASSIGNED`."
    PRD 3.4: "This closes a cycle: the analyst revises and submits again, taking the
    report `REVISION_REQUESTED → SUBMITTED` and the submission `READER_ASSIGNED →
    COVERAGE_IN_REVIEW` once more."

    Design: Difficulty/non_linear_state_machine/coverage_report_revision_cycle_returns_to_submitted
    """
    ctx = _report_returned_once_and_rescored()
    validate_success(
        api.request_report_revision(
            ctx["report"]["id"],
            {"revision_note": "Structure section is thin; re-argue the second act."},
            EDITOR_APPROVE,
        )
    )
    fill_report(
        ctx["report"]["id"],
        ctx["reader"]["id"],
        logline_score=8,
        structure_score=7,
        character_score=9,
        dialogue_score=6,
        marketability_score=8,
        recommendation="RECOMMEND",
        synopsis_word_count=420,
    )

    resp = api.submit_coverage_report(
        ctx["report"]["id"], make_reader_headers(ctx["reader"]["id"])
    )
    data = validate_success(resp, 200)

    assert data["status"] == "SUBMITTED", "the row re-enters a state it already occupied"
    assert data["revision_round_count"] == 1
    assert data["composite_score"] == 7.65, (
        "the second submission recomputes from the current field values"
    )
    assert data["normalized_score"] == 7.65


def test_revision_cycle_drives_the_assignment_and_submission_back_and_forth(api):
    """PRD 3.4: "This closes a cycle: the analyst revises and submits again, taking
    the report `REVISION_REQUESTED → SUBMITTED` and the submission `READER_ASSIGNED →
    COVERAGE_IN_REVIEW` once more."
    PRD 3.4: "On success the report moves to `SUBMITTED`, the assignment moves to
    `SUBMITTED` from whichever of `ASSIGNED` or `IN_PROGRESS` it held, and the
    submission advances `READER_ASSIGNED → COVERAGE_IN_REVIEW`."

    Design: Difficulty/non_linear_state_machine/coverage_report_revision_cycle_returns_to_submitted
    """
    ctx = _report_returned_once_and_rescored()
    validate_success(
        api.request_report_revision(
            ctx["report"]["id"], {"revision_note": "Re-argue the second act."},
            EDITOR_APPROVE,
        )
    )
    assert validate_success(
        api.get_coverage_assignment(ctx["assignment"]["id"], EDITOR_ASSIGN)
    )["status"] == "IN_PROGRESS"
    assert fetch_submission(ctx["submission"]["id"])["status"] == "READER_ASSIGNED"

    fill_report(
        ctx["report"]["id"], ctx["reader"]["id"],
        logline_score=8, structure_score=7, character_score=9,
        dialogue_score=6, marketability_score=8,
        recommendation="RECOMMEND", synopsis_word_count=420,
    )
    submit_report(ctx["report"]["id"], ctx["reader"]["id"])

    assert validate_success(
        api.get_coverage_assignment(ctx["assignment"]["id"], EDITOR_ASSIGN)
    )["status"] == "SUBMITTED"
    assert fetch_submission(ctx["submission"]["id"])["status"] == "COVERAGE_IN_REVIEW"
    reader = fetch_reader(ctx["reader"]["id"])
    assert reader["active_assignment_count"] == 1
    assert reader["calibration_bias"] == 0.00


def test_request_revision_third_round_returns_revision_limit_exceeded(api):
    """PRD 3.4: "The department allows two revision rounds per report and no more. A
    revision request is admissible only while `revision_round_count` is strictly below
    2; a third request is refused with `ERR_REVISION_LIMIT_EXCEEDED`."

    Design: Corner/state_machines/request_revision_third_round_returns_revision_limit_exceeded
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_submitted_coverage(
        genre="DRAMA",
        title="Two Passes Max",
        scores=(5, 5, 5, 5, 5),
        recommendation="CONSIDER",
        synopsis_word_count=260,
        revision_rounds=2,
    )

    resp = api.request_report_revision(
        ctx["report"]["id"], {"revision_note": "Round three notes."}, EDITOR_APPROVE
    )
    validate_error(resp, ApiErrorId.ERR_REVISION_LIMIT_EXCEEDED, 409)

    stored = fetch_report(ctx["report"]["id"])
    assert stored["status"] == "SUBMITTED"
    assert stored["revision_round_count"] == 2
    assert stored["revision_note"] == "Round 2 notes.", (
        "the refused third request must not overwrite the stored note"
    )
    assert validate_success(
        api.get_coverage_assignment(ctx["assignment"]["id"], EDITOR_ASSIGN)
    )["status"] == "SUBMITTED"
    assert fetch_submission(ctx["submission"]["id"])["status"] == "COVERAGE_IN_REVIEW"


def test_reject_after_the_revision_allowance_compensates_the_whole_assignment(api):
    """PRD 3.4: "Rejection is declared from `SUBMITTED` and only when
    `revision_round_count` is at 2 or above. It takes the report to `REJECTED`, drives
    the assignment to `RECALLED` with the reader's `active_assignment_count`
    decremented by one, and returns the submission `COVERAGE_IN_REVIEW →
    INTAKE_CLEARED`."

    Design: Corner/state_machines/reject_report_after_revision_limit_recalls_assignment_compensation
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_submitted_coverage(
        genre="DRAMA",
        title="Exhausted Notes",
        scores=(5, 5, 5, 5, 5),
        recommendation="CONSIDER",
        synopsis_word_count=260,
        revision_rounds=2,
    )

    data = reject_report(ctx["report"]["id"], reason="Analysis never improved.")

    assert data["status"] == "REJECTED"
    assert data["rejection_reason"] == "Analysis never improved."
    assert validate_success(
        api.get_coverage_assignment(ctx["assignment"]["id"], EDITOR_ASSIGN)
    )["status"] == "RECALLED"

    reader = fetch_reader(ctx["reader"]["id"])
    assert reader["active_assignment_count"] == 0
    assert reader["completed_report_count"] == 0
    assert reader["calibration_bias"] == 0.00

    submission = fetch_submission(ctx["submission"]["id"])
    assert submission["status"] == "INTAKE_CLEARED"
    assert submission["decision"] == "PENDING"
    assert board_entries_for_property(ctx["property"]["id"]) == []


# ==========================================================================
# Approval, the five-link cascade and calibration
# ==========================================================================


def _family_property_ready_for_approval():
    set_clock("2026-09-01T00:00:00Z")
    prop = make_clear_property(genre="FAMILY", title="The Paper Lantern Fleet")
    return setup_submitted_coverage(
        genre="FAMILY",
        title="The Paper Lantern Fleet",
        property_id=prop["id"],
        scores=(9, 9, 9, 9, 9),
        recommendation="STRONG_RECOMMEND",
        synopsis_word_count=500,
    )


def test_approval_completes_the_assignment_and_moves_the_submission_to_tracked(api):
    """PRD 3.4: "Link one: the report moves to `APPROVED` and `approved_by_user_id`
    records the approving editor."
    PRD 3.4: "Link three, caused by link two: the reader's `active_assignment_count`
    decrements by one, their `completed_report_count` increments by one, and their
    `calibration_bias` is recomputed."
    PRD 3.4: "Link four, also caused by link two: the submission's `decision` is set
    to the report's `recommendation`, and the submission moves `COVERAGE_IN_REVIEW →
    TRACKED` when the recommendation is `CONSIDER`, `RECOMMEND` or
    `STRONG_RECOMMEND`, or `COVERAGE_IN_REVIEW → PASSED` when the recommendation is
    `PASS`."

    Design: Difficulty/transitive_cascade/coverage_approval_cascades_four_links_to_property_tier
    """
    ctx = _family_property_ready_for_approval()

    resp = api.approve_coverage_report(ctx["report"]["id"], EDITOR_APPROVE)
    data = validate_success(resp, 200)

    assert data["status"] == "APPROVED"
    assert validate_success(
        api.get_coverage_assignment(ctx["assignment"]["id"], EDITOR_ASSIGN)
    )["status"] == "COMPLETED"

    reader = fetch_reader(ctx["reader"]["id"])
    assert reader["active_assignment_count"] == 0
    assert reader["completed_report_count"] == 1
    assert reader["calibration_bias"] == 3.50

    submission = fetch_submission(ctx["submission"]["id"])
    assert submission["status"] == "TRACKED"
    assert submission["decision"] == "STRONG_RECOMMEND"


def test_approval_mints_the_board_entry_and_raises_the_property_tier(api):
    """PRD 3.4: "Link five, caused by link four and only when the submission became
    `TRACKED`: a tracking board entry is created and the property's `tracking_tier` is
    raised if the new entry outranks it."
    PRD 3.4: "The `competing_submission_count` is how many *other* submissions on the
    same property — excluding the one being tracked — sit in `TRACKED` or
    `IN_DEVELOPMENT` status at the instant the entry is created."
    PRD 3.4: "Round the result half up to two decimal places, and apply the tier
    ladder to that rounded number, top to bottom with inclusive lower bounds: a
    `heat_score` of 110.00 or more is `PRIORITY`; otherwise 85.00 or more is `HOT`;
    otherwise 60.00 or more is `WATCH`; otherwise `NONE`."

    Design: Difficulty/transitive_cascade/coverage_approval_cascades_four_links_to_property_tier
    """
    ctx = _family_property_ready_for_approval()
    approve_report(ctx["report"]["id"])

    entries = board_entries_for_property(ctx["property"]["id"])
    assert len(entries) == 1, f"Expected exactly one board entry, got {len(entries)}"
    entry = entries[0]
    assert_tracking_board_entry(entry)
    assert entry["report_id"] == ctx["report"]["id"]
    assert entry["status"] == "LIVE"
    assert entry["competing_submission_count"] == 0
    assert entry["heat_score"] == 130.00, (
        "9.00 normalized x 10, plus 30 for STRONG_RECOMMEND, plus 10 for a CLEAR chain"
    )
    assert entry["board_tier"] == "PRIORITY"

    assert fetch_property(ctx["property"]["id"])["tracking_tier"] == "PRIORITY"


def test_calibration_bias_ignores_reports_that_are_not_approved(api):
    """PRD 3.4: "It is the mean `composite_score` across every coverage report
    authored by that reader whose status is `APPROVED` — including the report just
    approved — less 5.50, with the division carried at full precision and the single
    result rounded half up to two decimal places."
    PRD 3.4: "Reports still in `DRAFT`, `SUBMITTED`, `REVISION_REQUESTED` or
    `REJECTED` are excluded."

    Design: Corner/calculations/calibration_bias_ignores_non_approved_reports
    """
    set_clock("2026-09-01T00:00:00Z")
    generous = setup_submitted_coverage(
        genre="DRAMA",
        title="Calibration A",
        scores=(9, 9, 9, 9, 9),
        recommendation="RECOMMEND",
        synopsis_word_count=400,
        reader_capacity=3,
    )
    harsh = setup_assigned_coverage(
        genre="DRAMA",
        title="Calibration B",
        reader=generous["reader"],
        window_start="2026-09-20T00:00:00Z",
        window_due="2026-09-23T00:00:00Z",
    )
    fill_report(
        harsh["report"]["id"], generous["reader"]["id"],
        logline_score=4, structure_score=4, character_score=4,
        dialogue_score=4, marketability_score=4,
        recommendation="PASS", synopsis_word_count=300,
    )
    submit_report(harsh["report"]["id"], generous["reader"]["id"])

    approve_report(generous["report"]["id"])

    assert fetch_report(generous["report"]["id"])["composite_score"] == 9.00
    assert fetch_report(harsh["report"]["id"])["composite_score"] == 4.00
    assert fetch_report(harsh["report"]["id"])["status"] == "SUBMITTED"

    reader = fetch_reader(generous["reader"]["id"])
    assert reader["completed_report_count"] == 1
    assert reader["calibration_bias"] == 3.50, (
        "averaging the unapproved 4.00 in would give 1.25 instead"
    )
    assert reader["active_assignment_count"] == 1


def test_approval_cascade_is_visible_immediately_in_the_same_request(api):
    """PRD 3.4: "Link one: the report moves to `APPROVED` and `approved_by_user_id`
    records the approving editor."
    PRD 3.4: "Link five, caused by link four and only when the submission became
    `TRACKED`: a tracking board entry is created and the property's `tracking_tier` is
    raised if the new entry outranks it."

    Design: Corner/consistency_model/approval_cascade_is_visible_immediately_in_the_same_request
    """
    set_clock("2026-09-01T00:00:00Z")
    prop = make_clear_property(genre="COMEDY", title="Same Request")
    ctx = setup_submitted_coverage(
        genre="COMEDY",
        title="Same Request",
        property_id=prop["id"],
        scores=(9, 9, 9, 9, 9),
        recommendation="STRONG_RECOMMEND",
        synopsis_word_count=500,
    )

    resp = api.approve_coverage_report(ctx["report"]["id"], EDITOR_APPROVE)
    approved = validate_success(resp, 200)
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == "editor-approve-1"

    assert validate_success(
        api.get_literary_property(prop["id"], EDITOR_APPROVE)
    )["tracking_tier"] == "PRIORITY"

    rows, meta = validate_paginated(
        api.list_tracking_board_entries(EDITOR_APPROVE, {"property_id": prop["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["heat_score"] == 130.00
    assert rows[0]["board_tier"] == "PRIORITY"
    assert rows[0]["status"] == "LIVE"

    assert validate_success(
        api.get_coverage_assignment(ctx["assignment"]["id"], EDITOR_ASSIGN)
    )["status"] == "COMPLETED"
    assert fetch_submission(ctx["submission"]["id"])["status"] == "TRACKED"
    assert fetch_reader(ctx["reader"]["id"])["calibration_bias"] == 3.50


# ==========================================================================
# The heat score and the tier ladder
# ==========================================================================


def _two_boundary_properties():
    """Property A scores a heat of exactly 85.00; property B lands on 84.50."""
    set_clock("2026-09-01T00:00:00Z")
    prop_a = make_clear_property(genre="THRILLER", title="Boundary A")
    prop_b = make_clear_property(genre="THRILLER", title="Boundary B")
    ctx_a = setup_submitted_coverage(
        genre="THRILLER", title="Boundary A", property_id=prop_a["id"],
        scores=(5, 6, 6, 6, 5), recommendation="RECOMMEND",
        synopsis_word_count=300, submitter_contact_email="a@caa.example",
    )
    ctx_b = setup_submitted_coverage(
        genre="THRILLER", title="Boundary B", property_id=prop_b["id"],
        scores=(6, 6, 6, 5, 5), recommendation="RECOMMEND",
        synopsis_word_count=300, submitter_contact_email="b@caa.example",
    )
    return {"a": ctx_a, "b": ctx_b, "property_a": prop_a, "property_b": prop_b}


def test_heat_score_of_exactly_eighty_five_lands_in_hot(api):
    """PRD 3.4: "Round the result half up to two decimal places, and apply the tier
    ladder to that rounded number, top to bottom with inclusive lower bounds: a
    `heat_score` of 110.00 or more is `PRIORITY`; otherwise 85.00 or more is `HOT`;
    otherwise 60.00 or more is `WATCH`; otherwise `NONE`."
    PRD 3.4: "Add 10 more when the property's `rights_chain_status` is `CLEAR` at the
    instant of approval, and nothing otherwise."

    Design: Difficulty/boundary_precision_check/heat_score_tier_ladder_inclusive_at_eighty_five
    """
    ctx = _two_boundary_properties()
    assert fetch_report(ctx["a"]["report"]["id"])["normalized_score"] == 5.70

    approve_report(ctx["a"]["report"]["id"])

    entries = board_entries_for_property(ctx["property_a"]["id"])
    assert len(entries) == 1
    assert entries[0]["heat_score"] == 85.00
    assert entries[0]["board_tier"] == "HOT", "the HOT floor of 85.00 is inclusive"
    assert fetch_property(ctx["property_a"]["id"])["tracking_tier"] == "HOT"


def test_heat_score_a_half_point_below_the_floor_lands_in_watch(api):
    """PRD 3.4: "Round the result half up to two decimal places, and apply the tier
    ladder to that rounded number, top to bottom with inclusive lower bounds: a
    `heat_score` of 110.00 or more is `PRIORITY`; otherwise 85.00 or more is `HOT`;
    otherwise 60.00 or more is `WATCH`; otherwise `NONE`."
    PRD 3.4: "Start with the approved report's `normalized_score` multiplied by ten."

    Design: Difficulty/boundary_precision_check/heat_score_tier_ladder_inclusive_at_eighty_five
    """
    ctx = _two_boundary_properties()
    assert fetch_report(ctx["b"]["report"]["id"])["normalized_score"] == 5.65

    approve_report(ctx["b"]["report"]["id"])

    entries = board_entries_for_property(ctx["property_b"]["id"])
    assert len(entries) == 1
    assert entries[0]["heat_score"] == 84.50
    assert entries[0]["board_tier"] == "WATCH"
    assert fetch_property(ctx["property_b"]["id"])["tracking_tier"] == "WATCH"


def test_heat_score_revision_penalty_drops_the_tier_from_hot_to_watch(api):
    """PRD 3.4: "Then subtract 5 for each revision round the report went through, that
    is, 5 multiplied by its `revision_round_count`."
    PRD 3.4: "Round the result half up to two decimal places, and apply the tier
    ladder to that rounded number, top to bottom with inclusive lower bounds: a
    `heat_score` of 110.00 or more is `PRIORITY`; otherwise 85.00 or more is `HOT`;
    otherwise 60.00 or more is `WATCH`; otherwise `NONE`."

    Design: Corner/calculations/heat_score_revision_penalty_drops_tier_from_hot_to_watch
    """
    set_clock("2026-09-01T00:00:00Z")
    prop = make_clear_property(genre="THRILLER", title="Penalised")
    ctx = setup_submitted_coverage(
        genre="THRILLER", title="Penalised", property_id=prop["id"],
        scores=(5, 6, 6, 6, 5), recommendation="RECOMMEND",
        synopsis_word_count=300, revision_rounds=1,
    )
    report = fetch_report(ctx["report"]["id"])
    assert report["revision_round_count"] == 1
    assert report["normalized_score"] == 5.70

    approve_report(ctx["report"]["id"])

    entries = board_entries_for_property(prop["id"])
    assert len(entries) == 1
    assert entries[0]["heat_score"] == 80.00, (
        "85.00 less the single 5-point revision penalty"
    )
    assert entries[0]["board_tier"] == "WATCH"
    assert fetch_property(prop["id"])["tracking_tier"] == "WATCH"
    assert fetch_submission(ctx["submission"]["id"])["status"] == "TRACKED"


def test_tracking_board_filtered_by_board_tier(api):
    """PRD 3.4: "Board entries can be read individually and listed with filters on
    `property_id`, `report_id`, `board_tier` and `status`."
    PRD 3.4: "Add a recommendation bonus: nothing for `PASS`, 8 for `CONSIDER`, 18 for
    `RECOMMEND`, and 30 for `STRONG_RECOMMEND`."

    Design: Corner/endpoints/tracking_board_filtered_by_board_tier_computed_read
    """
    set_clock("2026-09-01T00:00:00Z")
    prop_a = make_clear_property(genre="DRAMA", title="Board A")
    prop_b = make_clear_property(genre="DRAMA", title="Board B")
    ctx_a = setup_submitted_coverage(
        genre="DRAMA", title="Board A", property_id=prop_a["id"],
        scores=(9, 9, 9, 9, 9), recommendation="STRONG_RECOMMEND",
        synopsis_word_count=500, submitter_contact_email="a@caa.example",
    )
    approve_report(ctx_a["report"]["id"])
    ctx_b = setup_submitted_coverage(
        genre="DRAMA", title="Board B", property_id=prop_b["id"],
        scores=(5, 6, 6, 6, 5), recommendation="RECOMMEND",
        synopsis_word_count=300, submitter_contact_email="b@caa.example",
    )
    approve_report(ctx_b["report"]["id"])

    resp = api.list_tracking_board_entries(
        EXEC_ALPHA, {"board_tier": "PRIORITY", "status": "LIVE"}
    )
    rows, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert meta["total_count"] == 1
    assert rows[0]["property_id"] == prop_a["id"]
    assert rows[0]["report_id"] == ctx_a["report"]["id"]
    assert rows[0]["heat_score"] == 130.00
    assert rows[0]["board_tier"] == "PRIORITY"
    assert rows[0]["competing_submission_count"] == 0

    hot_rows, hot_meta = validate_paginated(
        api.list_tracking_board_entries(EXEC_ALPHA, {"board_tier": "HOT"})
    )
    assert hot_meta["total_count"] == 1
    assert hot_rows[0]["property_id"] == prop_b["id"]
    assert hot_rows[0]["heat_score"] == 85.00

    assert fetch_property(prop_a["id"])["tracking_tier"] == "PRIORITY"
    assert fetch_property(prop_b["id"])["tracking_tier"] == "HOT"
