"""Composite setup helpers for multi-step prerequisites.

Every helper here builds its preconditions from an empty database using only
public API calls, because the harness restarts the server before each test.
Setup steps use the lenient success validator so a broken precondition surfaces
as a clear "Setup failed" error rather than a confusing assertion mismatch.
"""
from prd_bench_local_runner.testing import get_success_data

import uuid

from .api_client import api_client
from .constants import CLOCK_START_UTC, TEST_DEFAULTS
from .factories import (
    alert_subscription_payload,
    application_payload,
    campaign_payload,
    disposition_payload,
    employer_payload,
    event_payload,
    hold_payload,
    job_posting_payload,
    job_seeker_payload,
    posting_version_payload,
    sponsored_job_payload,
)
from .test_users import TEST_USERS, make_employer_headers, make_seeker_headers

ADMIN = TEST_USERS["admin_headers"]
TRUST = TEST_USERS["trust_headers"]


# ─── Tier 0: clock ────────────────────────────────────

def set_clock(instant_utc: str):
    """Move the logical clock forward and return the clock response payload."""
    res = api_client.set_current_utc({"current_utc": instant_utc}, ADMIN)
    return get_success_data(res)


def start_clock():
    """Pin the logical clock to the server's documented start instant."""
    return set_clock(CLOCK_START_UTC)


# ─── Tier 1: state progression ────────────────────────

def create_employer(**overrides) -> dict:
    return get_success_data(
        api_client.create_employer(employer_payload(**overrides), ADMIN))


def create_seeker(**overrides) -> dict:
    if "email" not in overrides:
        overrides["email"] = f"seeker-{uuid.uuid4().hex[:10]}@test.example"
    return get_success_data(
        api_client.create_job_seeker(job_seeker_payload(**overrides), ADMIN))


def create_campaign(employer: dict, **overrides) -> dict:
    res = api_client.create_campaign(
        campaign_payload(employer["id"], **overrides), make_employer_headers(employer["id"]))
    return get_success_data(res)


def create_active_campaign(employer: dict, **overrides) -> dict:
    campaign = create_campaign(employer, **overrides)
    res = api_client.activate_campaign(campaign["id"], make_employer_headers(employer["id"]))
    return get_success_data(res)


def create_posting(employer: dict, **overrides) -> dict:
    res = api_client.create_job_posting(
        job_posting_payload(employer["id"], **overrides), make_employer_headers(employer["id"]))
    return get_success_data(res)


def create_sponsored_job(campaign: dict, posting: dict, employer: dict, **overrides) -> dict:
    res = api_client.create_sponsored_job(
        sponsored_job_payload(campaign["id"], posting["id"], **overrides),
        make_employer_headers(employer["id"]))
    return get_success_data(res)


def get_campaign(campaign_id: str, employer: dict) -> dict:
    return get_success_data(
        api_client.get_campaign(campaign_id, make_employer_headers(employer["id"])))


def get_sponsored_job(sponsored_job_id: str, employer: dict) -> dict:
    return get_success_data(
        api_client.get_sponsored_job(sponsored_job_id, make_employer_headers(employer["id"])))


def get_posting(posting_id: str, actor=None) -> dict:
    headers = actor if actor is not None else ADMIN
    return get_success_data(api_client.get_job_posting(posting_id, headers))


def get_employer(employer_id: str) -> dict:
    return get_success_data(api_client.get_employer(employer_id, ADMIN))


# ─── Tier 2: entity hierarchies ───────────────────────

def setup_pacing_scenario(campaign_overrides=None, posting_overrides=None,
                          sponsored_job_overrides=None, activate=True, **employer_overrides):
    """Employer + campaign (+ activation) + posting + sponsored job.

    Returns a dict carrying the live entity payloads plus ready-made header
    dicts for the owning employer.
    """
    employer = create_employer(**employer_overrides)
    if activate:
        campaign = create_active_campaign(employer, **(campaign_overrides or {}))
    else:
        campaign = create_campaign(employer, **(campaign_overrides or {}))
    posting = create_posting(employer, **(posting_overrides or {}))
    sponsored_job = create_sponsored_job(
        campaign, posting, employer, **(sponsored_job_overrides or {}))
    return {
        "employer": employer,
        "campaign": campaign,
        "posting": posting,
        "sponsored_job": sponsored_job,
        "employer_headers": make_employer_headers(employer["id"]),
    }


def setup_campaign_with_two_sponsored_jobs(daily_budget_cents=300000,
                                           total_budget_cents=3000000,
                                           pricing_model="CPC",
                                           bid1=500, bid2=400,
                                           hold1=None, hold2=None):
    """One campaign, two postings, two sponsored jobs; optional pacing holds.

    Used by the waterfall-allocation and budget-cycle scenarios, which need a
    second candidate in the clearing pool.
    """
    employer = create_employer()
    headers = make_employer_headers(employer["id"])
    campaign = create_active_campaign(
        employer,
        pricing_model=pricing_model,
        daily_budget_cents=daily_budget_cents,
        total_budget_cents=total_budget_cents,
    )
    posting1 = create_posting(employer, title="Platform Engineer",
                              description_text="Own the platform.")
    posting2 = create_posting(employer, title="Platform Engineer II",
                              description_text="Own the platform too.")
    sj1 = create_sponsored_job(campaign, posting1, employer,
                               cpc_bid_cents=bid1, cpa_bid_cents=900)
    sj2 = create_sponsored_job(campaign, posting2, employer,
                               cpc_bid_cents=bid2, cpa_bid_cents=900)
    holds = []
    for sj, amount in ((sj1, hold1), (sj2, hold2)):
        if amount is not None:
            holds.append(get_success_data(
                api_client.create_pacing_hold(sj["id"], hold_payload(amount), headers)))
    return {
        "employer": employer,
        "employer_headers": headers,
        "campaign": campaign,
        "postings": [posting1, posting2],
        "sponsored_jobs": [sj1, sj2],
        "holds": holds,
    }


def setup_competing_employers(quality_b_middle=False, bid_a=300, bid_b=300,
                              pricing_model="CPC"):
    """Two employers each with an ACTIVE campaign and one ELIGIBLE sponsored job.

    Employer B's quality is lowered to the middle tier (70) by driving its
    response rate to exactly 5000 bps — two answered applications against two
    closed-unanswered ones, i.e. two responding of four dispositioned — which
    the auction ranking then observes. A single closed-unanswered application
    would instead produce a 0 bps rate and the base tier of 40 (PRD 3.7:
    "anything lower earns the base tier of 40"); `quality_b_middle` is False to
    leave both employers at the default of 100. Returns both sides.
    """
    emp_a = create_employer(legal_name="Auction A", domain="auction-a.example")
    emp_b = create_employer(legal_name="Auction B", domain="auction-b.example")
    seeker = create_seeker(full_name="Auction Seeker")

    post_a = create_posting(emp_a, title="Backend Engineer")
    post_b = create_posting(emp_b, title="Backend Engineer II")

    camp_a = create_active_campaign(emp_a, name="Campaign A",
                                    pricing_model=pricing_model,
                                    daily_budget_cents=300000,
                                    total_budget_cents=3000000)
    camp_b = create_active_campaign(emp_b, name="Campaign B",
                                    pricing_model=pricing_model,
                                    daily_budget_cents=300000,
                                    total_budget_cents=3000000)

    sj_a = create_sponsored_job(camp_a, post_a, emp_a,
                                cpc_bid_cents=bid_a, cpa_bid_cents=900)
    sj_b = create_sponsored_job(camp_b, post_b, emp_b,
                                cpc_bid_cents=bid_b, cpa_bid_cents=900)

    if quality_b_middle:
        # Two answered plus two closed-unanswered: four dispositioned, two
        # responding = 5000 bps -> the middle tier of 70 (PRD 3.7).
        for _ in range(2):
            answered = get_success_data(api_client.create_application(
                application_payload(post_b["id"], seeker["id"]),
                make_seeker_headers(seeker["id"])))
            get_success_data(api_client.complete_application(
                answered["id"], {}, make_seeker_headers(seeker["id"])))
            get_success_data(api_client.disposition_application(
                answered["id"], disposition_payload("REVIEWED"),
                make_employer_headers(emp_b["id"])))
        for _ in range(2):
            app_b = get_success_data(api_client.create_application(
                application_payload(post_b["id"], seeker["id"]),
                make_seeker_headers(seeker["id"])))
            get_success_data(api_client.complete_application(
                app_b["id"], {}, make_seeker_headers(seeker["id"])))
            # Close without a response: the non-response counts against the signal.
            get_success_data(api_client.close_application(
                app_b["id"], make_employer_headers(emp_b["id"])))

    return {
        "employer_a": emp_a, "employer_b": emp_b,
        "seeker": seeker,
        "posting_a": post_a, "posting_b": post_b,
        "campaign_a": camp_a, "campaign_b": camp_b,
        "sponsored_job_a": sj_a, "sponsored_job_b": sj_b,
        "headers_a": make_employer_headers(emp_a["id"]),
        "headers_b": make_employer_headers(emp_b["id"]),
    }


# ─── Tier 3: lifecycle shortcuts ──────────────────────

def start_application(posting: dict, seeker: dict, **overrides) -> dict:
    return get_success_data(api_client.create_application(
        application_payload(posting["id"], seeker["id"], **overrides),
        make_seeker_headers(seeker["id"])))


def create_completed_application(posting: dict, seeker: dict, employer: dict,
                                 **overrides) -> dict:
    application = start_application(posting, seeker, **overrides)
    return get_success_data(api_client.complete_application(
        application["id"], {}, make_seeker_headers(seeker["id"])))


def create_answered_application(posting: dict, seeker: dict, employer: dict,
                                disposition="REVIEWED", **overrides) -> dict:
    """Completed then dispositioned — the application ends RESPONDED."""
    application = create_completed_application(posting, seeker, employer, **overrides)
    return get_success_data(api_client.disposition_application(
        application["id"], disposition_payload(disposition),
        make_employer_headers(employer["id"])))


def create_closed_unanswered_application(posting: dict, seeker: dict,
                                         employer: dict, **overrides) -> dict:
    """Completed then closed with no disposition — counts as a non-response."""
    application = create_completed_application(posting, seeker, employer, **overrides)
    return get_success_data(api_client.close_application(
        application["id"], make_employer_headers(employer["id"])))


def create_hold(sponsored_job: dict, employer: dict, amount_cents: int) -> dict:
    return get_success_data(api_client.create_pacing_hold(
        sponsored_job["id"], hold_payload(amount_cents),
        make_employer_headers(employer["id"])))


def record_click(campaign: dict, sponsored_job: dict, employer: dict,
                 event_type="CLICK", device_fingerprint=None, ip_hash=None,
                 expected_version=None):
    """Record a sponsored event using the campaign's current version by default."""
    if expected_version is None:
        expected_version = get_campaign(campaign["id"], employer)["version"]
    suffix = device_fingerprint or f"fp-{uuid.uuid4().hex[:10]}"
    res = api_client.record_event(
        event_payload(campaign["id"], sponsored_job["id"], expected_version,
                      event_type=event_type,
                      device_fingerprint=suffix,
                      ip_hash=ip_hash or f"ip-{suffix}"),
        ADMIN)
    return get_success_data(res)


# ─── Tier 4: accumulation / threshold targeting ───────

def build_quality_history(posting: dict, seeker: dict, employer: dict,
                          reviewed=0, hired=0, interviewed=0, rejected=0,
                          closed_unanswered=0, applications=None):
    """Drive the employer's quality signal to a target disposition mix.

    Every application is either dispositioned with a responding value or closed
    without one; the counts given are absolute, not deltas. Returns the
    employer payload re-read after the last write.
    """
    applied = applications or []

    def _apply(disposition=None):
        app = create_completed_application(posting, seeker, employer)
        if disposition is None:
            return get_success_data(api_client.close_application(
                app["id"], make_employer_headers(employer["id"])))
        return get_success_data(api_client.disposition_application(
            app["id"], disposition_payload(disposition),
            make_employer_headers(employer["id"])))

    for _ in range(reviewed):
        applied.append(_apply("REVIEWED"))
    for _ in range(interviewed):
        applied.append(_apply("INTERVIEW"))
    for _ in range(rejected):
        applied.append(_apply("REJECTED"))
    for _ in range(hired):
        applied.append(_apply("HIRED"))
    for _ in range(closed_unanswered):
        applied.append(_apply(None))
    return get_employer(employer["id"])


def reach_pacing_hold(campaign_overrides=None, bid=6000, **employer_overrides):
    """Activate a campaign and drive it into PACING_HOLD with one billed click.

    The winning bid equals the daily budget so a single cleared event exhausts
    the day. Returns the scenario plus the post-click campaign payload.
    """
    scenario = setup_pacing_scenario(
        campaign_overrides=campaign_overrides, activate=True, **employer_overrides)
    employer = scenario["employer"]
    campaign = scenario["campaign"]
    sponsored_job = scenario["sponsored_job"]
    record_click(campaign, sponsored_job, employer,
                 device_fingerprint="fp-hold-drive-1")
    scenario["campaign"] = get_campaign(campaign["id"], employer)
    return scenario


# ─── Tier 5: finalization / terminal state ────────────

def complete_campaign(campaign: dict, sponsored_job: dict, employer: dict,
                      **overrides):
    """Drive a campaign to its terminal state with a single total-reaching click."""
    record_click(campaign, sponsored_job, employer,
                 device_fingerprint="fp-complete-1")
    return get_campaign(campaign["id"], employer)


def suspend_employer(employer: dict, reason: str = "Account under review") -> dict:
    return get_success_data(
        api_client.suspend_employer(employer["id"], {"reason": reason}, TRUST))


def reinstate_employer(employer: dict) -> dict:
    return get_success_data(
        api_client.reinstate_employer(employer["id"], TRUST))


# ─── Posting freshness helpers ────────────────────────

def ingest_version(posting: dict, employer: dict, external_posting_id: str,
                   **overrides) -> dict:
    res = api_client.ingest_job_posting_version(
        posting["id"],
        posting_version_payload(external_posting_id, **overrides),
        make_employer_headers(employer["id"]))
    return get_success_data(res)


def age_posting_to(posting: dict, days: int):
    """Advance the logical clock `days` past the posting's ingestion instant."""
    from datetime import datetime, timedelta

    ingested = datetime.strptime(posting["posted_at"], "%Y-%m-%dT%H:%M:%SZ")
    target = ingested + timedelta(days=days)
    return set_clock(target.strftime("%Y-%m-%dT%H:%M:%SZ"))