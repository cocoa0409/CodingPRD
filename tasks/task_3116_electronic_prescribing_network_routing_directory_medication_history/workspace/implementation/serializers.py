"""Wire serializers — the exact field set each read returns."""

import clock
import db
from services import billing, directory, history, routing


def participant(p):
    payload = db.dump(p)
    reachable, total, label = directory.reachability(p["id"])
    payload["delivery_reachability"] = label
    payload["open_route_attempt_count"] = routing.open_route_attempt_count(p["id"])
    payload["directory_listed"] = bool(p.get("directory_listed"))
    return payload


def endpoint(e):
    payload = db.dump(e)
    payload["effective_from"] = clock.iso(e["effective_from"])
    payload["effective_to"] = clock.iso(e["effective_to"]) if e.get("effective_to") else None
    payload["reliability_ratio"] = float(e.get("reliability_ratio", 1.0))
    payload["reliability_ratio_ewma"] = float(e.get("reliability_ratio_ewma", 1.0))
    return payload


def patient(p):
    return db.dump(p)


def consent(c):
    history.refresh_consent_status(c)
    payload = db.dump(c)
    payload["granted_at"] = clock.iso(c["granted_at"])
    payload["expires_at"] = clock.iso(c["expires_at"])
    payload["revoked_at"] = clock.iso(c["revoked_at"]) if c.get("revoked_at") else None
    return payload


def history_record(r):
    payload = db.dump(r)
    payload["fill_date"] = clock.iso(r["fill_date"])
    payload["retracted_at"] = clock.iso(r["retracted_at"]) if r.get("retracted_at") else None
    return payload


def batch(b):
    return db.dump(b)


def prescription(p):
    """The computed flags are derived immediately, not only at write time.

    §3.3 makes `monitored_under_consent` and therefore `significance` a function
    of the patient's live consent registry, so the read path re-derives both
    before serializing — a consent granted or revoked after the order was
    authored is reflected on the next read.
    """
    routing.recompute_derived(p)
    return db.dump(p)


def signing_session(s):
    return db.dump(s)


def signature_session(s):
    """The one signing session recorded as an order's signature authority."""
    return [db.dump(s)] if s else []


def routing_attempt(a):
    return db.dump(a)


def benefit_check(b):
    return db.dump(b)


def fee_entry(e):
    return billing.entry_payload(e)


def reachability_report(p):
    reachable, total, label = directory.reachability(p["id"])
    return {
        "participant_id": p["id"],
        "reachable_endpoint_count": reachable,
        "total_endpoint_count": total,
        "delivery_reachability": label,
    }