"""Employer account endpoints."""

from flask import Blueprint

import auth
import validations as V
from db import iso, logical_day, store, parse_iso
from models import campaign_view, create, employer_view, touch
from response import array, ok, page_meta, paginate
from services import calc

bp = Blueprint("employers", __name__)

ATS_PROVIDERS = ("WORKDAY", "GREENHOUSE", "LEVER", "TALEO", "NONE")
CAMPAIGN_STATUSES = ("DRAFT", "ACTIVE", "PACING_HOLD", "PAUSED", "COMPLETED")


@bp.post("/employers")
def create_employer():
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("PlatformAdmin",))
    data = V.body()
    V.require_fields(data, ["legal_name", "domain"])
    legal_name = V.require_string(data, "legal_name")
    domain = V.require_string(data, "domain")
    ats_provider = V.strict_enum(data, "ats_provider", ATS_PROVIDERS) or "NONE"
    employer = create(
        "employers",
        legal_name=legal_name,
        domain=domain,
        ats_provider=ats_provider,
        status="ACTIVE",
        quality_score=100,
        response_rate_bps=0,
        billing_status="CURRENT",
        balance_cents=0,
        last_invoice_at=None,
        suspended_at=None,
        suspension_reason=None,
    )
    return ok(employer_view(employer), 201)


def _employer_for_read(actor_id, role, employer_id):
    """Read gate: administrative roles unrestricted, Employer only its own account."""
    employer = V.get("employer", employer_id)
    if role == "Employer":
        auth.require_ownership(actor_id, role, "employer account", "Employer", employer_id)
    return employer


@bp.get("/employers/<employer_id>")
def get_employer(employer_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("PlatformAdmin", "Employer", "TrustReviewer"))
    employer = _employer_for_read(actor_id, role, employer_id)
    return ok(employer_view(employer))


@bp.post("/employers/<employer_id>/suspend")
def suspend_employer(employer_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("TrustReviewer",))
    data = V.require_object(V.body())
    V.require_fields(data, ["reason"])
    reason = V.require_string(data, "reason")
    employer = V.get("employer", employer_id)

    # Tier 4: lifecycle state.
    if employer["status"] != "ACTIVE":
        from errors import ERR_INVALID_STATE_TRANSITION, fail
        fail(ERR_INVALID_STATE_TRANSITION,
             "Only an ACTIVE employer can be suspended.")

    employer["status"] = "SUSPENDED"
    employer["billing_status"] = "FROZEN"
    employer["suspended_at"] = iso(store.clock)
    employer["suspension_reason"] = reason
    touch(employer)

    # Cascade hop 1: Employer -> JobPosting (SUSPENDED), Campaign (PAUSED),
    # SponsoredJob (PAUSED, every one) and their ACTIVE holds (RELEASED).
    for posting in store.job_postings.values():
        if posting["employer_id"] != employer["id"]:
            continue
        if posting["state"] != "SUSPENDED":
            posting["state"] = "SUSPENDED"
            touch(posting)
    for campaign in store.campaigns.values():
        if campaign["employer_id"] != employer["id"]:
            continue
        if campaign["status"] != "PAUSED":
            campaign["status"] = "PAUSED"
            touch(campaign)
    for job in store.sponsored_jobs.values():
        campaign = store.campaigns.get(job["campaign_id"])
        if campaign is None or campaign["employer_id"] != employer["id"]:
            continue
        calc.pause_sponsored_job(job)
    return ok(employer_view(employer))


@bp.post("/employers/<employer_id>/reinstate")
def reinstate_employer(employer_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("TrustReviewer",))
    V.body()
    employer = V.get("employer", employer_id)

    if employer["status"] != "SUSPENDED":
        from errors import ERR_EMPLOYER_NOT_SUSPENDED, fail
        fail(ERR_EMPLOYER_NOT_SUSPENDED,
             "Only a SUSPENDED employer can be reinstated.")

    employer["status"] = "ACTIVE"
    employer["billing_status"] = "CURRENT"
    employer["suspended_at"] = None
    employer["suspension_reason"] = None
    touch(employer)

    # Postings are re-derived from current_freshness; sponsored jobs are NOT resumed.
    for posting in store.job_postings.values():
        if posting["employer_id"] != employer["id"]:
            continue
        before = posting["state"]
        version = calc.newest_version(posting["id"])
        if version is None:
            derived = "DRAFT"
        elif calc.freshness_of(version["ingested_at"], store.clock) == "EXPIRED":
            derived = "EXPIRED"
        else:
            derived = "ACTIVE"
        if posting["state"] != derived:
            posting["state"] = derived
            touch(posting)
        _ = before
    return ok(employer_view(employer))


@bp.get("/employers/<employer_id>/campaigns")
def list_employer_campaigns(employer_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("PlatformAdmin", "Employer", "TrustReviewer"))
    employer = _employer_for_read(actor_id, role, employer_id)
    V.reject_unknown_query({"status", "limit", "offset"})
    status = V.enum_filter("status", CAMPAIGN_STATUSES)
    limit, offset = V.pagination()

    items = [
        campaign for campaign in store.campaigns.values()
        if campaign["employer_id"] == employer["id"]
        and (status is None or campaign["status"] == status)
    ]
    items = V.sort_newest(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array([campaign_view(row) for row in page], 200,
                 page_meta(limit, offset, total))