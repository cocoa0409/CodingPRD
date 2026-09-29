"""Derived state, cascades and the governance sweep (PRD sections 2.8-2.10, 3.x)."""

from datetime import timedelta

import calc
import timeutil
from errors import ApiError
from store import store, touch, by_created, new_row

GATE_ORDER = ("SME", "LEGAL", "BRAND", "ACCESSIBILITY")
CHANNEL_ORDER = ("OWNED", "EMAIL", "SOCIAL")
OPEN_ITEM_STATES = ("DRAFT", "IN_REVIEW", "CHANGES_REQUESTED", "READY")


# --------------------------------------------------------------------------
# path lookups (ladder rule 3) and body foreign keys (ladder rule 9)
# --------------------------------------------------------------------------

def _find(collection, row_id, error_id):
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id, "resource not found")
    return row


def get_campaign(cid):
    return _find(store.campaigns, cid, "ERR_CAMPAIGN_NOT_FOUND")


def get_slot(sid):
    return _find(store.slots, sid, "ERR_SLOT_NOT_FOUND")


def get_expert(eid):
    return _find(store.experts, eid, "ERR_EXPERT_NOT_FOUND")


def get_brief(bid):
    return _find(store.briefs, bid, "ERR_BRIEF_NOT_FOUND")


def get_item(iid):
    return _find(store.items, iid, "ERR_CONTENT_ITEM_NOT_FOUND")


def get_gate(gid):
    return _find(store.gates, gid, "ERR_GATE_NOT_FOUND")


def get_claim(cid):
    return _find(store.claims, cid, "ERR_CLAIM_NOT_FOUND")


def get_asset(aid):
    return _find(store.assets, aid, "ERR_ASSET_NOT_FOUND")


# --------------------------------------------------------------------------
# collection helpers
# --------------------------------------------------------------------------

def slots_of_campaign(cid):
    return [s for s in store.slots.values() if s["campaign_id"] == cid]


def briefs_of_campaign(cid):
    return [b for b in store.briefs.values() if b["campaign_id"] == cid]


def briefs_of_expert(eid):
    return [b for b in store.briefs.values() if b["sme_expert_id"] == eid]


def items_of_campaign(cid):
    return [i for i in store.items.values() if i["campaign_id"] == cid]


def items_of_brief(bid):
    return [i for i in store.items.values() if i["brief_id"] == bid]


def gates_of_item(iid):
    return [gt for gt in store.gates.values() if gt["content_item_id"] == iid]


def claims_of_item(iid):
    return [c for c in store.claims.values() if c["content_item_id"] == iid]


def evidence_of_claim(cid):
    return [e for e in store.evidence.values() if e["claim_id"] == cid]


def usages_of_item(iid):
    return [u for u in store.usages.values() if u["content_item_id"] == iid]


def usages_of_asset(aid):
    return [u for u in store.usages.values() if u["asset_id"] == aid]


def distributions_of_item(iid):
    return [d for d in store.distributions.values() if d["content_item_id"] == iid]


def snapshots_of_item(iid):
    return [s for s in store.snapshots.values() if s["content_item_id"] == iid]


def campaign_of_item(item):
    return store.campaigns[item["campaign_id"]]


def brief_of_item(item):
    return store.briefs[item["brief_id"]]


def sort_gates(rows):
    return sorted(rows, key=lambda r: (GATE_ORDER.index(r["gate_type"]),
                                       r["created_at"], r["id"]))


def sort_distributions(rows):
    return sorted(rows, key=lambda r: (CHANNEL_ORDER.index(r["channel"]),
                                       r["created_at"], r["id"]))


# --------------------------------------------------------------------------
# campaign posture (PRD section 2.8)
# --------------------------------------------------------------------------

def reconcile_campaign(campaign):
    """Recompute the three counters, committed_points_total and the posture.
    Returns the posture before the recompute."""
    previous = campaign["governance_posture"]
    live_items = [i for i in items_of_campaign(campaign["id"])
                  if i["workflow_state"] != "PRUNED"]
    live_ids = set(i["id"] for i in live_items)

    breached = sum(1 for gt in store.gates.values()
                   if gt["content_item_id"] in live_ids and gt["sla_breached"])
    expired_usages = sum(1 for u in store.usages.values()
                         if u["content_item_id"] in live_ids
                         and u["usage_state"] == "RIGHTS_LAPSED")
    unsubstantiated = 0
    for c in store.claims.values():
        if c["content_item_id"] not in live_ids:
            continue
        item = store.items[c["content_item_id"]]
        if (item["workflow_state"] in calc.PUBLISHED_LIKE
                and c["substantiation_state"] in calc.UNSUBSTANTIATED_STATES):
            unsubstantiated += 1

    committed = sum(s["committed_points"] for s in slots_of_campaign(campaign["id"]))
    posture = calc.governance_posture(unsubstantiated, expired_usages, breached)

    changed = (campaign["breached_gate_count"] != breached
               or campaign["expired_usage_count"] != expired_usages
               or campaign["unsubstantiated_published_claim_count"] != unsubstantiated
               or campaign["committed_points_total"] != committed
               or campaign["governance_posture"] != posture)
    campaign["breached_gate_count"] = breached
    campaign["expired_usage_count"] = expired_usages
    campaign["unsubstantiated_published_claim_count"] = unsubstantiated
    campaign["committed_points_total"] = committed
    campaign["governance_posture"] = posture
    if changed:
        touch(campaign)
    return previous


def require_not_frozen(campaign):
    if campaign["governance_posture"] == "FROZEN":
        raise ApiError("ERR_CAMPAIGN_POSTURE_FROZEN",
                       "campaign governance posture is FROZEN")


def require_open_posture(campaign):
    """Waivers demand an OPEN posture: FROZEN is evaluated before RESTRICTED."""
    if campaign["governance_posture"] == "FROZEN":
        raise ApiError("ERR_CAMPAIGN_POSTURE_FROZEN",
                       "campaign governance posture is FROZEN")
    if campaign["governance_posture"] == "RESTRICTED":
        raise ApiError("ERR_CAMPAIGN_POSTURE_RESTRICTED",
                       "campaign governance posture is RESTRICTED")


# --------------------------------------------------------------------------
# expert ledgers (PRD section 3.2)
# --------------------------------------------------------------------------

def recompute_expert_hours(expert):
    total = sum(b["sme_reserved_hours"] for b in briefs_of_expert(expert["id"])
                if b["state"] in calc.BRIEF_COUNTED_STATES)
    if expert["committed_hours_total"] != total:
        expert["committed_hours_total"] = total
        touch(expert)


def expert_week_committed_hours(expert_id, anchor, exclude_brief_id=None):
    total = 0
    for b in briefs_of_expert(expert_id):
        if b["state"] not in calc.BRIEF_COUNTED_STATES:
            continue
        if exclude_brief_id is not None and b["id"] == exclude_brief_id:
            continue
        if timeutil.week_anchor(b["review_window_start"]) == anchor:
            total += b["sme_reserved_hours"]
    return total


# --------------------------------------------------------------------------
# asset rights posture (PRD section 3.7)
# --------------------------------------------------------------------------

def refresh_asset_counts(asset, derive_status=True):
    active = sum(1 for u in usages_of_asset(asset["id"])
                 if u["usage_state"] == "ACTIVE")
    remaining = asset["max_licensed_uses"] - active
    if remaining < 0:
        remaining = 0
    status = calc.asset_status(asset["license_end"], store.clock) \
        if derive_status else asset["status"]
    changed = (asset["active_use_count"] != active
               or asset["remaining_licensed_uses"] != remaining
               or asset["status"] != status)
    asset["active_use_count"] = active
    asset["remaining_licensed_uses"] = remaining
    asset["status"] = status
    if changed:
        touch(asset)


def release_item_usages(item):
    """Retraction, refresh and prune all release ACTIVE and RIGHTS_LAPSED usages."""
    touched = []
    for u in by_created(usages_of_item(item["id"])):
        if u["usage_state"] in ("ACTIVE", "RIGHTS_LAPSED"):
            u["usage_state"] = "RELEASED"
            u["released_at"] = store.clock
            touch(u)
            if u["asset_id"] not in touched:
                touched.append(u["asset_id"])
    for asset_id in touched:
        asset = store.assets.get(asset_id)
        if asset is not None:
            refresh_asset_counts(asset)


def retract_item_distributions(item, states=("SCHEDULED", "LIVE", "SUPPRESSED")):
    for d in sort_distributions(distributions_of_item(item["id"])):
        if d["state"] in states:
            d["state"] = "RETRACTED"
            touch(d)


# --------------------------------------------------------------------------
# review gates (PRD section 3.5)
# --------------------------------------------------------------------------

def open_regulated_claim_count(item_id):
    return sum(1 for c in claims_of_item(item_id)
               if c["claim_type"] == "REGULATED"
               and c["substantiation_state"] != "SUBSTANTIATED")


def compute_gate_sla(gate_type, item):
    brief = brief_of_item(item)
    campaign = campaign_of_item(item)
    return calc.gate_sla_hours(gate_type, brief["funnel_stage"],
                               campaign["persona"],
                               open_regulated_claim_count(item["id"]))


def open_gate(item, gate_type):
    hours = compute_gate_sla(gate_type, item)
    opened_at = store.clock
    row = new_row("gates", {
        "content_item_id": item["id"],
        "gate_type": gate_type,
        "state": "PENDING",
        "opened_at": opened_at,
        "due_at": opened_at + timedelta(hours=hours),
        "sla_hours": hours,
        "decided_at": None,
        "decided_by_user_id": None,
        "decision_notes": None,
        "turnaround_hours": None,
        "sla_breached": False,
    })
    store.gates[row["id"]] = row
    return row


def reopen_gate(item, gate):
    hours = compute_gate_sla(gate["gate_type"], item)
    gate["state"] = "PENDING"
    gate["opened_at"] = store.clock
    gate["sla_hours"] = hours
    gate["due_at"] = store.clock + timedelta(hours=hours)
    gate["decided_at"] = None
    gate["decided_by_user_id"] = None
    gate["turnaround_hours"] = None
    gate["sla_breached"] = False
    touch(gate)


def void_gates(item, only_pending=True):
    """Voiding resets decided_at to null and sla_breached to false (PRD 3.5)."""
    for gate in sort_gates(gates_of_item(item["id"])):
        if only_pending:
            if gate["state"] != "PENDING":
                continue
        elif gate["state"] == "VOIDED":
            continue
        gate["state"] = "VOIDED"
        gate["decided_at"] = None
        gate["sla_breached"] = False
        touch(gate)


# --------------------------------------------------------------------------
# item derived figures (PRD section 3.9)
# --------------------------------------------------------------------------

def recompute_attribution(item):
    snaps = snapshots_of_item(item["id"])
    engaged, conversions, last_touch, assisted = calc.attribution(snaps)
    item["engaged_sessions_total"] = engaged
    item["conversions_total"] = conversions
    item["last_touch_pipeline_cents"] = last_touch
    item["assisted_pipeline_cents"] = assisted


def recompute_decay(item):
    """Runs the decay computation and refreshes both derived fields."""
    snaps = snapshots_of_item(item["id"])
    value = calc.decay_pct(snaps, item["published_at"], store.clock)
    brief = brief_of_item(item)
    flag = calc.refresh_required(value, brief["funnel_stage"],
                                 item["accuracy_status"])
    changed = item["decay_pct"] != value or item["refresh_required"] != flag
    item["decay_pct"] = value
    item["refresh_required"] = flag
    return changed


def recompute_refresh_flag(item):
    flag = calc.refresh_required(item["decay_pct"],
                                 brief_of_item(item)["funnel_stage"],
                                 item["accuracy_status"])
    item["refresh_required"] = flag


# --------------------------------------------------------------------------
# the ordered governance sweep (PRD section 3.11)
# --------------------------------------------------------------------------

def _suppress(distribution, reason, counted):
    distribution["state"] = "SUPPRESSED"
    distribution["suppression_reason"] = reason
    distribution["suppressed_at"] = store.clock
    touch(distribution)
    counted.add(distribution["id"])


def run_sweep():
    clock = store.clock
    assets_expired = 0
    usages_lapsed = 0
    distributions_activated = 0
    claims_expired = 0
    gates_breached = 0
    suppressed = set()
    flagged = set()
    lapsed = []
    prior = dict((c["id"], c["governance_posture"]) for c in store.campaigns.values())

    # Step 1 -- asset licences.
    for asset in by_created(list(store.assets.values())):
        target = calc.asset_status(asset["license_end"], clock)
        if asset["status"] == "LICENSED" and target == "EXPIRING":
            asset["status"] = "EXPIRING"
            touch(asset)
        elif asset["status"] in ("LICENSED", "EXPIRING") and target == "EXPIRED":
            asset["status"] = "EXPIRED"
            assets_expired += 1
            for usage in by_created(usages_of_asset(asset["id"])):
                if usage["usage_state"] == "ACTIVE":
                    usage["usage_state"] = "RIGHTS_LAPSED"
                    touch(usage)
                    usages_lapsed += 1
                    lapsed.append(usage)
            refresh_asset_counts(asset, derive_status=False)
            touch(asset)

    # Step 2 -- rights suppression.
    for usage in by_created(lapsed):
        for dist in sort_distributions(distributions_of_item(usage["content_item_id"])):
            if dist["channel"] == usage["channel"] and dist["state"] in ("SCHEDULED", "LIVE"):
                _suppress(dist, "ASSET_RIGHTS_LAPSED", suppressed)

    # Step 3 -- flagging from rights loss.
    for item in by_created(list(store.items.values())):
        if item["workflow_state"] != "PUBLISHED":
            continue
        dists = distributions_of_item(item["id"])
        if dists and all(d["state"] in ("SUPPRESSED", "RETRACTED") for d in dists):
            item["workflow_state"] = "NEEDS_REFRESH"
            touch(item)
            flagged.add(item["id"])

    # Step 4 -- claim expiry.
    for claim in by_created(list(store.claims.values())):
        if claim["substantiation_state"] != "SUBSTANTIATED":
            continue
        if claim["evidence_valid_until"] is None or claim["evidence_valid_until"] > clock:
            continue
        claim["substantiation_state"] = "EXPIRED"
        touch(claim)
        claims_expired += 1
        item = store.items.get(claim["content_item_id"])
        if item is not None and item["workflow_state"] in calc.PUBLISHED_LIKE:
            for dist in sort_distributions(distributions_of_item(item["id"])):
                if dist["state"] in ("SCHEDULED", "LIVE"):
                    _suppress(dist, "CLAIM_SUBSTANTIATION_EXPIRED", suppressed)

    # Step 5 -- scheduled activation.
    for dist in by_created(list(store.distributions.values())):
        if dist["state"] == "SCHEDULED" and dist["scheduled_at"] <= clock:
            dist["state"] = "LIVE"
            dist["went_live_at"] = clock
            touch(dist)
            distributions_activated += 1

    # Step 6 -- decay.
    for item in by_created(list(store.items.values())):
        if item["workflow_state"] != "PUBLISHED":
            continue
        if recompute_decay(item):
            touch(item)
        if item["refresh_required"]:
            item["workflow_state"] = "NEEDS_REFRESH"
            touch(item)
            flagged.add(item["id"])

    # Step 7 -- service-level breach.
    for gate in by_created(list(store.gates.values())):
        if gate["state"] == "PENDING" and not gate["sla_breached"] \
                and gate["due_at"] <= clock:
            gate["sla_breached"] = True
            touch(gate)
            gates_breached += 1

    # Step 8 -- posture, freeze tier evaluated before the restrict tier.
    campaigns_restricted = 0
    campaigns_frozen = 0
    for campaign in by_created(list(store.campaigns.values())):
        reconcile_campaign(campaign)
        was = prior.get(campaign["id"])
        now = campaign["governance_posture"]
        if now == "FROZEN" and was != "FROZEN":
            campaigns_frozen += 1
        elif now == "RESTRICTED" and was != "RESTRICTED":
            campaigns_restricted += 1

    return {
        "assets_expired": assets_expired,
        "usages_lapsed": usages_lapsed,
        "distributions_suppressed": len(suppressed),
        "distributions_activated": distributions_activated,
        "items_flagged_refresh": len(flagged),
        "claims_expired": claims_expired,
        "gates_breached": gates_breached,
        "campaigns_restricted": campaigns_restricted,
        "campaigns_frozen": campaigns_frozen,
    }
