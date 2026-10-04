"""POST /_clock/set_current_utc — advance the logical clock (§2.5)."""
from datetime import datetime, timezone

from flask import Blueprint, request

import calc
import store
from auth import require_role
from envelope import success
from errors import err
from helpers import cascade_grant_terminal, cascade_grant_suspended

bp = Blueprint("clock", __name__)


def _parse_iso(s):
    if not isinstance(s, str):
        return None
    try:
        v = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_role("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    to_iso = body.get("to_iso8601")
    target = _parse_iso(to_iso)
    if target is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 instant")

    old = store.clock_current
    delta_seconds = (target - old).total_seconds()
    advanced = int(delta_seconds // 86400)
    if advanced < 0:
        advanced = 0
    store.clock_current = target

    # 1. advance every org's period index by the whole-day delta
    for org in store.orgs.values():
        org["current_period_index"] += advanced
        store.touch(org)

    # 2. grant auto-expiry: ACTIVE grants with valid_to_period <= new period
    for grant in store.license_grants.values():
        if grant["status"] != "ACTIVE":
            continue
        org = store.orgs.get(grant["organization_id"])
        if org is None:
            continue
        if org["current_period_index"] >= grant["valid_to_period"]:
            cascade_grant_terminal(grant, "EXPIRED")

    # 3. EV renewal flips: APPROVED with valid_through_period <= new period
    for ev in store.eligibility_verifications.values():
        if ev["status"] != "APPROVED":
            continue
        org = store.orgs.get(ev["organization_id"])
        if org is None:
            continue
        vtp = ev.get("valid_through_period")
        if vtp is not None and org["current_period_index"] >= vtp:
            ev["status"] = "RENEWAL_REQUIRED"
            store.touch(ev)
            for grant in store.license_grants.values():
                if (grant["organization_id"] == ev["organization_id"]
                        and grant["grant_kind"] == ev["program_kind"]
                        and grant["status"] == "ACTIVE"):
                    cascade_grant_suspended(grant)

    # 4. sustained overage accrual per org (average-rate form)
    for org in store.orgs.values():
        total = 0
        for grant in store.license_grants.values():
            if grant["organization_id"] != org["id"] or grant["status"] != "ACTIVE":
                continue
            product = store.license_products.get(grant["license_product_id"])
            if not product or product["license_kind"] != "CONCURRENT_USE":
                continue
            sustained = max(0, grant["seats_in_use"] - grant["seats_allocated"])
            total += calc.sustained_overage_fee_cents(sustained)
        if total:
            org["seat_overage_fee_accrued_cents"] += total
            store.touch(org)

    # 5. posture recomputation for every org
    for pool in store.credit_pools.values():
        calc.refresh_pool(pool)

    current_utc = store.clock_current.strftime("%Y-%m-%dT%H:%M:%SZ")
    return success({"current_utc": current_utc, "advanced_periods": advanced})
