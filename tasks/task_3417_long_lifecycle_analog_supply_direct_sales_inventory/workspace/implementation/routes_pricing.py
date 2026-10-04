# Published pricing routes (PRD 3.3): schedules and channel-invariant quotes.
from flask import Blueprint

import constants as C
import derive
from auth import require_roles
from envelope import success
from errors import ApiError, ERR_NO_PUBLISHED_PRICING, ERR_STALE_VERSION
from lookups import get_part
from serialize import pricing_schedule_public
from store import store
from validate import (
    as_datetime,
    as_enum,
    as_int,
    as_int_at_least,
    as_str,
    check_unknown_fields,
    get_body,
    require_fields,
    validate_tiers,
)

bp = Blueprint("pricing", __name__)

_SCHEDULE_ALLOWED = {"part_id", "effective_from", "tiers", "expected_part_version"}
_QUOTE_ALLOWED = {"part_id", "quantity", "channel"}


@bp.post("/pricing-schedules")
def publish_pricing_schedule():
    require_roles("ChannelManager")
    body = get_body(required=True)
    # Existence (row 3) of the referenced part precedes schema (row 4).
    part = None
    if "part_id" in body and body["part_id"] is not None:
        part = get_part(body["part_id"])
    require_fields(body, ["part_id", "effective_from", "tiers", "expected_part_version"])
    check_unknown_fields(body, _SCHEDULE_ALLOWED)
    as_str(body["part_id"], "part_id")
    effective_from = as_datetime(body["effective_from"], "effective_from")
    tiers = validate_tiers(body["tiers"])
    expected_part_version = as_int(body["expected_part_version"], "expected_part_version")
    # OCC (PRD 2.7): stale view of the part rejects the publish.
    if expected_part_version != part["version"]:
        raise ApiError(
            ERR_STALE_VERSION, 412,
            "expected_part_version %s does not match the part's current version %s"
            % (expected_part_version, part["version"]),
        )
    # Supersede the part's prior PUBLISHED schedule, if any.
    for sched in store.pricing_schedules.values():
        if sched["part_id"] == part["id"] and sched["status"] == "PUBLISHED":
            sched["status"] = "SUPERSEDED"
            store.touch(sched)
    schedule = {
        "part_id": part["id"],
        "effective_from": effective_from,
        "tiers": tiers,
        "status": "PUBLISHED",
        "published_at": store.now(),
    }
    schedule.update(store.stamp())
    store.pricing_schedules[schedule["id"]] = schedule
    # Publishing advances Part.version — this is what serializes pricing writers.
    store.touch(part)
    return success(pricing_schedule_public(schedule), 201)


@bp.post("/pricing/quote")
def quote_price():
    require_roles("PlatformAdmin", "SupplyPlanner", "ChannelManager", "FieldEngineer", "Customer")
    body = get_body(required=True)
    part = None
    if "part_id" in body and body["part_id"] is not None:
        part = get_part(body["part_id"])
    require_fields(body, ["part_id", "quantity", "channel"])
    check_unknown_fields(body, _QUOTE_ALLOWED)
    quantity = as_int_at_least(body["quantity"], "quantity", 1)
    channel = as_enum(body["channel"], "channel", C.CHANNELS)
    schedule = derive.published_schedule(part["id"])
    if schedule is None:
        raise ApiError(ERR_NO_PUBLISHED_PRICING, 422, "No PUBLISHED pricing schedule is effective for this part")
    # The channel argument is validated but must never influence the price.
    tier = derive.tier_for_quantity(schedule, quantity)
    return success({
        "part_id": part["id"],
        "quantity": quantity,
        "channel": channel,
        "tier_min_qty": tier["min_qty"],
        "unit_price_cents": tier["unit_price_cents"],
    })
