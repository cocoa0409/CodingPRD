"""Sponsored event recording and the budget charge cascade."""

from db import iso, store
from models import create, touch
from services import calc


def find_serving_sponsored_job(posting_id):
    """The eligible sponsored job serving this posting, oldest first."""
    matches = []
    for job in store.sponsored_jobs.values():
        if job["job_posting_id"] != posting_id or job["status"] != "ELIGIBLE":
            continue
        campaign = store.campaigns.get(job["campaign_id"])
        if campaign is None or campaign["status"] != "ACTIVE":
            continue
        matches.append(job)
    if not matches:
        return None
    matches.sort(key=lambda job: (job["created_at"], job["id"]))
    return matches[0]


def settle_campaign(campaign):
    """Post-commit re-tests: lifetime completion, daily exhaustion, budget holds."""
    if campaign["spent_cents"] >= campaign["total_budget_cents"]:
        calc.complete_campaign(campaign)
        return campaign
    if campaign["daily_spent_cents"] >= campaign["daily_budget_cents"] \
            and campaign["status"] == "ACTIVE":
        campaign["status"] = "PACING_HOLD"
    calc.recompute_held_cents(campaign)
    if campaign["status"] in ("ACTIVE", "PACING_HOLD"):
        calc.recompute_budget_hold_states(campaign)
    return campaign


def apply_charge(campaign, cleared, sponsor_event_id):
    """Commit a cleared cost: split across holds, then update every posture."""
    calc.budget_commit_split(campaign, cleared, sponsor_event_id)
    campaign["daily_spent_cents"] += int(cleared)
    employer = store.employers.get(campaign["employer_id"])
    if employer is not None:
        employer["balance_cents"] = employer["balance_cents"] + int(cleared)
        touch(employer)
    settle_campaign(campaign)
    campaign["version"] = campaign.get("version", 1) + 1
    campaign["updated_at"] = iso(store.clock)
    calc.recompute_held_cents(campaign)
    _refresh_pacing(campaign)
    return campaign


def _refresh_pacing(campaign):
    for job in store.sponsored_jobs.values():
        if job["campaign_id"] != campaign["id"]:
            continue
        job["scheduled_pacing_multiplier"] = calc.campaign_pacing_multiplier(campaign)
        job["realized_pacing_multiplier"] = calc.realized_pacing_multiplier(campaign)
        touch(job)


def record_sponsor_event(campaign, job, event_type, device_fingerprint, ip_hash,
                         billable, cost_cents, status):
    event = create(
        "sponsor_events",
        campaign_id=campaign["id"],
        sponsored_job_id=job["id"],
        event_type=event_type,
        billable=billable,
        cost_cents=int(cost_cents),
        status=status,
        occurred_at=iso(store.clock),
        device_fingerprint=device_fingerprint,
        ip_hash=ip_hash,
    )
    if event_type == "IMPRESSION":
        job["impressions"] = job["impressions"] + 1
    elif event_type == "CLICK":
        job["clicks"] = job["clicks"] + 1
    else:
        job["applications"] = job["applications"] + 1
    touch(job)
    return event


def record_completion_event(posting):
    """A completed application records a sponsored APPLICATION event (PRD 3.6).

    On a CPA campaign the event is billable and its cost flows through the same
    commit split as any other billed event; on a CPC campaign it is counted only.
    """
    job = find_serving_sponsored_job(posting["id"])
    if job is None:
        return None
    campaign = store.campaigns[job["campaign_id"]]
    billable = campaign["pricing_model"] == "CPA"
    if not billable:
        return record_sponsor_event(campaign, job, "APPLICATION", None, None,
                                    False, 0, "RECORDED")
    cleared = calc.auction_clearing_price(job)
    event = record_sponsor_event(campaign, job, "APPLICATION", None, None,
                                 True, cleared, "BILLED")
    apply_charge(campaign, cleared, event["id"])
    return event