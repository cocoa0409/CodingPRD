"""Screening, second-opinion review, and episode state-machine behavior."""
from test_helpers import (
    ApiErrorId,
    assert_screening,
    get_episode,
    get_success_data,
    make_active_contract,
    make_employer,
    make_patient,
    make_template,
    open_episode,
    setup_approved_episode,
    setup_episode_in_sor_pending,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_review_on_pre_screening_episode_returns_invalid_state(
    api, physician_reviewer_headers, program_admin_headers
):
    """PRD §2.10: "Current-state legality of the transition or action
    (`ERR_INVALID_STATE`, HTTP 409) — for example a screening submitted on an
    already-approved episode, a review on an episode still in `SCREENING`, or
    adjudication of a claim already `PAID`."
    PRD §3.4: "Once awaiting review, a `PhysicianReviewer` records a
    second-opinion `conclusion`"

    Design: Corner/state_machines/review_on_pre_screening_episode_returns_invalid_state
    """
    employer = make_employer({"ORTHO_JOINT": 2500000})
    template = make_template()
    contract = make_active_contract(employer, template)
    patient = make_patient(employer)
    episode = open_episode(patient, contract)

    resp = api.record_review(
        episode["id"],
        {
            "conclusion": "SURGERY_INDICATED",
            "expected_episode_version": episode["version"],
        },
        physician_reviewer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = get_episode(episode["id"])
    assert after["status"] == "INTAKE_PENDING", "failed review must not mutate state"

    reviews, _ = validate_paginated(
        api.list_reviews(episode["id"], program_admin_headers)
    )
    assert reviews == [], "no review row may be created by a rejected review"


def test_sor_more_info_cycles_back_into_review(api, physician_reviewer_headers):
    """PRD §3.4: "from `SOR_PENDING` it moves the episode to `SOR_REVIEW`, and
    from `SOR_REVIEW` it keeps it there, each time incrementing `screen_seq`
    and stamping the review."
    PRD §3.4: "The review record captures the acting reviewer's id in
    `reviewer_id` and snapshots the episode's status before the review in
    `prev_status` (`SOR_PENDING` or `SOR_REVIEW`)"

    Design: Difficulty/non_linear_state_machine/sor_more_info_cycles_back_into_review
    """
    ctx = setup_episode_in_sor_pending()
    episode = ctx["episode"]

    r1 = validate_success(
        api.record_review(
            episode["id"],
            {"conclusion": "MORE_INFO_NEEDED",
             "expected_episode_version": episode["version"]},
            physician_reviewer_headers,
        ),
        expected_status=201,
    )
    assert r1["prev_status"] == "SOR_PENDING"
    assert r1["reviewer_id"] == "test-physician-reviewer-1"
    mid = get_episode(episode["id"])
    assert mid["status"] == "SOR_REVIEW"
    assert mid["screen_seq"] == episode["screen_seq"] + 1, (
        "each review consumes exactly one sequence step"
    )

    r2 = validate_success(
        api.record_review(
            episode["id"],
            {"conclusion": "MORE_INFO_NEEDED",
             "expected_episode_version": mid["version"]},
            physician_reviewer_headers,
        ),
        expected_status=201,
    )
    assert r2["prev_status"] == "SOR_REVIEW", "second review loops from SOR_REVIEW"
    loop = get_episode(episode["id"])
    assert loop["status"] == "SOR_REVIEW"
    assert loop["screen_seq"] == mid["screen_seq"] + 1


def test_sor_review_loop_resolves_to_approved(api, physician_reviewer_headers):
    """PRD §3.4: "Both `SOR_PENDING → SOR_REVIEW` and the deeper `SOR_REVIEW`
    loop may later resolve identically."
    PRD §3.4: "A conclusion of `SURGERY_INDICATED` — again from either
    `SOR_PENDING` or `SOR_REVIEW` — is the approval gate"

    Design: Difficulty/non_linear_state_machine/sor_more_info_cycles_back_into_review
    """
    ctx = setup_episode_in_sor_pending()
    episode = ctx["episode"]

    r1 = validate_success(
        api.record_review(
            episode["id"],
            {"conclusion": "MORE_INFO_NEEDED",
             "expected_episode_version": episode["version"]},
            physician_reviewer_headers,
        ),
        expected_status=201,
    )
    assert r1["conclusion"] == "MORE_INFO_NEEDED"
    mid = get_episode(episode["id"])

    validate_success(
        api.record_review(
            episode["id"],
            {"conclusion": "SURGERY_INDICATED",
             "expected_episode_version": mid["version"]},
            physician_reviewer_headers,
        ),
        expected_status=201,
    )
    final = get_episode(episode["id"])
    assert final["status"] == "APPROVED", (
        "SOR_REVIEW resolves to APPROVED on SURGERY_INDICATED"
    )
    assert final["screen_seq"] == episode["screen_seq"] + 2


def test_screening_record_is_immutable_no_update_endpoint(
    api, care_coordinator_headers, physician_reviewer_headers
):
    """PRD §2.4: "A `Screening` and a `SecondOpinionReview` are append-only log
    entries: each carries only `id` and `created_at` from the common set, and
    both `updated_at` and `version` are absent. They are immutable once
    created, and no update endpoint exists for them."
    PRD §3.4: "a `NOT_A_CANDIDATE` result moves it `SCREENING → CANCELLED`
    immediately, likewise incrementing `screen_seq`."

    Design: Corner/entities/screening_record_is_immutable_no_update_endpoint
    """
    employer = make_employer({"ORTHO_JOINT": 2500000})
    template = make_template()
    contract = make_active_contract(employer, template)
    patient = make_patient(employer)
    episode = open_episode(patient, contract)

    screening = validate_success(
        api.submit_screening(
            episode["id"], {"doc_type": "LAB", "result": "NOT_A_CANDIDATE"},
            care_coordinator_headers,
        ),
        expected_status=201,
    )
    assert_screening(screening)
    assert screening["doc_type"] == "LAB"
    assert screening["result"] == "NOT_A_CANDIDATE"

    rows, meta = validate_paginated(
        api.list_screenings(episode["id"], physician_reviewer_headers)
    )
    assert len(rows) == 1 and meta["total_count"] == 1
    assert_screening(rows[0])
    assert rows[0]["id"] == screening["id"]

    after = get_episode(episode["id"])
    assert after["status"] == "CANCELLED", (
        "NOT_A_CANDIDATE auto-transitions the episode to CANCELLED"
    )


def test_care_item_waive_then_complete_returns_invalid_state(
    api, care_coordinator_headers
):
    """PRD §3.5: "A coordinator later marks an item `DONE` or waives it to
    `WAIVED`; both actions require the item to still be `OPEN`."
    PRD §2.10: "Current-state legality of the transition or action
    (`ERR_INVALID_STATE`, HTTP 409)"

    Design: Corner/state_machines/care_item_waive_then_complete_returns_invalid_state
    """
    from test_helpers import add_care_item

    ctx = setup_approved_episode()
    episode = ctx["episode"]
    # APPROVED -> SCHEDULING -> PRE_OP via the shared fixture path.
    from test_helpers import drive_episode_to_pre_op

    episode = drive_episode_to_pre_op(episode)
    item = add_care_item(episode, phase="PRE_OP", required=False)

    waived = validate_success(
        api.waive_care_item(item["id"], care_coordinator_headers)
    )
    assert waived["status"] == "WAIVED"

    resp = api.complete_care_item(item["id"], care_coordinator_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    still = get_success_data(
        api.get_care_item(item["id"], care_coordinator_headers)
    )
    assert still["status"] == "WAIVED", "a WAIVED item accepts no further transition"


def test_schedule_reschedule_changes_day_and_bumps_version(
    api, care_coordinator_headers
):
    """PRD §3.5: "The same action on a `SCHEDULING` episode reschedules it to a
    new `requested_day_seq` under the same future-day and priority rules."
    PRD §3.5: "A successful schedule moves the episode `APPROVED → SCHEDULING`,
    records `requested_day_seq` into `scheduled_start_seq`, increments
    `screen_seq`, and bumps `version`."
    PRD §2.4: "`version`, an integer that increments on every mutation of the
    resource."

    Design: Corner/state_machines/schedule_reschedule_changes_day_and_bumps_version
    """
    from test_helpers import schedule_episode

    ctx = setup_approved_episode()
    approved = ctx["episode"]

    scheduled = schedule_episode(approved)
    assert scheduled["status"] == "SCHEDULING"
    assert scheduled["scheduled_start_seq"] > approved["screen_seq"]
    assert scheduled["version"] == approved["version"] + 1
    assert scheduled["screen_seq"] == approved["screen_seq"] + 1

    # Reschedule to an even later day (still strictly in the future).
    resp = api.schedule_episode(
        scheduled["id"],
        {
            "requested_day_seq": scheduled["scheduled_start_seq"] + 5,
            "expected_episode_version": scheduled["version"],
        },
        care_coordinator_headers,
    )
    rescheduled = validate_success(resp)
    assert rescheduled["status"] == "SCHEDULING", "reschedule is a self-transition"
    assert rescheduled["scheduled_start_seq"] == scheduled["scheduled_start_seq"] + 5
    assert rescheduled["version"] == scheduled["version"] + 1
    assert rescheduled["screen_seq"] == scheduled["screen_seq"] + 1
