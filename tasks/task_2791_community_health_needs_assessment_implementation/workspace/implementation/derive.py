"""Lookups, posture gates, derived-field recomputation and the cascades."""

from decimal import Decimal

import consts as K
from core import db, fail, now_iso, q0, q2, touch

# ---------------------------------------------------------------------------
# lookups (path identifiers resolve strictly left to right)
# ---------------------------------------------------------------------------


def _get(table, rid, err):
    rec = table.get(rid)
    if rec is None:
        fail(err)
    return rec


def cycle_or_404(rid):
    return _get(db.cycles, rid, "ERR_CYCLE_NOT_FOUND")


def indicator_or_404(rid):
    return _get(db.indicators, rid, "ERR_INDICATOR_NOT_FOUND")


def data_point_or_404(rid):
    return _get(db.data_points, rid, "ERR_DATA_POINT_NOT_FOUND")


def party_or_404(rid):
    return _get(db.parties, rid, "ERR_PARTY_NOT_FOUND")


def interview_or_404(rid):
    return _get(db.interviews, rid, "ERR_INTERVIEW_NOT_FOUND")


def candidate_or_404(rid):
    return _get(db.candidates, rid, "ERR_CANDIDATE_NOT_FOUND")


def strategy_or_404(rid):
    return _get(db.strategies, rid, "ERR_STRATEGY_NOT_FOUND")


def objective_or_404(rid):
    return _get(db.objectives, rid, "ERR_OBJECTIVE_NOT_FOUND")


def agreement_or_404(rid):
    return _get(db.agreements, rid, "ERR_PARTNERSHIP_NOT_FOUND")


def commitment_or_404(rid):
    return _get(db.commitments, rid, "ERR_COMMITMENT_NOT_FOUND")


def report_or_404(rid):
    return _get(db.reports, rid, "ERR_REPORT_NOT_FOUND")


def posting_or_404(rid):
    return _get(db.postings, rid, "ERR_POSTING_NOT_FOUND")


def evaluation_or_404(rid):
    return _get(db.evaluations, rid, "ERR_EVALUATION_NOT_FOUND")


# ---------------------------------------------------------------------------
# reachability helpers
# ---------------------------------------------------------------------------


def cycle_of_indicator(ind):
    return db.cycles.get(ind["cycle_id"])


def cycle_of_candidate(cand):
    return db.cycles.get(cand["cycle_id"])


def cycle_of_strategy(strat):
    cand = db.candidates.get(strat["candidate_id"])
    return db.cycles.get(cand["cycle_id"]) if cand else None


def cycle_of_objective(obj):
    strat = db.strategies.get(obj["strategy_id"])
    return cycle_of_strategy(strat) if strat else None


def cycle_of_commitment(com):
    strat = db.strategies.get(com["strategy_id"])
    return cycle_of_strategy(strat) if strat else None


def cycle_of_report(rep):
    return db.cycles.get(rep["cycle_id"])


def cycle_of_posting(post):
    rep = db.reports.get(post["report_id"])
    return cycle_of_report(rep) if rep else None


def strategies_of_cycle(cycle):
    """Every strategy whose priority candidate belongs to this cycle."""
    cand_ids = {c["id"] for c in db.candidates.values() if c["cycle_id"] == cycle["id"]}
    return [s for s in db.strategies.values() if s["candidate_id"] in cand_ids]


def objectives_of_strategy(strat):
    return [o for o in db.objectives.values() if o["strategy_id"] == strat["id"]]


def commitments_of_strategy(strat):
    return [c for c in db.commitments.values() if c["strategy_id"] == strat["id"]]


def data_points_of_indicator(ind):
    return [d for d in db.data_points.values() if d["indicator_id"] == ind["id"]]


def postings_of_report(rep):
    return [p for p in db.postings.values() if p["report_id"] == rep["id"]]


# ---------------------------------------------------------------------------
# posture gates
# ---------------------------------------------------------------------------


def gate_frozen(cycle):
    if cycle is not None and cycle["posture"] == "FROZEN":
        fail("ERR_CYCLE_FROZEN")


def gate_restricted(cycle):
    if cycle is not None and cycle["posture"] == "RESTRICTED":
        fail("ERR_CYCLE_RESTRICTED")


def gate_child_write(cycle, restricted=False):
    gate_frozen(cycle)
    if restricted:
        gate_restricted(cycle)


# ---------------------------------------------------------------------------
# derived-field recomputation
# ---------------------------------------------------------------------------


def compute_posture(cycle):
    if cycle["status"] in ("FILED", "CLOSED"):
        return "FROZEN"
    if cycle["status"] == "BOARD_REVIEW":
        return "RESTRICTED"
    if cycle["review_flag_count"] >= 1:
        return "RESTRICTED"
    return "OPEN"


def sync_cycle(cycle, force=False):
    """Recompute the four derived counters plus posture; version rises only on change."""
    if cycle is None:
        return
    cid = cycle["id"]
    new = {
        "sufficient_indicator_count": sum(
            1 for i in db.indicators.values()
            if i["cycle_id"] == cid and i["data_state"] == "SUFFICIENT"),
        "completed_interview_count": sum(
            1 for s in db.interviews.values()
            if s["cycle_id"] == cid and s["status"] == "COMPLETED"),
        "selected_priority_count": sum(
            1 for c in db.candidates.values()
            if c["cycle_id"] == cid and c["status"] == "SELECTED"),
        "review_flag_count": sum(
            1 for s in strategies_of_cycle(cycle)
            if s["execution_state"] == "SUSPENDED_PENDING_REVIEW"),
    }
    changed = any(cycle[k] != v for k, v in new.items())
    cycle.update(new)
    posture = compute_posture(cycle)
    if posture != cycle["posture"]:
        cycle["posture"] = posture
        changed = True
    if changed or force:
        touch(cycle)


def _newest(rows):
    """Newest by collected_on DESC then created_at DESC; identifiers never tie-break."""
    return sorted(rows, key=lambda d: (d["collected_on"], d["created_at"], d["_seq"]),
                  reverse=True)[0]


def recompute_indicator(ind, force=True):
    active = [d for d in data_points_of_indicator(ind) if d["status"] == "ACTIVE"]
    overall = [d for d in active if d["population_subgroup"] == "OVERALL"]
    if overall:
        latest = _newest(overall)["value"]
        severity = q2(Decimal(latest) / Decimal(ind["benchmark_value"]) * Decimal(50))
        if severity > Decimal(K.SEVERITY_SCORE_CEILING):
            severity = Decimal(K.SEVERITY_SCORE_CEILING)
    else:
        latest = None
        severity = None

    reps = {}
    for d in active:
        if d["population_subgroup"] == "OVERALL":
            continue
        reps.setdefault(d["population_subgroup"], []).append(d)
    rates = [_newest(rows)["value"] for rows in reps.values()]
    subgroup_count = len(reps)
    if subgroup_count >= K.MIN_SUBGROUPS_FOR_DISPARITY:
        disparity = q2(Decimal(max(rates)) / Decimal(min(rates)))
    else:
        disparity = None

    new = {
        "latest_overall_value": latest,
        "severity_score": severity,
        "disparity_ratio": disparity,
        "subgroup_count": subgroup_count,
        "evidence_count": len(active),
        "data_state": "SUFFICIENT" if (latest is not None
                                      and subgroup_count >= K.MIN_SUBGROUPS_FOR_DISPARITY)
        else "INSUFFICIENT",
    }
    changed = any(ind[k] != v for k, v in new.items())
    ind.update(new)
    if changed or force:
        touch(ind)


def recompute_party_fte(party):
    total = sum(c["fte_bp"] for c in db.commitments.values()
                if c["party_id"] == party["id"] and c["status"] in ("PENDING", "COMMITTED"))
    if party["committed_fte_bp"] != total:
        party["committed_fte_bp"] = total
        touch(party)


def recompute_strategy_budget(strat):
    encumbered = sum(c["funding_cents"] for c in commitments_of_strategy(strat)
                     if c["status"] in ("PENDING", "COMMITTED"))
    avail = strat["authorized_budget_cents"] - encumbered
    if strat["budget_available_cents"] != avail:
        strat["budget_available_cents"] = avail
        touch(strat)


def recompute_strategy_objective_count(strat):
    count = sum(1 for o in objectives_of_strategy(strat) if o["status"] == "ACTIVE")
    if strat["active_objective_count"] != count:
        strat["active_objective_count"] = count
        touch(strat)


def recompute_agreement_funding(agreement):
    total = sum(c["funding_cents"] for c in db.commitments.values()
                if c.get("partnership_id") == agreement["id"] and c["status"] == "COMMITTED")
    if agreement["funded_cents"] != total:
        agreement["funded_cents"] = total
        touch(agreement)
    return total


def overhead_rate_for(base_cents):
    if base_cents < K.TIER_1_CEILING_CENTS:
        return Decimal(K.TIER_1_RATE)
    if base_cents < K.TIER_2_CEILING_CENTS:
        return Decimal(K.TIER_2_RATE)
    return Decimal(K.TIER_3_RATE)


CATEGORY_TOTAL_FIELD = {
    "FINANCIAL_ASSISTANCE": "financial_assistance_cents",
    "SUBSIDIZED_SERVICES": "subsidized_services_cents",
    "COMMUNITY_HEALTH_IMPROVEMENT": "community_health_improvement_cents",
    "CASH_AND_INKIND": "cash_and_inkind_cents",
    "COMMUNITY_BUILDING": "community_building_cents",
}


def value_posting(post, rep):
    """Per-posting valuation; the totals are sums of these already-rounded integers."""
    if post["category"] in K.CHARGE_BASED_CATEGORIES:
        post["valued_cents"] = q0(Decimal(post["charges_cents"]) * rep["cost_to_charge_ratio"])
        post["ratio_applied"] = rep["cost_to_charge_ratio"]
    else:
        post["valued_cents"] = post["direct_cost_cents"]
        post["ratio_applied"] = None
    # ``valuation_basis_at_posting`` is *frozen* to the report's basis as it
    # stood at the moment of posting, so a reader can tell which numbers were
    # provisional when they were entered.  It is stamped once, when the posting
    # is created, and finalization's revaluation must never rewrite it.


def recompute_report(rep, force=False):
    posted = [p for p in postings_of_report(rep) if p["status"] == "POSTED"]
    new = {}
    for category, field in CATEGORY_TOTAL_FIELD.items():
        new[field] = sum(p["valued_cents"] for p in posted if p["category"] == category)
    base = sum(new[f] for f in CATEGORY_TOTAL_FIELD.values())
    new["total_valued_cents"] = base
    rate = overhead_rate_for(base)
    new["overhead_rate"] = rate
    indirect = q0(Decimal(base) * rate)
    new["indirect_allocation_cents"] = indirect
    new["grand_total_cents"] = base + indirect
    cycle = cycle_of_report(rep)
    denom = cycle["total_operating_expense_cents"] if cycle else 0
    if denom:
        new["benefit_pct_of_expense"] = q2(
            Decimal(new["grand_total_cents"]) / Decimal(denom) * Decimal(100))
    else:
        new["benefit_pct_of_expense"] = q2(Decimal(0))
    changed = any(rep[k] != v for k, v in new.items())
    rep.update(new)
    if changed or force:
        touch(rep)


# ---------------------------------------------------------------------------
# scoring calculations
# ---------------------------------------------------------------------------


def community_concern_index(cycle, domain):
    """Attendance-weighted mean rating on the 1..5 scale, scaled to 0..100.

    A single round-half-up is applied to the final product, never per session
    and never to the intermediate mean.
    """
    sessions = [s for s in db.interviews.values()
                if s["cycle_id"] == cycle["id"] and s["status"] == "COMPLETED"
                and isinstance(s.get("concern_ratings"), dict)
                and domain in s["concern_ratings"]]
    if not sessions:
        return None
    weighted = Decimal(0)
    weight = Decimal(0)
    for s in sessions:
        rating = Decimal(s["concern_ratings"][domain])
        attendees = Decimal(s["attendee_count"])
        weighted += rating * attendees
        weight += attendees
    if weight == 0:
        return None
    mean = weighted / weight
    return q2(mean * Decimal(K.RATING_TO_INDEX_FACTOR))


def disparity_points_for(indicator):
    if indicator["disparity_ratio"] is None:
        return q2(Decimal(0))
    points = q2((Decimal(indicator["disparity_ratio"]) - Decimal(1)) * Decimal(100))
    ceiling = Decimal(K.DISPARITY_POINTS_CEILING)
    if points > ceiling:
        points = ceiling
    return points


EQUAL_WEIGHTS = (Decimal("0.25"), Decimal("0.25"), Decimal("0.25"), Decimal("0.25"))
COMMUNITY_WEIGHTS = (Decimal("0.20"), Decimal("0.30"), Decimal("0.35"), Decimal("0.15"))


def composite_score(variant, severity, disparity, concern, capacity):
    weights = EQUAL_WEIGHTS if variant == "EQUAL_WEIGHT" else COMMUNITY_WEIGHTS
    terms = (Decimal(severity), Decimal(disparity), Decimal(concern), Decimal(capacity))
    total = sum(w * t for w, t in zip(weights, terms))
    return q2(total)


def compute_attainment(obj):
    base = Decimal(obj["baseline_value"])
    target = Decimal(obj["target_value"])
    actual = Decimal(obj["actual_value"])
    if target == base:
        pct = q2(Decimal(K.MET_THRESHOLD)) if actual >= target else q2(Decimal(0))
    else:
        pct = q2((actual - base) / (target - base) * Decimal(100))
        ceiling = Decimal(K.ATTAINMENT_CEILING)
        if pct > ceiling:
            pct = ceiling
        if pct < Decimal("0.00"):
            pct = q2(Decimal(0))
    obj["attainment_pct"] = pct
    if pct >= Decimal(K.MET_THRESHOLD):
        obj["attainment_status"] = "MET"
    elif pct >= Decimal(K.PARTIAL_THRESHOLD):
        obj["attainment_status"] = "PARTIAL"
    else:
        obj["attainment_status"] = "NOT_MET"


# ---------------------------------------------------------------------------
# cascades
# ---------------------------------------------------------------------------


def release_commitment(com, reason):
    """Compensating action for both conserved quantities."""
    was_committed = com["status"] == "COMMITTED"
    com["status"] = "RELEASED"
    com["release_reason"] = reason
    com["released_at"] = now_iso()
    touch(com)
    party = db.parties.get(com["party_id"])
    if party is not None:
        recompute_party_fte(party)
    strat = db.strategies.get(com["strategy_id"])
    if strat is not None:
        recompute_strategy_budget(strat)
    if com.get("partnership_id"):
        agreement = db.agreements.get(com["partnership_id"])
        if agreement is not None:
            total = recompute_agreement_funding(agreement)
            if was_committed and total == 0 and agreement["funding_state"] == "FUNDED":
                agreement["funding_state"] = "RELEASED"
                touch(agreement)


def void_cascade(dp):
    """Link one: indicator re-derives.  Link two: candidate scores invalidated.
    Link three: strategies suspended."""
    ind = db.indicators.get(dp["indicator_id"])
    if ind is None:
        return
    was_sufficient = ind["data_state"] == "SUFFICIENT"
    recompute_indicator(ind)
    cycle = cycle_of_indicator(ind)
    if was_sufficient and ind["data_state"] == "INSUFFICIENT":
        affected = [c for c in db.candidates.values()
                    if c["indicator_id"] == ind["id"]
                    and c["status"] in ("SCORED", "SELECTED")]
        previously_selected = [c for c in affected if c["status"] == "SELECTED"]
        for cand in sorted(affected, key=lambda c: c["_seq"]):
            cand["status"] = "SCORE_INVALIDATED"
            cand["composite_score"] = None
            cand["severity_input"] = None
            cand["disparity_points"] = None
            cand["community_concern_index"] = None
            touch(cand)
        for cand in previously_selected:
            for strat in sorted(db.strategies.values(), key=lambda s: s["_seq"]):
                if strat["candidate_id"] != cand["id"]:
                    continue
                if strat["execution_state"] in ("COMPLETED", "DISCONTINUED", "CLOSED_OUT"):
                    continue
                strat["execution_state"] = "SUSPENDED_PENDING_REVIEW"
                touch(strat)
    sync_cycle(cycle)


def adoption_cascade(cycle):
    stamp = now_iso()
    link_one = [s for s in sorted(strategies_of_cycle(cycle), key=lambda s: s["_seq"])
                if s["approval_state"] == "SUBMITTED"]
    for strat in link_one:
        strat["approval_state"] = "APPROVED"
        strat["approved_at"] = stamp
        touch(strat)
    for strat in link_one:
        before = strat["active_objective_count"]
        activated = 0
        for obj in sorted(objectives_of_strategy(strat), key=lambda o: o["_seq"]):
            if obj["status"] == "DRAFT":
                obj["status"] = "ACTIVE"
                obj["baseline_locked_at"] = stamp
                touch(obj)
                activated += 1
        recompute_strategy_objective_count(strat)
        if activated > 0 and strat["execution_state"] == "NOT_STARTED":
            strat["execution_state"] = "ON_TRACK"
            touch(strat)
        if activated > 0 and before == 0 and strat["active_objective_count"] >= 1:
            for com in sorted(commitments_of_strategy(strat), key=lambda c: c["_seq"]):
                if com["status"] != "PENDING":
                    continue
                com["status"] = "COMMITTED"
                com["committed_at"] = stamp
                touch(com)
                if com.get("partnership_id"):
                    agreement = db.agreements.get(com["partnership_id"])
                    if agreement is not None:
                        recompute_agreement_funding(agreement)
                        if agreement["funding_state"] == "PLEDGED":
                            agreement["funding_state"] = "FUNDED"
                            touch(agreement)


def closeout_cascade(cycle):
    live = [s for s in sorted(strategies_of_cycle(cycle), key=lambda s: s["_seq"])
            if s["execution_state"] in ("ON_TRACK", "AT_RISK", "BEHIND",
                                        "SUSPENDED_PENDING_REVIEW")]
    for strat in live:
        strat["execution_state"] = "CLOSED_OUT"
        touch(strat)
    for strat in live:
        for obj in sorted(objectives_of_strategy(strat), key=lambda o: o["_seq"]):
            if obj["status"] not in ("ACTIVE", "REVISED"):
                continue
            pct = obj["attainment_pct"]
            if pct is not None and Decimal(pct) >= Decimal(K.MET_THRESHOLD):
                obj["status"] = "FINALIZED_MET"
            else:
                obj["status"] = "FINALIZED_NOT_MET"
            touch(obj)
        recompute_strategy_objective_count(strat)
