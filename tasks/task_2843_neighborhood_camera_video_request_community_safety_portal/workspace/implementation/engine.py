"""Shared state machinery: version bookkeeping, counter reconciliation,
cascades, notification batches (PRD 2.11, 3.5, 3.6, 3.7, 3.8)."""
from datetime import timedelta

from flask import g

import calc
import store
from store import db, new_id, now


# --------------------------------------------------------------------------
# version / updated_at bookkeeping (PRD 2.4, 2.11)
# --------------------------------------------------------------------------

def _touched():
    bag = getattr(g, "_touched_rows", None)
    if bag is None:
        bag = set()
        g._touched_rows = bag
    return bag


def touch(row):
    """One version increment per row per API operation."""
    if row is None:
        return
    row["updated_at"] = now()
    bag = _touched()
    if row["id"] in bag:
        return
    bag.add(row["id"])
    row["version"] = row.get("version", 1) + 1


def new_row(extra=None, versioned=True):
    row = {"id": new_id(), "created_at": now()}
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    if extra:
        row.update(extra)
    _touched().add(row["id"])
    return row


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------

def solicitations_of_request(request_id):
    return [s for s in db.solicitations.values()
            if s["video_request_id"] == request_id]


def solicitations_of_device(device_id):
    return [s for s in db.solicitations.values() if s["device_id"] == device_id]


def solicitations_of_resident(resident_id):
    return [s for s in db.solicitations.values()
            if s["resident_id"] == resident_id]


def clips_of_solicitation(solicitation_id):
    return [c for c in db.clips.values()
            if c["consent_solicitation_id"] == solicitation_id]


def clips_of_resident(resident_id):
    return [c for c in db.clips.values()
            if c["owner_resident_id"] == resident_id]


def devices_of_resident(resident_id):
    return [d for d in db.devices.values()
            if d["owner_resident_id"] == resident_id]


def posts_of_author(resident_id):
    return [p for p in db.posts.values()
            if p["author_resident_id"] == resident_id]


# --------------------------------------------------------------------------
# counter reconciliation -- keeps every ledger invariant true by construction
# --------------------------------------------------------------------------

def sync_device(device):
    if device is None:
        return
    pending = sum(1 for s in solicitations_of_device(device["id"])
                  if s["status"] == "SOLICITED")
    if device["pending_solicitation_count"] != pending:
        device["pending_solicitation_count"] = pending
        touch(device)


def sync_resident_footage(resident):
    if resident is None:
        return
    retained = 0
    purged = 0
    for clip in clips_of_resident(resident["id"]):
        if clip["status"] == "PURGED":
            purged += clip["duration_seconds"]
        else:
            retained += clip["duration_seconds"]
    if (resident["retained_footage_seconds"] != retained
            or resident["purged_footage_seconds"] != purged):
        resident["retained_footage_seconds"] = retained
        resident["purged_footage_seconds"] = purged
        touch(resident)


def sync_agency_open_count(agency):
    if agency is None:
        return
    open_count = sum(1 for r in db.video_requests.values()
                     if r["agency_id"] == agency["id"]
                     and r["lifecycle_state"] == "SOLICITING")
    if agency["open_request_count"] != open_count:
        agency["open_request_count"] = open_count
        touch(agency)


def sync_request(request_row, resolve=True):
    """Recompute the solicitation buckets and auto-resolve when pending hits 0."""
    if request_row is None:
        return False
    sols = solicitations_of_request(request_row["id"])
    buckets = {"SOLICITED": 0, "SHARED": 0, "DECLINED": 0, "EXPIRED": 0,
               "WITHDRAWN": 0}
    for sol in sols:
        buckets[sol["status"]] += 1
    clip_total = sum(1 for c in db.clips.values()
                     if c["video_request_id"] == request_row["id"])
    updates = {
        "pending_count": buckets["SOLICITED"],
        "shared_count": buckets["SHARED"],
        "declined_count": buckets["DECLINED"],
        "expired_count": buckets["EXPIRED"],
        "withdrawn_count": buckets["WITHDRAWN"],
        "shared_clip_count": clip_total,
        "provisional_share_rate_bps": calc.share_rate_bps(
            buckets["SHARED"], len(sols)),
    }
    if any(request_row[k] != v for k, v in updates.items()):
        request_row.update(updates)
        touch(request_row)
    if (resolve and request_row["lifecycle_state"] == "SOLICITING"
            and request_row["pending_count"] == 0):
        return resolve_request(request_row)
    return False


def resolve_request(request_row):
    """SOLICITING -> FULFILLED / EXHAUSTED once pending_count reaches 0."""
    if request_row["shared_count"] >= 1:
        request_row["lifecycle_state"] = "FULFILLED"
        request_row["provisional_share_rate_bps"] = calc.share_rate_bps(
            request_row["shared_count"], request_row["solicitation_count"])
    else:
        request_row["lifecycle_state"] = "EXHAUSTED"
        request_row["provisional_share_rate_bps"] = 0
    touch(request_row)
    sync_agency_open_count(db.agencies.get(request_row["agency_id"]))
    return True


# --------------------------------------------------------------------------
# notification batches / fatigue (PRD 3.7)
# --------------------------------------------------------------------------

def emit_batch(kind, entries):
    """entries: ordered list of {"resident", "source_ref_id", "apply"?}.

    Returns (delivered_count, suppressed_count).
    """
    snapshots = {}
    for entry in entries:
        resident = entry["resident"]
        if resident["id"] in snapshots:
            continue
        snapshot = resident["notifications_sent_today"]
        budget = resident["notification_budget_per_day"]
        eff = calc.effective_budget(snapshot, budget)
        snapshots[resident["id"]] = {
            "resident": resident,
            "snapshot": snapshot,
            "effective": eff,
            "allowance": max(0, eff - snapshot),
            "delivered": 0,
        }

    delivered_total = 0
    suppressed_total = 0
    seq = 0
    for entry in entries:
        seq += 1
        resident = entry["resident"]
        state = snapshots[resident["id"]]
        suppressed = False
        reason = None
        if resident["notification_mute_enabled"]:
            suppressed = True
            reason = "RESIDENT_MUTED"
        elif state["delivered"] >= state["allowance"]:
            suppressed = True
            reason = "FATIGUE_BUDGET_EXHAUSTED"
        dispatch = new_row({
            "resident_id": resident["id"],
            "kind": kind,
            "source_ref_id": entry["source_ref_id"],
            "batch_sequence_no": seq,
            "suppressed": suppressed,
            "suppression_reason": reason,
            "recipient_budget_snapshot": state["snapshot"],
            "recipient_effective_budget": state["effective"],
            "dispatched_at": now(),
        }, versioned=False)
        db.dispatches[dispatch["id"]] = dispatch
        if suppressed:
            suppressed_total += 1
        else:
            state["delivered"] += 1
            resident["notifications_sent_today"] += 1
            delivered_total += 1
        apply_fn = entry.get("apply")
        if apply_fn is not None:
            apply_fn(dispatch)

    for state in snapshots.values():
        resident = state["resident"]
        resident["fatigue_state"] = calc.derive_fatigue_state(
            resident, state["effective"])
        touch(resident)
    return delivered_total, suppressed_total


def rederive_fatigue(resident):
    eff = calc.effective_budget(resident["notifications_sent_today"],
                                resident["notification_budget_per_day"])
    resident["fatigue_state"] = calc.derive_fatigue_state(resident, eff)


# --------------------------------------------------------------------------
# post alert fan-out (PRD 3.8)
# --------------------------------------------------------------------------

def post_fanout(post):
    candidates = []
    for resident in db.residents.values():
        if resident["id"] == post["author_resident_id"]:
            continue
        if resident["status"] != "ACTIVE":
            continue
        d2 = calc.dist_sq(post["post_x_m"], post["post_y_m"],
                          resident["home_x_m"], resident["home_y_m"])
        radius = resident["alert_radius_m"]
        if d2 <= radius * radius:
            candidates.append((d2, resident["created_at"], resident))
    candidates.sort(key=lambda item: (item[0], item[1]))
    post["alert_candidate_count"] = len(candidates)
    survivors = candidates[:post["alert_fanout_cap"]]
    entries = [{"resident": item[2], "source_ref_id": post["id"]}
               for item in survivors]
    delivered, suppressed = emit_batch("POST_ALERT", entries)
    post["alert_fanout_count"] = delivered
    post["alert_suppressed_count"] = suppressed


# --------------------------------------------------------------------------
# eligibility collapse (PRD 3.3)
# --------------------------------------------------------------------------

def check_eligibility_collapse(device_ids):
    device_ids = set(device_ids)
    if not device_ids:
        return
    for area in list(db.request_areas.values()):
        if area["status"] != "LOCKED":
            continue
        roster = db.rosters.get(area["id"]) or []
        member_ids = [m["device_id"] for m in roster]
        if not device_ids.intersection(member_ids):
            continue
        # PRD 3.3: "the eligible count is recomputed against the frozen
        # roster".  The recount is a transient comparison only -- the row's
        # own ``eligible_device_count`` was written once at lock time and PRD
        # 3.4 reads it back as "the area's frozen ``eligible_device_count``",
        # so it is never rewritten afterwards.
        count = sum(1 for did in member_ids
                    if calc.roster_member_still_eligible(db.devices.get(did)))
        if count < area["effective_min_devices"]:
            area["status"] = "INVALIDATED"
            area["invalidated_reason"] = "ELIGIBILITY_BELOW_THRESHOLD"
            touch(area)


# --------------------------------------------------------------------------
# solicitation transitions (PRD 3.5)
# --------------------------------------------------------------------------

def _resolve_solicitation(sol, status, decline_reason):
    sol["status"] = status
    sol["responded_at"] = now()
    if decline_reason is not None:
        sol["decline_reason"] = decline_reason
    touch(sol)
    sync_device(db.devices.get(sol["device_id"]))


def decline_solicitation(sol, reason):
    _resolve_solicitation(sol, "DECLINED", reason)


def expire_solicitation(sol):
    _resolve_solicitation(sol, "EXPIRED", None)


def withdraw_solicitation(sol):
    _resolve_solicitation(sol, "WITHDRAWN", None)


# --------------------------------------------------------------------------
# clip purging (PRD 3.6) + compensating consent withdrawal (PRD 3.5)
# --------------------------------------------------------------------------

COMPENSATING_REASONS = ("OWNER_REVOCATION", "ACCOUNT_DEACTIVATED")


def purge_clip(clip, reason):
    clip["status"] = "PURGED"
    clip["purged_at"] = now()
    clip["purge_reason"] = reason
    touch(clip)
    sync_resident_footage(db.residents.get(clip["owner_resident_id"]))
    sol = db.solicitations.get(clip["consent_solicitation_id"])
    withdrawn = False
    if reason in COMPENSATING_REASONS and sol is not None \
            and sol["status"] == "SHARED":
        remaining = [c for c in clips_of_solicitation(sol["id"])
                     if c["status"] != "PURGED"]
        if not remaining:
            sol["status"] = "WITHDRAWN"
            sol["responded_at"] = now()
            touch(sol)
            withdrawn = True
    sync_request(db.video_requests.get(clip["video_request_id"]))
    return withdrawn


# --------------------------------------------------------------------------
# moderation removal cascade (PRD 3.8 levels 1-5)
# --------------------------------------------------------------------------

def removal_cascade(post, decision):
    author = db.residents.get(post["author_resident_id"])
    if author is None:
        return
    if decision == "REMOVE_DISCRIMINATORY":
        author["discrimination_strike_count"] += 1
    else:
        author["accuracy_strike_count"] += 1
    author["total_strike_score"] = calc.total_strike_score(author)
    previous = author["post_privilege_state"]
    author["post_privilege_state"] = calc.privilege_for_score(
        author["total_strike_score"])
    touch(author)
    if (author["post_privilege_state"] != "POSTING_SUSPENDED"
            or previous == "POSTING_SUSPENDED"):
        return
    cutoff = now() - timedelta(days=calc.RECENT_POST_LOOKBACK_DAYS)
    sweep = [p for p in posts_of_author(author["id"])
             if p["id"] != post["id"] and p["state"] == "PUBLISHED"
             and p["created_at"] >= cutoff]
    for swept in store.by_created(sweep):
        swept["state"] = "UNDER_REVIEW"
        swept["auto_flag_reason"] = "AUTHOR_UNDER_REVIEW"
        touch(swept)
        case = new_row({
            "resident_post_id": swept["id"],
            "opened_reason": "AUTHOR_SUSPENDED",
            "opened_by_user_id": "system",
            "decided_by_user_id": None,
            "state": "OPEN",
            "decision": "NONE",
            "decision_note": None,
            "decided_at": None,
            "superseded_by_case_created_at": None,
            "post_discrimination_score_at_open": swept["discrimination_score"],
        })
        db.cases[case["id"]] = case
