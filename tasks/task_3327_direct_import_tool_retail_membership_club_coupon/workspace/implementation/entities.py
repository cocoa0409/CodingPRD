"""Shared entity helpers: common fields, lazy expiry, membership status."""
import uuid
from datetime import timedelta
from db import DB, fmt_iso, parse_iso
from errors import raise_err


def new_id():
    return str(uuid.uuid4())


def stamp_new(rec):
    now = fmt_iso(DB.now())
    rec["id"] = new_id()
    rec["created_at"] = now
    rec["updated_at"] = now
    rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = fmt_iso(DB.now())
    rec["version"] = rec.get("version", 1) + 1


def get_or_404(table, _id):
    rec = table.get(_id)
    if rec is None:
        raise_err("ERR_NOT_FOUND", "Resource not found")
    return rec


def lazy_membership(m):
    """Lazy expiry: ACTIVE -> LAPSED when past expires_at."""
    if m["status"] == "ACTIVE":
        exp = parse_iso(m["expires_at"])
        if exp is not None and DB.now() > exp:
            m["status"] = "LAPSED"
            touch(m)


def lazy_coupon(c):
    """Lazy expiry: ACTIVE/PAUSED -> EXPIRED when now >= window_end."""
    if c["status"] in ("ACTIVE", "PAUSED"):
        end = parse_iso(c["window_end"])
        if end is not None and DB.now() >= end:
            c["status"] = "EXPIRED"
            touch(c)


def effective_member(customer_id, now=None):
    """Membership status in {ACTIVE, LAPSED} and now <= expires_at + 30 days.
    CANCELLED never qualifies."""
    if now is None:
        now = DB.now()
    for m in DB.memberships.values():
        if m["customer_id"] == customer_id:
            lazy_membership(m)
            if m["status"] in ("ACTIVE", "LAPSED"):
                exp = parse_iso(m["expires_at"])
                if exp is not None and now <= exp + timedelta(days=30):
                    return m
            return None
    return None


def membership_of(customer_id):
    for m in DB.memberships.values():
        if m["customer_id"] == customer_id:
            return m
    return None
