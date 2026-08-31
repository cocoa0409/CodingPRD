"""The reader bench, the selector policy and the coverage-window rules."""

from test_helpers import (
    ADMIN,
    EDITOR_ASSIGN,
    ApiErrorId,
    assert_coverage_assignment,
    assert_reader,
    assign_reader,
    clear_intake,
    create_property,
    create_reader,
    create_submission,
    create_unsolicited_submission,
    execute_release_form,
    fetch_reader,
    fetch_release_form,
    fetch_submission,
    file_document,
    make_reader_headers,
    open_release_form,
    report_for_assignment,
    send_release_form,
    set_clock,
    setup_assigned_coverage,
    setup_cleared_submission,
    validate_error,
    validate_paginated,
    validate_success,
)


# ==========================================================================
# The reader bench
# ==========================================================================


def test_create_reader_ignores_client_supplied_counters(api):
    """PRD 3.3: "Three derived numbers ride along: `active_assignment_count` and
    `completed_report_count` both start at 0, and `calibration_bias` starts at 0.00."
    PRD 2.6: "Unknown fields in a request body are ignored rather than rejected, and
    any computed or system-maintained field a client supplies is likewise ignored."

    Design: Corner/entities/create_reader_computed_counters_input_ignored
    """
    set_clock("2026-09-01T00:00:00Z")

    resp = api.create_reader(
        {
            "display_name": "R Sneaky",
            "specialty_genre": "DRAMA",
            "weekly_capacity": 3,
            "employment_type": "STAFF",
            "active_assignment_count": 99,
            "completed_report_count": 42,
            "calibration_bias": -4.00,
        },
        ADMIN,
    )
    data = validate_success(resp, 201)
    assert_reader(data)

    assert data["active_assignment_count"] == 0
    assert data["completed_report_count"] == 0
    assert data["calibration_bias"] == 0.00
    assert data["weekly_capacity"] == 3


def test_create_reader_weekly_capacity_zero_returns_value_out_of_range(api):
    """PRD 2.6: "Numeric inputs sit inside their declared bounds, or
    `ERR_VALUE_OUT_OF_RANGE` (422). The declared bounds are: each of the five craft
    scores from 1 through 10; `weekly_capacity` from 1 through 20; `vote_weight_bps`
    from 1 through 10000; `initial_period_months` from 1 through 36;
    `extension_period_months` from 0 through 24; `option_fee_cents`,
    `purchase_price_cents`, `total_fee_cents` and `budget_cents` each at least 1;
    `limit` from 1 through 100; and `offset` at least 0."

    Design: Corner/entities/create_reader_weekly_capacity_zero_returns_value_out_of_range
    """
    set_clock("2026-09-01T00:00:00Z")

    resp = api.create_reader(
        {
            "display_name": "R Zero",
            "specialty_genre": "DRAMA",
            "weekly_capacity": 0,
            "employment_type": "STAFF",
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VALUE_OUT_OF_RANGE, 422)

    _, meta = validate_paginated(api.list_readers(ADMIN))
    assert meta["total_count"] == 0, "the out-of-range reader must not persist"


def test_patch_coverage_report_invalid_enum_recommendation_rejected(api):
    """PRD 2.6: "Every enum-typed input carries a declared member of that
    enumeration, or `ERR_INVALID_ENUM_VALUE` (422)."
    PRD 3.4: "All of these begin unset: the five scores and the `recommendation` start
    null, `synopsis_word_count` starts at 0, and `comparable_titles` starts as an
    empty list."

    Design: Corner/entities/patch_coverage_report_invalid_enum_recommendation_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_assigned_coverage(genre="DRAMA", title="Enum Guard")

    resp = api.patch_coverage_report(
        ctx["report"]["id"],
        {"recommendation": "MAYBE"},
        make_reader_headers(ctx["reader"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM_VALUE, 422)

    stored = validate_success(
        api.get_coverage_report(ctx["report"]["id"], EDITOR_ASSIGN)
    )
    assert stored["recommendation"] is None
    assert stored["status"] == "DRAFT"


# ==========================================================================
# Assignment preconditions
# ==========================================================================


def test_assign_reader_from_received_state_returns_invalid_state(api):
    """PRD 3.3: "The operation is declared only from `INTAKE_CLEARED` and drives the
    submission `INTAKE_CLEARED → READER_ASSIGNED`."
    PRD 2.6: "The target resource sits in a state from which the requested transition
    is declared, or `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/assign_reader_from_received_state_returns_invalid_state
    """
    set_clock("2026-09-01T00:00:00Z")
    prop = create_property(genre="DRAMA", title="Too Early")
    reader = create_reader(specialty_genre="DRAMA", weekly_capacity=3)
    submission = create_submission(prop["id"])

    resp = api.assign_reader(
        submission["id"],
        {
            "reader_id": reader["id"],
            "window_start": "2026-09-01T00:00:00Z",
            "window_due": "2026-09-04T00:00:00Z",
        },
        EDITOR_ASSIGN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    assert fetch_submission(submission["id"])["status"] == "RECEIVED"
    assert fetch_reader(reader["id"])["active_assignment_count"] == 0


def test_explicit_reader_at_capacity_with_clear_window_returns_reader_at_capacity(api):
    """PRD 3.3: "When the request names a `reader_id`, that analyst is used, but only
    if their `status` is `ACTIVE` and their `active_assignment_count` is strictly less
    than their `weekly_capacity`; otherwise the request is refused with
    `ERR_READER_AT_CAPACITY`."

    Design: Corner/errors/explicit_reader_at_capacity_with_clear_window_returns_reader_at_capacity
    """
    set_clock("2026-09-01T00:00:00Z")
    prop = create_property(genre="DRAMA", title="Capacity One")
    reader = create_reader(specialty_genre="DRAMA", weekly_capacity=1)
    first = setup_cleared_submission(
        property_id=prop["id"], submitter_contact_email="a@caa.example"
    )
    first_assignment = assign_reader(
        first["submission"]["id"],
        reader_id=reader["id"],
        window_start="2026-09-01T00:00:00Z",
        window_due="2026-09-02T00:00:00Z",
    )
    second = setup_cleared_submission(
        property_id=prop["id"], submitter_contact_email="b@caa.example"
    )

    resp = api.assign_reader(
        second["submission"]["id"],
        {
            "reader_id": reader["id"],
            "window_start": "2026-09-20T00:00:00Z",
            "window_due": "2026-09-23T00:00:00Z",
        },
        EDITOR_ASSIGN,
    )
    validate_error(resp, ApiErrorId.ERR_READER_AT_CAPACITY, 409)

    assert fetch_reader(reader["id"])["active_assignment_count"] == 1
    assert validate_success(
        api.get_coverage_assignment(first_assignment["id"], EDITOR_ASSIGN)
    )["status"] == "ASSIGNED"
    assert fetch_submission(second["submission"]["id"])["status"] == "INTAKE_CLEARED"


def test_list_coverage_assignments_filtered_by_reader_id(api):
    """PRD 3.3: "Assignments can be listed and filtered by `submission_id`, by
    `reader_id` and by `status`."
    PRD 2.3: "Filter parameters offered by an endpoint are combined conjunctively: a
    request naming both `property_id` and `status` returns only rows matching both.
    Filters are applied before pagination, so `total_count` reflects the filtered
    population."

    Design: Corner/endpoints/list_coverage_assignments_filtered_by_reader_id
    """
    set_clock("2026-09-01T00:00:00Z")
    prop = create_property(genre="DRAMA", title="Two Assignments")
    busy = create_reader(display_name="RA Busy", specialty_genre="DRAMA", weekly_capacity=4)
    idle = create_reader(display_name="RB Idle", specialty_genre="DRAMA", weekly_capacity=4)

    first = setup_cleared_submission(
        property_id=prop["id"], submitter_contact_email="a@caa.example"
    )
    assign_reader(
        first["submission"]["id"],
        reader_id=busy["id"],
        window_start="2026-09-01T00:00:00Z",
        window_due="2026-09-02T00:00:00Z",
    )
    second = setup_cleared_submission(
        property_id=prop["id"], submitter_contact_email="b@caa.example"
    )
    assign_reader(
        second["submission"]["id"],
        reader_id=busy["id"],
        window_start="2026-09-03T00:00:00Z",
        window_due="2026-09-04T00:00:00Z",
    )

    resp = api.list_coverage_assignments(EDITOR_ASSIGN, {"reader_id": busy["id"]})
    rows, meta = validate_paginated(resp)

    assert resp.json()["response_type"] == "array"
    assert meta["total_count"] == 2
    assert all(row["reader_id"] == busy["id"] for row in rows)

    idle_rows, idle_meta = validate_paginated(
        api.list_coverage_assignments(EDITOR_ASSIGN, {"reader_id": idle["id"]})
    )
    assert idle_meta["total_count"] == 0
    assert idle_rows == []
    assert fetch_reader(busy["id"])["active_assignment_count"] == 2
    assert fetch_reader(idle["id"])["active_assignment_count"] == 0


# ==========================================================================
# The selector policy
# ==========================================================================


def _three_reader_bench():
    """RA (DRAMA/STAFF, load 2/4), RB (DRAMA/FREELANCE, load 1/4), RC (COMEDY/STAFF, 0)."""
    set_clock("2026-09-01T00:00:00Z")
    filler = create_property(genre="DRAMA", title="Filler Pile")
    ra = create_reader(
        display_name="RA Staff Drama", specialty_genre="DRAMA",
        weekly_capacity=4, employment_type="STAFF",
    )
    rb = create_reader(
        display_name="RB Freelance Drama", specialty_genre="DRAMA",
        weekly_capacity=4, employment_type="FREELANCE",
    )
    rc = create_reader(
        display_name="RC Staff Comedy", specialty_genre="COMEDY",
        weekly_capacity=4, employment_type="STAFF",
    )
    for reader_id, start, due, email in (
        (ra["id"], "2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z", "f1@uta.example"),
        (ra["id"], "2026-09-03T00:00:00Z", "2026-09-04T00:00:00Z", "f2@uta.example"),
        (rb["id"], "2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z", "f3@uta.example"),
    ):
        ctx = setup_cleared_submission(
            property_id=filler["id"], submitting_agency="UTA",
            submitter_contact_email=email,
        )
        assign_reader(
            ctx["submission"]["id"], reader_id=reader_id,
            window_start=start, window_due=due,
        )

    target_property = create_property(genre="DRAMA", title="Cold Open")
    target = setup_cleared_submission(
        property_id=target_property["id"], submitting_agency="GERSH",
        submitter_contact_email="lit@gersh.example",
    )
    return {"ra": ra, "rb": rb, "rc": rc, "submission": target["submission"]}


def test_selector_genre_penalty_outranks_a_completely_idle_generalist(api):
    """PRD 3.3: "Candidates are then ranked on three keys evaluated left to right:
    first a genre penalty of 0 when the analyst's `specialty_genre` matches the
    property's `genre` and 1 otherwise, ascending, so specialists come before
    generalists; then the analyst's load ratio, their `active_assignment_count`
    divided by their `weekly_capacity`, ascending, compared as an exact rational with
    no rounding applied before comparison; then their `completed_report_count`,
    descending, so experience breaks a tie in favour of the busier veteran."
    PRD 3.3: "It sets `auto_selected` to true when the reader was chosen by the
    selector and false when the request named one explicitly."

    Design: Difficulty/combinatorial_formula/reader_selection_rank_key_three_factor_genre_then_load
    """
    bench = _three_reader_bench()

    resp = api.assign_reader(
        bench["submission"]["id"],
        {"window_start": "2026-09-20T00:00:00Z", "window_due": "2026-09-23T00:00:00Z"},
        EDITOR_ASSIGN,
    )
    data = validate_success(resp, 201)
    assert_coverage_assignment(data)

    assert data["reader_id"] == bench["rb"]["id"], (
        "the in-genre freelancer at load 0.25 must beat the in-genre staffer at 0.50 "
        "and the out-of-genre staffer at load 0.00"
    )
    assert data["reader_id"] != bench["rc"]["id"]
    assert data["auto_selected"] is True
    assert data["status"] == "ASSIGNED"


def test_selector_choice_increments_only_the_chosen_readers_counter(api):
    """PRD 3.3: "It increments the chosen reader's `active_assignment_count` by one."
    PRD 3.3: "Candidates are then ranked on three keys evaluated left to right: first
    a genre penalty of 0 when the analyst's `specialty_genre` matches the property's
    `genre` and 1 otherwise, ascending, so specialists come before generalists; then
    the analyst's load ratio, their `active_assignment_count` divided by their
    `weekly_capacity`, ascending, compared as an exact rational with no rounding
    applied before comparison; then their `completed_report_count`, descending, so
    experience breaks a tie in favour of the busier veteran."

    Design: Difficulty/combinatorial_formula/reader_selection_rank_key_three_factor_genre_then_load
    """
    bench = _three_reader_bench()
    assign_reader(
        bench["submission"]["id"],
        window_start="2026-09-20T00:00:00Z",
        window_due="2026-09-23T00:00:00Z",
    )

    assert fetch_reader(bench["rb"]["id"])["active_assignment_count"] == 2
    assert fetch_reader(bench["ra"]["id"])["active_assignment_count"] == 2
    assert fetch_reader(bench["rc"]["id"])["active_assignment_count"] == 0, (
        "the out-of-genre generalist was ranked last and stays idle"
    )


def _only_out_of_genre_freelancer():
    set_clock("2026-09-01T00:00:00Z")
    reader = create_reader(
        display_name="RC Freelance Comedy", specialty_genre="COMEDY",
        weekly_capacity=5, employment_type="FREELANCE",
    )
    prop = create_property(genre="DRAMA", title="No Reader For This")
    ctx = setup_cleared_submission(
        property_id=prop["id"], submitting_agency="WME",
        submitter_contact_email="lit@wme.example",
    )
    return {"reader": reader, "submission": ctx["submission"]}


def test_empty_candidate_pool_refuses_the_whole_assignment(api):
    """PRD 3.3: "Its candidate set consists of every analyst who is `ACTIVE`, whose
    `active_assignment_count` is strictly less than their `weekly_capacity`, whose
    `specialty_genre` equals the property's `genre` *or* whose `employment_type` is
    `STAFF` (staff readers are eligible for anything; freelancers only for their own
    genre), whose `id` is not among the supplied `excluded_reader_ids`, whose `id` is
    not the reader of any assignment on this same submission that has been `RECALLED`,
    and who survives the window-overlap test described below."
    PRD 3.3: "If the candidate set is empty, the entire request is refused with
    `ERR_NO_ELIGIBLE_READER` and neither a coverage assignment nor a coverage report
    is created."

    Design: Difficulty/boundary_precision_check/assign_reader_empty_candidate_pool_zero_eligible_readers
    """
    ctx = _only_out_of_genre_freelancer()

    resp = api.assign_reader(
        ctx["submission"]["id"],
        {"window_start": "2026-09-01T00:00:00Z", "window_due": "2026-09-04T00:00:00Z"},
        EDITOR_ASSIGN,
    )
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_READER, 409)

    assert fetch_submission(ctx["submission"]["id"])["status"] == "INTAKE_CLEARED"


def test_empty_candidate_pool_writes_neither_assignment_nor_report(api):
    """PRD 3.3: "If the candidate set is empty, the entire request is refused with
    `ERR_NO_ELIGIBLE_READER` and neither a coverage assignment nor a coverage report
    is created."

    Design: Difficulty/boundary_precision_check/assign_reader_empty_candidate_pool_zero_eligible_readers
    """
    ctx = _only_out_of_genre_freelancer()

    resp = api.assign_reader(
        ctx["submission"]["id"],
        {"window_start": "2026-09-01T00:00:00Z", "window_due": "2026-09-04T00:00:00Z"},
        EDITOR_ASSIGN,
    )
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_READER, 409)

    _, assignments_meta = validate_paginated(
        api.list_coverage_assignments(
            EDITOR_ASSIGN, {"submission_id": ctx["submission"]["id"]}
        )
    )
    assert assignments_meta["total_count"] == 0
    _, reports_meta = validate_paginated(api.list_coverage_reports(EDITOR_ASSIGN))
    assert reports_meta["total_count"] == 0
    assert fetch_reader(ctx["reader"]["id"])["active_assignment_count"] == 0


# ==========================================================================
# The window-overlap test
# ==========================================================================


def _incumbent_window(weekly_capacity: int, incumbent_due: str):
    set_clock("2026-09-01T00:00:00Z")
    first_property = create_property(genre="DRAMA", title="Buffer One")
    reader = create_reader(
        specialty_genre="DRAMA", weekly_capacity=weekly_capacity, employment_type="STAFF"
    )
    incumbent_ctx = setup_cleared_submission(
        property_id=first_property["id"], submitter_contact_email="a@caa.example"
    )
    incumbent = assign_reader(
        incumbent_ctx["submission"]["id"],
        reader_id=reader["id"],
        window_start="2026-09-01T00:00:00Z",
        window_due=incumbent_due,
    )
    second_property = create_property(genre="DRAMA", title="Buffer Two")
    candidate_ctx = setup_cleared_submission(
        property_id=second_property["id"], submitter_contact_email="b@caa.example"
    )
    return {
        "reader": reader,
        "incumbent": incumbent,
        "submission": candidate_ctx["submission"],
    }


def test_candidate_window_touching_the_twelve_hour_buffer_collides(api):
    """PRD 3.3: "A candidate window conflicts with an existing assignment when the
    candidate's `window_start` is at or before the existing assignment's `window_due`
    advanced by twelve hours, *and* the existing assignment's `window_start` is at or
    before the candidate's `window_due`."
    PRD 3.3: "Both bounds are inclusive, so windows that merely touch at an endpoint
    do collide."
    PRD 3.3: "A collision on an explicitly named reader is refused with
    `ERR_READER_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/reader_window_closed_interval_trailing_buffer_rejects_touching_start
    """
    ctx = _incumbent_window(weekly_capacity=3, incumbent_due="2026-09-04T00:00:00Z")

    resp = api.assign_reader(
        ctx["submission"]["id"],
        {
            "reader_id": ctx["reader"]["id"],
            "window_start": "2026-09-04T12:00:00Z",
            "window_due": "2026-09-07T00:00:00Z",
        },
        EDITOR_ASSIGN,
    )
    validate_error(resp, ApiErrorId.ERR_READER_WINDOW_CONFLICT, 409)

    reader = fetch_reader(ctx["reader"]["id"])
    assert reader["weekly_capacity"] == 3
    assert reader["active_assignment_count"] == 1, (
        "two free capacity slots remain, so capacity cannot be the reason"
    )


def test_window_collision_leaves_the_incumbent_and_submission_untouched(api):
    """PRD 3.3: "The test is run against every assignment of the resolved reader whose
    status is `ASSIGNED`, `IN_PROGRESS` or `SUBMITTED`; assignments already
    `COMPLETED` or `RECALLED` never conflict."
    PRD 3.3: "A collision on an explicitly named reader is refused with
    `ERR_READER_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/reader_window_closed_interval_trailing_buffer_rejects_touching_start
    """
    ctx = _incumbent_window(weekly_capacity=3, incumbent_due="2026-09-04T00:00:00Z")

    resp = api.assign_reader(
        ctx["submission"]["id"],
        {
            "reader_id": ctx["reader"]["id"],
            "window_start": "2026-09-04T12:00:00Z",
            "window_due": "2026-09-07T00:00:00Z",
        },
        EDITOR_ASSIGN,
    )
    validate_error(resp, ApiErrorId.ERR_READER_WINDOW_CONFLICT, 409)

    assert validate_success(
        api.get_coverage_assignment(ctx["incumbent"]["id"], EDITOR_ASSIGN)
    )["status"] == "ASSIGNED"
    _, meta = validate_paginated(
        api.list_coverage_assignments(
            EDITOR_ASSIGN, {"submission_id": ctx["submission"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert fetch_submission(ctx["submission"]["id"])["status"] == "INTAKE_CLEARED"


def test_window_conflict_is_reported_ahead_of_reader_capacity(api):
    """PRD 2.6: "The ladder below is evaluated strictly top to bottom; a check never
    masks one above it, and a check never fires before one above it has passed."
    PRD 2.6: "**Temporal admissibility.** In priority order: option-window
    intersection on execution, failing with `ERR_OPTION_PERIOD_OVERLAP` (409);
    reader-window collision on assignment, failing with `ERR_READER_WINDOW_CONFLICT`
    (409); option expiry on exercise or extension, failing with `ERR_OPTION_EXPIRED`
    (409); turnaround immaturity on a reversion notice, failing with
    `ERR_TURNAROUND_NOT_MATURE` (409); and writer over-commitment on attachment,
    failing with `ERR_WRITER_OVERCOMMITTED` (409)."
    PRD 2.6: "**Remaining business constraints**, in this order: an empty
    auto-selection candidate pool, `ERR_NO_ELIGIBLE_READER` (409); an explicitly named
    reader who is unavailable or full, `ERR_READER_AT_CAPACITY` (409); an incomplete
    coverage report on submit, `ERR_COVERAGE_INCOMPLETE` (422); an exhausted revision
    allowance on a revision request, `ERR_REVISION_LIMIT_EXCEEDED` (409); a repeat
    ballot, `ERR_DUPLICATE_VOTE` (409); an undersized committee at open-voting,
    `ERR_COMMITTEE_TOO_SMALL` (409); a failed quorum at close, `ERR_QUORUM_NOT_MET`
    (409); and an out-of-sequence milestone approval,
    `ERR_MILESTONE_SEQUENCE_VIOLATION` (409)."

    Design: Difficulty/priority_pair_validation_conflict/reader_window_conflict_check_beats_reader_capacity_check
    """
    ctx = _incumbent_window(weekly_capacity=1, incumbent_due="2026-09-04T00:00:00Z")

    resp = api.assign_reader(
        ctx["submission"]["id"],
        {
            "reader_id": ctx["reader"]["id"],
            "window_start": "2026-09-04T06:00:00Z",
            "window_due": "2026-09-07T00:00:00Z",
        },
        EDITOR_ASSIGN,
    )
    error = validate_error(resp, ApiErrorId.ERR_READER_WINDOW_CONFLICT, 409)
    assert error["error_id"] != ApiErrorId.ERR_READER_AT_CAPACITY.value, (
        "the temporal rung outranks the capacity rung"
    )


def test_window_conflict_over_capacity_writes_nothing(api):
    """PRD 2.6: "When a request violates more than one rule, the service reports the
    highest-precedence violation and stops."
    PRD 3.3: "A collision on an explicitly named reader is refused with
    `ERR_READER_WINDOW_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/reader_window_conflict_check_beats_reader_capacity_check
    """
    ctx = _incumbent_window(weekly_capacity=1, incumbent_due="2026-09-04T00:00:00Z")

    resp = api.assign_reader(
        ctx["submission"]["id"],
        {
            "reader_id": ctx["reader"]["id"],
            "window_start": "2026-09-04T06:00:00Z",
            "window_due": "2026-09-07T00:00:00Z",
        },
        EDITOR_ASSIGN,
    )
    validate_error(resp, ApiErrorId.ERR_READER_WINDOW_CONFLICT, 409)

    assert fetch_submission(ctx["submission"]["id"])["status"] == "INTAKE_CLEARED"
    _, meta = validate_paginated(
        api.list_coverage_assignments(
            EDITOR_ASSIGN, {"submission_id": ctx["submission"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert fetch_reader(ctx["reader"]["id"])["active_assignment_count"] == 1
    assert validate_success(
        api.get_coverage_assignment(ctx["incumbent"]["id"], EDITOR_ASSIGN)
    )["status"] == "ASSIGNED"


# ==========================================================================
# Rights posture and release-form expiry at assignment time
# ==========================================================================


def _disputed_property_with_cleared_submission():
    set_clock("2026-09-01T00:00:00Z")
    prop = create_property(genre="THRILLER", title="Clouded Title", material_type="BOOK")
    file_document(prop["id"], "CHAIN_OF_TITLE", "2026-01-15", True)
    file_document(
        prop["id"], "PRIOR_ASSIGNMENT", "2023-11-02", False,
        notes="Producer claim never released.",
    )
    reader = create_reader(specialty_genre="THRILLER", weekly_capacity=3)
    ctx = setup_cleared_submission(property_id=prop["id"])
    return {"property": prop, "reader": reader, "submission": ctx["submission"]}


def test_assign_reader_blocked_when_property_rights_are_disputed(api):
    """PRD 3.3: "Then the property's rights posture is checked: a property in
    `DISPUTED` blocks the assignment with `ERR_PROPERTY_RIGHTS_DISPUTED`."
    PRD 3.1: "First, if any live document is of type `PRIOR_ASSIGNMENT` and has not
    been verified, the property is `DISPUTED` — an unverified prior assignment is
    exactly the kind of unresolved competing grant that stops a deal."

    Design: Difficulty/cross_entity_state_dependency/assign_reader_gated_by_property_rights_chain_status
    """
    ctx = _disputed_property_with_cleared_submission()

    resp = api.assign_reader(
        ctx["submission"]["id"],
        {
            "reader_id": ctx["reader"]["id"],
            "window_start": "2026-09-01T00:00:00Z",
            "window_due": "2026-09-04T00:00:00Z",
        },
        EDITOR_ASSIGN,
    )
    validate_error(resp, ApiErrorId.ERR_PROPERTY_RIGHTS_DISPUTED, 409)

    stored_property = validate_success(
        api.get_literary_property(ctx["property"]["id"], EDITOR_ASSIGN)
    )
    assert stored_property["rights_chain_status"] == "DISPUTED"
    assert stored_property["verified_document_count"] == 1


def test_disputed_rights_block_leaves_submission_and_reader_untouched(api):
    """PRD 3.3: "Then the property's rights posture is checked: a property in
    `DISPUTED` blocks the assignment with `ERR_PROPERTY_RIGHTS_DISPUTED`."
    PRD 3.2: "A release form is required when the submission arrived through the
    `UNSOLICITED` channel, or when the submitting agency is not one of the five
    signatory agencies the studio has a standing submission agreement with — `CAA`,
    `WME`, `UTA`, `GERSH` and `APA`."

    Design: Difficulty/cross_entity_state_dependency/assign_reader_gated_by_property_rights_chain_status
    """
    ctx = _disputed_property_with_cleared_submission()

    resp = api.assign_reader(
        ctx["submission"]["id"],
        {
            "reader_id": ctx["reader"]["id"],
            "window_start": "2026-09-01T00:00:00Z",
            "window_due": "2026-09-04T00:00:00Z",
        },
        EDITOR_ASSIGN,
    )
    validate_error(resp, ApiErrorId.ERR_PROPERTY_RIGHTS_DISPUTED, 409)

    submission = fetch_submission(ctx["submission"]["id"])
    assert submission["status"] == "INTAKE_CLEARED"
    assert submission["release_form_required"] is False, (
        "a CAA agency submission needs no release, so only the rights gate can fire"
    )
    _, meta = validate_paginated(
        api.list_coverage_assignments(
            EDITOR_ASSIGN, {"submission_id": ctx["submission"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert fetch_reader(ctx["reader"]["id"])["active_assignment_count"] == 0


def _stale_release_on_disputed_property():
    set_clock("2026-09-01T00:00:00Z")
    prop = create_property(genre="COMEDY", title="Two Weeks in Reseda")
    file_document(prop["id"], "CHAIN_OF_TITLE", "2026-01-15", True)
    file_document(prop["id"], "COPYRIGHT_CERT", "2026-01-20", True)
    file_document(prop["id"], "WGA_REGISTRATION", "2026-01-22", True)
    reader = create_reader(specialty_genre="COMEDY", weekly_capacity=3)
    submission = create_unsolicited_submission(prop["id"])
    form = open_release_form(submission["id"], expires_at="2026-09-10T00:00:00Z")
    send_release_form(form["id"])
    execute_release_form(form["id"], signer_name="G. Mbeki")
    file_document(
        prop["id"], "PRIOR_ASSIGNMENT", "2024-06-30", False,
        notes="Unverified prior grant to a former producer.",
    )
    set_clock("2026-09-11T00:00:00Z")
    return {
        "property": prop, "reader": reader, "submission": submission, "form": form,
    }


def test_release_form_expiry_is_reported_ahead_of_disputed_rights(api):
    """PRD 2.6: "The ladder below is evaluated strictly top to bottom; a check never
    masks one above it, and a check never fires before one above it has passed."
    PRD 2.6: "Expiry is checked first: after lazy expiry has been applied, no release
    form on the submission may be in `EXPIRED` status, or `ERR_RELEASE_FORM_EXPIRED`
    (409); this guards reader assignment only."
    PRD 2.6: "**Rights posture.** Executing an option requires the property's
    `rights_chain_status` to equal `CLEAR`, or `ERR_RIGHTS_CHAIN_INCOMPLETE` (409).
    Assigning a reader requires the submission's property not to be in `DISPUTED`, or
    `ERR_PROPERTY_RIGHTS_DISPUTED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/release_expired_check_beats_rights_disputed_check_on_assign_reader
    """
    ctx = _stale_release_on_disputed_property()

    resp = api.assign_reader(
        ctx["submission"]["id"],
        {
            "reader_id": ctx["reader"]["id"],
            "window_start": "2026-09-11T00:00:00Z",
            "window_due": "2026-09-14T00:00:00Z",
        },
        EDITOR_ASSIGN,
    )
    error = validate_error(resp, ApiErrorId.ERR_RELEASE_FORM_EXPIRED, 409)
    assert error["error_id"] != ApiErrorId.ERR_PROPERTY_RIGHTS_DISPUTED.value

    assert fetch_release_form(ctx["form"]["id"])["status"] == "EXPIRED", (
        "lazy expiry runs before any other check and moves the executed form"
    )


def test_lazily_expired_release_blocks_assignment_without_partial_writes(api):
    """PRD 3.2: "At those two moments, any release form on the submission whose status
    is `REQUIRED`, `SENT` or `EXECUTED` and whose `expires_at` is strictly before the
    current logical clock value is moved to `EXPIRED` first, before any other check
    runs."
    PRD 3.2: "When that happens the submission remains `INTAKE_CLEARED`, but reader
    assignment is refused with `ERR_RELEASE_FORM_EXPIRED`, because the studio is no
    longer covered."

    Design: Difficulty/priority_pair_validation_conflict/release_expired_check_beats_rights_disputed_check_on_assign_reader
    """
    ctx = _stale_release_on_disputed_property()

    resp = api.assign_reader(
        ctx["submission"]["id"],
        {
            "reader_id": ctx["reader"]["id"],
            "window_start": "2026-09-11T00:00:00Z",
            "window_due": "2026-09-14T00:00:00Z",
        },
        EDITOR_ASSIGN,
    )
    validate_error(resp, ApiErrorId.ERR_RELEASE_FORM_EXPIRED, 409)

    assert validate_success(
        api.get_literary_property(ctx["property"]["id"], EDITOR_ASSIGN)
    )["rights_chain_status"] == "DISPUTED"
    assert fetch_submission(ctx["submission"]["id"])["status"] == "INTAKE_CLEARED"
    _, meta = validate_paginated(
        api.list_coverage_assignments(
            EDITOR_ASSIGN, {"submission_id": ctx["submission"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert fetch_reader(ctx["reader"]["id"])["active_assignment_count"] == 0


# ==========================================================================
# Recall: the compensating action for assignment
# ==========================================================================


def test_recall_rejects_the_draft_report_and_returns_the_submission(api):
    """PRD 3.3: "A story editor may pull an assignment back at any point while it is
    `ASSIGNED` or `IN_PROGRESS`, supplying a `reason` that is stored as
    `recall_reason`; the recall is the compensating action for the assignment and it
    takes the assignment to `RECALLED`, decrements the reader's
    `active_assignment_count` by one, drives the assignment's coverage report to
    `REJECTED` if that report is still in `DRAFT` or `REVISION_REQUESTED`, and returns
    the submission `READER_ASSIGNED → INTAKE_CLEARED` so the material can be
    reassigned."

    Design: Difficulty/compensating_invariant/reader_assignment_counter_conserved_across_assign_then_recall
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_assigned_coverage(
        genre="COMEDY", title="Recall Notice", reader_capacity=3,
        submitting_agency="UTA",
    )
    reason = "Reader has a conflict of interest with the submitting agency."

    resp = api.recall_coverage_assignment(
        ctx["assignment"]["id"], {"reason": reason}, EDITOR_ASSIGN
    )
    data = validate_success(resp, 200)

    assert data["status"] == "RECALLED"
    assert data["recall_reason"] == reason
    assert validate_success(
        api.get_coverage_report(ctx["report"]["id"], EDITOR_ASSIGN)
    )["status"] == "REJECTED"
    assert fetch_submission(ctx["submission"]["id"])["status"] == "INTAKE_CLEARED"


def test_recall_returns_the_reader_capacity_counter_to_its_pre_assign_value(api):
    """PRD 2.10: "A reader's `active_assignment_count` is the number of that reader's
    coverage assignments in `ASSIGNED`, `IN_PROGRESS` or `SUBMITTED` status; assigning
    a reader and then recalling that same assignment must leave the count exactly
    where it started, and must leave `completed_report_count` untouched."
    PRD 3.4: "A submission's `decision` is `PENDING` until a report is approved and
    thereafter mirrors that report's recommendation."

    Design: Difficulty/compensating_invariant/reader_assignment_counter_conserved_across_assign_then_recall
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_assigned_coverage(
        genre="COMEDY", title="Recall Notice", reader_capacity=3,
        submitting_agency="UTA",
    )
    assert fetch_reader(ctx["reader"]["id"])["active_assignment_count"] == 1

    validate_success(
        api.recall_coverage_assignment(
            ctx["assignment"]["id"], {"reason": "Conflict of interest."}, EDITOR_ASSIGN
        )
    )

    reader = fetch_reader(ctx["reader"]["id"])
    assert reader["active_assignment_count"] == 0, "the capacity counter is conserved"
    assert reader["completed_report_count"] == 0, "a recall is not a completion"
    assert reader["calibration_bias"] == 0.00
    assert fetch_submission(ctx["submission"]["id"])["decision"] == "PENDING"
