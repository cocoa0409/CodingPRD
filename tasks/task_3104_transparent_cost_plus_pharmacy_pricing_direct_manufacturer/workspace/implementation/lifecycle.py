"""The comparison lifecycle rule and the falsifiable-claim digest.

SCAFFOLD §1.3 comparison_lifecycle / PRD §3.9. Precedence is strict: an
enabled, unexpired substantiation always wins over the deadline branch.
"""

import hashlib

from clock import now, parse_iso
from registry import get, substantiations_of_order
from resources import touch


def substantiation_digest(order):
    """SHA-256 hex digest over the order id and the two reference figures."""
    retail = order.get("retail_reference_price_cents")
    benefit = order.get("insured_reference_price_cents")
    raw = "order=%s|retail=%s|benefit=%s" % (str(order.get("id")), str(retail), str(benefit))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def live_substantiations(order_id, clock):
    """The set S: status ENABLED and valid_until strictly after the clock."""
    live = []
    for record in substantiations_of_order(order_id):
        if record.get("status") != "ENABLED":
            continue
        valid_until = parse_iso(record.get("valid_until"))
        if valid_until is not None and valid_until > clock:
            live.append(record)
    return live


def derive(comparison, order, clock=None, force=False):
    """Re-derive state / substantiated / digest. Leaves REFRESH_REQUIRED alone
    unless force is set (the substitution transition owns that state)."""
    clock = clock or now()
    current = comparison.get("state")
    if current == "REFRESH_REQUIRED" and not force:
        return comparison

    live = live_substantiations(order.get("id"), clock)
    before = (
        comparison.get("state"),
        comparison.get("status"),
        comparison.get("substantiated"),
        comparison.get("substantiation_digest"),
    )

    if live:
        comparison["state"] = "FRESH"
        comparison["status"] = "SUBSTANTIATED"
        comparison["substantiated"] = True
        comparison["substantiation_digest"] = substantiation_digest(order)
    else:
        deadline = comparison.get("stale_deadline_at")
        deadline_at = parse_iso(deadline) if isinstance(deadline, str) else deadline
        ever_substantiated = comparison.get("ever_substantiated") is True
        disabled = [
            record
            for record in substantiations_of_order(order.get("id"))
            if record.get("status") == "DISABLED"
        ]
        if deadline_at is not None and clock > deadline_at and not ever_substantiated:
            comparison["state"] = "BLOCKED"
            comparison["status"] = "BLOCKED"
        elif disabled and _latest_valid_until(disabled) <= clock:
            comparison["state"] = "STALE"
            comparison["status"] = "UNSUBSTANTIATED"
        else:
            comparison["state"] = "FRESH"
            comparison["status"] = "UNSUBSTANTIATED"
        comparison["substantiated"] = False
        comparison["substantiation_digest"] = None

    after = (
        comparison.get("state"),
        comparison.get("status"),
        comparison.get("substantiated"),
        comparison.get("substantiation_digest"),
    )
    if before != after:
        touch(comparison)
    return comparison


def _latest_valid_until(records):
    latest = None
    for record in records:
        valid_until = parse_iso(record.get("valid_until"))
        if valid_until is None:
            continue
        if latest is None or valid_until > latest:
            latest = valid_until
    if latest is None:
        from datetime import datetime, timezone

        return datetime.min.replace(tzinfo=timezone.utc)
    return latest


def mark_ever_substantiated(comparison):
    comparison["ever_substantiated"] = True
    return comparison