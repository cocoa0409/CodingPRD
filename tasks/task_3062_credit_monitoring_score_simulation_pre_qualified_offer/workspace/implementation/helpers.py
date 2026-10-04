"""Shared lookups, derived-value recomputation and gating predicates."""

from datetime import timedelta

import store
from errors import fail

_CONSUMER_SCALARS = (
    "full_name", "email", "state_code", "bureau_pin", "dti_pct",
)


# ---------------------------------------------------------------------------
# Existence lookups (validation priority 3: left-to-right, ERR_CONSUMER_NOT_FOUND)
# ---------------------------------------------------------------------------
def _get(table, key, what):
    row = table.get(key)
    if row is None:
        fail("ERR_CONSUMER_NOT_FOUND", "%s not found: %s" % (what, key))
    return row


def consumer(cid):
    return _get(store.consumers, cid, "Consumer")


def snapshot(sid):
    return _get(store.bureau_snapshots, sid, "BureauSnapshot")


def decision(did):
    return _get(store.pre_qual_decisions, did, "PreQualificationDecision")


def referral(rid):
    return _get(store.referrals, rid, "Referral")


def offer(oid):
    return _get(store.pre_qualified_offers, oid, "PreQualifiedOffer")


def program(pid):
    return _get(store.lender_programs, pid, "LenderProgram")


def lender(lid):
    return _get(store.lenders, lid, "Lender")


def catalog_item(iid):
    return _get(store.product_catalog_items, iid, "ProductCatalogItem")


def tier(tid):
    return _get(store.score_tiers, tid, "ScoreTierThreshold")


def alert(aid):
    return _get(store.score_alerts, aid, "ScoreAlert")


def dispute(did):
    return _get(store.dispute_referrals, did, "DisputeReferral")


def simulation(sid):
    return _get(store.score_simulations, sid, "ScoreSimulation")


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------
def identity_matches(cid, uid):
    """A Consumer caller owns `cid` when it is that record's id or enrolling agent."""
    if cid == uid:
        return True
    cns = store.consumers.get(cid)
    return bool(cns is not None and cns.get("_owner_uid") == uid)


def owned(row, uid, role, field="consumer_id"):
    """Consumer role may only act on its own consumer-scoped resources."""
    if role == "Consumer" and not identity_matches(row.get(field), uid):
        fail("ERR_FORBIDDEN_FOR_ROLE", "A Consumer may only act on its own resources.")
    return row


# ---------------------------------------------------------------------------
# Derived consumer values (PRD 2.6)
# ---------------------------------------------------------------------------
def consumer_snapshots(cid):
    rows = [s for s in store.bureau_snapshots.values() if s["consumer_id"] == cid]
    rows.sort(key=lambda s: s["snapshot_ordinal"])
    return rows


def counted_ordinals(cid):
    """Snapshots whose status is not CANCELLED, ordered by ordinal ASC."""
    return [s for s in consumer_snapshots(cid) if s["status"] != "CANCELLED"]


def active_snapshot(cid):
    found = [s for s in store.bureau_snapshots.values()
             if s["consumer_id"] == cid and s["status"] == "ACTIVE"]
    found.sort(key=lambda s: s["snapshot_ordinal"])
    return found[-1] if found else None


def active_snapshot_for_decision(cid, pinned_id):
    """Pinned snapshot when it is still ACTIVE, else the consumer's ACTIVE one."""
    pinned = store.bureau_snapshots.get(pinned_id)
    if pinned is not None and pinned["status"] == "ACTIVE":
        return pinned
    return active_snapshot(cid)


def recompute_consumer(cns):
    """Derive score_version / current_score / previous_score / utilization_pct.

    Also keeps the stored monitoring_posture in sync with the pull counter rule.
    """
    counted = counted_ordinals(cns["id"])
    all_rows = consumer_snapshots(cns["id"])
    cns["score_version"] = len(counted)
    if counted:
        top = counted[-1]
        cns["current_score"] = top["score"]
        cns["utilization_pct"] = top["overall_credit_utilization_pct"]
    else:
        cns["current_score"] = None
        cns["utilization_pct"] = None
    if len(counted) >= 2:
        cns["previous_score"] = counted[-2]["score"]
    else:
        cns["previous_score"] = None
    del all_rows
    refresh_posture(cns)
    return cns


def counted_snapshots_all(cid):
    return [s for s in store.bureau_snapshots.values()
            if s["consumer_id"] == cid and s["status"] != "CANCELLED"]


def bump_consumer(cns):
    cns["version"] = int(cns.get("version", 0)) + 1
    cns["updated_at"] = store.now()
    return cns


def checkout_version(cns, payload):
    """Priority-ordered OCC check: state, then non-malformed, then match."""
    stored = int(cns.get("version", 0))
    if "expected_consumer_version" in payload:
        supplied = payload["expected_consumer_version"]
        if isinstance(supplied, bool) or not isinstance(supplied, int):
            fail("ERR_INVALID_REQUEST", "expected_consumer_version must be an integer.")
        if supplied != stored:
            fail("ERR_STALE_VERSION")
    return stored


# ---------------------------------------------------------------------------
# Snapshot utilisation
# ---------------------------------------------------------------------------
def compute_utilization(total_balance_cents, limit_total_cents):
    if not limit_total_cents:
        return 0.0
    from envelope import rhu
    return rhu(float(total_balance_cents) * 100.0 / float(limit_total_cents), 2)


def pull_cooldown_active(cid, reference):
    """True when a pull landed strictly after `reference` - PULL_COOLDOWN_HOURS."""
    cutoff = reference - timedelta(hours=store.PULL_COOLDOWN_HOURS)
    for s in store.bureau_snapshots.values():
        if s["consumer_id"] != cid:
            continue
        when = s.get("pulled_at") or s.get("cancelled_at")
        if when is not None and when > cutoff:
            return True
    return False


def is_over_presentation(cid, product_kind):
    """presented_count > floor(cap_bps * total_offer_count / 10000)."""
    cap = None
    for row in store.offer_presentation_caps.values():
        if row["consumer_id"] == cid and row["product_kind"] == product_kind:
            cap = row
            break
    presented = cap["presented_count"] if cap else 0
    cap_bps = cap["presentation_cap_bps"] if cap else store.OFFER_CAP_BPS
    total = len([o for o in store.pre_qualified_offers.values()
                 if o["consumer_id"] == cid])
    allowed = (cap_bps * total) // 10000
    return presented > allowed


# ---------------------------------------------------------------------------
# Program eligibility predicates (PRD 3.5 / 3.7)
# ---------------------------------------------------------------------------
def sponsor_of(prog):
    return store.lenders.get(prog["lender_id"])


def program_deliverable(prog):
    clock = store.now()
    go_live = prog.get("go_live_at")
    expiry = prog.get("expiry_at")
    if go_live is not None and clock < go_live:
        return False
    if expiry is not None and clock > expiry:
        return False
    return True


def collision_snapshot(cns):
    return active_snapshot(cns["id"])


def collateral_eligible(cns, prog):
    """A pinned hard criterion that no longer matches current consumer data."""
    snap = active_snapshot(cns["id"])
    if snap is None:
        return False
    for crit in criteria_of(prog["id"]):
        if not crit["is_hard_requirement"]:
            continue
        if not criterion_matches(crit, cns, snap):
            return False
    return True


def criteria_of(pid):
    rows = [c for c in store.targeting_criteria.values() if c["lender_program_id"] == pid]
    rows.sort(key=lambda c: (c["criterion_field"], c["operator"], str(c["criterion_value"])))
    return rows


def criterion_matches(crit, cns, snap):
    field = crit["criterion_field"]
    op = crit["operator"]
    try:
        value = float(crit["criterion_value"])
    except (TypeError, ValueError):
        value = None
    if field == "SCORE":
        actual = snap.get("score")
    elif field == "DTI_PCT":
        actual = cns.get("dti_pct")
    elif field == "UTILIZATION_PCT":
        actual = snap.get("overall_credit_utilization_pct")
    elif field == "STATE_CODE":
        return (str(crit["criterion_value"]) == str(cns.get("state_code")))
    else:
        return False
    if actual is None or value is None:
        return False
    if op == "GTE":
        return float(actual) >= value
    if op == "LTE":
        return float(actual) <= value
    if op == "EQ":
        return float(actual) == value
    return False


def presentation_policy_eligible(cns, prog, snap):
    """min_modeled_score floor, utilisation ceiling, sponsor ACTIVE."""
    if snap is None:
        return False
    sponsor = sponsor_of(prog)
    if sponsor is None or sponsor.get("status") != "ACTIVE":
        return False
    if sponsor.get("compliance_status") != "APPROVED":
        return False
    score = snap.get("score")
    if score is None or score < prog["min_modeled_score"]:
        return False
    util = snap.get("overall_credit_utilization_pct")
    if util is None:
        util = 0.0
    if util > prog["max_eligible_utilization_pct"]:
        return False
    return True


def whole_render_completeness(cid):
    facets = [f for f in store.content_quality_facets.values() if f["consumer_id"] == cid]
    topics = {f["topic"] for f in facets}
    if not {"factor_explanations", "accuracy_education"} <= topics:
        return False
    return all(f["status"] == "COMPLETE" for f in facets)


def content_quality_required_met(cid):
    """Both scorable topics must satisfy the authored content-quality minimum."""
    facets = [f for f in store.content_quality_facets.values()
              if f["consumer_id"] == cid
              and f["topic"] in ("factor_explanations", "accuracy_education")]
    topics = {f["topic"] for f in facets}
    if not {"factor_explanations", "accuracy_education"} <= topics:
        return False
    return all(int(f.get("score_bps") or 0) >= store.CONTENT_QUALITY_MIN
               for f in facets)


def policy_for(cid):
    for row in store.render_policies.values():
        if row["consumer_id"] == cid:
            return row
    return None


def open_dispute_count(cid):
    return len([d for d in store.dispute_referrals.values()
                if d["consumer_id"] == cid
                and d["status"] in ("SUBMITTED_OFFLINE", "ACKNOWLEDGED_BY_BUREAU")])


def refresh_posture(cns):
    """Derive the stored monitoring postures from the underlying row counts."""
    cns["open_dispute_count"] = open_dispute_count(cns["id"])
    if cns.get("status") == "CLOSED":
        return cns
    counted = counted_snapshots_all(cns["id"])
    if len(counted) >= 2:
        cns["monitoring_posture"] = "COMPLETE"
    elif counted:
        cns["monitoring_posture"] = "IMMATURE"
    elif cns.get("monitoring_consent_at") is not None:
        cns["monitoring_posture"] = "MONITORING"
    else:
        cns["monitoring_posture"] = "ENROLLED"
    return cns