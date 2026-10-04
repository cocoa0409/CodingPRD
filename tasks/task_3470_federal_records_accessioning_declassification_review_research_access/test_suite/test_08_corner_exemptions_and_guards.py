"""Corner coverage: exemption-code requirements, the restricted-records
gates, double adjudication, authentication context, and presidential guard
rails."""

import test_helpers as th

E = th.ApiErrorId


def test_exemption_required_on_deny_and_exempt(api):
    """PRD §3.9: "Partial grants and denials must say why:
    `claimed_exemptions` must be a non-empty subset of the recognized exemption
    codes `B1`, `B3`, and `B5` (`ERR_EXEMPTION_REQUIRED`, 422, otherwise),
    while a pure grant claims none."
    PRD §3.5: "The response carries a `decision` of `DECLASSIFY` or `EXEMPT`;
    an `EXEMPT` decision must also carry a non-empty `exemption_code`
    (`ERR_EXEMPTION_REQUIRED`, 422)."

    Design: Corner/validations/exemption_required_on_deny_and_exempt
    """
    th.set_clock()
    ctx = th.setup_in_progress_mdr_with_referral()
    collection = ctx["collection"]
    referral = ctx["referral"]
    ada = ctx["researcher"]
    foia = th.create_foia(ada, collection, "exemption probe")

    th.validate_error(
        api.adjudicate_foia_request(
            foia["id"], th.adjudicate_payload("DENY"),
            headers=th.TEST_USERS["foia_officer_headers"],
        ),
        E.ERR_EXEMPTION_REQUIRED,
    )
    th.validate_error(
        api.respond_to_referral(
            referral["id"], th.respond_referral_payload("EXEMPT"),
            headers=th.make_agency_liaison_headers(referral["agency_id"]),
        ),
        E.ERR_EXEMPTION_REQUIRED,
    )

    foia_after = th.get_success_data(
        api.get_foia_request(foia["id"], headers=th.TEST_USERS["foia_officer_headers"])
    )
    referral_after = th.get_success_data(
        api.get_equity_referral(
            referral["id"], headers=th.TEST_USERS["declass_reviewer_headers"]
        )
    )
    assert foia_after["status"] == "RECEIVED"
    assert referral_after["status"] == "SENT"


def test_foia_not_required_and_review_not_restricted(api):
    """PRD §3.9: "FOIA exists only for restricted records: the collection's
    posture must be `CLASSIFIED_REVIEW_REQUIRED` or `PRESIDENTIAL_HOLD`, and a
    request filed against a `PUBLIC` collection — whose records are already
    open — is rejected with `ERR_FOIA_NOT_REQUIRED` (409)."
    PRD §3.5: "Third, the collection must actually require review: the posture
    must be `CLASSIFIED_REVIEW_REQUIRED` — for a systematic review this means
    the collection still carries a classification level other than `NONE` — and
    a request against a collection that does not is rejected with
    `ERR_COLLECTION_NOT_RESTRICTED` (409)."

    Design: Corner/validations/foia_not_required_and_review_not_restricted
    """
    th.set_clock()
    bundle = th.create_collection_bundle()  # classification NONE -> PUBLIC
    collection = bundle["collection"]
    ada = th.create_active_researcher()
    researcher = th.make_researcher_headers(ada["id"])

    th.validate_error(
        api.create_foia_request(
            th.foia_request_payload(ada["id"], collection["id"], "already public"),
            headers=researcher,
        ),
        E.ERR_FOIA_NOT_REQUIRED,
    )

    payload = th.build_review_create_payload(
        collection["id"], "MANDATORY", researcher=ada,
        justification="nothing classified here",
    )
    th.validate_error(api.create_declass_review(payload, headers=researcher),
                      E.ERR_COLLECTION_NOT_RESTRICTED)

    foias, foia_meta = th.validate_paginated(
        api.list_foia_requests(
            headers=th.TEST_USERS["foia_officer_headers"],
            params={"researcher_id": ada["id"]},
        )
    )
    reviews, review_meta = th.validate_paginated(
        api.list_declass_reviews(
            headers=th.TEST_USERS["declass_reviewer_headers"],
            params={"collection_id": collection["id"]},
        )
    )
    assert foias == [] and foia_meta["total_count"] == 0
    assert reviews == [] and review_meta["total_count"] == 0


def test_adjudicate_twice_rejected(api):
    """PRD §3.9: "Adjudicating a request that already stands decided and has
    not been remanded — one in `GRANTED`, `PARTIAL_GRANT`, or `DENIED` — is
    rejected with `ERR_FOIA_ALREADY_ADJUDICATED` (409)."

    Design: Corner/validations/adjudicate_twice_rejected
    """
    th.set_clock()
    bundle = th.setup_classified_collection(classification_default="SECRET")
    ada = th.create_active_researcher()
    foia = th.create_foia(ada, bundle["collection"], "twice probe")
    foia = th.adjudicate_foia(foia, "GRANT")
    assert foia["status"] == "GRANTED"
    assert foia["adjudicator_id"] == "foia-1"

    th.validate_error(
        api.adjudicate_foia_request(
            foia["id"], th.adjudicate_payload("DENY", ["B1"]),
            headers=th.TEST_USERS["foia_officer_2_headers"],
        ),
        E.ERR_FOIA_ALREADY_ADJUDICATED,
    )

    after = th.get_success_data(
        api.get_foia_request(foia["id"], headers=th.TEST_USERS["foia_officer_headers"])
    )
    assert after["status"] == "GRANTED"
    assert after["adjudicator_id"] == "foia-1"


def test_missing_auth_headers_return_400(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, naming their operational
    capacity. If either header is missing, or if `X-User-Role` is not one of
    the declared roles, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_headers_return_400
    """
    th.set_clock()
    agency = th.create_agency()

    th.validate_error(
        api.get_agency(agency["id"], headers=None),
        E.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    )

    ok = th.validate_success(
        api.get_agency(agency["id"], headers=th.TEST_USERS["admin_headers"]), 200
    )
    assert ok["id"] == agency["id"]


def test_presidential_guard_rails(api):
    """PRD §3.6: "The target collection's `records_domain` must be
    `PRESIDENTIAL`; imposing a restriction on a federal-domain collection is
    rejected with `ERR_NOT_PRESIDENTIAL_RECORDS` (409)."
    PRD §3.6: "It requires a designated representative — notifying without one
    is rejected with `ERR_REPRESENTATIVE_REQUIRED` (409)"
    PRD §3.6: "Releasing a restriction that was never notified is rejected with
    `ERR_RESTRICTION_NOT_NOTIFIED` (409)."

    Design: Corner/validations/presidential_guard_rails
    """
    th.set_clock()
    agency = th.create_agency()
    federal = th.create_collection_bundle(
        agency=agency, schedule_kwargs={"schedule_number": "SCH-DOJ-050"}
    )
    presidential = th.setup_presidential_collection(
        agency=agency, schedule_kwargs={"schedule_number": "SCH-DOJ-051"}
    )
    chief = th.TEST_USERS["chief_archivist_headers"]

    p6 = th.impose_restriction(presidential["collection"], "P6_PERSONAL_PRIVACY")

    th.validate_error(
        api.create_presidential_restriction(
            th.restriction_payload(federal["collection"]["id"], "P3_STATUTORY"),
            headers=chief,
        ),
        E.ERR_NOT_PRESIDENTIAL_RECORDS,
    )
    th.validate_error(api.notify_restriction(p6["id"], headers=chief),
                      E.ERR_REPRESENTATIVE_REQUIRED)
    th.validate_error(api.release_restriction(p6["id"], headers=chief),
                      E.ERR_RESTRICTION_NOT_NOTIFIED)

    after = th.get_success_data(
        api.get_presidential_restriction(p6["id"], headers=chief)
    )
    assert after["status"] == "IMPOSED"

    data, meta = th.validate_paginated(
        api.list_presidential_restrictions(
            headers=chief, params={"collection_id": federal["collection"]["id"]}
        )
    )
    assert data == []
    assert meta["total_count"] == 0
