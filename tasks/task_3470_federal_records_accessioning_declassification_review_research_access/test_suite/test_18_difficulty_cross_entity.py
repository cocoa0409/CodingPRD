"""Difficulty coverage (queue A): cross-entity state dependencies — pull
creation gated by the collection's posture and processing state, and review
completion gated by the child referrals' states."""

import test_helpers as th

E = th.ApiErrorId


def test_pull_create_gated_by_collection_state(api):
    """PRD §3.7: "After existence, ownership, and the active-researcher rung
    (`ERR_RESEARCHER_NOT_ACTIVE`), the collection must be open: its posture
    must be `PUBLIC` (`ERR_COLLECTION_RESTRICTED`, 403). The `visit_date` must
    then fall within the booking window — on or after the clock's current
    instant and no later than 30 days out (`ERR_VISIT_DATE_OUT_OF_WINDOW`,
    409). The collection must be described: `processing_status` must be
    `DESCRIBED` or `PUBLISHED` (`ERR_COLLECTION_NOT_DESCRIBED`, 409)."

    Design: Difficulty/cross_entity_state_dependency/pull_create_gated_by_collection_state
    """
    th.set_clock()
    agency = th.create_agency()
    # C1: DESCRIBED but still classified -> posture CLASSIFIED_REVIEW_REQUIRED.
    classified = th.setup_classified_collection(
        agency=agency, classification_default="SECRET", described=True,
        schedule_kwargs={"schedule_number": "SCH-DOJ-001"},
    )
    # C3: PUBLIC (no restrictions, no classification) but UNPROCESSED.
    presidential = th.setup_presidential_collection(
        agency=agency, schedule_kwargs={"schedule_number": "SCH-DOJ-003"}
    )
    ada = th.create_active_researcher()
    researcher = th.make_researcher_headers(ada["id"])

    resp = api.create_pull_request(
        th.pull_request_payload(ada["id"], classified["collection"]["id"],
                                1, 5, "2026-09-10T00:00:00Z"),
        headers=researcher,
    )
    assert resp.status_code == 403
    th.validate_error(resp, E.ERR_COLLECTION_RESTRICTED)

    resp = api.create_pull_request(
        th.pull_request_payload(ada["id"], presidential["collection"]["id"],
                                1, 5, "2026-09-10T00:00:00Z"),
        headers=researcher,
    )
    assert resp.status_code == 409
    th.validate_error(resp, E.ERR_COLLECTION_NOT_DESCRIBED)

    # Neither rejection persisted a pull.
    data, meta = th.validate_paginated(
        api.list_pull_requests(
            headers=th.TEST_USERS["research_room_staff_headers"],
            params={"researcher_id": ada["id"]},
        )
    )
    assert data == []
    assert meta["total_count"] == 0


def test_pull_create_processing_and_published_states(api):
    """PRD §3.7: "The collection must be described: `processing_status` must
    be `DESCRIBED` or `PUBLISHED` (`ERR_COLLECTION_NOT_DESCRIBED`, 409)."
    PRD §3.4: "A `ProcessingArchivist` claims an `UNPROCESSED` collection by
    beginning processing; the collection moves to `PROCESSING` and
    `assigned_archivist_id` is stamped with the archivist's `X-User-ID`."

    Design: Difficulty/cross_entity_state_dependency/pull_create_gated_by_collection_state
    """
    th.set_clock()
    agency = th.create_agency()
    # PROCESSING (begun but not yet described) still fails the gate.
    processing_bundle = th.create_collection_bundle(
        agency=agency, schedule_kwargs={"schedule_number": "SCH-DOJ-070"}
    )
    processing_collection = th.begin_processing(processing_bundle["collection"])
    assert processing_collection["processing_status"] == "PROCESSING"
    # PUBLISHED satisfies "DESCRIBED or PUBLISHED".
    published_bundle = th.setup_published_collection(
        agency=agency, schedule_kwargs={"schedule_number": "SCH-DOJ-071"}
    )

    ada = th.create_active_researcher()
    researcher = th.make_researcher_headers(ada["id"])

    th.validate_error(
        api.create_pull_request(
            th.pull_request_payload(ada["id"], processing_collection["id"],
                                    1, 5, "2026-09-10T00:00:00Z"),
            headers=researcher,
        ),
        E.ERR_COLLECTION_NOT_DESCRIBED,
    )
    resp = api.create_pull_request(
        th.pull_request_payload(ada["id"], published_bundle["collection"]["id"],
                                1, 5, "2026-09-10T00:00:00Z"),
        headers=researcher,
    )
    pull = th.validate_success(resp, 201)
    assert pull["status"] == "REQUESTED"


def test_review_complete_gated_by_referral_states(api):
    """PRD §3.5: "Completion also requires that every referral of the review
    be either `RESPONDED` or overdue. A `SENT` referral is overdue only when
    the logical clock is strictly later than its `response_due_at`: at exactly
    the due instant the referral is not overdue and still blocks completion,
    and the completing call is rejected with `ERR_REFERRALS_OUTSTANDING`
    (409)."
    PRD §3.5: "A `DECLASSIFIED` outcome clears the collection's
    `classification_level` to `NONE` and stamps `declass_outcome` as
    `DECLASSIFIED`."

    Design: Difficulty/cross_entity_state_dependency/review_complete_gated_by_referral_states
    """
    th.set_clock()
    ctx = th.setup_in_progress_mdr_with_referral()
    review = ctx["review"]
    referral = ctx["referral"]
    reviewer = th.TEST_USERS["declass_reviewer_headers"]

    # The SENT referral (due 2026-09-22, clock at 2026-09-01) blocks
    # completion.
    resp = api.complete_declass_review(
        review["id"], th.complete_review_payload("DECLASSIFY"), headers=reviewer
    )
    assert resp.status_code == 409
    th.validate_error(resp, E.ERR_REFERRALS_OUTSTANDING)

    responded = th.respond_referral(referral, "DECLASSIFY")
    assert responded["status"] == "RESPONDED"
    assert responded["decision"] == "DECLASSIFY"

    completed = th.validate_success(
        api.complete_declass_review(
            review["id"], th.complete_review_payload("DECLASSIFY"), headers=reviewer
        ),
        200,
    )
    assert completed["status"] == "COMPLETED"
    assert completed["outcome"] == "DECLASSIFIED"

    collection_after = th.read_collection(ctx["collection"]["id"])
    assert collection_after["classification_level"] == "NONE"


def test_review_complete_waits_for_every_referral(api):
    """PRD §3.5: "Completion also requires that every referral of the review
    be either `RESPONDED` or overdue."
    PRD §3.5: "If the reviewer's own assessment is `EXEMPT`, the outcome is
    `EXEMPT_RETAINED`. Otherwise, if at least one `RESPONDED` referral decided
    `EXEMPT`, the outcome is `PARTIAL`. Otherwise the outcome is
    `DECLASSIFIED`. The review's `exemption_codes` field becomes the sorted set
    containing the assessment's exemption code (when the assessment is `EXEMPT`)
    together with the exemption code of every `EXEMPT` referral"

    Design: Difficulty/cross_entity_state_dependency/review_complete_gated_by_referral_states
    """
    th.set_clock()
    ctx = th.setup_in_progress_mdr_with_referral()
    review = ctx["review"]
    reviewer = th.TEST_USERS["declass_reviewer_headers"]
    second_agency = th.create_agency("FBI", "Federal Bureau of Investigation")
    referrals = th.create_referrals(review, [second_agency["id"]])
    referral_b = referrals[0]

    # With one RESPONDED and one still SENT, completion is still blocked.
    th.respond_referral(ctx["referral"], "DECLASSIFY")
    th.validate_error(
        api.complete_declass_review(
            review["id"], th.complete_review_payload("DECLASSIFY"), headers=reviewer
        ),
        E.ERR_REFERRALS_OUTSTANDING,
    )

    # Only when the last referral answers does completion proceed; the EXEMPT
    # referral makes the outcome PARTIAL and contributes its code.
    th.respond_referral(referral_b, "EXEMPT", "B3")
    completed = th.validate_success(
        api.complete_declass_review(
            review["id"], th.complete_review_payload("DECLASSIFY"), headers=reviewer
        ),
        200,
    )
    assert completed["status"] == "COMPLETED"
    assert completed["outcome"] == "PARTIAL"
    assert completed["exemption_codes"] == ["B3"]

    collection_after = th.read_collection(ctx["collection"]["id"])
    assert collection_after["classification_level"] == "SECRET"
    assert collection_after["declass_outcome"] == "PARTIAL"
