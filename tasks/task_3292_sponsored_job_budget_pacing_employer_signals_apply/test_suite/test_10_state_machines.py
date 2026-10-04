"""Lifecycle transitions and their guard rails.

Each test drives one resource to a state and exercises either the declared
transition out of it or an undeclared one that must be refused.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    TEST_USERS, ApiErrorId,
    make_employer_headers, make_seeker_headers, set_clock, create_employer,
    create_seeker, create_posting, create_campaign, create_active_campaign,
    create_sponsored_job,
    get_campaign, get_posting, start_application, create_completed_application,
    assert_application, assert_campaign,
)

ADMIN = TEST_USERS["admin_headers"]
TRUST = TEST_USERS["trust_headers"]


def test_activating_a_draft_campaign_moves_it_to_active(api):
    """PRD §3.2: "Activation is an employer action permitted only while the
    owning employer's `status` is `ACTIVE`, and on success the campaign moves to
    `ACTIVE` and its `spent_cents` is re-derived from the sum of its ledger's
    `COMMIT` entries".
    PRD §2.4: "`version`, an integer that starts at its creation value and is
    incremented by exactly one on every mutation of that resource."

    Design: Corner/state_machines/campaign_activate_moves_draft_to_active
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Activate Co", domain="act.example")
    headers = make_employer_headers(employer["id"])
    campaign = create_campaign(employer, name="Act")

    activated = validate_success(api.activate_campaign(campaign["id"], headers), 200)
    assert_campaign(activated)
    assert activated["status"] == "ACTIVE"
    assert activated["version"] == 2


def test_activating_an_already_active_campaign_is_refused(api):
    """PRD §2.8: "4. **Lifecycle state.** The target resource must be in a state
    that permits the requested action. Failures here surface as ... or
    `ERR_INVALID_STATE_TRANSITION`, all HTTP 409."

    Design: Corner/state_machines/campaign_activate_when_already_active_returns_invalid_state
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Double Co", domain="dbl.example")
    headers = make_employer_headers(employer["id"])
    campaign = create_active_campaign(employer, name="Dbl")

    res = api.activate_campaign(campaign["id"], headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)
    assert get_campaign(campaign["id"], employer)["status"] == "ACTIVE"


def test_posting_expiry_pauses_its_sponsored_job(api):
    """PRD §3.1: "A posting that goes `STALE` → `EXPIRED`, or directly `ACTIVE`
    → `EXPIRED` when a single re-derivation skips the intermediate freshness, is
    terminal for distribution, and every `SponsoredJob` sponsoring that posting
    is moved to `PAUSED` in the same response."

    Design: Corner/state_machines/sponsored_job_paused_when_posting_freshness_expires
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Expire Co", domain="exp.example")
    headers = make_employer_headers(employer["id"])
    posting = create_posting(employer, title="Expiring Engineer",
                             location="Tulsa, OK", description_text="Expiry side effect.")
    campaign = create_active_campaign(employer, name="EX")
    sponsored_job = create_sponsored_job(campaign, posting, employer)

    get_success_data(api.set_current_utc({"current_utc": "2026-11-05T00:00:00Z"}, ADMIN))

    assert get_posting(posting["id"])["state"] == "EXPIRED"
    assert get_success_data(api_client.get_sponsored_job(
        sponsored_job["id"], headers))["status"] == "PAUSED"
    assert get_campaign(campaign["id"], employer)["status"] == "ACTIVE"


def test_completing_a_closed_application_is_refused(api):
    """PRD §3.6: "The application must be in `STARTED`; any other state fails
    with `ERR_INVALID_APPLICATION_STATE` (HTTP 409)."

    Design: Corner/state_machines/application_complete_from_closed_returns_invalid_state
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Close Co", domain="cls.example")
    seeker = create_seeker(full_name="Close Seeker")
    posting = create_posting(employer, title="Close Engineer")
    seeker_headers = make_seeker_headers(seeker["id"])

    application = start_application(posting, seeker)
    validate_success(api.close_application(application["id"], seeker_headers), 200)

    res = api.complete_application(application["id"], {}, seeker_headers)
    assert res.status_code == 409
    error_id = res.json()["data"]["error_id"]
    assert error_id in (
        ApiErrorId.ERR_INVALID_APPLICATION_STATE.value,
        ApiErrorId.ERR_APPLICATION_ALREADY_TERMINAL.value,
    )


def test_starting_an_application_yields_started_and_counts_the_start(api):
    """PRD §3.6: "An apply flow begins when a `JobSeeker` creates an application
    against a posting ... The application begins in `STARTED` with `started_at`
    stamped from the logical clock, its `completed_at` and `responded_at` both
    null, and its `disposition` set to `NONE`. Creating it increments the
    posting's `apply_started_count` by one."

    Design: Corner/state_machines/application_initial_state_is_started
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Start Co", domain="str.example")
    seeker = create_seeker(full_name="Start Seeker")
    posting = create_posting(employer, title="Start Engineer",
                             apply_mode="ATS_REDIRECT",
                             apply_redirect_url="https://ats.example/apply/1")

    res = api.create_application({
        "job_posting_id": posting["id"],
        "job_seeker_id": seeker["id"],
    }, make_seeker_headers(seeker["id"]))

    application = validate_success(res, 201)
    assert_application(application)
    assert application["status"] == "STARTED"
    assert application["completed_at"] is None
    assert application["disposition"] == "NONE"

    live_posting = get_posting(posting["id"], ADMIN)
    assert live_posting["apply_started_count"] == 1
    assert live_posting["apply_completed_count"] == 0


def test_closing_an_application_twice_is_refused(api):
    """PRD §3.6: "`CLOSED` is the application's only terminal state, and any
    further transition attempted against a closed application is rejected with
    `ERR_APPLICATION_ALREADY_TERMINAL` (HTTP 409)."

    Design: Corner/state_machines/application_close_twice_returns_already_terminal
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Terminal Co", domain="term.example")
    headers = make_employer_headers(employer["id"])
    seeker = create_seeker(full_name="Terminal Seeker")
    posting = create_posting(employer, title="Terminal Engineer")

    application = create_completed_application(posting, seeker, employer)
    validate_success(api.close_application(application["id"], headers), 200)

    res = api.close_application(application["id"], headers)
    validate_error(res, ApiErrorId.ERR_APPLICATION_ALREADY_TERMINAL.value, expected_status=409)


def test_reinstating_an_active_employer_is_refused(api):
    """PRD §3.1: "Reinstatement requires the employer to be `SUSPENDED` — a
    request against an `ACTIVE` employer is rejected with
    `ERR_EMPLOYER_NOT_SUSPENDED` (HTTP 409)".

    Design: Corner/state_machines/employer_reinstate_when_active_returns_not_suspended
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Live Co", domain="live.example")

    res = api.reinstate_employer(employer["id"], TRUST)
    validate_error(res, ApiErrorId.ERR_EMPLOYER_NOT_SUSPENDED.value, expected_status=409)
    assert get_success_data(api_client.get_employer(employer["id"], ADMIN))["status"] == "ACTIVE"