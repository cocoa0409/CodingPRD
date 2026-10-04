"""Correction requests: filing, adjudication, the review cycle and its gates."""
from test_helpers import (
    VERIFIER_USER_ID,
    ApiErrorId,
    award_seal,
    create_filing,
    extract,
    file_correction_request,
    get_correction,
    get_filing,
    get_org,
    list_fields,
    make_organization_user_headers,
    make_verifier_headers,
    normalize,
    scenario_cascade,
    scenario_org_with_open_correction,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    void_filing,
)


def test_correction_request_against_a_pending_field_returns_field_not_correctable(api):
    """PRD §3.6: "A field whose `normalization_status` is `PENDING` or `CONFLICT`
    has no settled value to argue about, and a correction request against it is
    refused with `ERR_FIELD_NOT_CORRECTABLE` (HTTP 422). A field must be
    `NORMALIZED` or `CORRECTED` before it can be corrected."

    Design: Corner/validations/correction_request_against_a_pending_field_returns_field_not_correctable
    """
    set_clock()
    org = scenario_cascade()
    filing = create_filing(org["id"])
    extract(filing["id"], [{"line_code": "TOTREV", "raw_value": "1000.00",
                            "raw_format": "USD_WHOLE", "is_revenue_component": True}])
    field = list_fields(filing["id"], as_org=org["id"])[0]
    assert field["normalization_status"] == "PENDING"

    resp = api.create_correction_request(
        field["id"],
        {"requested_value": "2000.00",
         "evidence_url": "https://evidence.example.org/audited-2025.pdf",
         "justification": "The audited statement reports a different total.",
         "expected_extracted_field_version": field["version"]},
        make_organization_user_headers(org["id"]))

    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    validate_error(resp, ApiErrorId.ERR_FIELD_NOT_CORRECTABLE.value)

    rows = get_correction(field["id"], as_org=org["id"])
    assert rows == [], "No correction request may be created against a PENDING field"
    assert list_fields(filing["id"], as_org=org["id"])[0]["normalization_status"] == "PENDING"


def test_claiming_a_correction_request_twice_returns_invalid_state(api):
    """PRD §3.6: "Claiming a request moves it from `SUBMITTED` to `UNDER_REVIEW`."
    PRD §2.10: "A requested transition that is not declared for the resource's
    current state yields `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/claiming_a_correction_request_twice_returns_invalid_state
    """
    set_clock()
    org, filing, field, request = scenario_org_with_open_correction()

    claimed = validate_success(
        api.decide_correction_request(
            request["id"], {"decision": "CLAIM"}, make_verifier_headers()), 200)
    assert claimed["status"] == "UNDER_REVIEW"
    assert claimed["decided_by_user_id"] == VERIFIER_USER_ID

    again = api.decide_correction_request(
        request["id"], {"decision": "CLAIM"}, make_verifier_headers())
    assert again.status_code == 409, f"Expected 409, got {again.status_code}: {again.text}"
    validate_error(again, ApiErrorId.ERR_INVALID_STATE.value)

    after = get_correction(field["id"], request["id"])
    assert after["status"] == "UNDER_REVIEW"
    assert after["decided_by_user_id"] == VERIFIER_USER_ID
    refreshed = list_fields(filing["id"])[0]
    assert refreshed["normalized_value_cents"] == 100000
    assert refreshed["normalization_status"] == "NORMALIZED"


def test_third_open_correction_request_suspends_the_organization_and_revokes_its_seal(api):
    """PRD §3.3: "when the organization's `open_correction_count` reaches 3,
    `profile_status` moves to `SUSPENDED` with no client request, every one of the
    organization's `ACTIVE` transparency seals is revoked, `transparency_seal_level`
    returns to `NONE`, `seal_expires_on` becomes null, and the organization's
    `version` is incremented by 1."

    Design: Corner/state_machines/third_open_correction_request_suspends_the_organization_and_revokes_its_seal
    """
    set_clock()
    org = scenario_cascade()
    seal = award_seal(org["id"])
    assert seal["status"] == "ACTIVE"

    filing = create_filing(org["id"])
    extract(filing["id"], [
        {"line_code": "TOTREV", "raw_value": "1000.00", "raw_format": "USD_WHOLE",
         "is_revenue_component": True},
        {"line_code": "PROGREV", "raw_value": "2000.00", "raw_format": "USD_WHOLE",
         "is_revenue_component": True},
        {"line_code": "CONTRIB", "raw_value": "3000.00", "raw_format": "USD_WHOLE",
         "is_revenue_component": True},
    ])
    normalize(filing["id"])
    fields = list_fields(filing["id"], as_org=org["id"])
    assert len(fields) == 3

    for index, field in enumerate(fields[:2]):
        file_correction_request(org["id"], field["id"], field["version"],
                                requested_value=f"{1500 + index * 1000}.00",
                                evidence_url=f"https://evidence.example.org/{index}.pdf",
                                justification=f"Line {index} corrected.")

    before = get_org(org["id"])
    assert before["open_correction_count"] == 2
    assert before["profile_status"] == "ACTIVE"

    third = api.create_correction_request(
        fields[2]["id"],
        {"requested_value": "3500.00",
         "evidence_url": "https://evidence.example.org/c.pdf",
         "justification": "Line C corrected.",
         "expected_extracted_field_version": fields[2]["version"]},
        make_organization_user_headers(org["id"]))
    created = validate_success(third, 201)
    assert created["status"] == "SUBMITTED"

    after = get_org(org["id"])
    assert after["open_correction_count"] == 3
    assert after["profile_status"] == "SUSPENDED", (
        "the count crossing 3 suspends the profile without a client request"
    )
    assert after["transparency_seal_level"] == "NONE"
    assert after.get("seal_expires_on") is None

    seal_rows, _ = validate_paginated(
        api.list_seals(org["id"], make_verifier_headers()))
    assert len(seal_rows) == 1
    assert seal_rows[0]["status"] == "REVOKED"

    open_requests, _ = validate_paginated(
        api.list_organization_correction_requests(org["id"], make_verifier_headers()))
    assert len([r for r in open_requests if r["status"] in ("SUBMITTED", "UNDER_REVIEW")]) == 3


# ---------------------------------------------------------------------------
# Segregation of duties on correction adjudication (corner instance)
# ---------------------------------------------------------------------------

def test_correction_submitter_cannot_claim_its_own_request(api):
    """PRD §2.6: "On the adjudication of a correction request, the deciding
    `X-User-ID` must differ from the request's `submitted_by_user_id`, and again a
    match is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/roles/correction_submitter_cannot_accept_its_own_request
    """
    set_clock()
    org, filing, field, request = scenario_org_with_open_correction()
    assert request["submitted_by_user_id"] == org["id"]

    # PRD §3.6: "The `PlatformVerifier` drives the first five decisions". A
    # claim must therefore come from a PlatformVerifier; the gate under test is
    # the one that compares the acting X-User-ID to submitted_by_user_id, so the
    # verifier acts under the submitter's own identifier.
    resp = api.decide_correction_request(
        request["id"], {"decision": "CLAIM"},
        make_verifier_headers(org["id"]))
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    after = get_correction(field["id"], request["id"])
    assert after["status"] == "SUBMITTED"
    assert after.get("decided_by_user_id") is None
    assert list_fields(filing["id"])[0]["normalized_value_cents"] == 100000


def test_correction_submitter_cannot_accept_its_own_request(api):
    """PRD §3.6: "Accepting a request is the heaviest branch, and it is the one
    with a cross-entity gate. The acting `X-User-ID` must differ from
    `submitted_by_user_id`, or the request is refused with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/roles/correction_submitter_cannot_accept_its_own_request
    """
    set_clock()
    org, filing, field, request = scenario_org_with_open_correction()

    claimed = validate_success(
        api.decide_correction_request(
            request["id"], {"decision": "CLAIM"}, make_verifier_headers()), 200)
    assert claimed["status"] == "UNDER_REVIEW"

    # PRD §3.6: "The `PlatformVerifier` drives the first five decisions"; the
    # acceptance gate compares the acting X-User-ID to submitted_by_user_id, so
    # the verifier acts under the submitter's own identifier.
    resp = api.decide_correction_request(
        request["id"], {"decision": "ACCEPT"},
        make_verifier_headers(org["id"]))
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    after = get_correction(field["id"], request["id"])
    assert after["status"] == "UNDER_REVIEW"
    assert list_fields(filing["id"])[0]["normalized_value_cents"] == 100000
    assert list_fields(filing["id"])[0]["normalization_status"] == "NORMALIZED"


# ---------------------------------------------------------------------------
# The correction review cycle (difficulty instance)
# ---------------------------------------------------------------------------

def test_correction_request_cycles_through_return_for_info_back_to_submitted(api):
    """PRD §3.6: "Returning a request for information moves it back from
    `UNDER_REVIEW` to `SUBMITTED`."
    PRD §3.6: "On success `decided_by_user_id` is cleared back to null, the request
    re-enters the `SUBMITTED` queue, and a later claim re-enters review".
    PRD §3.6: "Rejecting a request moves it from `UNDER_REVIEW` to `REJECTED`."
    PRD §3.6: "no `ExtractedField` is mutated at all, and the request's `version`
    is incremented by 1."

    Design: Difficulty/non_linear_state_machine/correction_request_return_for_info_cycles_back_to_submitted
    """
    set_clock()
    org, filing, field, request = scenario_org_with_open_correction()

    first = validate_success(api.decide_correction_request(
        request["id"], {"decision": "CLAIM"}, make_verifier_headers()), 200)
    returned = validate_success(api.decide_correction_request(
        request["id"],
        {"decision": "RETURN_FOR_INFO",
         "review_note": "Please attach the audited statement for fiscal 2025."},
        make_verifier_headers()), 200)
    reclaimed = validate_success(api.decide_correction_request(
        request["id"], {"decision": "CLAIM"}, make_verifier_headers()), 200)
    rejected = validate_success(api.decide_correction_request(
        request["id"],
        {"decision": "REJECT",
         "review_note": "The filed return already matches the audited statement."},
        make_verifier_headers()), 200)

    assert [first["status"], returned["status"], reclaimed["status"], rejected["status"]] == [
        "UNDER_REVIEW", "SUBMITTED", "UNDER_REVIEW", "REJECTED"]

    assert rejected["status"] == "REJECTED"
    assert rejected["decided_by_user_id"] == VERIFIER_USER_ID

    refreshed = list_fields(filing["id"])[0]
    assert refreshed["normalized_value_cents"] == 100000
    assert refreshed["normalization_status"] == "NORMALIZED"
    filing_after = get_filing(filing["id"])
    assert filing_after["status"] == "NORMALIZED"
    assert filing_after["total_revenue_cents"] == 100000
    assert get_org(org["id"])["open_correction_count"] == 0


def test_return_for_info_requires_a_note_and_clears_the_decider(api):
    """PRD §3.6: "The `review_note` must be non-empty, and an empty one is refused
    with `ERR_INVALID_REQUEST` (HTTP 400). On success `decided_by_user_id` is
    cleared back to null".

    Design: Difficulty/non_linear_state_machine/correction_request_return_for_info_cycles_back_to_submitted
    """
    set_clock()
    org, filing, field, request = scenario_org_with_open_correction()
    validate_success(api.decide_correction_request(
        request["id"], {"decision": "CLAIM"}, make_verifier_headers()), 200)

    empty_note = api.decide_correction_request(
        request["id"], {"decision": "RETURN_FOR_INFO", "review_note": ""},
        make_verifier_headers())
    assert empty_note.status_code == 400, (
        f"Expected 400 for an empty review_note, got {empty_note.status_code}"
    )
    validate_error(empty_note, ApiErrorId.ERR_INVALID_REQUEST.value)

    returned = validate_success(api.decide_correction_request(
        request["id"],
        {"decision": "RETURN_FOR_INFO", "review_note": "Attach the audited statement."},
        make_verifier_headers()), 200)
    assert returned["status"] == "SUBMITTED"
    assert returned.get("decided_by_user_id") is None
    assert returned["version"] > request["version"]


# ---------------------------------------------------------------------------
# Cross-entity gate on correction approval (difficulty instance)
# ---------------------------------------------------------------------------

def test_correction_accept_requires_target_filing_still_normalized(api):
    """PRD §3.6: "Independently, the target extracted field's filing must be in
    `NORMALIZED` or `DISPUTED` status; a filing in any other state refuses the
    acceptance with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/correction_accept_requires_target_filing_still_normalized
    """
    set_clock()
    org, filing, field, request = scenario_org_with_open_correction()
    validate_success(api.decide_correction_request(
        request["id"], {"decision": "CLAIM"}, make_verifier_headers()), 200)

    void_filing(filing["id"])
    assert get_filing(filing["id"])["status"] == "VOIDED"

    resp = api.decide_correction_request(
        request["id"], {"decision": "ACCEPT"}, make_verifier_headers())
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    assert get_filing(filing["id"])["status"] == "VOIDED"
    assert get_correction(field["id"], request["id"])["status"] == "UNDER_REVIEW"
    unchanged = list_fields(filing["id"])[0]
    assert unchanged["normalized_value_cents"] == 100000
    assert unchanged["normalization_status"] == "NORMALIZED"


def test_correction_accept_succeeds_while_the_filing_is_normalized(api):
    """PRD §3.6: "When both gates pass, the request moves to `ACCEPTED` ... the
    target field's `normalized_value_cents` is replaced by the accepted
    `requested_value` converted to cents by the field's own unit multiplier and
    rounded half up, and the field's `normalization_status` moves to `CORRECTED`".
    PRD §3.6: "That field change drags its filing into `DISPUTED` if the filing
    was `NORMALIZED`".

    Design: Difficulty/cross_entity_state_dependency/correction_accept_requires_target_filing_still_normalized
    """
    set_clock()
    org, filing, field, request = scenario_org_with_open_correction(
        requested_value="2000.00")
    validate_success(api.decide_correction_request(
        request["id"], {"decision": "CLAIM"}, make_verifier_headers()), 200)

    accepted = validate_success(api.decide_correction_request(
        request["id"], {"decision": "ACCEPT"}, make_verifier_headers()), 200)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["decided_by_user_id"] == VERIFIER_USER_ID

    corrected = list_fields(filing["id"])[0]
    assert corrected["normalization_status"] == "CORRECTED"
    assert corrected["normalized_value_cents"] == 200000
    assert corrected["is_verified"] is True

    filing_after = get_filing(filing["id"])
    assert filing_after["status"] == "DISPUTED"
    assert filing_after["total_revenue_cents"] == 200000
    assert get_org(org["id"])["total_revenue_cents"] == 0, (
        "a DISPUTED filing is excluded from the organization roll-up"
    )
