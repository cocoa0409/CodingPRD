"""Plan comparison engine (PRD 3.4)."""

from decimal import Decimal

import calculations as calc
import db


def candidate_plans(member):
    return [
        plan for plan in sorted(db.plans.values(), key=lambda row: row["_seq"])
        if plan["status"] == "ACTIVE"
        and plan["state_code"] == member["state_code"]
        and plan["county_code"] == member["county_code"]
    ]


def formulary_rows(plan_id):
    return [row for row in db.formulary_drugs.values() if row["plan_id"] == plan_id]


def cost_breakdown(member, plan):
    rows = formulary_rows(plan["id"])
    drugs = []
    subtotal = Decimal("0.00")
    for member_drug in member.get("drug_list") or []:
        status, cost = calc.drug_annual_cost_cents(member_drug, rows)
        drugs.append({
            "drug_name": member_drug.get("drug_name"),
            "rxcui": member_drug.get("rxcui"),
            "monthly_fills": member_drug.get("monthly_fills"),
            "plan_drug_status": status,
            "drug_annual_cost_cents": calc.num(cost),
        })
        subtotal += cost
    out_of_pocket = calc.plan_out_of_pocket_cents(plan, [calc.dec(d["drug_annual_cost_cents"]) for d in drugs])
    return drugs, out_of_pocket


def most_recent_captured_scope(member_id):
    captured = [
        row for row in db.scopes.values()
        if row["member_id"] == member_id and row["status"] == "CAPTURED"
    ]
    if not captured:
        return None
    captured.sort(key=lambda row: (row["captured_on"], row["_seq"]))
    return captured[-1]


def plan_type_affinity(member, plan):
    scope = most_recent_captured_scope(member["id"])
    if scope is None:
        return 0
    return 1 if plan["plan_type"] in (scope.get("plan_types_authorized") or []) else 0


def pharmacy_component(plan):
    for row in db.pharmacy_entries.values():
        if row["plan_id"] == plan["id"] and row["network_tier"] in ("PREFERRED", "STANDARD"):
            return 1
    return 0


def provider_ratio(member, plan):
    wanted = member.get("provider_npis") or []
    matched = 0
    for row in db.provider_entries.values():
        if row["plan_id"] != plan["id"]:
            continue
        if row.get("network_status") != "IN_NETWORK":
            continue
        if row.get("accepting_new_patients") is not True:
            continue
        if row.get("provider_npi") in wanted:
            matched += 1
    return Decimal(matched) / Decimal(max(1, len(wanted)))


def score_plan(member, plan, out_of_pocket):
    affinity = plan_type_affinity(member, plan)
    pharmacy = pharmacy_component(plan)
    ratio = provider_ratio(member, plan)
    cost_score = max(Decimal("0"), Decimal("1000") - calc.dec(out_of_pocket) / calc.COST_DIVISOR_CENTS)
    composite = calc.composite_score(affinity, plan["star_rating"], pharmacy, ratio, out_of_pocket)
    return {
        "plan_type_affinity_match": affinity,
        "pharmacy_component": pharmacy,
        "provider_ratio": calc.num(ratio),
        "cost_score": calc.num(cost_score),
        "composite_score": calc.num(composite),
    }


def ranked_plans(member):
    ranked = []
    for plan in candidate_plans(member):
        drugs, out_of_pocket = cost_breakdown(member, plan)
        scores = score_plan(member, plan, out_of_pocket)
        entry = {
            "plan_id": plan["id"],
            "plan_id_code": plan["plan_id_code"],
            "plan_type": plan["plan_type"],
            "state_code": plan["state_code"],
            "county_code": plan["county_code"],
            "monthly_premium_cents": plan["monthly_premium_cents"],
            "star_rating": calc.num(plan["star_rating"]),
            "plan_out_of_pocket_cents": calc.num(out_of_pocket),
            "drug_results": drugs,
            "_created_at": plan["created_at"],
        }
        entry.update(scores)
        ranked.append(entry)

    ranked.sort(key=lambda e: (
        -calc.dec(e["composite_score"]),
        calc.dec(e["monthly_premium_cents"]),
        e["_created_at"],
    ))
    for entry in ranked:
        entry.pop("_created_at", None)
    return ranked