"""Action endpoints: billing decisions, cascades and reverse lookups.

Whether an event costs anything depends on both its type and the campaign's
pricing model; pausing a campaign cascades to its sponsored jobs; sub-resource
collections are reachable through their parent.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_paginated, get_success_data,
    TEST_USERS, make_employer_headers, make_seeker_headers,
    set_clock, create_employer, create_seeker, create_posting,
    create_active_campaign, create_sponsored_job, get_campaign, get_posting,
    start_application, ingest_version,
    assert_apply_event, assert_sponsor_event, assert_version_incremented,
)

ADMIN = TEST_USERS["admin_headers"]


def test_impression_is_recorded_without_billing(api):
    """PRD §3.5: "an `IMPRESSION` is never billable under either model. A
    non-billable event carries a `cost_cents` of 0 and does not touch the ledger
    or the campaign's spend counters at all".

    Design: Corner/endpoints/impression_event_is_recorded_but_not_billable
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Impr Co", domain="impr.example")
    headers = make_employer_headers(employer["id"])
    posting = create_posting(employer, title="Impr Engineer")
    campaign = create_active_campaign(employer, name="IM2")
    sponsored_job = create_sponsored_job(campaign, posting, employer)

    live_campaign = get_campaign(campaign["id"], employer)
    event = get_success_data(api.record_event({
        "campaign_id": campaign["id"],
        "sponsored_job_id": sponsored_job["id"],
        "event_type": "IMPRESSION",
        "device_fingerprint": "fp-impr-1",
        "ip_hash": "ip-impr-1",
        "expected_campaign_version": live_campaign["version"],
    }, ADMIN))

    assert_sponsor_event(event)
    assert event["event_type"] == "IMPRESSION"
    assert event["billable"] is False
    assert event["cost_cents"] == 0
    assert get_campaign(campaign["id"], employer)["spent_cents"] == 0

    served = get_success_data(api_client.get_sponsored_job(sponsored_job["id"], headers))
    assert served["impressions"] == 1
    assert served["clicks"] == 0


def test_click_on_a_cpa_campaign_is_recorded_but_not_billed(api):
    """PRD §3.5: "a `CLICK` on a `CPA` campaign is recorded and counted but never
    charged, an `APPLICATION` on a `CPC` campaign is recorded and counted but
    never charged".
    PRD §3.4: "a `CPC` campaign clears on `cpc_bid_cents` and bills one charge per
    click, while a `CPA` campaign clears on `cpa_bid_cents` and bills one charge
    per application, recording click events without billing them."

    Design: Corner/endpoints/cpa_campaign_records_clicks_without_billing
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Cpa Co", domain="cpa.example")
    posting = create_posting(employer, title="Cpa Engineer")
    campaign = create_active_campaign(employer, name="CPA", pricing_model="CPA")
    sponsored_job = create_sponsored_job(campaign, posting, employer,
                                         cpa_bid_cents=900)

    live_campaign = get_campaign(campaign["id"], employer)
    event = get_success_data(api.record_event({
        "campaign_id": campaign["id"],
        "sponsored_job_id": sponsored_job["id"],
        "event_type": "CLICK",
        "device_fingerprint": "fp-cpa-1",
        "ip_hash": "ip-cpa-1",
        "expected_campaign_version": live_campaign["version"],
    }, ADMIN))

    assert event["event_type"] == "CLICK"
    assert event["billable"] is False
    assert event["cost_cents"] == 0
    assert get_campaign(campaign["id"], employer)["spent_cents"] == 0


def test_posting_versions_lists_every_ingested_snapshot(api):
    """PRD §2.10: "Some resources are addressed only through their parent — a job
    posting's versions, a job posting's assessments, a seeker's alert
    subscriptions, an application's apply events, a sponsored job's and a
    campaign's collections".

    Design: Corner/endpoints/posting_versions_reverse_lookup_lists_ingested_snapshots
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Versions Co", domain="vers.example",
                               ats_provider="WORKDAY")
    headers = make_employer_headers(employer["id"])
    posting = create_posting(employer, title="Versions Engineer",
                             location="Boise, ID", description_text="Version one.",
                             external_posting_id="VER-1")

    second = ingest_version(posting, employer, "VER-1",
                            title="Versions Engineer",
                            description_text="Version two.")

    versions = get_success_data(api_client.list_job_posting_versions(posting["id"], headers))
    assert len(versions) == 2
    assert all(v["job_posting_id"] == posting["id"] for v in versions)
    assert second["content_hash"] != versions[0]["content_hash"] or \
        second["content_hash"] != versions[1]["content_hash"]


def test_hosted_completion_emits_a_completed_apply_event(api):
    """PRD §3.6: "It appends an `ApplyEvent` whose `kind` is `COMPLETED`, whose
    `occurred_at` is the logical clock at emission, and whose `source` is
    `HOSTED` when the posting's `apply_mode` is `HOSTED` and `REDIRECT` when it is
    `ATS_REDIRECT`."
    PRD §3.6: "It increments the posting's `apply_completed_count` by one."

    Design: Corner/endpoints/apply_events_recorded_on_start_and_completion
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Events Co", domain="evt.example")
    seeker = create_seeker(full_name="Events Seeker")
    posting = create_posting(employer, title="Events Engineer", apply_mode="HOSTED")

    application = start_application(posting, seeker)
    validate_success(api.complete_application(
        application["id"], {}, make_seeker_headers(seeker["id"])), 200)

    events = get_success_data(api_client.list_application_apply_events(
        application["id"], ADMIN))
    assert len(events) >= 1
    for event in events:
        assert_apply_event(event)
    assert any(e["kind"] == "COMPLETED" and e["source"] == "HOSTED" for e in events)
    assert get_posting(posting["id"], ADMIN)["apply_completed_count"] == 1


def test_pausing_a_campaign_pauses_its_eligible_sponsored_job(api):
    """PRD §3.2: "Pausing is permitted from `ACTIVE` or from `PACING_HOLD` and
    moves the campaign to `PAUSED`, taking every `ELIGIBLE` `SponsoredJob` in the
    campaign to `PAUSED` along with it".
    PRD §3.2: "the campaign's own `version` is incremented by one on each such
    write."

    Design: Corner/endpoints/campaign_pause_cascades_to_eligible_sponsored_jobs
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Pause Co", domain="pause.example")
    headers = make_employer_headers(employer["id"])
    posting = create_posting(employer, title="Pause Engineer")
    campaign = create_active_campaign(employer, name="PS")
    sponsored_job = create_sponsored_job(campaign, posting, employer)

    paused = validate_success(api.pause_campaign(campaign["id"], headers), 200)
    assert paused["status"] == "PAUSED"
    assert_version_incremented(paused["version"], campaign["version"])

    live_job = get_success_data(api_client.get_sponsored_job(sponsored_job["id"], headers))
    assert live_job["status"] == "PAUSED"