"""Class packs: sale, expiry clock, extension and the expiry sweep."""

from core import (
    PACK_EXPIRY_GRACE_DAYS,
    PACK_MAX_EXTENSION_DAYS,
    PACK_PROMOTIONAL_DAYS,
    PACK_PROMOTIONAL_MAX_SIZE,
    PACK_SEASONAL_DAYS,
    PACK_VALIDITY_DAYS,
    EXPIRY_SCHEMES,
    add_days,
    fail,
    now,
    parse_dt,
)
from commons import mint, require_gate, touch
from store import CLASS_PACKS, CLIENTS, STUDIOS, SUBSCRIPTIONS

import calc


def pack_or_404(pack_id):
    pack = CLASS_PACKS.get(pack_id)
    if pack is None:
        fail("ERR_CLASS_PACK_NOT_FOUND")
    return pack


def create_pack(body):
    studio = STUDIOS.get(body.get("studio_id"))
    if studio is None:
        fail("ERR_STUDIO_NOT_FOUND")
    client = CLIENTS.get(body.get("client_id"))
    if client is None:
        fail("ERR_CLIENT_NOT_FOUND")
    require_gate(studio, "staff_payroll")
    if studio.get("status") in ("SUSPENDED", "CANCELLED"):
        fail("ERR_STUDIO_NOT_OPERATING")
    subscription = SUBSCRIPTIONS.get(studio.get("subscription_id"))
    if subscription is not None and subscription.get("status") in ("SUSPENDED", "CANCELLED"):
        fail("ERR_SUBSCRIPTION_INACTIVE")

    scheme = body.get("expiry_scheme")
    if scheme not in EXPIRY_SCHEMES:
        fail("ERR_INVALID_STATE", "Unknown expiry_scheme.", 409)
    pack_size = int(body.get("pack_size", 0))
    if pack_size < 1:
        fail("ERR_INVALID_STATE", "pack_size must be at least 1.", 409)
    if scheme == "PROMOTIONAL" and pack_size > PACK_PROMOTIONAL_MAX_SIZE:
        fail("ERR_INVALID_STATE", "A promotional pack may hold at most 12 credits.", 409)

    purchased_at = parse_dt(body.get("purchased_at")) or now()
    if scheme == "SEASONAL":
        span = PACK_SEASONAL_DAYS
    elif scheme == "PROMOTIONAL":
        span = PACK_PROMOTIONAL_DAYS
    else:
        span = PACK_VALIDITY_DAYS
    expires_at = add_days(purchased_at, span)

    pack = mint(
        CLASS_PACKS,
        {
            "studio_id": studio["id"],
            "client_id": client["id"],
            "pack_size": pack_size,
            "credits_remaining": pack_size,
            "purchased_at": purchased_at,
            "expires_at": expires_at,
            "extension_days_used": 0,
            "status": "ACTIVE",
            "pending_expiry_grace_until": None,
            "expiry_scheme": scheme,
            "_overage_cents": 0,
            "_pre_expiry_credits": pack_size,
            "_voided": 0,
            "_grace_used": 0,
        },
    )
    touch(client)
    return pack


def extend_pack(pack, body):
    extend_days = int(body.get("extend_days", 0))
    if extend_days <= 0:
        fail("ERR_PACK_EXTENSION_CAP_EXCEEDED")
    if pack.get("extension_days_used", 0) + extend_days > PACK_MAX_EXTENSION_DAYS:
        fail("ERR_PACK_EXTENSION_CAP_EXCEEDED")
    pack["expires_at"] = add_days(pack.get("expires_at"), extend_days)
    pack["extension_days_used"] = pack.get("extension_days_used", 0) + extend_days
    touch(pack)
    return pack


def sweep_expiry(body=None, pack=None):
    body = body or {}
    days = body.get("advance_clock_days")
    if days not in (None, ""):
        from core import advance_clock as move_clock

        move_clock(days=int(days))

    expired_count = 0
    credits_voided = 0
    credits_returned = 0
    candidates = [pack] if pack is not None else list(CLASS_PACKS.values())
    for row in candidates:
        if row is None or row.get("status") not in ("ACTIVE", "FROZEN", "DEPLETED"):
            continue
        expires_at = row.get("expires_at")
        if expires_at is None or not (expires_at <= now()):
            continue
        at_expiry = max(
            0, row.get("credits_remaining", 0) - row.get("_grace_used", 0)
        )
        row["_pre_expiry_credits"] = at_expiry
        row["_voided"] = at_expiry
        row["status"] = "EXPIRED"
        row["pending_expiry_grace_until"] = add_days(expires_at, PACK_EXPIRY_GRACE_DAYS)
        touch(row)
        expired_count += 1
        credits_voided += at_expiry
        credits_returned += calc.credits_returned_to_studio(at_expiry)
    return {
        "expired_count": expired_count,
        "credits_voided": credits_voided,
        "credits_returned_to_studio": credits_returned,
    }


def pack_zero_value_next(pack_id):
    from store import PACK_ZERO_DISCOUNTS

    return PACK_ZERO_DISCOUNTS.get(pack_id, 0) > 0


def consume_pack_zero_value(pack_id):
    from store import PACK_ZERO_DISCOUNTS

    if PACK_ZERO_DISCOUNTS.get(pack_id, 0) > 0:
        PACK_ZERO_DISCOUNTS[pack_id] -= 1
        return True
    return False