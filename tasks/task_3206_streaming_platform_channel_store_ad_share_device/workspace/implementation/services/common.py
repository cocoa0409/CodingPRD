"""Shared service helpers: math, cascades, serializers."""

from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from db import store
from middleware import to_iso_z

# ---- constants (SCAFFOLD §1.3) ----
STANDING_PENALTY_BPS = 500
PROCESSING_FEE_PER_CHARGE_CENTS = 55
STANDARD_FEE_BPS = 2000
PREMIER_FEE_BPS = 1500
PREMIER_THRESHOLD_CENTS = 10000000
STRAIGHT_LINE_MONTHS = 24
MONETIZATION_RECOVERY_BPS = 3500
LAB_BUFFER_HOURS = 24
LAB_CAPACITY = 3
CAMPAIGN_CREDIT_LIMIT_CENTS = 100000


def round_half_up_cents(numerator, denominator=1):
    """round_half_up(numerator / denominator) -> int; away from zero on .5."""
    d = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(d)


def floor_div(numerator, denominator=1):
    d = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_FLOOR
    )
    return int(d)


def dt_of_iso(s):
    """Parse a stored ISO timestamp string back to datetime."""
    from middleware import parse_iso8601  # local import to avoid cycle
    return parse_iso8601(s, "ts")


# ---- cascades ----

def release_campaign_bookings(campaign):
    """Every HELD/CONFIRMED booking of this campaign -> RELEASED."""
    for b in store.placement_bookings.values():
        if b["campaign_id"] == campaign["id"] and b["status"] in ("HELD", "CONFIRMED"):
            b["status"] = "RELEASED"
            store.touch(b)


def pause_campaign(campaign):
    """ACTIVE or PAUSED -> PAUSED, releasing its bookings (cascade link 3)."""
    if campaign["status"] in ("ACTIVE", "PAUSED"):
        if campaign["status"] != "PAUSED":
            campaign["status"] = "PAUSED"
            store.touch(campaign)
        release_campaign_bookings(campaign)


def channel_suspension_cascade(channel):
    """Campaigns ACTIVE/PAUSED -> PAUSED; their bookings released."""
    for c in store.campaigns.values():
        if c["channel_id"] == channel["id"] and c["status"] in ("ACTIVE", "PAUSED"):
            pause_campaign(c)


def channel_removal_cascade(channel):
    """Suspend cascade + cancel ACTIVE subscriptions (billing + entitlement)."""
    channel_suspension_cascade(channel)
    for s in store.subscriptions.values():
        if s["channel_id"] == channel["id"] and s["billing_status"] == "ACTIVE":
            s["billing_status"] = "CANCELLED"
            s["entitlement_status"] = "REVOKED"
            store.touch(s)


# ---- serializers ----

def pub_view(p):
    return dict(p)


def channel_view(c):
    return dict(c)


def channel_version_view(v):
    return dict(v)


def viewer_view(v):
    return dict(v)


def subscription_view(s):
    return dict(s)


def grant_view(g):
    return dict(g)


def campaign_view(c):
    """Adds live pacing projection fields."""
    out = dict(c)
    fs = dt_of_iso(c["flight_start"])
    fe = dt_of_iso(c["flight_end"])
    total_hours = int((fe - fs).total_seconds() // 3600)
    if total_hours < 1:
        total_hours = 1
    elapsed = int((store.clock - fs).total_seconds() // 3600)
    if elapsed < 0:
        elapsed = 0
    if elapsed > total_hours:
        elapsed = total_hours
    expected = round_half_up_cents(c["budget_cents"] * elapsed, total_hours)
    out["expected_spend_cents"] = expected
    out["pacing_delta_cents"] = c["spent_cents"] - expected
    return out


def booking_view(b):
    return dict(b)


def manufacturer_view(m):
    return dict(m)


def device_model_view(m):
    return dict(m)


def lab_booking_view(b):
    return dict(b)


def os_update_view(u):
    return dict(u)


def device_unit_view(u):
    return dict(u)


def statement_view(s):
    return dict(s)


def dispute_view(d):
    return dict(d)
