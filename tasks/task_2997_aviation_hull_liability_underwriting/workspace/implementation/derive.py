"""Cross-entity figures that are re-derived rather than stored.

Every aggregate in PRD 2.9 and 3.3 is computed from the live rows on demand, which is
what makes "after every request the invariant holds" trivially true.
"""

import constants as C
from store import db, ordered, sort_key


# --- collections --------------------------------------------------------------

def schedules_of_policy(policy_id):
    return sorted((s for s in db.schedules.values() if s["policy_id"] == policy_id), key=sort_key)


def live_schedules_of_policy(policy_id):
    return [s for s in schedules_of_policy(policy_id) if s["coverage_status"] in C.LIVE_COVERAGE]


def schedules_of_pilot(pilot_id):
    return sorted((s for s in db.schedules.values() if s["named_pilot_id"] == pilot_id), key=sort_key)


def schedules_of_aircraft(aircraft_id):
    return sorted((s for s in db.schedules.values() if s["aircraft_id"] == aircraft_id), key=sort_key)


def claims_of_policy(policy_id):
    return sorted((c for c in db.claims.values() if c["policy_id"] == policy_id), key=sort_key)


def claims_of_schedule(schedule_id):
    return sorted((c for c in db.claims.values() if c["schedule_id"] == schedule_id), key=sort_key)


def assessments_of_claim(claim_id):
    return sorted((a for a in db.assessments.values() if a["claim_id"] == claim_id), key=sort_key)


def transactions_of_policy(policy_id):
    return sorted((t for t in db.transactions.values() if t["policy_id"] == policy_id), key=sort_key)


def placements_of_policy(policy_id):
    return sorted((p for p in db.placements.values() if p["policy_id"] == policy_id), key=sort_key)


def placements_of_market(market_id):
    return sorted((p for p in db.placements.values() if p["market_id"] == market_id), key=sort_key)


def endorsements_of_policy(policy_id):
    return sorted((e for e in db.endorsements.values() if e["policy_id"] == policy_id), key=sort_key)


def declarations_of_policy(policy_id):
    return sorted((d for d in db.declarations.values() if d["policy_id"] == policy_id), key=sort_key)


# --- operator ----------------------------------------------------------------

def operator_policy_count(operator_id):
    return sum(1 for p in db.policies.values()
               if p["operator_id"] == operator_id and p["status"] in ("DRAFT", "BOUND"))


# --- policy aggregates -------------------------------------------------------

def total_hull_sum_insured(policy_id):
    return sum(s["agreed_value_cents"] for s in live_schedules_of_policy(policy_id))


def live_schedule_count(policy_id):
    return len(live_schedules_of_policy(policy_id))


def written_premium(policy_id):
    return sum(t["amount_cents"] for t in db.transactions.values() if t["policy_id"] == policy_id)


def outstanding_reserve(policy_id):
    return sum(c["reserve_cents"] for c in db.claims.values()
               if c["policy_id"] == policy_id and c["adjustment_status"] == "RESERVED")


def paid_hull(policy_id):
    total = 0
    for c in db.claims.values():
        if c["policy_id"] != policy_id:
            continue
        if c["adjustment_status"] != "SETTLED":
            continue
        if c["loss_type"] not in ("HULL_DAMAGE", "TOTAL_LOSS"):
            continue
        total += c["settlement_amount_cents"] or 0
    return total


# --- market aggregates -------------------------------------------------------

def committed_line(market_id):
    return sum(p["war_hull_line_cents"] for p in db.placements.values()
               if p["market_id"] == market_id and p["status"] == "BOUND")


def all_ordered(collection):
    return ordered(collection)
