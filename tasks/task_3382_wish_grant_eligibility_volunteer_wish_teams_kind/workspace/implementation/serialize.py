"""Entity serializers.

Computed fields (chapter aggregates, plan totals, offer availability) are
derived live from the store at serialization time so they can never drift
from the underlying mutations. All money is integer cents; divisions round
half-up; the budget freeze threshold uses floor.
"""

from db import STORE, now
from util import iso3, rhu_div


def _spine(e):
    return {
        "id": e["id"],
        "created_at": iso3(e["created_at"]),
        "updated_at": iso3(e["updated_at"]),
        "version": e["version"],
    }


def _dt(v):
    return iso3(v) if v is not None else None


# ----- plan / chapter aggregates ------------------------------------------------

def plan_in_kind(plan):
    """Sum of line_fmv_cents over lines in RESERVED/COMMITTED/CONSUMED."""
    return sum(
        l["line_fmv_cents"]
        for l in STORE["lines"].values()
        if l["plan_id"] == plan["id"] and l["status"] in ("RESERVED", "COMMITTED", "CONSUMED")
    )


def plan_total(plan):
    return plan["cash_cost_cents"] + plan_in_kind(plan)


def chapter_committed(chapter_id):
    """Sum of total_cost_cents over APPROVED plans of this chapter's wishes."""
    total = 0
    for p in STORE["plans"].values():
        if p["status"] != "APPROVED":
            continue
        w = STORE["wishes"].get(p["wish_id"])
        if w is not None and w["chapter_id"] == chapter_id:
            total += plan_total(p)
    return total


def chapter_granted_aggs(chapter_id):
    """(count, cost_total, cash_total) over wishes GRANTED in the clock's year."""
    year = now().year
    cnt = 0
    cost = 0
    cash = 0
    for w in STORE["wishes"].values():
        if w["chapter_id"] != chapter_id:
            continue
        if w["status"] != "GRANTED" or w["granted_at"] is None:
            continue
        if w["granted_at"].year != year:
            continue
        cnt += 1
        plan = None
        for p in STORE["plans"].values():
            if p["wish_id"] == w["id"] and p["status"] == "COMPLETED":
                plan = p
                break
        if plan is not None:
            cost += plan_total(plan)
            cash += plan["cash_cost_cents"]
    return cnt, cost, cash


def chapter_posture(chapter, committed):
    threshold = (chapter["fiscal_year_budget_cents"] * 95) // 100
    return "FROZEN" if committed >= threshold else "OPEN"


# ----- serializers ---------------------------------------------------------------

def ser_chapter(ch):
    committed = chapter_committed(ch["id"])
    cnt, cost, cash = chapter_granted_aggs(ch["id"])
    out = _spine(ch)
    out.update({
        "name": ch["name"],
        "territory_zip_prefixes": list(ch["territory_zip_prefixes"]),
        "fiscal_year_budget_cents": ch["fiscal_year_budget_cents"],
        "target_avg_cost_per_wish_cents": ch["target_avg_cost_per_wish_cents"],
        "committed_cost_cents": committed,
        "granted_wish_count": cnt,
        "granted_cost_total_cents": cost,
        "granted_cash_total_cents": cash,
        "avg_cost_blended_cents": rhu_div(cost, cnt) if cnt else 0,
        "avg_cost_cash_cents": rhu_div(cash, cnt) if cnt else 0,
        "posture": chapter_posture(ch, committed),
    })
    return out


def ser_volunteer(v):
    out = _spine(v)
    out.update({
        "chapter_id": v["chapter_id"],
        "full_name": v["full_name"],
        "email": v["email"],
        "status": v["status"],
    })
    return out


def ser_child(c):
    out = _spine(c)
    out.update({
        "full_name": c["full_name"],
        "normalized_full_name": c["normalized_full_name"],
        "date_of_birth": c["date_of_birth"],
        "zip_code": c["zip_code"],
        "parent_email": c["parent_email"],
        "diagnosis_summary": c["diagnosis_summary"],
        "chapter_id": c["chapter_id"],
        "treatment_windows": [dict(w) for w in c["treatment_windows"]],
    })
    return out


def ser_referral(r):
    out = _spine(r)
    out.update({
        "child_id": r["child_id"],
        "source_type": r["source_type"],
        "prognosis_months": r["prognosis_months"],
        "status": r["status"],
        "qualifying_condition": r["qualifying_condition"],
        "certification_note": r["certification_note"],
        "certified_at": _dt(r["certified_at"]),
        "age_months_at_intake": r["age_months_at_intake"],
        "denial_reason": r["denial_reason"],
        "determined_at": _dt(r["determined_at"]),
        "wish_id": r["wish_id"],
    })
    return out


def ser_wish(w):
    out = _spine(w)
    out.update({
        "child_id": w["child_id"],
        "chapter_id": w["chapter_id"],
        "referral_id": w["referral_id"],
        "wish_type": w["wish_type"],
        "urgency": w["urgency"],
        "status": w["status"],
        "true_wish_description": w["true_wish_description"],
        "determined_at": _dt(w["determined_at"]),
        "hold_return_state": w["hold_return_state"],
        "granted_at": _dt(w["granted_at"]),
    })
    return out


def ser_team(t):
    out = _spine(t)
    out.update({
        "wish_id": t["wish_id"],
        "lead_volunteer_id": t["lead_volunteer_id"],
        "second_volunteer_id": t["second_volunteer_id"],
        "status": t["status"],
    })
    return out


def ser_visit(v):
    out = _spine(v)
    out.update({
        "wish_team_id": v["wish_team_id"],
        "scheduled_start": iso3(v["scheduled_start"]),
        "scheduled_end": iso3(v["scheduled_end"]),
        "visit_method": v["visit_method"],
        "status": v["status"],
        "captured_true_wish": v["captured_true_wish"],
        "captured_wish_type": v["captured_wish_type"],
    })
    return out


def ser_offer(o):
    out = _spine(o)
    out.update({
        "partner_name": o["partner_name"],
        "category": o["category"],
        "valuation_method": o["valuation_method"],
        "description": o["description"],
        "quantity_total": o["quantity_total"],
        "quantity_reserved": o["quantity_reserved"],
        "quantity_available": o["quantity_total"] - o["quantity_reserved"],
        "unit_retail_cents": o["unit_retail_cents"],
        "partner_declared_unit_cents": o["partner_declared_unit_cents"],
        "fmv_unit_cents": o["fmv_unit_cents"],
        "valid_from": o["valid_from"].isoformat(),
        "valid_until": o["valid_until"].isoformat(),
        "status": o["status"],
    })
    return out


def ser_plan(p):
    in_kind = plan_in_kind(p)
    out = _spine(p)
    out.update({
        "wish_id": p["wish_id"],
        "cash_cost_cents": p["cash_cost_cents"],
        "notes": p["notes"],
        "in_kind_value_cents": in_kind,
        "total_cost_cents": p["cash_cost_cents"] + in_kind,
        "status": p["status"],
        "created_by_user_id": p["created_by_user_id"],
        "approved_by_user_id": p["approved_by_user_id"],
        "escalation_required": p["escalation_required"],
    })
    return out


def ser_line(l):
    out = _spine(l)
    out.update({
        "plan_id": l["plan_id"],
        "donation_offer_id": l["donation_offer_id"],
        "quantity": l["quantity"],
        "line_fmv_cents": l["line_fmv_cents"],
        "status": l["status"],
    })
    return out


def ser_clearance(c):
    out = _spine(c)
    out.update({
        "wish_id": c["wish_id"],
        "status": c["status"],
        "accommodations": list(c["accommodations"]),
        "valid_until": c["valid_until"].isoformat() if c["valid_until"] is not None else None,
        "decision_note": c["decision_note"],
        "decided_at": _dt(c["decided_at"]),
    })
    return out


def ser_event(e):
    out = _spine(e)
    out.update({
        "wish_id": e["wish_id"],
        "event_start_date": e["event_start_date"].isoformat(),
        "event_end_date": e["event_end_date"].isoformat(),
        "status": e["status"],
        "completed_at": _dt(e["completed_at"]),
    })
    return out
