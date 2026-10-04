"""Blind reviewer selection: eligibility filter, empty-pool fallback, capacity
quorum, alias sequencing, identity masking, eligibility gating on accept, and
the reviewer counter conservation identity (PRD §3.5, §3.3, §2.11).
"""

from test_helpers import (
    ApiErrorId,
    AWARDS_DIRECTOR,
    accept_assignment,
    apply_for_reviewer,
    assert_review_assignment,
    assert_reviewer_alias,
    assert_reviewer_count_invariant,
    attest_independence,
    create_assignment,
    create_draft_submission,
    create_eligible_reviewer,
    create_eligible_reviewers,
    create_government,
    create_member,
    decline_assignment,
    make_government_contact_headers,
    make_reviewer_headers,
    refresh_reviewer,
    refresh_submission,
    reinstate_reviewer,
    review_assignment_payload,
    set_logical_clock,
    setup_submission_with_review_round,
    setup_submitted_submission,
    submit_submission,
    suspend_reviewer,
    train_reviewer,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_no_eligible_reviewer_empty_pool(api):
    """PRD §3.5: "The candidate must be `ELIGIBLE`; the candidate's
    `employer_government_id` must differ from the submitting government's
    `id`; the submitting government must not appear in the candidate's
    `conflicted_government_ids`; the candidate's `open_assignment_count` must
    be below five; and the candidate must hold no assignment for this
    submission in any appeal round whatsoever — prior `OFFERED`, `ACCEPTED`,
    `DECLINED`, `SUBMITTED`, and `CANCELLED` assignments all exclude, so a
    reviewer who declined or was cancelled out of an earlier round is never
    re-offered this submission."
    PRD §3.5: "If no reviewer survives the filter, the request is rejected
    with `ERR_NO_ELIGIBLE_REVIEWER`."

    Design: Corner/errors/no_eligible_reviewer_empty_pool
    """
    bundle = setup_submitted_submission(api)
    government = bundle["government"]
    submission = bundle["submission"]

    member = create_member(api)
    insider = apply_for_reviewer(api, member["id"], government["id"])
    train_reviewer(api, insider["id"])
    attest_independence(api, insider["id"])

    resp = api.create_review_assignment(
        review_assignment_payload(submission["id"]), headers=AWARDS_DIRECTOR
    )
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_REVIEWER)

    assert refresh_reviewer(api, insider["id"])["open_assignment_count"] == 0
    assert refresh_submission(api, submission["id"])["status"] == "SUBMITTED", (
        "the submission must not flip to UNDER_REVIEW without an assignment"
    )


def test_conflicted_government_attestation_excludes_reviewer(api):
    """PRD §3.5: "The candidate must be `ELIGIBLE`; the candidate's
    `employer_government_id` must differ from the submitting government's
    `id`; the submitting government must not appear in the candidate's
    `conflicted_government_ids`; the candidate's `open_assignment_count` must
    be below five; and the candidate must hold no assignment for this
    submission in any appeal round whatsoever — prior `OFFERED`, `ACCEPTED`,
    `DECLINED`, `SUBMITTED`, and `CANCELLED` assignments all exclude, so a
    reviewer who declined or was cancelled out of an earlier round is never
    re-offered this submission."
    With the conflicted reviewer filtered out, exactly one candidate survives,
    and PRD §3.5 selects "the first row of that ranking".

    Design: Corner/errors/conflicted_government_attestation_excludes_reviewer
    """
    bundle = setup_submitted_submission(api)
    government = bundle["government"]
    submission = bundle["submission"]

    member_1 = create_member(api)
    employer_1 = create_government(api)
    conflicted = apply_for_reviewer(api, member_1["id"], employer_1["id"])
    train_reviewer(api, conflicted["id"])
    attest_independence(
        api, conflicted["id"], conflicted_government_ids=[government["id"]]
    )
    clean = create_eligible_reviewer(api)

    assignment = create_assignment(api, submission["id"])
    assert assignment["reviewer_id"] == clean["id"], (
        "the conflict-attested reviewer is excluded despite earlier training"
    )
    assert refresh_reviewer(api, conflicted["id"])["open_assignment_count"] == 0
    assert refresh_reviewer(api, clean["id"])["open_assignment_count"] == 1


def test_blind_assignment_selector_ranking_order(api):
    """PRD §3.5: "Survivors are ranked by `open_assignment_count` ascending,
    then `completed_review_count` descending, then `trained_at` ascending, and
    finally `created_at` ascending as the last tie-break, and the first row of
    that ranking is selected."
    PRD §3.5: "The blind `reviewer_alias` is formed from the letter R, the
    current appeal round, and a sequence number, as in `R1-3` for the third
    assignment created for that submission in round one; the sequence counts
    every assignment ever created for the submission in that round plus one
    and is never reused, even by declined or cancelled assignments."

    Design: Corner/cross_cutting_layers/blind_assignment_selector_ranking_order
    """
    bundle = setup_submitted_submission(api)
    cycle = bundle["cycle"]
    submission_a = bundle["submission"]

    other_gov = create_government(api)
    submission_b = create_draft_submission(api, other_gov["id"], cycle["id"])
    submit_submission(api, submission_b["id"], other_gov["id"])

    reviewers = create_eligible_reviewers(api, count=2)

    # Whoever the first assignment lands on holds one open assignment; the
    # primary ranking key (open count ascending) then forces the next
    # assignment — on the other submission — to the reviewer holding none.
    first_on_a = create_assignment(api, submission_a["id"])
    busy_id = first_on_a["reviewer_id"]
    free = [r for r in reviewers if r["id"] != busy_id]
    assert len(free) == 1

    first_on_b = create_assignment(api, submission_b["id"])
    assert first_on_b["reviewer_id"] == free[0]["id"], (
        "open_assignment_count 0 must outrank 1 regardless of training order"
    )
    assert_reviewer_alias(first_on_b["reviewer_alias"], appeal_round=1, seq=1)

    second_on_b = create_assignment(api, submission_b["id"])
    assert_reviewer_alias(second_on_b["reviewer_alias"], appeal_round=1, seq=2)


def test_quorum_full_fourth_assignment_rejected(api):
    """PRD §3.5: "the current appeal round must still have seats open: a round
    holds at most three active assignments, where active means `OFFERED`,
    `ACCEPTED`, or `SUBMITTED`, and an attempt to seat a fourth is rejected
    with `ERR_REVIEW_QUORUM_FULL`."

    Design: Corner/state_machines/quorum_full_fourth_assignment_rejected
    """
    bundle = setup_submitted_submission(api)
    submission = bundle["submission"]
    reviewers = create_eligible_reviewers(api, count=4)

    assignments = [create_assignment(api, submission["id"]) for _ in range(3)]
    for seq, assignment in enumerate(assignments, start=1):
        assert assignment["status"] == "OFFERED"
        assert_reviewer_alias(assignment["reviewer_alias"], appeal_round=1, seq=seq)

    fourth = api.create_review_assignment(
        review_assignment_payload(submission["id"]), headers=AWARDS_DIRECTOR
    )
    validate_error(fourth, ApiErrorId.ERR_REVIEW_QUORUM_FULL)

    assigned_ids = {a["reviewer_id"] for a in assignments}
    assert len(assigned_ids) == 3
    never_offered = [r for r in reviewers if r["id"] not in assigned_ids]
    assert len(never_offered) == 1
    assert (
        refresh_reviewer(api, never_offered[0]["id"])["open_assignment_count"] == 0
    )


def test_government_contact_cannot_assign_forbidden(api):
    """PRD §2.1: "Each operation declares the roles authorized to call it (§4);
    a caller whose role is not on that operation's list is rejected with
    `ERR_FORBIDDEN_ROLE`."
    PRD §4 (endpoint table, POST /gfoa/review-assignments): "Blind-assign the
    next eligible reviewer to a submission" — authorized role: `AwardsDirector`
    only.

    Design: Corner/rbac/government_contact_cannot_assign_forbidden
    """
    bundle = setup_submitted_submission(api)

    resp = api.create_review_assignment(
        review_assignment_payload(bundle["submission"]["id"]),
        headers=make_government_contact_headers(bundle["government"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_reviewer_cannot_accept_others_assignment(api):
    """PRD §3.5: "Accepting requires the caller's identity to equal the
    assignment's `reviewer_id` (else `ERR_NOT_RESOURCE_OWNER`), the assignment
    to be `OFFERED` (else `ERR_ASSIGNMENT_STATE_INVALID`), and the reviewer's
    profile to be `ELIGIBLE` at that moment (else
    `ERR_REVIEWER_NOT_ELIGIBLE`); acceptance moves the assignment to
    `ACCEPTED`."

    Design: Corner/rbac/reviewer_cannot_accept_others_assignment
    """
    bundle = setup_submission_with_review_round(api, num_reviewers=2, accept=False)
    assignment = bundle["assignments"][0]
    owner_id = assignment["reviewer_id"]
    others = [r for r in bundle["reviewers"] if r["id"] != owner_id]
    assert len(others) == 1

    resp = api.accept_review_assignment(
        assignment["id"], headers=make_reviewer_headers(others[0]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

    stayed = validate_success(
        api.get_review_assignment(assignment["id"], headers=AWARDS_DIRECTOR)
    )
    assert stayed["status"] == "OFFERED"


def test_assignment_read_masks_reviewer_for_government(api):
    """PRD §2.11: "When a `GovernmentContact` reads a review assignment —
    singly or in a list — the assignment's `reviewer_id` is masked to null and
    only the blind `reviewer_alias` is visible; `PlatformAdmin`,
    `AwardsDirector`, and `Reviewer` callers see the true value."

    Design: Corner/endpoints/assignment_read_masks_reviewer_for_government
    """
    bundle = setup_submission_with_review_round(api, num_reviewers=1, accept=False)
    assignment = bundle["assignments"][0]

    masked = validate_success(
        api.get_review_assignment(
            assignment["id"],
            headers=make_government_contact_headers(bundle["government"]["id"]),
        )
    )
    assert_review_assignment(masked, expect_masked=True)
    assert masked["reviewer_alias"] == "R1-1"

    privileged = validate_success(
        api.get_review_assignment(assignment["id"], headers=AWARDS_DIRECTOR)
    )
    assert_review_assignment(privileged, expect_masked=False)
    assert privileged["reviewer_id"] == bundle["reviewers"][0]["id"]


def test_assignment_accept_gated_by_reviewer_eligibility(api):
    """PRD §3.3: "Suspension never cancels the reviewer's open assignments —
    they remain on the books — but nothing can move on them while the reviewer
    is suspended, because both accepting an assignment and filing a finding
    require the reviewer to be `ELIGIBLE` at that moment (§3.5)."
    PRD §3.3: "A `PlatformAdmin` may suspend an `ELIGIBLE` reviewer, moving the
    profile to `SUSPENDED`; reinstate a `SUSPENDED` reviewer back to
    `ELIGIBLE`"

    Design: Difficulty/cross_entity_state_dependency/assignment_accept_gated_by_reviewer_eligibility
    """
    bundle = setup_submission_with_review_round(api, num_reviewers=1, accept=False)
    reviewer = bundle["reviewers"][0]
    assignment = bundle["assignments"][0]

    suspend_reviewer(api, reviewer["id"])

    blocked = api.accept_review_assignment(
        assignment["id"], headers=make_reviewer_headers(reviewer["id"])
    )
    validate_error(blocked, ApiErrorId.ERR_REVIEWER_NOT_ELIGIBLE)
    stayed = validate_success(
        api.get_review_assignment(assignment["id"], headers=AWARDS_DIRECTOR)
    )
    assert stayed["status"] == "OFFERED"

    reinstate_reviewer(api, reviewer["id"])
    accepted = accept_assignment(api, assignment)
    assert accepted["status"] == "ACCEPTED"

    profile = refresh_reviewer(api, reviewer["id"])
    assert profile["open_assignment_count"] == 1, (
        "the suspension episode must not touch the offer bookkeeping"
    )


def test_reviewer_counters_conserve_assignment_totals(api):
    """PRD §3.5: "Declining requires the same ownership and the same `OFFERED`
    state, moves the assignment to `DECLINED`, decrements the reviewer's
    `open_assignment_count`, increments their `declined_assignment_count`, and
    bumps the `version` of both records."
    PRD §3.5: "the candidate must hold no assignment for this submission in
    any appeal round whatsoever — prior `OFFERED`, `ACCEPTED`, `DECLINED`,
    `SUBMITTED`, and `CANCELLED` assignments all exclude, so a reviewer who
    declined or was cancelled out of an earlier round is never re-offered this
    submission."

    Design: Difficulty/compensating_invariant/reviewer_counters_conserve_assignment_totals
    """
    bundle = setup_submitted_submission(api)
    cycle = bundle["cycle"]
    submission_one = bundle["submission"]

    other_gov = create_government(api)
    submission_two = create_draft_submission(api, other_gov["id"], cycle["id"])
    submit_submission(api, submission_two["id"], other_gov["id"])

    reviewer = create_eligible_reviewer(api)

    offered = create_assignment(api, submission_one["id"])
    assert offered["reviewer_id"] == reviewer["id"]
    decline_assignment(api, offered)
    after_decline = refresh_reviewer(api, reviewer["id"])
    assert after_decline["open_assignment_count"] == 0
    assert after_decline["declined_assignment_count"] == 1

    # Decline excludes the reviewer from submission one only — the second
    # submission's blind assignment selects the same (sole) reviewer again.
    reselected = create_assignment(api, submission_two["id"])
    assert reselected["reviewer_id"] == reviewer["id"]
    assert_reviewer_alias(reselected["reviewer_alias"], appeal_round=1, seq=1)

    profile = refresh_reviewer(api, reviewer["id"])
    assert profile["open_assignment_count"] == 1
    assert profile["completed_review_count"] == 0
    assert profile["declined_assignment_count"] == 1

    rows, meta = validate_paginated(
        api.list_review_assignments(
            headers=AWARDS_DIRECTOR, params={"reviewer_id": reviewer["id"]}
        )
    )
    non_cancelled = [row for row in rows if row["status"] != "CANCELLED"]
    assert len(non_cancelled) == 2
    assert_reviewer_count_invariant(profile, len(non_cancelled))
