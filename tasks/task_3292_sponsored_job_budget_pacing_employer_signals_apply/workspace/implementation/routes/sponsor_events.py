"""Sponsor event recording and refund endpoints."""

from flask import Blueprint

import auth
import validations as V
from db import iso, parse_iso, store
from models import sponsor_event_view, touch
from response import ok
from services import calc, events

bp = Blueprint("sponsor_events", __name__)

EVENT_TYPES = ("IMPRESSION", "CLICK", "APPLICATION")
REFUND_WINDOW_SECONDS = 86400


@bp.post("/events")
def create_event():
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("PlatformAdmin",))
    data = V.body()
    V.require_fields(data, ["campaign_id", "sponsored_job_id", "event_type",
                            "device_fingerprint", "ip_hash"])
    campaign_id = V.require_string(data, "campaign_id")
    job_id = V.require_string(data, "sponsored_job_id")
    event_type = V.require_enum(data, "event_type", EVENT_TYPES)
    device_fingerprint = V.optional_string(data, "device_fingerprint")
    ip_hash = V.optional_string(data, "ip_hash")

    campaign = V.get("campaign", campaign_id)
    job = V.get("sponsored_job", job_id)

    from errors import (
        ERR_CAMPAIGN_NOT_ACTIVE,
        ERR_CAMPAIGN_TERMINAL,
        ERR_DAILY_BUDGET_EXCEEDED,
        ERR_MISSING_EXPECTED_VERSION,
        ERR_SPONSORED_JOB_NOT_ELIGIBLE,
        ERR_STALE_VERSION,
        ERR_TOTAL_BUDGET_EXCEEDED,
        fail,
    )

    # Tier 4: lifecycle state.
    if campaign["status"] == "COMPLETED":
        fail(ERR_CAMPAIGN_TERMINAL, "The campaign is COMPLETED.")
    if campaign["status"] != "ACTIVE":
        fail(ERR_CAMPAIGN_NOT_ACTIVE, "The campaign must be ACTIVE to record an event.")
    if job["status"] != "ELIGIBLE":
        fail(ERR_SPONSORED_JOB_NOT_ELIGIBLE,
             "The sponsored job must be ELIGIBLE to serve a placement.")
    posting = store.job_postings.get(job["job_posting_id"])
    if posting is None or posting["state"] != "ACTIVE":
        fail(ERR_SPONSORED_JOB_NOT_ELIGIBLE,
             "The sponsored job's posting is not ACTIVE.")

    billable = ((event_type == "CLICK" and campaign["pricing_model"] == "CPC")
                or (event_type == "APPLICATION" and campaign["pricing_model"] == "CPA"))

    cleared = 0
    if billable:
        cleared = calc.auction_clearing_price(job)
        # Tier 8: budget capacity, evaluated after fraud and time checks.
        if campaign["daily_spent_cents"] + cleared > campaign["daily_budget_cents"]:
            fail(ERR_DAILY_BUDGET_EXCEEDED,
                 "The cleared cost would exceed the campaign's daily budget.")
        if campaign["spent_cents"] + cleared > campaign["total_budget_cents"]:
            fail(ERR_TOTAL_BUDGET_EXCEEDED,
                 "The cleared cost would exceed the campaign's total budget.")

    # Tier 10: optimistic concurrency on the campaign.
    expected = data.get("expected_campaign_version")
    if expected is None:
        fail(ERR_MISSING_EXPECTED_VERSION,
             "expected_campaign_version is required for this write.")
    if isinstance(expected, bool) or not isinstance(expected, int):
        fail(ERR_MISSING_EXPECTED_VERSION,
             "expected_campaign_version must be an integer.")
    if expected != campaign["version"]:
        fail(ERR_STALE_VERSION,
             "expected_campaign_version does not match the campaign's current version.")

    event = events.record_sponsor_event(
        campaign, job, event_type, device_fingerprint, ip_hash,
        billable, cleared, "RECORDED",
    )
    if billable:
        event["status"] = "BILLED"
        touch(event)
        events.apply_charge(campaign, cleared, event["id"])
    else:
        calc.refresh_campaign_pacing(campaign)
    return ok(sponsor_event_view(event), 201)


@bp.post("/events/<event_id>/refund")
def refund_event(event_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("TrustReviewer", "PlatformAdmin"))
    data = V.body()
    V.require_fields(data, ["reason"])
    V.require_string(data, "reason")

    event = V.get("sponsor_event", event_id)
    campaign = store.campaigns.get(event["campaign_id"])

    from errors import (
        ERR_DUPLICATE_REFUND_CLAIM,
        ERR_EVENT_NOT_REFUNDABLE,
        ERR_MISSING_EXPECTED_VERSION,
        ERR_REFUND_WINDOW_EXPIRED,
        ERR_STALE_VERSION,
        fail,
    )

    # Tier 9: refundability, window and duplicate-claim protection.
    if event["status"] != "BILLED":
        fail(ERR_EVENT_NOT_REFUNDABLE,
             "Only a BILLED sponsor event can be refunded.")

    occurred = parse_iso(event["occurred_at"])
    age_seconds = (store.clock - occurred).total_seconds()
    if age_seconds > REFUND_WINDOW_SECONDS:
        fail(ERR_REFUND_WINDOW_EXPIRED,
             "The 24-hour invalid-click refund window has passed.")

    fingerprint = event["device_fingerprint"]
    if fingerprint is not None:
        for other in store.sponsor_events.values():
            if other["id"] == event["id"]:
                continue
            if other["device_fingerprint"] != fingerprint:
                continue
            if other["status"] != "REFUNDED":
                continue
            other_age = (store.clock - parse_iso(other["occurred_at"])).total_seconds()
            if other_age <= REFUND_WINDOW_SECONDS:
                fail(ERR_DUPLICATE_REFUND_CLAIM,
                     "A refund has already been granted for this device fingerprint.")

    # Tier 10: concurrency on the campaign.
    expected = data.get("expected_campaign_version")
    if expected is None:
        fail(ERR_MISSING_EXPECTED_VERSION,
             "expected_campaign_version is required for this write.")
    if isinstance(expected, bool) or not isinstance(expected, int):
        fail(ERR_MISSING_EXPECTED_VERSION,
             "expected_campaign_version must be an integer.")
    if campaign is None:
        fail(ERR_EVENT_NOT_REFUNDABLE, "The event's campaign no longer exists.")
    if expected != campaign["version"]:
        fail(ERR_STALE_VERSION,
             "expected_campaign_version does not match the campaign's current version.")

    amount = event["cost_cents"]
    event["status"] = "REFUNDED"
    touch(event)

    calc.append_ledger(campaign, "REFUND", -amount, event["id"])
    # spent_cents falls by the refunded amount through the invariant of 2.5; the
    # daily counter falls by the same amount, restoring daily capacity.
    campaign["daily_spent_cents"] = campaign["daily_spent_cents"] - amount
    campaign["spent_cents"] = campaign["spent_cents"] - amount
    employer = store.employers.get(campaign["employer_id"])
    if employer is not None:
        employer["balance_cents"] = employer["balance_cents"] - amount
        touch(employer)
    campaign["version"] = campaign.get("version", 1) + 1
    campaign["updated_at"] = iso(store.clock)

    # Restored daily capacity can lift a sponsored job out of BUDGET_HOLD, and a
    # refund against a PACING_HOLD campaign returns it to ACTIVE when capacity is back.
    calc.recompute_held_cents(campaign)
    if campaign["status"] == "PACING_HOLD" \
            and campaign["daily_spent_cents"] < campaign["daily_budget_cents"]:
        campaign["status"] = "ACTIVE"
    if campaign["status"] in ("ACTIVE", "PACING_HOLD"):
        calc.recompute_budget_hold_states(campaign)
    return ok(sponsor_event_view(event))