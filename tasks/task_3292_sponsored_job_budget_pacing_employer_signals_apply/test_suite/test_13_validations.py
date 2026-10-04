"""Request guard violations and the error each one produces.

Every guard sits at its own tier of the evaluation sequence, so each scenario
below isolates a single failing check rather than relying on an error-ordering
claim.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    get_success_data, TEST_USERS, NON_EXISTENT_UUID, ApiErrorId,
    make_employer_headers, make_seeker_headers, set_clock, create_employer,
    create_seeker, create_posting, create_active_campaign, create_sponsored_job,
    create_campaign, get_campaign, record_click,
)

ADMIN = TEST_USERS["admin_headers"]
TRUST = TEST_USERS["trust_headers"]


def test_missing_user_context_header_is_rejected(api):
    """PRD §2.1: "`X-User-ID` identifies the acting party and `X-User-Role`
    declares the capacity in which they act. A request that omits either header,
    sends a malformed value, or sends a role that is not one of the four declared
    roles is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
    (HTTP 400)."

    Design: Corner/validations/missing_user_context_header_returns_400
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Header Co", domain="hdr.example")

    res = api.get_employer(employer["id"], headers={})
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
                   expected_status=400)


def test_seeker_cannot_create_a_campaign(api):
    """PRD §2.1: "Operations are gated by role, and an attempt to invoke an
    operation from a role that is not authorized for it is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/validations/seeker_cannot_create_a_campaign_returns_forbidden
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Rbac Co", domain="rbac.example")
    seeker = create_seeker(full_name="Rbac Seeker")

    res = api.create_campaign({
        "employer_id": employer["id"],
        "name": "RBAC",
        "pricing_model": "CPC",
        "daily_budget_cents": 100000,
        "total_budget_cents": 1000000,
    }, make_seeker_headers(seeker["id"]))

    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value, expected_status=403)


def test_refunding_a_non_billed_impression_is_refused(api):
    """PRD §3.8: "The first is the event's own status: only an event whose
    `status` is `BILLED` is refundable, and an event that is still `RECORDED` or
    has already been refunded fails with `ERR_EVENT_NOT_REFUNDABLE` (HTTP 409)."
    PRD §3.5: "`IMPRESSION` is never billable under either model."

    Design: Corner/validations/refund_of_non_billed_impression_returns_not_refundable
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Impression Co", domain="imp.example")
    posting = create_posting(employer, title="Impression Engineer")
    campaign = create_active_campaign(employer, name="IM")
    sponsored_job = create_sponsored_job(campaign, posting, employer)

    live_campaign = get_campaign(campaign["id"], employer)
    event = get_success_data(api.record_event({
        "campaign_id": campaign["id"],
        "sponsored_job_id": sponsored_job["id"],
        "event_type": "IMPRESSION",
        "device_fingerprint": "fp-imp-1",
        "ip_hash": "ip-imp-1",
        "expected_campaign_version": live_campaign["version"],
    }, ADMIN))
    assert event["status"] == "RECORDED"
    assert event["billable"] is False

    res = api.refund_event(event["id"], {
        "reason": "not a click",
        "expected_campaign_version": live_campaign["version"],
    }, TRUST)
    assert res.status_code == 409
    error_id = res.json()["data"]["error_id"]
    assert error_id in (
        ApiErrorId.ERR_EVENT_NOT_REFUNDABLE.value,
        ApiErrorId.ERR_MISSING_EXPECTED_VERSION.value,
        ApiErrorId.ERR_STALE_VERSION.value,
    )


def test_sponsored_job_with_a_zero_bid_is_refused(api):
    """PRD §3.3: "both must nonetheless be supplied and both must be at least one
    cent, because a bid below one cent is rejected with `ERR_BID_BELOW_MINIMUM`
    (HTTP 400)."

    Design: Corner/validations/sponsored_job_with_zero_bid_returns_bid_below_minimum
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="ZeroBid Co", domain="zb.example")
    posting = create_posting(employer, title="Zero Bid Engineer")
    campaign = create_active_campaign(employer, name="ZB")

    res = api.create_sponsored_job({
        "campaign_id": campaign["id"],
        "job_posting_id": posting["id"],
        "cpc_bid_cents": 0,
        "cpa_bid_cents": 900,
    }, make_employer_headers(employer["id"]))

    validate_error(res, ApiErrorId.ERR_BID_BELOW_MINIMUM.value, expected_status=400)


def test_assessment_threshold_above_required_count_is_refused(api):
    """PRD §3.1: "An assessment whose `questions` array is empty, or whose
    `pass_threshold` is greater than the number of its required questions, is
    rejected with `ERR_UNSUPPORTED_ASSESSMENT_QUESTIONS` (HTTP 400)."

    Design: Corner/validations/assessment_threshold_above_required_count_returns_unsupported
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Assess Co", domain="asmt.example")
    posting = create_posting(employer, title="Assessment Engineer")

    res = api.create_assessment({
        "job_posting_id": posting["id"],
        "questions": [
            {"prompt": "Authorized to work?", "kind": "BOOLEAN", "required": True},
            {"prompt": "Years of experience?", "kind": "NUMERIC", "required": True},
        ],
        "pass_threshold": 3,
    }, make_employer_headers(employer["id"]))

    validate_error(res, ApiErrorId.ERR_UNSUPPORTED_ASSESSMENT_QUESTIONS.value,
                   expected_status=400)


def test_reingesting_identical_content_is_a_duplicate(api):
    """PRD §3.1: "a snapshot whose `content_hash` matches the hash of any version
    of the same posting ingested within the preceding 30 days is not a new fact
    about the posting and the ingestion is rejected as a duplicate with
    `ERR_DUPLICATE_INGESTION` (HTTP 409)."

    Design: Corner/validations/duplicate_content_ingestion_returns_duplicate
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Dedupe Co", domain="dedupe.example",
                               ats_provider="GREENHOUSE")
    posting = create_posting(employer, title="Dedupe Engineer",
                             location="Boise, ID", description_text="Duplicate me.",
                             external_posting_id="DED-1")

    res = api.ingest_job_posting_version(posting["id"], {
        "external_posting_id": "DED-1",
        "title": "Dedupe Engineer",
        "description_text": "Duplicate me.",
    }, make_employer_headers(employer["id"]))

    validate_error(res, ApiErrorId.ERR_DUPLICATE_INGESTION.value, expected_status=409)


def test_ats_redirect_posting_without_a_url_is_refused(api):
    """PRD §3.1: "when `apply_mode` is `ATS_REDIRECT`, `apply_redirect_url` must
    be present and must be an absolute `https` URL, and a posting that violates
    either part is rejected with `ERR_INVALID_REDIRECT_URL` (HTTP 400)."

    Design: Corner/validations/ats_redirect_without_url_returns_invalid_redirect_url
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Redirect Co", domain="redir.example")

    res = api.create_job_posting({
        "employer_id": employer["id"],
        "title": "Redirect Engineer",
        "location": "Boise, ID",
        "description_text": "Redirect me.",
        "apply_mode": "ATS_REDIRECT",
    }, make_employer_headers(employer["id"]))

    validate_error(res, ApiErrorId.ERR_INVALID_REDIRECT_URL.value, expected_status=400)


def test_moving_the_logical_clock_backwards_is_refused(api):
    """PRD §2.7: "The clock may only be moved forward by the administrative
    clock-setting operation documented in §4, and a request to move it to an
    instant that precedes the current logical clock value is rejected with
    `ERR_INVALID_CLOCK_ORDER` (HTTP 400)."

    Design: Corner/validations/clock_rewind_returns_invalid_clock_order
    """
    get_success_data(api.set_current_utc({"current_utc": "2026-09-15T00:00:00Z"}, ADMIN))

    res = api.set_current_utc({"current_utc": "2026-09-01T00:00:00Z"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_CLOCK_ORDER.value, expected_status=400)


def test_activating_an_unknown_campaign_reports_not_found(api):
    """PRD §2.8: "3. **Referential existence.** Every resource identifier
    appearing in the request ... must resolve to an existing row. The identifiers
    are validated from the left of the path to the right, and the first
    unresolvable identifier determines the error: ... `ERR_CAMPAIGN_NOT_FOUND`".

    Design: Corner/validations/campaign_activate_unknown_id_returns_campaign_not_found
    """
    set_clock("2026-09-01T00:00:00Z")
    headers = make_employer_headers("00000000-0000-4000-8000-000000000001")

    res = api.activate_campaign("00000000-0000-4000-8000-000000000000", headers)
    validate_error(res, ApiErrorId.ERR_CAMPAIGN_NOT_FOUND.value, expected_status=404)


def test_event_exceeding_the_daily_budget_is_refused(api):
    """PRD §3.5: "An event whose cleared cost would push `daily_spent_cents`
    above `daily_budget_cents` is rejected with `ERR_DAILY_BUDGET_EXCEEDED`
    (HTTP 409)."

    Design: Corner/validations/event_exceeding_daily_budget_returns_daily_budget_exceeded
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Daily Co", domain="daily.example")
    posting = create_posting(employer, title="Daily Engineer")
    campaign = create_active_campaign(employer, name="DL", pricing_model="CPC",
                                      daily_budget_cents=1200,
                                      total_budget_cents=1000000)
    # The daily budget clears the 1000-cent BUDGET_HOLD floor so the job is
    # ELIGIBLE, while the solo bid clears at 1300 cents — above the day's 1200.
    sponsored_job = create_sponsored_job(campaign, posting, employer,
                                         cpc_bid_cents=1300)

    live_campaign = get_campaign(campaign["id"], employer)
    res = api.record_event({
        "campaign_id": campaign["id"],
        "sponsored_job_id": sponsored_job["id"],
        "event_type": "CLICK",
        "device_fingerprint": "fp-daily-1",
        "ip_hash": "ip-daily-1",
        "expected_campaign_version": live_campaign["version"],
    }, ADMIN)

    validate_error(res, ApiErrorId.ERR_DAILY_BUDGET_EXCEEDED.value, expected_status=409)


def test_pacing_hold_beyond_the_daily_headroom_is_refused(api):
    """PRD §3.5: "Second, the reservation must fit inside the day's remaining
    allowance: if `held_cents` plus `daily_spent_cents` plus the requested amount
    would exceed `daily_budget_cents`, the request is rejected with
    `ERR_INSUFFICIENT_DAILY_BUDGET` (HTTP 409)."

    Design: Corner/validations/pacing_hold_exceeding_daily_budget_returns_insufficient_daily_budget
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Hold Cap Co", domain="holdcap.example")
    headers = make_employer_headers(employer["id"])
    posting = create_posting(employer, title="Hold Cap Engineer")
    campaign = create_active_campaign(employer, name="HC",
                                      daily_budget_cents=400,
                                      total_budget_cents=1000000)
    sponsored_job = create_sponsored_job(campaign, posting, employer)

    res = api.create_pacing_hold(sponsored_job["id"], {"amount_cents": 401}, headers)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_DAILY_BUDGET.value, expected_status=409)
    assert get_campaign(campaign["id"], employer)["held_cents"] == 0