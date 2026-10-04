"""Civil investigative demand lifecycle: required fields, quash/enforce detour,
and the exclusive response deadline."""
from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    TEST_USERS,
    advance_clock,
    advance_investigation_to_state,
    api_client,
    create_company,
    create_draft_cid,
    create_investigation,
    enforce_cid,
    get_success_data,
    issue_cid,
    make_company_representative_headers,
    parse_iso,
    quash_cid,
    reset_clock_to_epoch,
    respond_to_cid,
    setup_issued_cid,
    validate_error,
    validate_success,
)

_ATTORNEY = TEST_USERS["staff_attorney_headers"]


def test_cid_create_missing_response_due_date_returns_400():
    """PRD section 3.2: "Each demand carries a `subject_matter` describing the
    documents or testimony demanded and a `response_due_date` fixing the
    company's deadline; its `investigation_id` binds it to the parent
    investigation."
    PRD section 2.8: "required fields present, enum values within their
    declared sets, integer and datetime types valid, else
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/cid_create_missing_response_due_date_returns_400
    """
    reset_clock_to_epoch()
    company = create_company()
    investigation = create_investigation(company["id"])
    advance_investigation_to_state(investigation["id"], "EVIDENCE_GATHERING")

    resp = api_client.create_cid(
        investigation["id"],
        {"subject_matter": TEST_DEFAULTS["CID_SUBJECT_MATTER"]},
        _ATTORNEY,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    rows = get_success_data(api_client.list_cids(investigation["id"], _ATTORNEY))
    assert rows == [], f"no CID row may be left behind, got {rows!r}"


def test_cid_quash_petition_enforced_then_late_response_accepted():
    """PRD section 3.2: "Court enforcement strips the deadline's protection —
    a demand in `ENFORCED` may still be answered to `RESPONDED` with a
    `response_document_ref`, and the overdue check no longer applies to that
    enforced response, though the ownership rule still does."

    Design: Corner/state_machines/cid_quash_petition_enforced_then_late_response_accepted
    """
    bundle = setup_issued_cid(response_due_date="2026-09-15T00:00:00Z")
    cid_id = bundle["cid"]["id"]
    company_id = bundle["company"]["id"]

    quash_cid(cid_id, company_id)
    enforce_cid(cid_id)
    advance_clock("2026-09-20T00:00:00Z")

    data = respond_to_cid(cid_id, company_id, response_document_ref="doc-production-1")
    assert data["status"] == "RESPONDED"
    assert parse_iso(data["responded_at"]) == parse_iso("2026-09-20T00:00:00Z")
    assert data["response_document_ref"] == "doc-production-1"


def test_cid_response_at_exact_due_instant_is_overdue():
    """PRD section 3.2: "the response must arrive while the logical clock is
    still strictly before `response_due_date`: a response attempted at or after
    the deadline fails with `ERR_CID_RESPONSE_OVERDUE`."

    Design: Corner/validations/cid_response_at_exact_due_instant_is_overdue
    """
    reset_clock_to_epoch()
    company = create_company()
    investigation = create_investigation(company["id"])
    advance_investigation_to_state(investigation["id"], "EVIDENCE_GATHERING")
    cid_1 = create_draft_cid(
        investigation["id"],
        response_due_date="2026-09-15T00:00:00Z",
        subject_matter="Pricing spreadsheets",
    )
    cid_2 = create_draft_cid(
        investigation["id"],
        response_due_date="2026-09-15T00:00:00Z",
        subject_matter="Marketing emails",
    )
    issue_cid(cid_1["id"])
    issue_cid(cid_2["id"])

    advance_clock("2026-09-14T00:00:00Z")
    early = respond_to_cid(cid_1["id"], company["id"], response_document_ref="doc-early")
    assert early["status"] == "RESPONDED"
    assert parse_iso(early["responded_at"]) == parse_iso("2026-09-14T00:00:00Z")

    advance_clock("2026-09-15T00:00:00Z")
    late = api_client.transition_cid(
        cid_2["id"],
        {"target_state": "RESPONDED", "response_document_ref": "doc-late"},
        make_company_representative_headers(company["id"]),
    )
    validate_error(late, ApiErrorId.ERR_CID_RESPONSE_OVERDUE)

    rows = get_success_data(api_client.list_cids(investigation["id"], _ATTORNEY))
    cid_2_after = next(r for r in rows if r["id"] == cid_2["id"])
    assert cid_2_after["status"] == "ISSUED"
    assert cid_2_after["responded_at"] is None
