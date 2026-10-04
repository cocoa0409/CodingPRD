"""Sponsored job endpoints: attachment, resume, pacing holds and bid quotes."""

from flask import Blueprint

import auth
import validations as V
from db import store
from models import create, pacing_hold_view, sponsored_job_view, touch
from response import array, ok, page_meta, paginate
from services import calc

bp = Blueprint("sponsored_jobs", __name__)

JOB_STATUSES = ("DRAFT", "ELIGIBLE", "PAUSED", "BUDGET_HOLD")
HOLD_STATUSES = ("ACTIVE", "COMMITTED", "RELEASED")


def owning_employer(job):
    campaign = store.campaigns.get(job["campaign_id"])
    if campaign is None:
        return None
    return store.employers.get(campaign["employer_id"])


def load_job(actor_id, role, job_id):
    job = V.get("sponsored_job", job_id)
    if role == "Employer":
        employer = owning_employer(job)
        auth.require_ownership(actor_id, role, "sponsored job", "Employer",
                               employer["id"] if employer else None)
    return job


def refresh_pacing(job):
    """Derived pacing multipliers are refreshed whenever the job is served."""
    campaign = store.campaigns.get(job["campaign_id"])
    if campaign is None:
        return job
    job["scheduled_pacing_multiplier"] = calc.campaign_pacing_multiplier(campaign)
    job["realized_pacing_multiplier"] = calc.realized_pacing_multiplier(campaign)
    return job


@bp.post("/sponsored-jobs")
def create_sponsored_job():
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("Employer",))
    data = V.body()
    V.require_fields(data, ["campaign_id", "job_posting_id", "cpc_bid_cents", "cpa_bid_cents"])
    campaign_id = V.require_string(data, "campaign_id")
    posting_id = V.require_string(data, "job_posting_id")
    cpc_bid = V.require_int(data, "cpc_bid_cents")
    cpa_bid = V.require_int(data, "cpa_bid_cents")

    campaign = V.get("campaign", campaign_id)
    posting = V.get("job_posting", posting_id)

    # Tier 2: the caller owns both the campaign and the posting.
    auth.require_ownership(actor_id, role, "campaign", "Employer", campaign["employer_id"])
    auth.require_ownership(actor_id, role, "job posting", "Employer", posting["employer_id"])

    # Tier 4: lifecycle state.
    if campaign["status"] == "COMPLETED":
        from errors import ERR_CAMPAIGN_TERMINAL, fail
        fail(ERR_CAMPAIGN_TERMINAL, "The campaign is COMPLETED.")
    if campaign["status"] != "ACTIVE":
        from errors import ERR_CAMPAIGN_NOT_ACTIVE, fail
        fail(ERR_CAMPAIGN_NOT_ACTIVE, "The campaign must be ACTIVE to sponsor a posting.")
    if posting["state"] != "ACTIVE":
        from errors import ERR_POSTING_NOT_ACTIVE, fail
        fail(ERR_POSTING_NOT_ACTIVE, "The job posting must be ACTIVE to be sponsored.")

    # Tier 5: fraud / trust safety.
    employer = store.employers.get(campaign["employer_id"])
    if employer is None or employer["status"] == "SUSPENDED":
        from errors import ERR_EMPLOYER_SUSPENDED, fail
        fail(ERR_EMPLOYER_SUSPENDED, "A SUSPENDED employer may not create sponsored jobs.")

    # Tier 6: minimum bid coherence.
    if cpc_bid < 1 or cpa_bid < 1:
        from errors import ERR_BID_BELOW_MINIMUM, fail
        fail(ERR_BID_BELOW_MINIMUM, "Both bids must be at least one cent.")

    job = create(
        "sponsored_jobs",
        campaign_id=campaign["id"],
        job_posting_id=posting["id"],
        cpc_bid_cents=cpc_bid,
        cpa_bid_cents=cpa_bid,
        scheduled_pacing_multiplier=1.0,
        realized_pacing_multiplier=1.0,
        status="ELIGIBLE",
        impressions=0,
        clicks=0,
        applications=0,
    )
    refresh_pacing(job)
    calc.recompute_budget_hold_states(campaign)
    return ok(sponsored_job_view(job), 201)


@bp.get("/sponsored-jobs")
def list_sponsored_jobs():
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("PlatformAdmin", "Employer"))
    V.reject_unknown_query({"campaign_id", "job_posting_id", "status", "limit", "offset"})
    campaign_id = V.str_filter("campaign_id")
    posting_id = V.str_filter("job_posting_id")
    status = V.enum_filter("status", JOB_STATUSES)
    limit, offset = V.pagination()
    if campaign_id is not None:
        V.get("campaign", campaign_id)
    if posting_id is not None:
        V.get("job_posting", posting_id)

    items = []
    for job in store.sponsored_jobs.values():
        if campaign_id is not None and job["campaign_id"] != campaign_id:
            continue
        if posting_id is not None and job["job_posting_id"] != posting_id:
            continue
        if status is not None and job["status"] != status:
            continue
        if role == "Employer":
            employer = owning_employer(job)
            if employer is None or employer["id"] != actor_id:
                continue
        items.append(job)

    items = V.sort_newest(items)
    total = len(items)
    page = paginate(items, limit, offset)
    payload = []
    for job in page:
        refresh_pacing(job)
        payload.append(sponsored_job_view(job))
    return array(payload, 200, page_meta(limit, offset, total))


@bp.get("/sponsored-jobs/<job_id>")
def get_sponsored_job(job_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("PlatformAdmin", "Employer"))
    job = load_job(actor_id, role, job_id)
    refresh_pacing(job)
    return ok(sponsored_job_view(job))


@bp.post("/sponsored-jobs/<job_id>/resume")
def resume_sponsored_job(job_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("Employer",))
    V.body()
    job = load_job(actor_id, role, job_id)

    from errors import ERR_INVALID_STATE_TRANSITION, fail

    if job["status"] != "PAUSED":
        fail(ERR_INVALID_STATE_TRANSITION,
             "Only a PAUSED sponsored job can be resumed.")

    campaign = store.campaigns[job["campaign_id"]]
    posting = store.job_postings.get(job["job_posting_id"])
    employer = store.employers.get(campaign["employer_id"])
    # The three guards are evaluated together; any failure is an invalid transition.
    if campaign["status"] != "ACTIVE":
        fail(ERR_INVALID_STATE_TRANSITION,
             "The owning campaign must be ACTIVE to resume a sponsored job.")
    if posting is None or posting["state"] != "ACTIVE":
        fail(ERR_INVALID_STATE_TRANSITION,
             "The sponsored job's posting must be ACTIVE to resume it.")
    if employer is None or employer["status"] == "SUSPENDED":
        fail(ERR_INVALID_STATE_TRANSITION,
             "A SUSPENDED employer's sponsored job cannot be resumed.")

    job["status"] = "ELIGIBLE"
    touch(job)
    refresh_pacing(job)
    return ok(sponsored_job_view(job))


@bp.post("/sponsored-jobs/<job_id>/pacing-holds")
def create_pacing_hold(job_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("Employer",))
    data = V.body()
    V.require_fields(data, ["amount_cents"])
    amount = V.require_int(data, "amount_cents")
    job = load_job(actor_id, role, job_id)
    campaign = store.campaigns[job["campaign_id"]]

    from errors import (
        ERR_CAMPAIGN_NOT_ACTIVE,
        ERR_CAMPAIGN_TERMINAL,
        ERR_INSUFFICIENT_DAILY_BUDGET,
        ERR_INVALID_REQUEST,
        ERR_PACING_HOLD_OVERLAP,
        fail,
    )

    # Tier 4: the campaign must still be able to spend.
    if campaign["status"] == "COMPLETED":
        fail(ERR_CAMPAIGN_TERMINAL,
             "The campaign is COMPLETED and accepts no further holds.")
    if campaign["status"] != "ACTIVE":
        fail(ERR_CAMPAIGN_NOT_ACTIVE,
             "The campaign must be ACTIVE to reserve budget.")

    # Tier 11 shape (amount must be a positive integer number of cents).
    if amount < 1:
        fail(ERR_INVALID_REQUEST, "amount_cents must be at least one cent.")

    calc.recompute_held_cents(campaign)
    if campaign["held_cents"] + campaign["daily_spent_cents"] + amount > \
            campaign["daily_budget_cents"]:
        fail(ERR_INSUFFICIENT_DAILY_BUDGET,
             "The reservation would exceed the campaign's remaining daily budget.")

    # Tier 9: one ACTIVE reservation per sponsored job per logical day.
    for hold in store.pacing_holds.values():
        if hold["sponsored_job_id"] != job["id"] or hold["status"] != "ACTIVE":
            continue
        if _hold_is_current_day(hold, campaign):
            fail(ERR_PACING_HOLD_OVERLAP,
                 "This sponsored job already holds an ACTIVE reservation for today.")

    hold = create(
        "pacing_holds",
        sponsored_job_id=job["id"],
        campaign_id=campaign["id"],
        amount_cents=amount,
        status="ACTIVE",
        sponsor_event_id=None,
    )
    hold["day_open_date"] = campaign["day_open_date"]
    calc.append_ledger(campaign, "HOLD", amount, None)
    calc.recompute_held_cents(campaign)
    campaign["version"] = campaign.get("version", 1) + 1
    from db import iso
    campaign["updated_at"] = iso(store.clock)
    calc.recompute_budget_hold_states(campaign)
    return ok(pacing_hold_view(hold), 201)


def _hold_is_current_day(hold, campaign):
    from db import logical_day, parse_iso
    created = parse_iso(hold["created_at"])
    return logical_day(created) == logical_day(store.clock)


@bp.get("/sponsored-jobs/<job_id>/pacing-holds")
def list_pacing_holds(job_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("PlatformAdmin", "Employer"))
    job = load_job(actor_id, role, job_id)
    V.reject_unknown_query({"status", "limit", "offset"})
    status = V.enum_filter("status", HOLD_STATUSES)
    limit, offset = V.pagination()
    items = [
        hold for hold in store.pacing_holds.values()
        if hold["sponsored_job_id"] == job["id"]
        and (status is None or hold["status"] == status)
    ]
    items = V.sort_newest(items)
    total = len(items)
    return array([pacing_hold_view(row) for row in paginate(items, limit, offset)], 200,
                 page_meta(limit, offset, total))