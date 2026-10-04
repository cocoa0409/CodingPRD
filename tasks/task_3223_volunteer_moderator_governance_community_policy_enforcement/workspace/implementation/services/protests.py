"""Protest events, quorum, cross-power breadth and coordination (§3.7).

§1.2 transitions (9) and the Community ACTIVE <-> PROTEST_RESTRICTED edges.
"""

from math import ceil

import db
from db import iso, now, parse_dt
from errors import fail
from services import community as community_svc
from services import teams

ACCESS_MODES = ("READ_ONLY", "RESTRICTED", "PRIVATE")
PROTEST_STATES = ("REQUESTED", "COORDINATED", "ENDED")
MIN_QUORUM = 2
CROSS_POWER_MIN = 2
CONFLICT_STATES = ("PROTEST_RESTRICTED", "RESTRICTED", "INSTITUTION_NEGOTIATION", "QUARANTINED")


def required_quorum_count(community_id):
    active = len(community_svc.active_moderators(community_id))
    return max(MIN_QUORUM, ceil(active / 2))


def power_of_account(account_id):
    """Distinct communities the account moderates, derived from Moderator rows."""
    community_ids = sorted({row["community_id"] for row in db.all_of("Moderator")
                            if row["moderator_account_id"] == account_id})
    return community_ids


def account_width(account_id):
    """width(A) = 1 + min(linear_span, wrap_span) measured on a circle of power(A)."""
    community_ids = power_of_account(account_id)
    power = len(community_ids)
    if power == 0:
        return 0
    ranks = list(range(1, power + 1))
    linear_span = max(ranks) - min(ranks)
    wrap_span = power - linear_span
    return 1 + min(linear_span, wrap_span)


def distinct_power_count(protest_id):
    approvals = [a for a in db.all_of("ProtestApproval") if a["protest_id"] == protest_id]
    if not approvals:
        return 0
    accounts = {a["approving_account_id"] for a in approvals}
    return max(account_width(account) for account in accounts)


def refresh_protest(protest):
    """Recompute quorum, requirement and breadth from the whole approval set."""
    community_id = protest["community_id"]
    protest["required_quorum_count"] = required_quorum_count(community_id)
    approvals = [a for a in db.all_of("ProtestApproval") if a["protest_id"] == protest["id"]]
    protest["quorum_approval_count"] = len({a["moderator_id"] for a in approvals})
    protest["distinct_power_count"] = distinct_power_count(protest["id"])
    return protest


def refresh_community_protests(community_id):
    for protest in db.children("ProtestEvent", "community_id", community_id):
        refresh_protest(protest)


# --------------------------------------------------------------------------
# Requesting a protest
# --------------------------------------------------------------------------
def request_protest(community, data):
    community_svc.guard_mutable(community)
    # §3.7 places no state precondition on *requesting* a protest — only the
    # coordination that follows it requires the community to be ACTIVE — so a
    # second protest may legitimately be requested while the first restricts
    # access, and it is coordination that is then refused.
    mode = data["requested_access_mode"]
    if mode not in ACCESS_MODES:
        fail("ERR_INVALID_REQUEST", "requested_access_mode is not a recognised value")
    if mode == "PRIVATE":
        fail("ERR_PRIVATE_PROTEST_FORBIDDEN")
    conflicting = data.get("conflicting_cross_power_account_ids")
    if conflicting is None:
        conflicting = []
    if not isinstance(conflicting, list):
        fail("ERR_INVALID_REQUEST", "conflicting_cross_power_account_ids must be an array")

    record = {
        "community_id": community["id"],
        "requested_access_mode": mode,
        "status": "REQUESTED",
        "quorum_approval_count": 0,
        "required_quorum_count": required_quorum_count(community["id"]),
        "distinct_power_count": 0,
        "conflicting_cross_power_account_ids": conflicting,
        "started_at_utc": None,
        "ended_at_utc": None,
        "exemption_granted_until_utc": None,
    }
    db.insert("ProtestEvent", record)
    db.touch(community)
    return record


# --------------------------------------------------------------------------
# Approvals
# --------------------------------------------------------------------------
def record_approval(community, protest, moderator, approving_account_id):
    community_svc.guard_mutable(community)
    if protest["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE")

    existing = [a for a in db.all_of("ProtestApproval") if a["protest_id"] == protest["id"]]
    if any(a["approving_account_id"] == approving_account_id for a in existing):
        fail("ERR_QUORUM_NOT_MET", "this account has already approved the protest")

    # A ProtestApproval is a pure join record: id and created_at only.
    stamp = iso(now())
    record = {
        "id": db.new_id(),
        "created_at": stamp,
        "protest_id": protest["id"],
        "moderator_id": moderator["id"],
        "approving_account_id": approving_account_id,
        "approved_on_utc": stamp,
    }
    db.bucket("ProtestApproval")[record["id"]] = record

    teams.mark_action(community["id"], "PROTEST_APPROVAL")
    refresh_protest(protest)
    db.touch(community)
    return record


# --------------------------------------------------------------------------
# Coordination and ending
# --------------------------------------------------------------------------
def coordinate(community, protest):
    community_svc.guard_mutable(community)
    refresh_protest(protest)

    if protest["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE")
    if community["state"] != "ACTIVE":
        fail("ERR_INVALID_STATE")
    if protest["quorum_approval_count"] < protest["required_quorum_count"]:
        fail("ERR_QUORUM_NOT_MET")
    if protest["distinct_power_count"] < CROSS_POWER_MIN:
        fail("ERR_CROSS_POWER_QUORUM_NOT_MET")
    if protest["requested_access_mode"] == "PRIVATE":
        fail("ERR_PRIVATE_PROTEST_FORBIDDEN")

    protest["status"] = "COORDINATED"
    protest["started_at_utc"] = iso(now())
    protest["exemption_granted_until_utc"] = community.get("protest_exemption_until_utc")
    db.touch(protest)

    community["state"] = "PROTEST_RESTRICTED"
    community["restricted_since_utc"] = iso(now())
    community_svc.refresh_derived(community)
    db.touch(community)
    return protest


def end_protest(community, protest):
    community_svc.guard_mutable(community)
    if protest["status"] == "ENDED":
        fail("ERR_INVALID_STATE")

    if protest["status"] == "COORDINATED":
        if community["state"] != "PROTEST_RESTRICTED":
            fail("ERR_INVALID_STATE")
        protest["status"] = "ENDED"
        protest["ended_at_utc"] = iso(now())
        db.touch(protest)
        community["state"] = "ACTIVE"
        community["restricted_since_utc"] = None
        community_svc.refresh_derived(community)
        db.touch(community)
        return protest

    protest["status"] = "ENDED"
    protest["ended_at_utc"] = iso(now())
    db.touch(protest)
    db.touch(community)
    return protest


def refresh_for_community(community_id):
    refresh_community_protests(community_id)