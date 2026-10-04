"""Corner coverage: schedule and transfer state machines, the accession
cascade, and immediate read-after-write consistency."""

import test_helpers as th

E = th.ApiErrorId


def test_schedule_happy_path_stamps_and_version_progression(api):
    """PRD §3.1: "Submission moves the schedule from `DRAFT` to `SUBMITTED`."
    PRD §3.1: "Appraisal records the archivist's `appraisal_recommendation` —
    either `APPROVE` or `RETURN` — supplied with the call, and stamps
    `appraiser_id` with the archivist's `X-User-ID`."
    PRD §3.1: "Either way, `decided_by` is stamped with the decider's
    `X-User-ID` and the note is recorded."
    PRD §3.1: "Every submit, appraise, decide, and resubmit advances the
    schedule's `version` by one."

    Design: Corner/state_machines/schedule_happy_path_stamps_and_version_progression
    """
    th.set_clock()
    agency = th.create_agency()
    officer = th.make_records_officer_headers(agency["id"])
    schedule = th.create_draft_schedule(
        agency, schedule_number="SCH-DOJ-020", title="Field Office General Files",
        classification_default="CONFIDENTIAL",
    )
    assert schedule["version"] == 1
    assert schedule["status"] == "DRAFT"

    submitted = th.validate_success(api.submit_schedule(schedule["id"], headers=officer), 200)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["version"] == 2

    appraised = th.validate_success(
        api.appraise_schedule(
            schedule["id"], th.appraise_payload("APPROVE"),
            headers=th.TEST_USERS["appraiser_headers"],
        ),
        200,
    )
    assert appraised["status"] == "APPRAISED"
    assert appraised["version"] == 3
    assert appraised["appraiser_id"] == "arch-ap-1"
    assert appraised["appraisal_recommendation"] == "APPROVE"

    decided = th.validate_success(
        api.decide_schedule(
            schedule["id"], th.decide_schedule_payload("APPROVE", "permanent"),
            headers=th.TEST_USERS["chief_archivist_headers"],
        ),
        200,
    )
    assert decided["status"] == "APPROVED"
    assert decided["version"] == 4
    assert decided["decided_by"] == "arch-chief-1"
    assert decided["decision_note"] == "permanent"


def test_schedule_decide_before_appraise_rejected(api):
    """PRD §3.1: "Deciding a schedule that is not `APPRAISED` is rejected with
    `ERR_SCHEDULE_NOT_APPRAISED`."

    Design: Corner/state_machines/schedule_decide_before_appraise_rejected
    """
    th.set_clock()
    agency = th.create_agency()
    schedule = th.create_draft_schedule(
        agency, schedule_number="SCH-DOJ-021", title="Premature"
    )
    schedule = th.submit_schedule(schedule)

    resp = api.decide_schedule(
        schedule["id"], th.decide_schedule_payload("APPROVE"),
        headers=th.TEST_USERS["chief_archivist_headers"],
    )
    th.validate_error(resp, E.ERR_SCHEDULE_NOT_APPRAISED)

    after = th.get_success_data(
        api.get_schedule(schedule["id"], headers=th.TEST_USERS["chief_archivist_headers"])
    )
    assert after["status"] == "SUBMITTED"

    schedule = th.appraise_schedule(schedule, "APPROVE")
    schedule = th.decide_schedule(schedule, "APPROVE")
    assert schedule["status"] == "APPROVED"


def test_terminal_lockdown_on_approved_schedule_and_accessioned_transfer(api):
    """PRD §3.1: "appraising a schedule in any other status is rejected with
    `ERR_INVALID_STATE`."
    PRD §3.1: "A decision of `APPROVE` moves the schedule to `APPROVED`, its
    terminal state, and only then can it underlie transfers."
    PRD §3.2: "An accessioned transfer can never be withdrawn."
    PRD §2.6: "The generic rejection is `ERR_INVALID_STATE` (409)"

    Design: Corner/state_machines/terminal_lockdown_on_approved_schedule_and_accessioned_transfer
    """
    th.set_clock()
    bundle = th.create_collection_bundle()
    agency = bundle["agency"]
    schedule = bundle["schedule"]
    transfer = bundle["transfer"]
    assert schedule["status"] == "APPROVED"
    assert transfer["status"] == "ACCESSIONED"
    officer = th.make_records_officer_headers(agency["id"])

    th.validate_error(api.submit_schedule(schedule["id"], headers=officer),
                      E.ERR_INVALID_STATE)
    th.validate_error(
        api.appraise_schedule(
            schedule["id"], th.appraise_payload("RETURN"),
            headers=th.TEST_USERS["appraiser_headers"],
        ),
        E.ERR_INVALID_STATE,
    )
    th.validate_error(api.withdraw_transfer(transfer["id"], headers=officer),
                      E.ERR_INVALID_STATE)

    schedule_after = th.get_success_data(
        api.get_schedule(schedule["id"], headers=th.TEST_USERS["chief_archivist_headers"])
    )
    transfer_after = th.get_success_data(
        api.get_transfer(transfer["id"], headers=th.TEST_USERS["processing_archivist_headers"])
    )
    assert schedule_after["status"] == "APPROVED"
    assert transfer_after["status"] == "ACCESSIONED"


def test_accession_creates_collection_with_copied_fields(api):
    """PRD §3.3: "In the same transaction, the system creates the transfer's
    **Collection** — exactly one collection per accessioned transfer, with
    `transfer_id` recording the link. The new collection inherits
    `schedule_id`, `agency_id`, `records_domain`, and `records_cutoff_date`
    from the transfer and its schedule; its `classification_level` is copied
    from the schedule's `classification_default`; `units_total` is set from the
    transfer's `unit_count`."
    PRD §3.3: "On the transfer itself, accession moves the status from
    `VALIDATED` to `ACCESSIONED` (terminal), stamps `accessioned_at` with the
    logical clock, records the new collection's id on `collection_id`, and
    advances `version`."

    Design: Corner/state_machines/accession_creates_collection_with_copied_fields
    """
    th.set_clock()
    bundle = th.setup_classified_collection(classification_default="SECRET")
    transfer = bundle["transfer"]
    collection = th.read_collection(transfer["collection_id"])

    assert transfer["status"] == "ACCESSIONED"
    assert th.same_instant(transfer["accessioned_at"], th.STARTUP_CLOCK_UTC)
    assert transfer["collection_id"] == collection["id"]

    data, meta = th.validate_paginated(
        api.list_collections(
            headers=th.TEST_USERS["processing_archivist_headers"],
            params={"transfer_id": transfer["id"]},
        )
    )
    assert len(data) == 1
    assert meta["total_count"] == 1
    assert data[0]["id"] == collection["id"]

    th.assert_collection(collection)
    assert collection["units_total"] == 50
    assert collection["classification_level"] == "SECRET"
    assert collection["records_domain"] == "FEDERAL"
    assert collection["schedule_id"] == bundle["schedule"]["id"]
    assert collection["agency_id"] == bundle["agency"]["id"]
    assert th.same_instant(collection["records_cutoff_date"], "2001-03-15T00:00:00Z")


def test_immediate_visibility_after_accession(api):
    """PRD §1: "Consistency is immediate: every mutation described in this
    document, including cascade effects and derived-field recomputation, is
    visible in the response of the call that triggered it."
    PRD §2.5: "Because consistency is immediate, a call that cascades into
    another resource (for example, a pull fulfillment that increments the
    collection's pull counter) advances that resource's `version` and refreshes
    its `updated_at` within the same transaction, and the effect is visible to
    the very next read."

    Design: Corner/consistency_model/immediate_visibility_after_accession
    """
    th.set_clock()
    agency = th.create_agency()
    schedule = th.create_approved_schedule(
        agency, schedule_number="SCH-DOJ-001", classification_default="SECRET"
    )
    transfer = th.create_validated_transfer(agency, schedule)
    accessioned = th.accession_transfer(transfer)

    # The cascade product is visible inside the accession response itself.
    collection_id = accessioned["collection_id"]
    assert collection_id

    got = th.validate_success(
        api.get_collection(
            collection_id, headers=th.TEST_USERS["processing_archivist_headers"]
        ),
        200,
    )
    assert got["processing_status"] == "UNPROCESSED"
    assert got["units_total"] == 50
    assert got["classification_level"] == "SECRET"

    data, meta = th.validate_paginated(
        api.list_collections(
            headers=th.TEST_USERS["processing_archivist_headers"],
            params={"transfer_id": accessioned["id"]},
        )
    )
    assert len(data) == 1
    assert meta["total_count"] == 1
    assert data[0]["id"] == collection_id
