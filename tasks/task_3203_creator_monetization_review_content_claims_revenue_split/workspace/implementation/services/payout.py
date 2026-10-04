"""Memberships, member payout runs and the two-stage payout batches."""

from decimal import Decimal

import db
from db import now, parse_iso8601, to_iso8601, touch
from errors import raise_error
from services.money import (
    MEMBERSHIP_CREATOR_RATE,  # noqa: F401
    MEMBER_REVENUE_UNIT_CENTS,
    NETWORK_FEE_RATE,
    PAYMENT_THRESHOLD_DEFAULT_CENTS,
    half_up,
    withholding_rate_for,
)

PLATFORM_SHARE_RATE = Decimal("1") - MEMBERSHIP_CREATOR_RATE

ROUTED_STATUSES = ("RELEASED_TO_CREATOR", "PAID_CREATOR", "ESCROW")


def publish_membership_schedule(channel, tier_name, monthly_fee_cents, perks):
    """membership_schedule: every component is rounded independently."""
    fee = int(monthly_fee_cents)
    creator_share = half_up(Decimal(fee) * MEMBERSHIP_CREATOR_RATE)
    platform_share = half_up(Decimal(fee) * PLATFORM_SHARE_RATE)
    network_fee = half_up(Decimal(fee) * NETWORK_FEE_RATE)

    schedule = db.common_fields(
        {
            "channel_id": channel["id"],
            "tier_name": tier_name,
            "monthly_fee_cents": fee,
            "perks": perks or [],
            "creator_share_cents": creator_share,
            "platform_share_cents": platform_share,
            "network_fee_cents": network_fee,
            "member_charge_cents": fee + network_fee,
        }
    )
    db.insert("membership_schedules", schedule)

    channel["membership_offered"] = True
    touch(channel)
    return schedule


def enrol_member(channel, member_name, monthly_fee_cents, joined_at):
    stamp = parse_iso8601(joined_at) if joined_at else None
    member = db.common_fields(
        {
            "channel_id": channel["id"],
            "member_name": member_name,
            "monthly_fee_cents": int(monthly_fee_cents),
            "joined_at": to_iso8601(stamp or now()),
            "paid_member_months": 0,
            "status": "ACTIVE",
            "payout_cents": 0,
        }
    )
    db.insert("channel_memberships", member)
    return member


def run_member_payout(channel, total_payout_cents):
    """member_payout_ranking: paid months DESC, joined_at ASC, created_at ASC."""
    eligible = [
        m
        for m in db.all_of("channel_memberships")
        if m["channel_id"] == channel["id"] and m["status"] == "ACTIVE"
    ]
    if not eligible:
        raise_error("ERR_NO_ELIGIBLE_MEMBERS")

    ordered = sorted(
        eligible,
        key=lambda m: (-int(m["paid_member_months"]), m["joined_at"], m["created_at"], m["id"]),
    )

    remaining = int(total_payout_cents)
    for member in ordered:
        grant = half_up(int(member["paid_member_months"]) * MEMBER_REVENUE_UNIT_CENTS)
        if remaining < grant:
            grant = max(remaining, 0)
        member["payout_cents"] = grant
        touch(member)
        remaining -= grant

    touch(channel)
    return ordered


def routed_set(channel_id, period_start_at, period_end_at):
    start = parse_iso8601(period_start_at)
    end = parse_iso8601(period_end_at)
    selected = []
    for routing in db.all_of("revenue_routings"):
        if routing["status"] not in ROUTED_STATUSES:
            continue
        if channel_id_of_routing(routing) != channel_id:
            continue
        created = parse_iso8601(routing["created_at"])
        if created is None:
            continue
        if start is not None and created < start:
            continue
        if end is not None and created >= end:
            continue
        selected.append(routing)
    return selected


def channel_id_of_routing(routing):
    item = db.get("content_items", routing["content_item_id"])
    return item["channel_id"] if item else None


def batch_totals(channel, period_start_at, period_end_at):
    rows = routed_set(channel["id"], period_start_at, period_end_at)
    gross = sum(int(r["gross_revenue_cents"]) for r in rows)
    creator = sum(int(r["creator_share_cents"]) for r in rows)
    partner = sum(int(r["partner_share_cents"]) for r in rows)
    held = sum(int(r["creator_share_cents"]) for r in rows if r["status"] == "ESCROW")
    return rows, gross, creator, partner, held


def compute_withholding(channel, creator_share_cents, held_cents):
    payer_base = creator_share_cents - held_cents
    rate = withholding_rate_for(
        channel.get("country_code"),
        channel.get("tax_treaty", False),
        channel.get("tax_tin_status", "TIN_MISSING"),
    )
    withheld = half_up(Decimal(payer_base) * rate)
    raw_net = payer_base - withheld
    adjusted_net = 0 if raw_net < 0 else raw_net
    return payer_base, withheld, adjusted_net, rate


def lock_payout_batch(channel, period_start_at, period_end_at):
    """POST /channels/{id}/payouts/lock -- a ROUTE-stage batch in LOCKED status."""
    rows, gross, creator, partner, held = batch_totals(
        channel, period_start_at, period_end_at
    )
    _, withheld, adjusted_net, rate = compute_withholding(channel, creator, held)

    batch = db.common_fields(
        {
            "channel_id": channel["id"],
            "route_batch_id": None,
            "stage": "ROUTE",
            "status": "LOCKED",
            "period_start_at": period_start_at,
            "period_end_at": period_end_at,
            "gross_cents": gross,
            "creator_share_cents": creator,
            "partner_share_cents": partner,
            "held_cents": held,
            "tax_withheld_cents": withheld,
            "withholding_rate_pct": float(rate),
            "adjusted_net_cents": adjusted_net,
            "paid_at": None,
        }
    )
    db.insert("payout_batches", batch)

    touch(channel)
    return batch


def release_payout_batch(channel, batch, expected_payout_batch_version):
    """POST /channels/{id}/payouts/{batchId}/release."""
    if batch["channel_id"] != channel["id"]:
        raise_error("ERR_PAYOUT_BATCH_NOT_FOUND")
    if batch["status"] != "LOCKED":
        raise_error("ERR_INVALID_STATE")
    if (
        expected_payout_batch_version is not None
        and int(expected_payout_batch_version) != batch["version"]
    ):
        raise_error("ERR_STALE_VERSION")

    # Recompute the post-resolution ledger from the routed set as it stands now.
    _, gross, creator, partner, held = batch_totals(
        channel, batch["period_start_at"], batch["period_end_at"]
    )
    payer_base, withheld, adjusted_net, rate = compute_withholding(channel, creator, held)

    threshold = int(channel.get("payment_threshold_cents", PAYMENT_THRESHOLD_DEFAULT_CENTS))
    if adjusted_net < threshold:
        raise_error("ERR_BELOW_PAYMENT_THRESHOLD")

    batch["gross_cents"] = gross
    batch["creator_share_cents"] = creator
    batch["partner_share_cents"] = partner
    batch["held_cents"] = held
    batch["tax_withheld_cents"] = withheld
    batch["withholding_rate_pct"] = float(rate)
    batch["adjusted_net_cents"] = adjusted_net

    paid_at = to_iso8601(now())
    batch["status"] = "RELEASED"
    batch["paid_at"] = paid_at
    touch(batch)

    payout_row = db.common_fields(
        {
            "channel_id": channel["id"],
            "route_batch_id": batch["id"],
            "stage": "PAYOUT",
            "status": "RELEASED",
            "period_start_at": batch["period_start_at"],
            "period_end_at": batch["period_end_at"],
            "gross_cents": gross,
            "creator_share_cents": creator,
            "partner_share_cents": partner,
            "held_cents": held,
            "tax_withheld_cents": withheld,
            "withholding_rate_pct": float(rate),
            "adjusted_net_cents": adjusted_net,
            "paid_at": paid_at,
        }
    )
    db.insert("payout_batches", payout_row)
    return batch