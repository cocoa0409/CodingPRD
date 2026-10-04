"""Campaign endpoints: lifecycle, events listing, budget ledger."""

from flask import Blueprint

import auth
import validations as V
from db import iso, logical_day, parse_iso, store
from models import campaign_view, create, ledger_view, sponsor_event_view, touch
from response import array, ok, page_meta, paginate
from services import calc

bp = Blueprint("campaigns", __name__)

PRICING_MODELS = ("CPC", "CPA")
CAMPAIGN_STATUSES = ("DRAFT", "ACTIVE", "PACING_HOLD", "PAUSED", "COMPLETED")
EVENT_TYPES = ("IMPRESSION", "CLICK", "APPLICATION")
EVENT_STATUSES = ("RECORDED", "BILLED", "REFUNDED")
ENTRY_TYPES = ("HOLD", "COMMIT", "RELEASE", "REFUND")


def campaign_owner(campaign):
    return store.employers.get(campaign["employer_id"])


def load_campaign(actor_id, role, campaign_id):
    campaign = V.get("campaign", campaign_id)
    if role == "Employer":
        auth.require_ownership(actor_id, role, "campaign", "Employer", campaign["employer_id"])
    return campaign


@bp.post("/campaigns")
def create_campaign():
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("Employer", "PlatformAdmin"))
    data = V.body()
    V.require_fields(data, ["employer_id", "name", "pricing_model",
                            "daily_budget_cents", "total_budget_cents"])
    employer_id = V.require_string(data, "employer_id")
    name = V.require_string(data, "name")
    pricing_model = V.require_enum(data, "pricing_model", PRICING_MODELS)
    daily_budget = V.require_int(data, "daily_budget_cents")
    total_budget = V.require_int(data, "total_budget_cents")
    if daily_budget < 0 or total_budget < 0:
        from errors import ERR_INVALID_REQUEST, fail
        fail(ERR_INVALID_REQUEST, "Budget values must not be negative.")

    employer = V.get("employer", employer_id)
    if role == "Employer":
        auth.require_ownership(actor_id, role, "campaign", "Employer", employer["id"])

    # Tier 5: the acting employer must not be suspended.
    if employer["status"] == "SUSPENDED":
        from errors import ERR_EMPLOYER_SUSPENDED, fail
        fail(ERR_EMPLOYER_SUSPENDED,
             "A SUSPENDED employer may not create campaigns.")

    campaign = create(
        "campaigns",
        employer_id=employer["id"],
        name=name,
        pricing_model=pricing_model,
        daily_budget_cents=daily_budget,
        total_budget_cents=total_budget,
        status="DRAFT",
        spent_cents=0,
        daily_spent_cents=0,
        held_cents=0,
        day_open_date=iso(logical_day(store.clock)),
    )
    return ok(campaign_view(campaign), 201)


@bp.get("/campaigns/<campaign_id>")
def get_campaign(campaign_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("PlatformAdmin", "Employer"))
    campaign = load_campaign(actor_id, role, campaign_id)
    _refresh(campaign)
    return ok(campaign_view(campaign))


def _refresh(campaign):
    """Keep derived fields reconciled with the ledger/holds before serving."""
    calc.recompute_spent_cents(campaign)
    calc.recompute_held_cents(campaign)


@bp.post("/campaigns/<campaign_id>/activate")
def activate_campaign(campaign_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("Employer",))
    V.body()
    campaign = load_campaign(actor_id, role, campaign_id)

    if campaign["status"] != "DRAFT":
        from errors import ERR_INVALID_STATE_TRANSITION, fail
        fail(ERR_INVALID_STATE_TRANSITION, "Only a DRAFT campaign can be activated.")

    employer = campaign_owner(campaign)
    if employer is None or employer["status"] != "ACTIVE":
        from errors import ERR_EMPLOYER_SUSPENDED, fail
        fail(ERR_EMPLOYER_SUSPENDED,
             "Only an employer in ACTIVE status can activate a campaign.")

    campaign["status"] = "ACTIVE"
    campaign["spent_cents"] = calc.recompute_spent_cents(campaign)
    touch(campaign)
    calc.recompute_budget_hold_states(campaign)
    _pacing_refresh(campaign)
    return ok(campaign_view(campaign))


@bp.post("/campaigns/<campaign_id>/pause")
def pause_campaign(campaign_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("Employer",))
    V.body()
    campaign = load_campaign(actor_id, role, campaign_id)

    if campaign["status"] not in ("ACTIVE", "PACING_HOLD"):
        from errors import ERR_INVALID_STATE_TRANSITION, fail
        fail(ERR_INVALID_STATE_TRANSITION,
             "Only an ACTIVE or PACING_HOLD campaign can be paused.")

    campaign["status"] = "PAUSED"
    calc.pause_sponsored_jobs_for_campaign(campaign, only_eligible=True)
    touch(campaign)
    _pacing_refresh(campaign)
    return ok(campaign_view(campaign))


@bp.post("/campaigns/<campaign_id>/resume")
def resume_campaign(campaign_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("Employer",))
    V.body()
    campaign = load_campaign(actor_id, role, campaign_id)

    if campaign["status"] != "PAUSED":
        from errors import ERR_INVALID_STATE_TRANSITION, fail
        fail(ERR_INVALID_STATE_TRANSITION, "Only a PAUSED campaign can be resumed.")
    if campaign["spent_cents"] >= campaign["total_budget_cents"]:
        from errors import ERR_CAMPAIGN_TERMINAL, fail
        fail(ERR_CAMPAIGN_TERMINAL,
             "A campaign that has exhausted its total budget cannot be resumed.")

    employer = campaign_owner(campaign)
    if employer is None or employer["status"] != "ACTIVE":
        from errors import ERR_EMPLOYER_SUSPENDED, fail
        fail(ERR_EMPLOYER_SUSPENDED,
             "Only an employer in ACTIVE status can resume a campaign.")

    campaign["status"] = "ACTIVE"
    touch(campaign)
    for job in store.sponsored_jobs.values():
        if job["campaign_id"] != campaign["id"] or job["status"] != "PAUSED":
            continue
        posting = store.job_postings.get(job["job_posting_id"])
        if posting is not None and posting["state"] == "ACTIVE":
            job["status"] = "ELIGIBLE"
            touch(job)
    _pacing_refresh(campaign)
    return ok(campaign_view(campaign))


def _pacing_refresh(campaign):
    for job in store.sponsored_jobs.values():
        if job["campaign_id"] != campaign["id"]:
            continue
        job["scheduled_pacing_multiplier"] = calc.campaign_pacing_multiplier(campaign)
        job["realized_pacing_multiplier"] = calc.realized_pacing_multiplier(campaign)
        touch(job)


@bp.get("/campaigns/<campaign_id>/events")
def list_campaign_events(campaign_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("PlatformAdmin", "Employer"))
    campaign = load_campaign(actor_id, role, campaign_id)
    V.reject_unknown_query({"event_type", "status", "limit", "offset"})
    event_type = V.enum_filter("event_type", EVENT_TYPES)
    status = V.enum_filter("status", EVENT_STATUSES)
    limit, offset = V.pagination()

    items = [
        event for event in store.sponsor_events.values()
        if event["campaign_id"] == campaign["id"]
        and (event_type is None or event["event_type"] == event_type)
        and (status is None or event["status"] == status)
    ]
    items = V.sort_newest(items)
    total = len(items)
    return array([sponsor_event_view(row) for row in paginate(items, limit, offset)], 200,
                 page_meta(limit, offset, total))


@bp.get("/campaigns/<campaign_id>/budget-ledger")
def list_campaign_ledger(campaign_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("PlatformAdmin", "Employer"))
    campaign = load_campaign(actor_id, role, campaign_id)
    V.reject_unknown_query({"entry_type", "limit", "offset"})
    entry_type = V.enum_filter("entry_type", ENTRY_TYPES)
    limit, offset = V.pagination()

    items = [
        entry for entry in store.budget_ledger.values()
        if entry["campaign_id"] == campaign["id"]
        and (entry_type is None or entry["entry_type"] == entry_type)
    ]
    items = V.sort_newest(items)
    total = len(items)
    return array([ledger_view(row) for row in paginate(items, limit, offset)], 200,
                 page_meta(limit, offset, total))