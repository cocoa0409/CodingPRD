"""Award application drafting and submission: creation-time checklist pinning,
initial states, window/posture gating, duplicate live submissions, ownership,
pagination, and list filtering (PRD §3.4, §2.3, §2.7, §2.11).
"""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    PLATFORM_ADMIN,
    apply_for_reviewer,
    assert_report_submission,
    create_checklist,
    create_cycle,
    create_draft_submission,
    create_government,
    create_member,
    create_standard,
    activate_standard,
    make_government_contact_headers,
    refresh_cycle,
    refresh_submission,
    report_submission_payload,
    set_logical_clock,
    standards_reference_payload,
    setup_submitted_submission,
    submit_submission,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_submission_create_pins_checklist_and_copies_program(api):
    """PRD §3.4: "At creation the system copies the cycle's `program_type` onto
    the submission and pins `pinned_checklist_version_id` from the cycle's
    `checklist_version_id`, freezing the criteria this application will be
    judged against even if the checklist is later superseded."
    PRD §3.4: "The draft begins with `appeal_round` set to 1, `award_conferred`
    false, `pinned_checklist_stale` false, and the score fields
    `provisional_score`, `final_score`, and the timestamps `submitted_at`,
    `decided_at`, and `conferred_at` all null, with `major_deficiency_total`
    at zero and `required_improvements` empty."

    Design: Corner/entities/submission_create_pins_checklist_and_copies_program
    """
    set_logical_clock(api)
    checklist = create_checklist(api)
    cycle = create_cycle(api, checklist["id"])
    government = create_government(api)

    resp = api.create_report_submission(
        report_submission_payload(government["id"], cycle["id"]),
        headers=make_government_contact_headers(government["id"]),
    )
    data = validate_success(resp, 201)
    assert_report_submission(data)
    assert data["pinned_checklist_version_id"] == checklist["id"]
    assert data["program_type"] == "FINANCIAL_REPORTING"
    assert data["status"] == "DRAFT"
    assert data["appeal_round"] == 1
    assert data["pinned_checklist_stale"] is False
    assert data["award_conferred"] is False


def test_submission_get_not_found_returns_404(api):
    """PRD §2.7: "Every unresolvable reference reports the error paired with
    its resource kind: `ERR_GOVERNMENT_NOT_FOUND` for a government,
    `ERR_MEMBER_NOT_FOUND` for a member, `ERR_REVIEWER_NOT_FOUND` for a
    reviewer profile, `ERR_CYCLE_NOT_FOUND` for an award cycle,
    `ERR_CHECKLIST_NOT_FOUND` for a checklist version, `ERR_STANDARD_NOT_FOUND`
    for a standards reference, `ERR_SUBMISSION_NOT_FOUND` for a report
    submission, `ERR_ASSIGNMENT_NOT_FOUND` for a review assignment,
    `ERR_PUBLICATION_NOT_FOUND` for a publication, `ERR_COMMENT_NOT_FOUND` for
    a member comment, `ERR_FUND_NOT_FOUND` for a scholarship fund, and
    `ERR_APPLICATION_NOT_FOUND` for a scholarship application."

    Design: Corner/entities/submission_get_not_found_returns_404
    """
    set_logical_clock(api)

    resp = api.get_report_submission(NON_EXISTENT_UUID, headers=PLATFORM_ADMIN)
    validate_error(resp, ApiErrorId.ERR_SUBMISSION_NOT_FOUND, 404)


def test_report_submissions_list_paginates(api):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items
    returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The
    `offset` parameter sets the number of items skipped and defaults to 0."
    PRD §2.3: "The `meta` object of every list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/report_submissions_list_paginates
    """
    set_logical_clock(api)
    checklist = create_checklist(api)
    cycle = create_cycle(api, checklist["id"])
    for _ in range(3):
        government = create_government(api)
        create_draft_submission(api, government["id"], cycle["id"])

    page1, meta1 = validate_paginated(
        api.list_report_submissions(
            headers=PLATFORM_ADMIN,
            params={"cycle_id": cycle["id"], "limit": 2, "offset": 0},
        )
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_report_submissions(
            headers=PLATFORM_ADMIN,
            params={"cycle_id": cycle["id"], "limit": 2, "offset": 2},
        )
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    all_rows, meta3 = validate_paginated(
        api.list_report_submissions(
            headers=PLATFORM_ADMIN, params={"cycle_id": cycle["id"]}
        )
    )
    assert len(all_rows) == 3
    assert meta3["limit"] == 10 and meta3["offset"] == 0


def test_submissions_list_filters_by_status_and_government(api):
    """PRD §2.11: "List scoping also applies to governments: a
    `GovernmentContact` listing report submissions or scholarship applications
    sees only rows belonging to their own government, while privileged roles
    see the full collections."
    PRD §4 (endpoint table, GET /gfoa/report-submissions): "List submissions;
    filterable by `government_id`, `cycle_id`, `pinned_checklist_version_id`,
    `status`; GovernmentContact sees only own rows"

    Design: Corner/endpoints/submissions_list_filters_by_status_and_government
    """
    bundle = setup_submitted_submission(api)
    cycle_id = bundle["cycle"]["id"]
    submitted_id = bundle["submission"]["id"]

    other_gov = create_government(api)
    other_draft = create_draft_submission(api, other_gov["id"], cycle_id)

    drafts, meta_drafts = validate_paginated(
        api.list_report_submissions(
            headers=PLATFORM_ADMIN,
            params={"cycle_id": cycle_id, "status": "DRAFT"},
        )
    )
    assert meta_drafts["total_count"] == 1
    assert [row["id"] for row in drafts] == [other_draft["id"]]

    everything, meta_all = validate_paginated(
        api.list_report_submissions(
            headers=PLATFORM_ADMIN, params={"cycle_id": cycle_id}
        )
    )
    assert meta_all["total_count"] == 2
    assert {row["id"] for row in everything} == {submitted_id, other_draft["id"]}

    own_rows, meta_own = validate_paginated(
        api.list_report_submissions(
            headers=make_government_contact_headers(other_gov["id"])
        )
    )
    assert meta_own["total_count"] == 1
    assert [row["id"] for row in own_rows] == [other_draft["id"]]


def test_submission_starts_draft_and_reviewer_applicant(api):
    """PRD §3.4: "The draft begins with `appeal_round` set to 1,
    `award_conferred` false, `pinned_checklist_stale` false, and the score
    fields `provisional_score`, `final_score`, and the timestamps
    `submitted_at`, `decided_at`, and `conferred_at` all null, with
    `major_deficiency_total` at zero and `required_improvements` empty."
    PRD §3.3: "The new profile starts as `APPLICANT`, its three counters
    `open_assignment_count`, `completed_review_count`, and
    `declined_assignment_count` start at zero, and `trained_at` stays null."
    PRD §3.7: "the record begins `ISSUED`."

    Design: Corner/state_machines/submission_starts_draft_and_reviewer_applicant
    """
    set_logical_clock(api)
    checklist = create_checklist(api)
    cycle = create_cycle(api, checklist["id"])
    government = create_government(api)
    member = create_member(api)
    employer = create_government(api)

    submission = create_draft_submission(api, government["id"], cycle["id"])
    profile = apply_for_reviewer(api, member["id"], employer["id"])
    standard = validate_success(
        api.create_standards_reference(
            standards_reference_payload(),
            headers=PLATFORM_ADMIN,
        ),
        201,
    )

    assert submission["status"] == "DRAFT"
    assert profile["status"] == "APPLICANT"
    assert standard["status"] == "ISSUED"


def test_submit_twice_returns_state_invalid(api):
    """PRD §3.4: "The submission must be in `DRAFT`, else
    `ERR_SUBMISSION_STATE_INVALID`."
    PRD §3.4: "A successful submit stamps `submitted_at` with the logical
    clock, moves the submission from `DRAFT` to `SUBMITTED`, advances the
    cycle's `submitted_count` by one, and increments the `version` of both the
    submission and the cycle."

    Design: Corner/state_machines/submit_twice_returns_state_invalid
    """
    bundle = setup_submitted_submission(api)
    submission = bundle["submission"]
    government = bundle["government"]

    second = api.submit_report_submission(
        submission["id"],
        headers=make_government_contact_headers(government["id"]),
    )
    validate_error(second, ApiErrorId.ERR_SUBMISSION_STATE_INVALID)

    cycle = refresh_cycle(api, bundle["cycle"]["id"])
    assert cycle["submitted_count"] == 1, "the failed submit must not double-count"


def test_duplicate_open_submission_rejected(api):
    """PRD §3.4: "A government may hold only one live application per cycle:
    creation is rejected with `ERR_DUPLICATE_SUBMISSION` when a submission
    already exists for the same government and cycle in `DRAFT`, `SUBMITTED`,
    `UNDER_REVIEW`, `DECISION_READY`, or `APPEALED`; an earlier application
    that reached `DECIDED_AWARDED` or `DECIDED_DENIED` does not block a fresh
    draft."

    Design: Corner/validations/duplicate_open_submission_rejected
    """
    set_logical_clock(api)
    checklist = create_checklist(api)
    cycle = create_cycle(api, checklist["id"])
    government = create_government(api)
    create_draft_submission(api, government["id"], cycle["id"])

    duplicate = api.create_report_submission(
        report_submission_payload(government["id"], cycle["id"]),
        headers=make_government_contact_headers(government["id"]),
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_SUBMISSION)

    rows, meta = validate_paginated(
        api.list_report_submissions(
            headers=PLATFORM_ADMIN, params={"government_id": government["id"]}
        )
    )
    assert meta["total_count"] == 1 and len(rows) == 1


def test_government_contact_cannot_submit_others_submission(api):
    """PRD §2.1: "Any attempt to act on a resource owned by someone else —
    another government's submission, another reviewer's assignment or profile,
    a publication whose committee the caller does not sit on — is rejected
    with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/validations/government_contact_cannot_submit_others_submission
    """
    set_logical_clock(api)
    checklist = create_checklist(api)
    cycle = create_cycle(api, checklist["id"])
    owner = create_government(api)
    stranger = create_government(api)
    submission = create_draft_submission(api, owner["id"], cycle["id"])

    resp = api.submit_report_submission(
        submission["id"],
        headers=make_government_contact_headers(stranger["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    assert refresh_submission(api, submission["id"])["status"] == "DRAFT"


def test_submit_gated_by_cycle_posture(api):
    """PRD §3.4: "The cycle's `posture` must be `OPEN`, meaning the logical
    clock is at or after `submission_opens_at` and before
    `submission_deadline_at`; submitting at any other posture is rejected with
    `ERR_SUBMISSION_WINDOW_CLOSED`."
    PRD §2.4: "at or after `submission_deadline_at` and before
    `review_close_at` it is `IN_REVIEW`"

    Design: Difficulty/cross_entity_state_dependency/submit_gated_by_cycle_posture
    """
    set_logical_clock(api, "2026-09-15T00:00:00Z")
    checklist = create_checklist(api)
    cycle = create_cycle(api, checklist["id"])  # window [09-01, 10-15)

    # Positive control: a draft submitted while the posture is OPEN succeeds.
    early_gov = create_government(api)
    early_draft = create_draft_submission(api, early_gov["id"], cycle["id"])
    assert (
        submit_submission(api, early_draft["id"], early_gov["id"])["status"]
        == "SUBMITTED"
    )

    held_gov = create_government(api)
    held_draft = create_draft_submission(api, held_gov["id"], cycle["id"])

    # No write to the cycle in between — only the logical clock advances.
    set_logical_clock(api, "2026-10-16T00:00:00Z")
    assert refresh_cycle(api, cycle["id"])["posture"] == "IN_REVIEW"

    resp = api.submit_report_submission(
        held_draft["id"],
        headers=make_government_contact_headers(held_gov["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SUBMISSION_WINDOW_CLOSED)
    assert refresh_submission(api, held_draft["id"])["status"] == "DRAFT"


def test_submit_referential_error_beats_temporal_error(api):
    """PRD §2.6: "A single request can fail several rules at once, so the
    system evaluates checks in a fixed order and reports the first failure
    encountered."  Referential and pin integrity (rule 8: "pinned checklists
    and standards must be current") precedes temporal gates (rule 9:
    "submissions only while a cycle is `OPEN`").
    PRD §3.4: "Its pinned checklist must still be trustworthy —
    `pinned_checklist_stale` must be false, else `ERR_CHECKLIST_PIN_STALE`
    (§3.7 describes how the flag is set)."
    PRD §3.7: "every report submission still in `DRAFT` that pinned that
    checklist has its `pinned_checklist_stale` set to true, which bars it from
    submitting until a fresh cycle and checklist apply."

    Design: Difficulty/priority_pair_validation_conflict/submit_referential_error_beats_temporal_error
    """
    set_logical_clock(api, "2026-09-15T00:00:00Z")
    checklist = create_checklist(api)
    cycle = create_cycle(api, checklist["id"])
    government = create_government(api)
    submission = create_draft_submission(api, government["id"], cycle["id"])

    standard = create_standard(api, effective_date="2026-09-10T00:00:00Z")
    activate_standard(api, standard["id"])

    stale = refresh_submission(api, submission["id"])
    assert stale["pinned_checklist_stale"] is True

    # Past the deadline the posture gate also fails — but the referential
    # error is reported first.
    set_logical_clock(api, "2026-10-16T00:00:00Z")
    assert refresh_cycle(api, cycle["id"])["posture"] == "IN_REVIEW"

    resp = api.submit_report_submission(
        submission["id"],
        headers=make_government_contact_headers(government["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CHECKLIST_PIN_STALE)
    assert refresh_submission(api, submission["id"])["status"] == "DRAFT"
