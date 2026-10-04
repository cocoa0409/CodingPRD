"""Corner coverage: segregation of duties, duplicate/uniqueness gates, and
the open-review uniqueness check against a fresh OCC token."""

import test_helpers as th

E = th.ApiErrorId


def test_segregation_of_duties_schedule_decide(api):
    """PRD §3.1: "Segregation of duties applies at this step: the decider's
    `X-User-ID` must differ from the recorded `appraiser_id`, or the call fails
    with `ERR_SEGREGATION_OF_DUTIES` (403) — the archivist who appraised a
    schedule may never be the one who decides it."

    Design: Corner/validations/segregation_of_duties_schedule_decide
    """
    th.set_clock()
    agency = th.create_agency()
    schedule = th.create_draft_schedule(
        agency, schedule_number="SCH-DOJ-022", title="SoD probe"
    )
    schedule = th.submit_schedule(schedule)
    schedule = th.appraise_schedule(schedule, "APPROVE")  # appraiser arch-ap-1

    # Same person, correct role: still forbidden.
    th.validate_error(
        api.decide_schedule(
            schedule["id"], th.decide_schedule_payload("APPROVE"),
            headers=th.make_headers("arch-ap-1", "ChiefArchivist"),
        ),
        E.ERR_SEGREGATION_OF_DUTIES,
    )
    after = th.get_success_data(
        api.get_schedule(schedule["id"], headers=th.TEST_USERS["chief_archivist_headers"])
    )
    assert after["status"] == "APPRAISED"

    decided = th.validate_success(
        api.decide_schedule(
            schedule["id"], th.decide_schedule_payload("APPROVE"),
            headers=th.TEST_USERS["chief_archivist_headers"],
        ),
        200,
    )
    assert decided["status"] == "APPROVED"


def test_segregation_of_duties_foia_appeal(api):
    """PRD §3.9: "Segregation of duties binds here: the appeals decider's
    `X-User-ID` must differ from the recorded `adjudicator_id`, or the call
    fails with `ERR_SEGREGATION_OF_DUTIES` (403)."

    Design: Corner/validations/segregation_of_duties_foia_appeal
    """
    th.set_clock()
    bundle = th.setup_classified_collection(classification_default="SECRET")
    ada = th.create_active_researcher()
    foia = th.create_appealed_foia(ada, bundle["collection"])  # adjudicator foia-1

    # The adjudicator's identity under the appeals role: forbidden.
    th.validate_error(
        api.decide_foia_appeal(
            foia["id"], th.decide_appeal_payload("GRANT"),
            headers=th.make_headers("foia-1", "FoiaAppealsOfficer"),
        ),
        E.ERR_SEGREGATION_OF_DUTIES,
    )
    after = th.get_success_data(
        api.get_foia_request(foia["id"], headers=th.TEST_USERS["foia_officer_headers"])
    )
    assert after["status"] == "APPEALED"

    decided = th.validate_success(
        api.decide_foia_appeal(
            foia["id"], th.decide_appeal_payload("UPHOLD"),
            headers=th.TEST_USERS["foia_appeals_officer_headers"],
        ),
        200,
    )
    assert decided["status"] == "APPEAL_UPHELD"


def test_duplicate_referral_rejected_atomically(api):
    """PRD §3.5: "Referrals are created in bulk: the call carries a list of
    `agency_ids`, and the operation is atomic — if any id is unknown
    (`ERR_AGENCY_NOT_FOUND`), if the list contains a duplicate, or if a
    referral already exists for the same review and agency
    (`ERR_DUPLICATE_REFERRAL`, 409), the whole request is aborted and no
    referral is created."

    Design: Corner/validations/duplicate_referral_rejected_atomically
    """
    th.set_clock()
    ctx = th.setup_in_progress_mdr_with_referral()
    review = ctx["review"]
    reviewer = th.TEST_USERS["declass_reviewer_headers"]

    th.validate_error(
        api.create_referrals(
            review["id"], th.referrals_payload([ctx["referral_agency"]["id"]]),
            headers=reviewer,
        ),
        E.ERR_DUPLICATE_REFERRAL,
    )

    data, meta = th.validate_paginated(
        api.list_equity_referrals(headers=reviewer, params={"review_id": review["id"]})
    )
    assert len(data) == 1
    assert meta["total_count"] == 1


def test_duplicate_restriction_category_released_frees_slot(api):
    """PRD §3.6: "At most one non-`RELEASED` restriction may exist per
    collection and category: a second live restriction of the same category on
    the same collection is rejected with `ERR_DUPLICATE_RESTRICTION_CATEGORY`
    (409)."
    PRD §2.8: "A `RELEASED` restriction no longer constrains the posture."

    Design: Corner/validations/duplicate_restriction_category_released_frees_slot
    """
    th.set_clock()
    bundle = th.setup_presidential_collection()
    collection = bundle["collection"]
    chief = th.TEST_USERS["chief_archivist_headers"]

    p1 = th.impose_restriction(collection, "P1_NATIONAL_SECURITY")
    th.validate_error(
        api.create_presidential_restriction(
            th.restriction_payload(collection["id"], "P1_NATIONAL_SECURITY"),
            headers=chief,
        ),
        E.ERR_DUPLICATE_RESTRICTION_CATEGORY,
    )

    # A different category coexists with the live P1.
    resp = api.create_presidential_restriction(
        th.restriction_payload(collection["id"], "P2_APPOINTMENTS"), headers=chief
    )
    th.validate_success(resp, 201)

    # Releasing P1 frees the (collection, category) slot for a fresh P1.
    p1 = th.designate_representative(p1, "rep-44")
    p1 = th.notify_restriction(p1)
    th.set_clock("2026-10-01T00:00:00Z")
    p1 = th.release_restriction(p1)
    assert p1["status"] == "RELEASED"

    resp = api.create_presidential_restriction(
        th.restriction_payload(collection["id"], "P1_NATIONAL_SECURITY"),
        headers=chief,
    )
    th.validate_success(resp, 201)

    posture = th.read_collection(collection["id"])["restriction_posture"]
    assert posture == "PRESIDENTIAL_HOLD"


def test_review_already_open_with_fresh_version(api):
    """PRD §3.5: "Second, a collection may host at most one review in `OPEN`
    or `IN_PROGRESS` at a time; opening a second concurrent review is rejected
    with `ERR_REVIEW_ALREADY_OPEN` (409)."
    PRD §3.5: "A newly opened review starts in `OPEN` status, and its creation
    records review demand against the collection by advancing the collection's
    `version` by one — which is exactly why the OCC check exists."

    Design: Corner/validations/review_already_open_with_fresh_version
    """
    th.set_clock()
    bundle = th.setup_classified_collection(classification_default="SECRET")
    collection = bundle["collection"]
    ada = th.create_active_researcher()
    researcher = th.make_researcher_headers(ada["id"])

    version_before = th.current_collection_version(collection["id"])
    first = th.create_open_mdr(collection, ada, "first review")
    assert first["status"] == "OPEN"
    version_after_first = th.current_collection_version(collection["id"])
    assert version_after_first == version_before + 1

    # The OCC token is fresh, so the uniqueness gate is what fires.
    fresh_payload = th.build_review_create_payload(
        collection["id"], "MANDATORY", researcher=ada, justification="second review"
    )
    th.validate_error(
        api.create_declass_review(fresh_payload, headers=researcher),
        E.ERR_REVIEW_ALREADY_OPEN,
    )

    data, meta = th.validate_paginated(
        api.list_declass_reviews(
            headers=th.TEST_USERS["declass_reviewer_headers"],
            params={"collection_id": collection["id"]},
        )
    )
    assert len(data) == 1
    assert meta["total_count"] == 1


def test_uniqueness_email_and_schedule_number(api):
    """PRD §3.7: "The email must be unique across all registrations — a
    duplicate is rejected with `ERR_EMAIL_EXISTS` (409)"
    PRD §3.1: "The `schedule_number` is an agency-local identifier, unique per
    agency — a second schedule with the same number under the same agency is
    rejected with `ERR_SCHEDULE_NUMBER_EXISTS` (409)."
    PRD §3.1: "The `agency_code` must be unique across all agencies; a
    duplicate registration is rejected with `ERR_AGENCY_CODE_EXISTS` (409)."

    Design: Corner/validations/uniqueness_email_and_schedule_number
    """
    th.set_clock()
    agency = th.create_agency()
    other_agency = th.create_agency("CIA", "Central Intelligence Agency")
    th.register_researcher()  # ada@example.org
    th.create_draft_schedule(agency, schedule_number="SCH-DOJ-002")

    th.validate_error(
        api.create_researcher(
            th.researcher_payload("Ada Clone", "ada@example.org", "GENEALOGIST",
                                  "DL-9999"),
            headers=th.TEST_USERS["anonymous_headers"],
        ),
        E.ERR_EMAIL_EXISTS,
    )

    th.validate_error(
        api.create_schedule(
            th.schedule_payload(agency["id"], schedule_number="SCH-DOJ-002",
                                title="Duplicate number", disposition="TEMPORARY",
                                transfer_lag_years=None),
            headers=th.make_records_officer_headers(agency["id"]),
        ),
        E.ERR_SCHEDULE_NUMBER_EXISTS,
    )

    # The same number under a different agency is a different key.
    resp = api.create_schedule(
        th.schedule_payload(other_agency["id"], schedule_number="SCH-DOJ-002",
                            title="Same number other agency", disposition="TEMPORARY",
                            transfer_lag_years=None),
        headers=th.make_records_officer_headers(other_agency["id"]),
    )
    th.validate_success(resp, 201)

    th.validate_error(
        api.create_agency(
            th.agency_payload("DOJ", "Department of Justice Duplicate"),
            headers=th.TEST_USERS["admin_headers"],
        ),
        E.ERR_AGENCY_CODE_EXISTS,
    )
