"""Serialisation helpers.

Each resource is emitted with exactly the fields the scaffold declares for it --
no side ledgers, no internal bookkeeping keys.
"""

import db
from services import channel as channel_svc
from services import claims as claim_svc
from services import content as content_svc


def copy(record):
    return dict(record) if record is not None else None


def channel_view(channel):
    """Channels are always served with their derived posture freshly computed."""
    if channel is None:
        return None
    channel["copyright_strike_count"] = channel_svc.count_copyright_strikes(channel["id"])
    channel_svc.recompute_posture(channel)
    return dict(channel)


def content_item_view(item):
    if item is None:
        return None
    content_svc.recompute_item(item)
    return dict(item)


def claim_view(claim):
    if claim is None:
        return None
    claim_svc.refresh_claim_derived(claim)
    return dict(claim)


def plain(record):
    return copy(record)