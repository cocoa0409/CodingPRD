from datetime import timedelta

import db
import clock
import fiscal
from util import fmt_iso, parse_iso, add_years
from services import (
    AUTO_RENEW_GRACE_DAYS, REDEMPTION_GRACE_DAYS, PENDING_DELETE_DAYS,
)


def _auto_renew(d):
    now = clock.now()
    old_expiry = parse_iso(d["expires_on"])
    d["auto_renewed_on"] = d["expires_on"]
    new_expiry = add_years(old_expiry, 1)
    d["expires_on"] = fmt_iso(new_expiry)
    d["grace_deadline"] = fmt_iso(new_expiry + timedelta(days=AUTO_RENEW_GRACE_DAYS))
    d["status"] = "AUTO_RENEW_GRACE"
    db.touch(d, now)
    if d.get("registrar_id"):
        fiscal.lifecycle_invoice(d["registrar_id"], d, "AUTO_RENEW", 1)


def _enter_redemption(d, entry_instant):
    now = clock.now()
    # void outstanding AUTO_RENEW invoice if present
    if d["status"] == "AUTO_RENEW_GRACE":
        for inv in db.invoices.values():
            if inv["domain_id"] == d["id"] and inv["kind"] == "AUTO_RENEW" and inv["status"] == "OPEN":
                fiscal.void_invoice(inv)
        old = parse_iso(d["expires_on"])
        d["expires_on"] = fmt_iso(add_years(old, -1))
        d["grace_deadline"] = fmt_iso(add_years(old, -1) + timedelta(days=AUTO_RENEW_GRACE_DAYS))
    d["status"] = "REDEMPTION_GRACE"
    d["auto_renewed_on"] = None
    d["_redemption_entered_at"] = fmt_iso(entry_instant)
    db.touch(d, now)


def _enter_pending_delete(d):
    now = clock.now()
    entry = parse_iso(d["_redemption_entered_at"])
    d["status"] = "PENDING_DELETE"
    d["delete_scheduled_on"] = fmt_iso(entry + timedelta(days=REDEMPTION_GRACE_DAYS + PENDING_DELETE_DAYS))
    db.touch(d, now)


def _purge_deleted(d):
    d["status"] = "DELETED"
    db.touch(d, clock.now())


def _complete_transfer_side_effects(t):
    """Domain moves to gaining registrar, +1y, TRANSFER invoice."""
    now = clock.now()
    d = db.domains.get(t["domain_id"])
    if d is not None:
        d["registrar_id"] = t["to_registrar_id"]
        new_expiry = add_years(parse_iso(d["expires_on"]), 1)
        d["expires_on"] = fmt_iso(new_expiry)
        d["grace_deadline"] = fmt_iso(new_expiry + timedelta(days=AUTO_RENEW_GRACE_DAYS))
        d["status"] = "ACTIVE"
        db.touch(d, now)
        fiscal.lifecycle_invoice(t["to_registrar_id"], d, "TRANSFER", 1)


def _auto_ack(t):
    t["status"] = "AUTO_ACKED"
    db.touch(t, clock.now())


def _enforce_court_order(c):
    now = clock.now()
    d = db.domains.get(c["domain_id"])
    if d is not None:
        if c["action"] == "SUSPEND":
            d["suspension_status"] = "HOLD"
            db.touch(d, now)
        elif c["action"] == "UNSUSPEND":
            d["suspension_status"] = "NONE"
            db.touch(d, now)
        elif c["action"] == "TRANSFER_TO_REGISTRY":
            d["registrar_id"] = None
            d["suspension_status"] = "HOLD"
            if d["status"] == "TRANSFERRING":
                d["status"] = "ACTIVE"
            db.touch(d, now)
            for t in db.transfers.values():
                if t["domain_id"] == d["id"] and t["status"] in ("REQUESTED", "ACKED", "AUTO_ACKED"):
                    t["status"] = "NACKED"
                    db.touch(t, now)
    c["status"] = "ENFORCED"
    db.touch(c, now)


def _activate_schedule(s):
    now = clock.now()
    # supersede previously EFFECTIVE schedules
    for other in db.price_schedules.values():
        if other["id"] != s["id"] and other["status"] == "EFFECTIVE":
            other["status"] = "SUPERSEDED"
            db.touch(other, now)
    s["status"] = "EFFECTIVE"
    db.touch(s, now)
    fiscal.emit_effective_notices(s)


def advance_clock(target_dt):
    """Set the logical clock forward, firing all due time-driven transitions.

    Iterates until quiescent since one transition can feed another.
    """
    from errors import err_invalid_request
    current = clock.now()
    if target_dt < current:
        raise err_invalid_request("to_iso8601 must not move the clock backwards")
    clock.set_now(target_dt)

    changed = True
    while changed:
        changed = False
        now = clock.now()

        # domains
        for d in sorted(db.domains.values(), key=lambda x: (x["created_at"], x["id"])):
            if d["status"] == "ACTIVE" and d.get("registrar_id") and now > parse_iso(d["expires_on"]):
                _auto_renew(d)
                changed = True
            elif d["status"] == "AUTO_RENEW_GRACE":
                aro = parse_iso(d["auto_renewed_on"])
                if now > aro + timedelta(days=AUTO_RENEW_GRACE_DAYS):
                    _enter_redemption(d, aro + timedelta(days=AUTO_RENEW_GRACE_DAYS))
                    changed = True
            elif d["status"] == "REDEMPTION_GRACE":
                entry = parse_iso(d["_redemption_entered_at"])
                if now > entry + timedelta(days=REDEMPTION_GRACE_DAYS):
                    _enter_pending_delete(d)
                    changed = True
            elif d["status"] == "PENDING_DELETE":
                entry = parse_iso(d["_redemption_entered_at"])
                if now > entry + timedelta(days=REDEMPTION_GRACE_DAYS + PENDING_DELETE_DAYS):
                    _purge_deleted(d)
                    changed = True

        # transfers: auto-ack
        for t in sorted(db.transfers.values(), key=lambda x: (x["created_at"], x["id"])):
            if t["status"] == "REQUESTED":
                if now > parse_iso(t["requested_at"]) + timedelta(days=5):
                    _auto_ack(t)
                    changed = True

        # court orders: deferred enforcement
        for c in sorted(db.court_orders.values(), key=lambda x: (x["created_at"], x["id"])):
            if c["status"] == "LODGED":
                lodged = parse_iso(c["created_at"])
                if now > lodged + timedelta(hours=48):
                    _enforce_court_order(c)
                    changed = True

        # price schedules: effectiveness
        for s in sorted(db.price_schedules.values(), key=lambda x: (parse_iso(x["effective_on"]), x["id"])):
            if s["status"] == "PROPOSED" and now >= parse_iso(s["effective_on"]):
                _activate_schedule(s)
                changed = True

    return clock.now()


def explicit_delete_to_redemption(d):
    """POST /domains/{id}/delete: ACTIVE or AUTO_RENEW_GRACE -> REDEMPTION_GRACE."""
    _enter_redemption(d, clock.now())
