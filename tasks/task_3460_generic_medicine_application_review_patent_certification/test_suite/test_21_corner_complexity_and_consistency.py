"""Queue B / complexity_layers + consistency_model: OCC and immediate reads."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    set_clock, make_applicant, make_reference_product, make_application,
    add_be_study, make_listed_patent, add_certification, submit_application,
    get_application, list_awards, setup_submitted, send_notice,
    make_applicant_headers,
)

REVIEWER = TEST_USERS["regulatory_reviewer_headers"]


def test_occ_stale_version_on_amendment_returns_412_then_fresh_succeeds():
    """PRD section 2.6: "If the application's current `version` no longer
    matches — that is, the client is acting on a stale view of the
    application — the write is rejected with `ERR_STALE_VERSION` (HTTP 412)
    and nothing is persisted."

    Design: Corner/complexity_layers/occ_stale_version_on_amendment_returns_412_then_fresh_succeeds
    """
    applicant = make_applicant(legal_name="Occ Co")
    rld = make_reference_product(brand_name="Occex", rld_approval_date="2000-01-01")
    patent = make_listed_patent(rld, patent_number="US1818001")
    app = make_application(rld["id"], applicant["id"])
    stale_version = app["version"]
    headers = make_applicant_headers(applicant["id"])
    add_be_study(app["id"], applicant["id"])
    add_certification(app["id"], applicant["id"], patent["id"], "PARAGRAPH_III_DEFER")
    submit_application(app["id"], applicant["id"])
    fresh_version = get_application(app["id"])["version"]
    assert fresh_version > stale_version, "cert creation and submit each bumped version"

    stale = api_client.create_amendment(app["id"], {
        "classification": "MINOR", "contains_new_be_data": False,
        "expected_application_version": stale_version}, headers)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert stale.status_code == 412

    fresh = api_client.create_amendment(app["id"], {
        "classification": "MINOR", "contains_new_be_data": False,
        "expected_application_version": fresh_version}, headers)
    validate_success(fresh, 201)
    assert get_application(app["id"])["version"] == fresh_version + 1, (
        "exactly one successful mutation landed")


def test_approval_decision_and_dependent_reads_agree_immediately():
    """PRD section 3.7: "When both gates are clear, `APPROVE` yields
    `APPROVED`: `approval_date` is stamped, the current cycle closes with
    `closed_reason` `APPROVAL`, an `ELIGIBLE` award held by this application
    converts to `AWARDED`, and `version` increments by one." PRD section 3.8:
    "When the award-holding application reaches `APPROVED` — directly or
    through the re-evaluation of §3.7 — the award converts to `AWARDED`:
    `awarded_date` and the copied `approval_date` are set, and
    `marketing_deadline` is computed as the calendar date 75 days after the
    approval date." The very next read therefore agrees.

    Design: Corner/consistency_model/approval_decision_and_dependent_reads_agree_immediately
    """
    ctx = setup_submitted(with_facility=True, patent_expiry="2030-01-01",
                          cert_type="PARAGRAPH_IV_CHALLENGE")
    app_id, ac_id = ctx["app"]["id"], ctx["applicant"]["id"]
    send_notice(ctx["cert"]["id"], ac_id)

    set_clock("2026-12-01T00:00:00Z")
    decided = validate_success(api_client.approval_decision(
        app_id, {"decision": "APPROVE"}, REVIEWER), 200)
    assert decided["status"] == "APPROVED"
    assert decided["approval_date"] == "2026-12-01"

    awards = list_awards(application_id=app_id)
    assert awards[0]["status"] == "AWARDED", (
        "the award conversion is visible in the immediately following read")
    assert awards[0]["marketing_deadline"] == "2027-02-14"
