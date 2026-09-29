"""Derived counters, the compliance-posture gate and the plan-wide cascades.

Every counter is recomputed from scratch rather than patched incrementally --
that is what makes the two conservation invariants of PRD 2.10 hold exactly.
"""
from decimal import Decimal

import constants as K
from db import bump, db, dec
from errors import ApiError
from services import calc, repo


def ensure_not_adopted(plan):
    if plan["status"] == "ADOPTED":
        raise ApiError("ERR_PLAN_ALREADY_ADOPTED")


# --- derived counters (PRD 2.9 / 2.10) --------------------------------------

def recompute_counters(plan):
    plan_id = plan["id"]

    open_links = 0
    for row in repo.links_of_plan(plan_id):
        if row["status"] in ("OPEN", "STALE"):
            open_links += 1
    plan["open_consistency_link_count"] = open_links

    complete_types = set()
    for row in repo.elements_of(plan_id):
        if row["status"] in ("APPROVED", "ADOPTED"):
            complete_types.add(row["element_type"])
    plan["required_elements_complete_count"] = len(complete_types)

    shortfall = 0
    for row in repo.allocations_of(plan_id):
        shortfall += int(row["shortfall_units"])
    plan["housing_shortfall_total"] = shortfall

    total = Decimal(0)
    under = Decimal(0)
    for row in repo.activities_of(plan_id):
        if row["status"] == "COMPLETED":
            total += dec(row["total_weighted_count"])
            under += dec(row["underrepresented_weighted_count"])
    plan["participation_weight_total"] = calc.weight_sum([total])
    plan["underrepresented_weight_total"] = calc.weight_sum([under])
    plan["equity_share_pct"] = calc.equity_share(
        plan["underrepresented_weight_total"],
        plan["participation_weight_total"])

    on_track = 0
    for row in repo.actions_of(plan_id):
        if row["on_track"]:
            on_track += 1
    plan["monitoring_on_track_count"] = on_track


# --- posture and hearing cascade (PRD 2.9) ----------------------------------

def block_scheduled_hearings(plan, exclude_ids=()):
    for row in repo.hearings_of(plan["id"]):
        if row["id"] in exclude_ids:
            continue
        if row["status"] == "SCHEDULED":
            row["status"] = "BLOCKED"
            bump(row)


def unblock_hearings(plan):
    for row in repo.hearings_of(plan["id"]):
        if row["status"] == "BLOCKED":
            row["status"] = "SCHEDULED"
            bump(row)


def refresh(plan, force_block=False, exclude_hearing_ids=()):
    """Recompute every counter, then the posture, then cascade to hearings."""
    recompute_counters(plan)
    previous = plan.get("compliance_posture")
    posture = calc.compliance_posture(plan)
    plan["compliance_posture"] = posture
    if posture == "CLEAR":
        unblock_hearings(plan)
    elif force_block or previous == "CLEAR":
        block_scheduled_hearings(plan, exclude_hearing_ids)
    return posture


# --- housing allocation waterfall (PRD 3.3) ---------------------------------

def run_waterfall(plan, skip_bump_id=None):
    rows = repo.allocations_of(plan["id"])
    by_tier = {}
    for row in rows:
        by_tier[row["income_tier"]] = row
    pool = 0
    scenario_id = plan.get("adopted_scenario_id")
    if scenario_id is not None:
        scenario = db.growth_scenarios.get(scenario_id)
        if scenario is not None:
            pool = scenario["land_capacity_units"]
    results, _total = calc.run_waterfall(pool, by_tier)
    for tier, row in by_tier.items():
        computed = results.get(tier)
        if computed is None:
            continue
        changed = False
        for field, value in computed.items():
            if row[field] != value:
                row[field] = value
                changed = True
        if changed and row["id"] != skip_bump_id:
            bump(row)


# --- element / link cascades (PRD 3.4 / 3.5 / 3.8 / 3.9) --------------------

def element_consistency_from_links(element):
    """CLEARED when every link sourced from the element is CLEARED."""
    for row in repo.links_sourced_from(element["id"]):
        if row["status"] != "CLEARED":
            return "PENDING"
    return "CLEARED"


def demote_approved_elements(plan, types=None, include_source=False):
    """The shared demotion cascade of a deficient determination (types given)
    and of a council denial (types is None, links matched on either end)."""
    touched = {}
    demoted_ids = set()
    for row in repo.elements_of(plan["id"]):
        if row["status"] != "APPROVED":
            continue
        if types is not None and row["element_type"] not in types:
            continue
        row["status"] = "REVISION_REQUESTED"
        row["revision_round"] = int(row["revision_round"]) + 1
        row["consistency_status"] = "STALE"
        demoted_ids.add(row["id"])
        touched[row["id"]] = row

    for row in repo.links_of_plan(plan["id"]):
        if row["status"] != "CLEARED":
            continue
        hit = row["target_element_id"] in demoted_ids
        if include_source and not hit:
            hit = row["source_element_id"] in demoted_ids
        if not hit:
            continue
        row["status"] = "OPEN"
        row["reconciled_by_user_id"] = None
        row["reconciliation_note"] = None
        bump(row)
        src = db.plan_elements.get(row["source_element_id"])
        if src is not None and src["consistency_status"] != "STALE":
            src["consistency_status"] = "STALE"
            if src["id"] not in touched:
                touched[src["id"]] = src

    for row in touched.values():
        bump(row)
    return demoted_ids


def certified_review(plan):
    for row in repo.reviews_of(plan["id"]):
        if row["status"] == "CERTIFIED":
            return row
    return None


def required_element_types_missing(plan):
    present = set()
    for row in repo.elements_of(plan["id"]):
        if row["status"] in ("APPROVED", "ADOPTED"):
            present.add(row["element_type"])
    return [t for t in K.REQUIRED_ELEMENT_TYPES if t not in present]
