"""Revenue events, routing records and the settlement waterfall.

The split is computed once per routing record (PRD section 3.8) and the
settlement waterfall consumes buckets highest-confidence first (PRD 3.9).
"""

import db
from db import now, to_iso8601, touch
from errors import raise_error
from services.money import (
    HOLDER_KEEP_RATE,
    SPLITTER_SHARE_RATE,
    STREAM_CREATOR_RATES,
    STREAM_TYPES,
    half_up,
    split_amount,
)

# Settlement results are held in a side ledger that is never serialised onto a
# resource, keeping the declared schemas exact.
SETTLEMENT_LEDGER = {}


def validate_stream_type(stream_type):
    if stream_type not in STREAM_TYPES:
        raise_error("ERR_UNSUPPORTED_STREAM_TYPE")


def record_revenue_event(channel_id, stream_type, amount_cents, content_item_id):
    validate_stream_type(stream_type)
    event = db.subresource_fields(
        {
            "channel_id": channel_id,
            "stream_type": stream_type,
            "content_item_id": content_item_id,
            "amount_cents": int(amount_cents),
            "occurred_at": to_iso8601(now()),
            "routed": False,
        }
    )
    db.insert("revenue_events", event)
    return event


def create_routing(content_item, claim, stream_type, gross_revenue_cents):
    """Mint one RevenueRouting row and split it per record."""
    validate_stream_type(stream_type)
    gross = int(gross_revenue_cents)
    creator, partner = split_amount(gross, STREAM_CREATOR_RATES[stream_type])

    # PRD section 3.8 dates the record from the item's own routing ledger: "When
    # the item's `holds_revenue` flag is true -- that is, when at least one of its
    # routing rows is in `ESCROW` or `RETROACTIVE_OWED` -- the new record is
    # created as `ESCROW`".  A claim that has not yet parked a routing row
    # therefore leaves the next record PAID_CREATOR.
    parked = any(
        r["status"] in ("ESCROW", "RETROACTIVE_OWED")
        for r in db.all_of("revenue_routings")
        if r["content_item_id"] == content_item["id"]
    )
    status = "ESCROW" if parked else "PAID_CREATOR"
    routing = db.subresource_fields(
        {
            "content_item_id": content_item["id"],
            "claim_id": claim["id"] if claim else None,
            "stream_type": stream_type,
            "gross_revenue_cents": gross,
            "matched_segment_seconds": 0,
            "creator_share_cents": creator,
            "partner_share_cents": partner,
            "status": status,
        }
    )
    db.insert("revenue_routings", routing)

    from services import content as content_svc

    content_svc.recompute_item(content_item)
    return routing


def routings_of_channel(channel_id):
    item_ids = {
        item["id"]
        for item in db.all_of("content_items")
        if item["channel_id"] == channel_id
    }
    return [r for r in db.all_of("revenue_routings") if r["content_item_id"] in item_ids]


def settle_item(item):
    """The settlement waterfall across the item's claims and its channel.

    Buckets: the item's claims ordered by match_confidence DESC then created_at
    ASC, followed by the null-claim bucket, followed by the channel bucket which
    absorbs the rounding remainder.
    """
    claims = sorted(
        [c for c in db.all_of("claims") if c["content_item_id"] == item["id"]],
        key=lambda c: (-float(c["match_confidence"]), c["created_at"], c["id"]),
    )

    buckets = [{"kind": "claim", "claim_id": c["id"], "amount": 0} for c in claims]
    buckets.append({"kind": "no_claim", "claim_id": None, "amount": 0})
    buckets.append({"kind": "channel", "claim_id": None, "amount": 0})

    remaining = int(item["gross_revenue_cents"])
    for bucket in buckets[:-1]:
        holder_amount = remaining - half_up(remaining * SPLITTER_SHARE_RATE)
        bucket["amount"] = holder_amount
        remaining -= holder_amount
    buckets[-1]["amount"] = remaining

    SETTLEMENT_LEDGER[item["id"]] = buckets
    touch(item)
    return item