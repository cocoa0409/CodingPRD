"""Shared business-listing services: suspension cascade, reverify transition,
edit payload application, publish/revert cascades."""
from datetime import timedelta

import clock
import domain
import store
from errors import raise_err

NONTERMINAL_EDIT_STATES = {"SUBMITTED", "QUEUED", "IN_REVIEW", "NEEDS_MORE_INFO"}


def apply_edit_payload(l, edit):
    """Apply an edit's payload to the listing. Records prior values for revert."""
    prior = {}
    et = edit["edit_type"]
    p = edit.get("payload") or {}
    if et == "NAME" and "name" in p:
        prior["name"] = l["name"]
        l["name"] = p["name"]
    elif et == "CATEGORY" and "category" in p:
        prior["category"] = l["category"]
        l["category"] = p["category"]
    elif et == "ADDRESS":
        if "address_text" in p:
            prior["address_text"] = l["address_text"]
            l["address_text"] = p["address_text"]
        if "geo_lat" in p:
            prior["geo_lat"] = l["geo_lat"]
            l["geo_lat"] = p["geo_lat"]
        if "geo_lng" in p:
            prior["geo_lng"] = l["geo_lng"]
            l["geo_lng"] = p["geo_lng"]
    elif et == "LOCATION":
        if "geo_lat" in p:
            prior["geo_lat"] = l["geo_lat"]
            l["geo_lat"] = p["geo_lat"]
        if "geo_lng" in p:
            prior["geo_lng"] = l["geo_lng"]
            l["geo_lng"] = p["geo_lng"]
    # HOURS and ATTRIBUTE payloads do not mutate listing scalar fields
    edit["_applied_prior"] = prior
    return prior


def undo_edit_payload(l, edit):
    prior = edit.get("_applied_prior") or {}
    for k, v in prior.items():
        l[k] = v


def create_grant(contributor_id, source_type, source_id, base_points, multiplier, note=""):
    points = domain.round_half_up_int(base_points * multiplier)
    rec = {
        "id": domain.new_id(),
        "contributor_id": contributor_id,
        "source_type": source_type,
        "source_id": source_id,
        "base_points": base_points,
        "quality_multiplier": float(multiplier),
        "points": points,
        "status": "POSTED",
        "note": note,
        "created_at": clock.iso(clock.now()),
    }
    store.grants[rec["id"]] = rec
    return rec


def publish_edit(edit):
    """Full publish cascade: apply payload, ledger, grant, trust, health."""
    l = store.listings[edit["listing_id"]]
    apply_edit_payload(l, edit)
    edit["status"] = "PUBLISHED"
    domain.touch(edit)
    domain.recompute_listing(l)
    domain.touch(l)
    grant = create_grant(edit["contributor_id"], "EDIT", edit["id"], 5,
                         edit["quality_weight"])
    edit["_publish_grant_id"] = grant["id"]
    c = store.contributors.get(edit["contributor_id"])
    if c is not None:
        domain.recompute_contributor(c, demote=True)
    return l


def revert_edit(edit):
    l = store.listings[edit["listing_id"]]
    undo_edit_payload(l, edit)
    edit["status"] = "REVERTED"
    domain.touch(edit)
    gid = edit.get("_publish_grant_id")
    if gid and gid in store.grants:
        store.grants[gid]["status"] = "REVOKED"
    domain.recompute_listing(l)
    domain.touch(l)
    c = store.contributors.get(edit["contributor_id"])
    if c is not None:
        domain.recompute_contributor(c, demote=True)
    return l


def do_require_reverify(l):
    l["status"] = "REVERIFY_REQUIRED"
    for a in store.attempts.values():
        if a["listing_id"] == l["id"] and a["status"] == "ISSUED":
            a["status"] = "CANCELLED"
            domain.touch(a)
    domain.recompute_listing(l)
    domain.touch(l)


def suspend_listing(l, violation_type, evidence_notes, analyst_id):
    """Full suspension cascade; returns the created SuspensionCase."""
    if violation_type == "KEYWORD_STUFFING" and l["keyword_stuffing_strikes"] < 2:
        raise_err("ERR_STRIKES_BELOW_THRESHOLD",
                  "keyword-stuffing suspension requires >= 2 strikes")
    l["_pre_suspension_status"] = l["status"]
    now = clock.now()
    case = {
        "id": domain.new_id(),
        "listing_id": l["id"],
        "violation_type": violation_type,
        "status": "OPEN",
        "evidence_notes": evidence_notes,
        "appeal_text": None,
        "appeal_deadline": clock.iso(now + timedelta(days=30)),
        "decided_by": None,
        "suspended_by": analyst_id,
        "created_at": clock.iso(now),
        "updated_at": clock.iso(now),
        "version": 1,
    }
    store.cases[case["id"]] = case

    # rejection storm over non-terminal edits on this listing
    authors = set()
    for e in store.edits.values():
        if e["listing_id"] == l["id"] and e["status"] in NONTERMINAL_EDIT_STATES:
            e["status"] = "REJECTED"
            e["rejection_reason"] = "POLICY"
            domain.touch(e)
            authors.add(e["contributor_id"])
    l["status"] = "SUSPENDED"
    domain.recompute_listing(l)
    domain.touch(l)

    # cancel outstanding verification attempts
    for a in store.attempts.values():
        if a["listing_id"] == l["id"] and a["status"] in ("ISSUED", "CODE_SUBMITTED"):
            a["status"] = "CANCELLED"
            domain.touch(a)

    # trust demotion cascade
    for cid in authors:
        c = store.contributors.get(cid)
        if c is not None:
            domain.recompute_contributor(c, demote=True)
    return case
