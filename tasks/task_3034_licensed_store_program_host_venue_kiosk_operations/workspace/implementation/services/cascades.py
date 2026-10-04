"""Cascading side effects (SCAFFOLD §1.2 state machines, PRD §2.7)."""
import middleware as mw
from db import db


def suspend_agreement(agreement):
    """Agreement ACTIVE -> SUSPENDED cascade (manual or breach-strike auto)."""
    agreement["status"] = "SUSPENDED"
    mw.touch(agreement)
    for store in db.stores.values():
        if store["agreement_id"] != agreement["id"]:
            continue
        if store["operating_status"] != "OPERATING":
            continue
        _suspend_store(store)


def _suspend_store(store):
    """Store OPERATING -> SUSPENDED cascade."""
    store["operating_status"] = "SUSPENDED"
    mw.touch(store)
    for o in db.supply_orders.values():
        if o["store_id"] == store["id"] and o["status"] in ("DRAFT", "SUBMITTED"):
            o["status"] = "CANCELLED"
            mw.touch(o)
    for c in db.promotion_campaigns.values():
        if c["store_id"] == store["id"] and c["status"] == "ACTIVE":
            c["status"] = "ENDED"
            mw.touch(c)


def suspend_store(store):
    """Manual store suspend (OPERATING -> SUSPENDED)."""
    _suspend_store(store)


def delicense_store(store):
    """Store -> DELICENSED cascade (manual or agreement terminate/expire)."""
    store["operating_status"] = "DELICENSED"
    mw.touch(store)
    for o in db.supply_orders.values():
        if o["store_id"] == store["id"] and o["status"] in ("DRAFT", "SUBMITTED", "APPROVED"):
            o["status"] = "CANCELLED"
            mw.touch(o)
    for c in db.promotion_campaigns.values():
        if c["store_id"] == store["id"] and c["status"] in ("PLANNED", "ACTIVE"):
            # goes directly to CANCELLED; ACTIVE campaigns do NOT pass through ENDED
            c["status"] = "CANCELLED"
            mw.touch(c)


def terminate_or_expire_agreement(agreement, new_status):
    """Agreement ACTIVE/SUSPENDED -> TERMINATED or EXPIRED cascade."""
    agreement["status"] = new_status
    mw.touch(agreement)
    for store in db.stores.values():
        if store["agreement_id"] != agreement["id"]:
            continue
        if store["operating_status"] == "DELICENSED":
            continue
        delicense_store(store)
