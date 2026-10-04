"""Usage-event routes (PRD 3.5): metered SEARCH / DOC_VIEW recording with the
full validation gauntlet, plus billing-side reads."""

from datetime import timedelta

from flask import Blueprint, g, request

from constants import EVENT_TYPES, PRACTICE_AREAS
from db import fmt_dt, stamp_ledger, store
from errors import raise_err
from middleware import require_roles
from response import list_response, ok_object
from serializers import serialize_usage_event
from util import day_start, get_body, opt_enum_query, opt_str, req_enum

bp = Blueprint("usage", __name__)

USAGE_READERS = ("BillingAdmin", "LicensingManager")


@bp.post("/legal-research/usage-events")
@require_roles("Researcher")
def create_usage_event():
    body = get_body()
    event_type = req_enum(body, "event_type", EVENT_TYPES)
    practice_area_tag = req_enum(body, "practice_area_tag", PRACTICE_AREAS)
    license_agreement_id = opt_str(body, "license_agreement_id")
    matter_code = opt_str(body, "matter_code")
    if license_agreement_id is not None and event_type != "DOC_VIEW":
        raise_err("ERR_INVALID_REQUEST", "license_agreement_id is only allowed on DOC_VIEW events")

    # The caller never names the subscription: it is derived from the acting
    # user's ACTIVE seat, and X-User-ID is the SubscriberUser id (PRD 2.1).
    user = store.users.get(g.user_id)

    # Existence of a body-referenced agreement (priority 12).
    agreement = None
    if license_agreement_id is not None:
        agreement = store.agreements.get(license_agreement_id)
        if agreement is None:
            raise_err("ERR_AGREEMENT_NOT_FOUND", "license agreement %s does not exist" % license_agreement_id)

    seat_held = (
        user is not None
        and user["seat_status"] == "ACTIVE"
        and user["seat_subscription_id"] is not None
        and user["seat_subscription_id"] in store.subscriptions
    )
    subscription = store.subscriptions[user["seat_subscription_id"]] if seat_held else None

    # State gauntlet, in cascade order (21, 22, 23, then 25).
    if subscription is not None and subscription["status"] != "ACTIVE":
        raise_err("ERR_SUBSCRIPTION_NOT_ACTIVE", "subscription behind the seat is not ACTIVE")
    if agreement is not None and agreement["status"] != "ACTIVE":
        raise_err("ERR_AGREEMENT_NOT_ACTIVE", "license agreement %s is not ACTIVE" % license_agreement_id)
    if subscription is not None:
        now = store.clock
        for inv in store.invoices.values():
            if inv["subscription_id"] != subscription["id"]:
                continue
            if inv["status"] not in ("ISSUED", "OVERDUE", "PAID"):
                continue  # DRAFT and VOID windows do not close the period
            if day_start(inv["_period_start"]) <= now < day_start(inv["_period_end"]):
                raise_err("ERR_INVOICE_PERIOD_CLOSED", "event falls inside a closed invoice window")
    if not seat_held:
        raise_err("ERR_NO_SEAT_HELD", "acting user holds no ACTIVE seat")

    plan = store.plans[subscription["plan_id"]]

    # Business-safety gate 1: bulk-rate thresholds. The event that brings a
    # count up to the limit is admitted; the one after is refused.
    now = store.clock
    hourly_floor = now - timedelta(minutes=60)
    hourly = 0
    daily = 0
    for event in store.usage_events.values():
        if event["user_id"] != user["id"]:
            continue
        occurred = event["_occurred_dt"]
        if hourly_floor < occurred <= now:
            hourly += 1
        if occurred.date() == now.date():
            daily += 1
    if hourly >= plan["bulk_hourly_limit"] or daily >= plan["bulk_daily_limit"]:
        raise_err("ERR_BULK_RATE_EXCEEDED", "bulk rate limit reached for this user")

    # Business-safety gate 2: scope enforcement.
    in_scope = plan["practice_area"] == "ALL" or practice_area_tag == plan["practice_area"]
    if not in_scope and plan["scope_enforcement"] == "HARD":
        raise_err("ERR_USAGE_OUT_OF_SCOPE", "event practice area is outside the plan scope")

    # Referential gate: matter code carriage follows the account flag.
    account = store.accounts.get(subscription["account_id"])
    cost_recovery = account is not None and account["cost_recovery_enabled"]
    if cost_recovery and matter_code is None:
        raise_err("ERR_MATTER_CODE_REQUIRED", "matter_code is required on a cost-recovery account")
    if not cost_recovery and matter_code is not None:
        raise_err("ERR_MATTER_CODE_REQUIRED", "matter_code must be omitted on a non-recovery account")

    event = stamp_ledger({
        "subscription_id": subscription["id"],
        "user_id": user["id"],
        "event_type": event_type,
        "practice_area_tag": practice_area_tag,
        "license_agreement_id": license_agreement_id,
        "matter_code": matter_code,
        "in_scope": in_scope,
        "occurred_at": fmt_dt(now),
        "_occurred_dt": now,
    })
    store.usage_events[event["id"]] = event
    return ok_object(serialize_usage_event(event), 201)


@bp.get("/legal-research/usage-events")
@require_roles(*USAGE_READERS)
def list_usage_events():
    f_subscription = request.args.get("subscription_id")
    f_user = request.args.get("user_id")
    f_agreement = request.args.get("license_agreement_id")
    f_type = opt_enum_query("event_type", EVENT_TYPES)

    rows = list(store.usage_events.values())
    if f_subscription is not None:
        rows = [e for e in rows if e["subscription_id"] == f_subscription]
    if f_user is not None:
        rows = [e for e in rows if e["user_id"] == f_user]
    if f_agreement is not None:
        rows = [e for e in rows if e["license_agreement_id"] == f_agreement]
    if f_type is not None:
        rows = [e for e in rows if e["event_type"] == f_type]
    return list_response(rows, serialize_usage_event)


@bp.get("/legal-research/usage-events/<event_id>")
@require_roles(*USAGE_READERS)
def get_usage_event(event_id):
    event = store.usage_events.get(event_id)
    if event is None:
        raise_err("ERR_USAGE_EVENT_NOT_FOUND", "usage event %s does not exist" % event_id)
    return ok_object(serialize_usage_event(event))
