"""PerformanceMeasurement helpers per PRD §3.7."""
from db import db
from services import calculations
from services.resources import base_fields, touch


def find_measurement(payer_contract_id, member_id, period_index):
    for m in db.measurements.values():
        if (m.get("payer_contract_id") == payer_contract_id
                and m.get("member_id") == member_id
                and m.get("period_index") == period_index):
            return m
    return None


def get_or_create_measurement(payer_contract_id, member_id, period_index):
    m = find_measurement(payer_contract_id, member_id, period_index)
    if m is not None:
        return m
    m = base_fields()
    m.update({
        "payer_contract_id": payer_contract_id,
        "member_id": member_id,
        "period_index": period_index,
        "urgent_episodes_triggered": 0,
        "urgent_episodes_sla_met": 0,
        "urgent_episodes_avoided_ed": 0,
        "visits_completed": 0,
        "visits_no_show": 0,
        "visits_cancelled": 0,
        "pcp_coordination_rate": 0,
        # All components fall back to 1.0 on empty denominators (PRD §3.5).
        "composite_score": 1.0,
    })
    db.measurements[m["id"]] = m
    return m


def recompute_pcp_coordination_rate(m):
    """Fraction of COMPLETED visits in the period whose assessment has
    pcp_notified == true; 0 if no visits have completed (PRD §3.7)."""
    completed = []
    for v in db.visits.values():
        if v.get("member_id") != m.get("member_id"):
            continue
        if v.get("status") != "COMPLETED":
            continue
        completed.append(v)
    if not completed:
        m["pcp_coordination_rate"] = 0
        return
    notified = 0
    for v in completed:
        for a in db.assessments.values():
            if a.get("visit_id") == v["id"] and a.get("pcp_notified"):
                notified += 1
                break
    m["pcp_coordination_rate"] = notified / len(completed)


def recompute_composite(m):
    m["composite_score"] = calculations.compute_composite_score(m)


def bump_counter(m, field, delta):
    m[field] = int(m.get(field) or 0) + delta
    touch(m)
    recompute_composite(m)


def serialize(m):
    return {
        "id": m["id"],
        "payer_contract_id": m["payer_contract_id"],
        "member_id": m["member_id"],
        "period_index": m["period_index"],
        "urgent_episodes_triggered": m["urgent_episodes_triggered"],
        "urgent_episodes_sla_met": m["urgent_episodes_sla_met"],
        "urgent_episodes_avoided_ed": m["urgent_episodes_avoided_ed"],
        "visits_completed": m["visits_completed"],
        "visits_no_show": m["visits_no_show"],
        "visits_cancelled": m["visits_cancelled"],
        "pcp_coordination_rate": m["pcp_coordination_rate"],
        "composite_score": m["composite_score"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }
