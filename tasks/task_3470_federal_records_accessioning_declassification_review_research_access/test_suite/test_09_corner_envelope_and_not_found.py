"""Corner coverage: the error envelope shape, the digitization-queue
computed read's membership rule, body-FK existence order, and
entity-specific 404s."""

import test_helpers as th

E = th.ApiErrorId
UNKNOWN_RESEARCHER = "00000000-0000-4000-8000-0000000000aa"
UNKNOWN_COLLECTION = "00000000-0000-4000-8000-0000000000bb"


def test_error_envelope_shape_on_failures(api):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error." and "The `message` provides a
    human-readable explanation of what went wrong."

    Design: Corner/endpoints/error_envelope_shape_on_failures
    """
    th.set_clock()
    resp = api.get_collection(
        th.NON_EXISTENT_UUID, headers=th.TEST_USERS["processing_archivist_headers"]
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
    error = th.validate_error(resp, E.ERR_COLLECTION_NOT_FOUND)
    assert error["message"].strip()


def test_digitization_queue_excludes_non_queued_collections(api):
    """PRD §3.4: "The digitization queue itself is a computed read. It lists
    exactly the collections whose `digitization_status` is `QUEUED`, ordered by
    `digitization_priority` descending, then by `records_cutoff_date` ascending
    so that older records come first on a tie, then by `created_at` ascending
    as the final tie-break — a collection's `id` is never used for ordering."

    Design: Corner/endpoints/digitization_queue_excludes_non_queued_collections
    """
    th.set_clock()
    agency = th.create_agency()
    queued = th.setup_queued_collection(
        agency=agency, schedule_kwargs={"schedule_number": "SCH-DOJ-060"}
    )
    classified = th.setup_classified_collection(
        agency=agency, schedule_kwargs={"schedule_number": "SCH-DOJ-061"}
    )
    presidential = th.setup_presidential_collection(
        agency=agency, schedule_kwargs={"schedule_number": "SCH-DOJ-062"}
    )

    data, meta = th.validate_paginated(
        api.get_digitization_queue(headers=th.TEST_USERS["processing_archivist_headers"])
    )
    ids = [row["id"] for row in data]
    assert ids == [queued["collection"]["id"]]
    assert meta["total_count"] == 1
    assert classified["collection"]["id"] not in ids
    assert presidential["collection"]["id"] not in ids


def test_pull_create_body_fks_checked_in_input_order(api):
    """PRD §2.6: "Foreign-key identifiers in the request body must exist,
    validated in the endpoint's declared input order — for example,
    `schedule_id` before `agency_id` when initiating a transfer, and
    `researcher_id` before `collection_id` when requesting a pull. A missing
    reference yields the same entity-specific 404 family as rung 3."

    Design: Corner/errors/pull_create_body_fks_checked_in_input_order
    """
    th.set_clock()
    bundle = th.setup_public_described_collection()
    ada = th.create_active_researcher()

    th.validate_error(
        api.create_pull_request(
            th.pull_request_payload(UNKNOWN_RESEARCHER, UNKNOWN_COLLECTION,
                                    1, 5, "2026-09-10T00:00:00Z"),
            headers=th.make_researcher_headers(UNKNOWN_RESEARCHER),
        ),
        E.ERR_RESEARCHER_NOT_FOUND,
    )
    th.validate_error(
        api.create_pull_request(
            th.pull_request_payload(ada["id"], UNKNOWN_COLLECTION,
                                    1, 5, "2026-09-10T00:00:00Z"),
            headers=th.make_researcher_headers(ada["id"]),
        ),
        E.ERR_COLLECTION_NOT_FOUND,
    )


def test_review_and_referral_unknown_ids_return_entity_404s(api):
    """PRD §2.6: "Path-segment identifiers must exist, validated left to
    right. Each segment maps to its entity-specific 404: `ERR_AGENCY_NOT_FOUND`,
    `ERR_SCHEDULE_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`,
    `ERR_COLLECTION_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`,
    `ERR_REFERRAL_NOT_FOUND`, `ERR_RESEARCHER_NOT_FOUND`,
    `ERR_PULL_REQUEST_NOT_FOUND`, `ERR_REPRODUCTION_NOT_FOUND`,
    `ERR_FOIA_NOT_FOUND`, or `ERR_RESTRICTION_NOT_FOUND`."

    Design: Corner/errors/review_and_referral_unknown_ids_return_entity_404s
    """
    th.set_clock()
    reviewer = th.TEST_USERS["declass_reviewer_headers"]
    th.validate_error(api.get_declass_review(th.NON_EXISTENT_UUID, headers=reviewer),
                      E.ERR_REVIEW_NOT_FOUND)
    th.validate_error(api.get_equity_referral(th.NON_EXISTENT_UUID, headers=reviewer),
                      E.ERR_REFERRAL_NOT_FOUND)


def test_remaining_entity_404s(api):
    """PRD §2.6: "Path-segment identifiers must exist, validated left to
    right. Each segment maps to its entity-specific 404: `ERR_AGENCY_NOT_FOUND`,
    `ERR_SCHEDULE_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`,
    `ERR_COLLECTION_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`,
    `ERR_REFERRAL_NOT_FOUND`, `ERR_RESEARCHER_NOT_FOUND`,
    `ERR_PULL_REQUEST_NOT_FOUND`, `ERR_REPRODUCTION_NOT_FOUND`,
    `ERR_FOIA_NOT_FOUND`, or `ERR_RESTRICTION_NOT_FOUND`."

    Design: Corner/errors/remaining_entity_404s
    """
    th.set_clock()
    th.validate_error(
        api.get_pull_request(
            th.NON_EXISTENT_UUID, headers=th.TEST_USERS["research_room_staff_headers"]
        ),
        E.ERR_PULL_REQUEST_NOT_FOUND,
    )
    th.validate_error(
        api.get_reproduction_request(
            th.NON_EXISTENT_UUID, headers=th.TEST_USERS["research_room_staff_headers"]
        ),
        E.ERR_REPRODUCTION_NOT_FOUND,
    )
    th.validate_error(
        api.get_presidential_restriction(
            th.NON_EXISTENT_UUID, headers=th.TEST_USERS["chief_archivist_headers"]
        ),
        E.ERR_RESTRICTION_NOT_FOUND,
    )
    th.validate_error(
        api.get_foia_request(
            th.NON_EXISTENT_UUID, headers=th.TEST_USERS["foia_officer_headers"]
        ),
        E.ERR_FOIA_NOT_FOUND,
    )
    th.validate_error(
        api.get_schedule(
            th.NON_EXISTENT_UUID, headers=th.make_records_officer_headers(UNKNOWN_RESEARCHER)
        ),
        E.ERR_SCHEDULE_NOT_FOUND,
    )
