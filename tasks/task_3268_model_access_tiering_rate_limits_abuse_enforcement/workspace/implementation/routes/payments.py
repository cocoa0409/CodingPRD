"""Payment event routes."""
from __future__ import annotations

import db
from errors import (invalid_amount, invalid_state, not_found,
                    org_status_blocked)
from middleware import require_roles
from response import success
from services.domain import recompute_tier, MIN_QUALIFYING_PAYMENT_CENTS
from services.util import body, require_enum, require_int, require_str, stamp_new, touch, simple_view

from flask import Blueprint

bp = Blueprint("payment_events", __name__)


@bp.post("/payment-events")
def create_payment_event():
    require_roles("PlatformAdmin", "BillingContact")
    data = body()
    org_id = require_str(data, "organization_id")
    kind = require_enum(data, "kind", {"PREPAID_TOPUP", "INVOICE_SETTLEMENT", "REFUND"})
    amount = require_int(data, "amount_cents")
    org = db.organizations.get(org_id)
    if org is None:
        raise not_found("organization not found")
    if org["status"] == "TERMINATED":
        raise org_status_blocked("TERMINATED organization blocks new payments")
    if amount == 0:
        raise invalid_amount("amount_cents may not be zero")
    if kind == "REFUND" and amount >= 0:
        raise invalid_amount("REFUND amounts must be negative")
    if kind in ("PREPAID_TOPUP", "INVOICE_SETTLEMENT") and amount <= 0:
        raise invalid_amount("amount must be positive for this kind")
    event = {
        "organization_id": org_id,
        "kind": kind,
        "amount_cents": amount,
        "status": "PENDING",
    }
    stamp_new(event, common=False)
    db.payment_events[event["id"]] = event
    return success(simple_view(event), status=201)


@bp.post("/payment-events/<event_id>/settle")
def settle_payment_event(event_id):
    require_roles("PlatformAdmin")
    event = db.payment_events.get(event_id)
    if event is None:
        raise not_found("payment event not found")
    if event["status"] != "PENDING":
        raise invalid_state("payment is not PENDING")
    org = db.organizations.get(event["organization_id"])
    if org is not None and org["status"] == "TERMINATED":
        raise invalid_state("cannot settle payment for TERMINATED organization")
    event["status"] = "SETTLED"
    if org is not None:
        org["lifetime_spend_cents"] += event["amount_cents"]
        if event["amount_cents"] >= MIN_QUALIFYING_PAYMENT_CENTS:
            org["qualifying_payment_count"] += 1
        if event["kind"] == "PREPAID_TOPUP":
            org["credit_balance_cents"] += event["amount_cents"]
        elif event["kind"] == "REFUND":
            org["credit_balance_cents"] = max(0, org["credit_balance_cents"] + event["amount_cents"])
        recompute_tier(org)
        touch(org)
    return success(simple_view(event))
