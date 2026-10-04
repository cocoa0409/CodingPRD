"""Concurrency preconditions on campaign writes.

Two write operations — recording a sponsored event and granting a refund —
require the caller to prove it has an up-to-date view of the affected campaign.
A superseded view is refused before any ledger effect is applied.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, TEST_USERS,
    ApiErrorId, make_employer_headers, set_clock, create_employer, create_posting,
    create_active_campaign, create_sponsored_job, get_campaign, record_click,
    refund_payload, assert_campaign,
)

ADMIN = TEST_USERS["admin_headers"]
TRUST = TEST_USERS["trust_headers"]


def _occ_scenario():
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Occ Co", domain="occ.example")
    headers = make_employer_headers(employer["id"])
    posting = create_posting(employer, title="Occ Engineer")
    campaign = create_active_campaign(employer, name="OC")
    sponsored_job = create_sponsored_job(campaign, posting, employer)
    return employer, headers, campaign, sponsored_job


def test_event_with_a_stale_campaign_version_is_refused(api):
    """PRD §2.9: "If the field is present but does not equal the campaign's
    current `version` — because any other write has advanced the campaign since
    the caller last read it — the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412), and no event is recorded, no refund is granted, and no ledger
    entry is appended."

    Design: Corner/cross_cutting_complexity_layers/stale_campaign_version_on_event_returns_412
    """
    employer, headers, campaign, sponsored_job = _occ_scenario()

    stale_version = get_campaign(campaign["id"], employer)["version"]
    # First write advances the campaign version legitimately.
    record_click(campaign, sponsored_job, employer,
                 device_fingerprint="fp-occ1a", expected_version=stale_version)
    advanced = get_campaign(campaign["id"], employer)
    assert advanced["version"] > stale_version

    res = api.record_event({
        "campaign_id": campaign["id"],
        "sponsored_job_id": sponsored_job["id"],
        "event_type": "CLICK",
        "device_fingerprint": "fp-occ1b",
        "ip_hash": "ip-occ1b",
        "expected_campaign_version": stale_version,
    }, ADMIN)

    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)
    unchanged = get_campaign(campaign["id"], employer)
    assert unchanged["spent_cents"] == advanced["spent_cents"]


def test_refund_with_a_stale_campaign_version_is_refused(api):
    """PRD §3.8: "The fourth is the concurrency precondition of §2.9, which
    rejects a caller whose view of the campaign is stale with
    `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/stale_campaign_version_on_refund_returns_412
    """
    employer, headers, campaign, sponsored_job = _occ_scenario()

    version = get_campaign(campaign["id"], employer)["version"]
    event = record_click(campaign, sponsored_job, employer,
                         device_fingerprint="fp-occ2a", expected_version=version)
    # A second click commits against the campaign, advancing its version.
    record_click(campaign, sponsored_job, employer, device_fingerprint="fp-occ2b")

    res = api.refund_event(event["id"], refund_payload(version), TRUST)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


def test_fresh_campaign_version_is_accepted(api):
    """PRD §2.9: "Both must carry a non-optional request field named
    `expected_campaign_version` holding the value of `version` that the caller
    last observed on the campaign."

    Design: Corner/cross_cutting_complexity_layers/stale_campaign_version_on_event_returns_412
    """
    employer, headers, campaign, sponsored_job = _occ_scenario()

    version = get_campaign(campaign["id"], employer)["version"]
    res = api.record_event({
        "campaign_id": campaign["id"],
        "sponsored_job_id": sponsored_job["id"],
        "event_type": "CLICK",
        "device_fingerprint": "fp-occ3a",
        "ip_hash": "ip-occ3a",
        "expected_campaign_version": version,
    }, ADMIN)

    event = validate_success(res, 201)
    assert event["status"] == "BILLED"
    assert event["cost_cents"] > 0