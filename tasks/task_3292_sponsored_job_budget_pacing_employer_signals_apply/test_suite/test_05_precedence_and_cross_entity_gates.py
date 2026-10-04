"""Graded request evaluation and cross-entity state dependencies.

Request guards run in a fixed sequence and the first failure wins, so a state
failure pre-empts a fiscal one and a safety failure pre-empts a coherence one.
Separately, resuming one resource is gated on the state of another.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    validate_paginated, get_success_data, TEST_USERS, ApiErrorId,
    make_employer_headers, set_clock, create_employer, create_posting,
    create_active_campaign, create_sponsored_job, get_campaign, get_posting,
    record_click,
)

ADMIN = TEST_USERS["admin_headers"]
TRUST = TEST_USERS["trust_headers"]


# ─── Priority pair: state vs fiscal ───────────────────

def test_completed_campaign_state_failure_preempts_daily_budget_failure(api):
    """PRD §2.8: "When a request arrives, the following checks run in this fixed
    sequence, and the first one that fails terminates the request with its own
    error without later checks being attempted."
    PRD §3.5: "The campaign identified must be in `ACTIVE` status — anything else
    fails with `ERR_CAMPAIGN_NOT_ACTIVE` — and the sponsored job must be in a
    serving state, failing with `ERR_SPONSORED_JOB_NOT_ELIGIBLE` otherwise."

    Design: Difficulty/priority_pair_validation_conflict/events_completed_campaign_beats_daily_budget_check
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="PriCo", domain="pri.example")
    headers = make_employer_headers(employer["id"])
    campaign = create_active_campaign(
        employer, name="PR", pricing_model="CPC",
        daily_budget_cents=3000, total_budget_cents=3000)
    posting = create_posting(employer, title="Priority Engineer",
                             description_text="Priority one.")
    sponsored_job = create_sponsored_job(campaign, posting, employer,
                                         cpc_bid_cents=3000)

    # Drive the campaign to its terminal state with a 3000-cent click.
    record_click(campaign, sponsored_job, employer, device_fingerprint="fp-pr-1")
    completed = get_campaign(campaign["id"], employer)
    assert completed["status"] == "COMPLETED"

    res = api.record_event({
        "campaign_id": campaign["id"],
        "sponsored_job_id": sponsored_job["id"],
        "event_type": "CLICK",
        "device_fingerprint": "fp-pr-2",
        "ip_hash": "ip-pr-2",
        "expected_campaign_version": completed["version"],
    }, ADMIN)

    assert res.status_code == 409
    error_id = validate_error_is_one_of(res, [
        ApiErrorId.ERR_CAMPAIGN_NOT_ACTIVE.value,
        ApiErrorId.ERR_CAMPAIGN_TERMINAL.value,
        ApiErrorId.ERR_SPONSORED_JOB_NOT_ELIGIBLE.value,
    ])
    assert error_id not in (
        ApiErrorId.ERR_DAILY_BUDGET_EXCEEDED.value,
        ApiErrorId.ERR_TOTAL_BUDGET_EXCEEDED.value,
    ), "a lifecycle failure must pre-empt the fiscal capacity checks"


def test_rejected_second_event_on_completed_campaign_changes_nothing(api):
    """PRD §2.8: "a request whose path is malformed and whose payload is also
    missing required fields fails on the missing-required-field rule only after
    every preceding tier has passed" — the earlier tier's failure terminates the
    request before any later work is done.

    Design: Difficulty/priority_pair_validation_conflict/events_completed_campaign_beats_daily_budget_check
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="PriCo2", domain="pri2.example")
    headers = make_employer_headers(employer["id"])
    campaign = create_active_campaign(
        employer, name="PR2", pricing_model="CPC",
        daily_budget_cents=3000, total_budget_cents=3000)
    posting = create_posting(employer, title="Priority Engineer II",
                             description_text="Priority two.")
    sponsored_job = create_sponsored_job(campaign, posting, employer,
                                         cpc_bid_cents=3000)

    record_click(campaign, sponsored_job, employer, device_fingerprint="fp-pr-3")
    before = get_campaign(campaign["id"], employer)

    res = api.record_event({
        "campaign_id": campaign["id"],
        "sponsored_job_id": sponsored_job["id"],
        "event_type": "CLICK",
        "device_fingerprint": "fp-pr-4",
        "ip_hash": "ip-pr-4",
        "expected_campaign_version": before["version"],
    }, ADMIN)
    assert res.status_code == 409

    after = get_campaign(campaign["id"], employer)
    assert after["status"] == "COMPLETED"
    assert after["spent_cents"] == before["spent_cents"] == 3000


# ─── Priority pair: fraud safety vs redirect coherence ───

def test_fraud_keyword_preempts_missing_redirect_url(api):
    """PRD §2.8: "5. **Fraud and trust safety.** The acting employer must not be
    `SUSPENDED`, and submitted posting content must not contain a
    misleading-posting keyword."
    PRD §3.1: "If the submitted `title` or `description_text` carries any
    misleading-posting keyword — the canonical examples being an instruction to
    send a wire transfer, a demand for an upfront fee, or a request to pay to
    start — the ingestion or posting creation is rejected with
    `ERR_FRAUD_KEYWORDS_DETECTED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/posting_creation_fraud_keyword_beats_redirect_url_constraint
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="SafetyCo", domain="safety.example")

    res = api.create_job_posting({
        "employer_id": employer["id"],
        "title": "Work From Home - Upfront Fee",
        "location": "Remote",
        "description_text": "Pay to start today.",
        "apply_mode": "ATS_REDIRECT",
    }, make_employer_headers(employer["id"]))

    validate_error(res, ApiErrorId.ERR_FRAUD_KEYWORDS_DETECTED.value, expected_status=409)


def test_rejected_fraud_posting_is_not_persisted(api):
    """PRD §3.1: "the ingestion or posting creation is rejected with
    `ERR_FRAUD_KEYWORDS_DETECTED` (HTTP 409)" — a rejected creation leaves no
    posting behind.

    Design: Difficulty/priority_pair_validation_conflict/posting_creation_fraud_keyword_beats_redirect_url_constraint
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="SafetyCo2", domain="safety2.example")

    res = api.create_job_posting({
        "employer_id": employer["id"],
        "title": "Send a Wire Transfer to Begin",
        "location": "Remote",
        "description_text": "Contact us to arrange the transfer.",
        "apply_mode": "ATS_REDIRECT",
    }, make_employer_headers(employer["id"]))
    assert res.status_code == 409
    assert res.json()["data"]["error_id"] == ApiErrorId.ERR_FRAUD_KEYWORDS_DETECTED.value

    listed_res = api.list_job_postings(ADMIN, params={"employer_id": employer["id"]})
    data, meta = validate_paginated(listed_res)
    assert meta["total_count"] == 0
    assert data == []


# ─── Cross-entity gating: sponsored job resume ────────

def test_sponsored_job_resume_rejected_when_posting_expired(api):
    """PRD §3.3: "The sponsored job may be resumed only when its campaign's
    `status` is `ACTIVE`, when the sponsored job's `JobPosting` state is
    `ACTIVE`, and when the campaign's owning employer is not `SUSPENDED`."
    PRD §3.3: "an operation that requires an `ACTIVE` posting and finds the
    posting `DRAFT`, `STALE`, `EXPIRED` or `SUSPENDED` fails with
    `ERR_POSTING_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/sponsored_job_resume_requires_posting_active
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="PairCo", domain="pair.example")
    headers = make_employer_headers(employer["id"])
    posting = create_posting(employer, title="Pair Engineer",
                             description_text="Pair dependency.")
    campaign = create_active_campaign(employer, name="PP")
    sponsored_job = create_sponsored_job(campaign, posting, employer)

    get_success_data(api.set_current_utc({"current_utc": "2026-11-05T00:00:00Z"}, ADMIN))

    # The decay is a precondition of the test, not the claim under test.
    assert get_posting(posting["id"])["state"] == "EXPIRED"
    assert get_success_data(api_client.get_sponsored_job(
        sponsored_job["id"], headers))["status"] == "PAUSED"
    assert get_campaign(campaign["id"], employer)["status"] == "ACTIVE"

    res = api.resume_sponsored_job(sponsored_job["id"], headers)
    assert res.status_code == 409
    validate_error_is_one_of(res, [
        ApiErrorId.ERR_POSTING_NOT_ACTIVE.value,
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
    ])


def test_failed_resume_leaves_sponsored_job_paused(api):
    """PRD §3.3: "A successful resume returns the sponsored job to `ELIGIBLE`
    and re-admits it to the candidate set." — a resume blocked by the posting's
    state does not re-admit it.

    Design: Difficulty/cross_entity_state_dependency/sponsored_job_resume_requires_posting_active
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="PairCo2", domain="pair2.example")
    headers = make_employer_headers(employer["id"])
    posting = create_posting(employer, title="Pair Engineer II",
                             description_text="Pair dependency two.")
    campaign = create_active_campaign(employer, name="PP2")
    sponsored_job = create_sponsored_job(campaign, posting, employer)

    get_success_data(api.set_current_utc({"current_utc": "2026-11-05T00:00:00Z"}, ADMIN))
    res = api.resume_sponsored_job(sponsored_job["id"], headers)
    assert res.status_code == 409

    still_paused = get_success_data(api_client.get_sponsored_job(
        sponsored_job["id"], headers))
    assert still_paused["status"] == "PAUSED"


# ─── Cross-entity gating: campaign resume ─────────────

def test_campaign_resume_rejected_when_employer_suspended(api):
    """PRD §3.2: "Resuming is permitted only from `PAUSED`, and only when the
    campaign's `spent_cents` is still strictly below its `total_budget_cents` and
    the owning employer's `status` is `ACTIVE`."
    PRD §3.1: "The same guard blocks an employer whose `status` is `SUSPENDED`
    from creating postings, campaigns, sponsored jobs or events at all, in each
    case with `ERR_EMPLOYER_SUSPENDED` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/campaign_resume_requires_employer_active
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="GateCo", domain="gate.example")
    headers = make_employer_headers(employer["id"])
    posting = create_posting(employer, title="Gate Engineer",
                             location="Reno, NV",
                             description_text="Gate dependency.")
    campaign = create_active_campaign(employer, name="GT")
    create_sponsored_job(campaign, posting, employer)

    suspended = get_success_data(api.suspend_employer(
        employer["id"], {"reason": "Account under review"}, TRUST))
    assert suspended["status"] == "SUSPENDED"
    assert get_campaign(campaign["id"], employer)["status"] == "PAUSED"

    res = api.resume_campaign(campaign["id"], headers)
    validate_error(res, ApiErrorId.ERR_EMPLOYER_SUSPENDED.value, expected_status=409)


def test_failed_campaign_resume_leaves_campaign_paused(api):
    """PRD §3.2: "Resuming is permitted only from `PAUSED`, and only when the
    campaign's `spent_cents` is still strictly below its `total_budget_cents` and
    the owning employer's `status` is `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/campaign_resume_requires_employer_active
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="GateCo2", domain="gate2.example")
    headers = make_employer_headers(employer["id"])
    posting = create_posting(employer, title="Gate Engineer II",
                             description_text="Gate dependency two.")
    campaign = create_active_campaign(employer, name="GT2")
    create_sponsored_job(campaign, posting, employer)

    get_success_data(api.suspend_employer(
        employer["id"], {"reason": "Account under review"}, TRUST))
    res = api.resume_campaign(campaign["id"], headers)
    assert res.status_code == 409

    assert get_campaign(campaign["id"], employer)["status"] == "PAUSED"