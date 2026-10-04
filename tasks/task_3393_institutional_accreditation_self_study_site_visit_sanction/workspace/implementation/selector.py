"""Deterministic peer-review team selector (PRD §3.5, reviewer_selection_ranking).

Eligibility filter (all must hold):
  is_active; affiliation null or != cycle institution; cycle institution not in
  declared conflicts; current_assignment_count < 3; no ACTIVE assignment on any
  team of this cycle.
Chair: prior_chair_count >= 2, ranked quality_rating DESC, prior_chair_count
  DESC, created_at ASC. Empty chair pool -> ERR_NO_ELIGIBLE_CHAIR.
Members: remaining candidates ranked by specialty-coverage count DESC,
  quality_rating DESC, created_at ASC; top 3. Fewer -> ERR_INSUFFICIENT_REVIEWER_POOL.
Decline replacement: same filter and member ranking over candidates not
  already assigned to this team; empty pool leaves the seat open.
"""
import constants as C
from db import STORE
from errors import ERR_INSUFFICIENT_REVIEWER_POOL, ERR_NO_ELIGIBLE_CHAIR, raise_err
from helpers import new_entity, reviewer_assignment_count, touch


def _has_active_assignment_on_cycle(reviewer_id, cycle_id):
    for a in STORE.team_assignments.values():
        if a["reviewer_id"] != reviewer_id or a["status"] != "ACTIVE":
            continue
        team = STORE.review_teams.get(a["review_team_id"])
        if team is not None and team["review_cycle_id"] == cycle_id:
            return True
    return False


def eligible_candidates(cycle):
    institution_id = cycle["institution_id"]
    result = []
    for r in STORE.reviewers.values():
        if not r["is_active"]:
            continue
        if r["affiliation_institution_id"] is not None and r["affiliation_institution_id"] == institution_id:
            continue
        if institution_id in (r["declared_conflict_institution_ids"] or []):
            continue
        if reviewer_assignment_count(r["id"]) >= C.MAX_CONCURRENT_ASSIGNMENTS:
            continue
        if _has_active_assignment_on_cycle(r["id"], cycle_id=cycle["id"]):
            continue
        result.append(r)
    return result


def _chair_key(r):
    return (-r["quality_rating"], -r["prior_chair_count"], r["_seq"])


def _member_key(r):
    return (-len(r["specialty_criteria"]), -r["quality_rating"], r["_seq"])


def pick_chair(candidates):
    pool = [r for r in candidates if r["prior_chair_count"] >= C.CHAIR_MIN_PRIOR_VISITS]
    if not pool:
        raise_err(ERR_NO_ELIGIBLE_CHAIR, "No eligible candidate meets the chair bar")
    return sorted(pool, key=_chair_key)[0]


def pick_members(candidates, chair):
    pool = [r for r in candidates if r["id"] != chair["id"]]
    ranked = sorted(pool, key=_member_key)
    if len(ranked) < C.TEAM_MEMBER_MIN:
        raise_err(ERR_INSUFFICIENT_REVIEWER_POOL, "Eligible pool cannot fill three member seats")
    return ranked[:C.TEAM_MEMBER_MIN]


def make_assignment(team, reviewer, role_on_team):
    assignment = new_entity({
        "review_team_id": team["id"],
        "reviewer_id": reviewer["id"],
        "role_on_team": role_on_team,
        "conflict_status": "CLEARED",
        "response": "PENDING",
        "status": "ACTIVE",
    })
    STORE.team_assignments[assignment["id"]] = assignment
    # The reviewer's computed assignment load changed: a cascade-equivalent
    # mutation, so the reviewer record is touched per §2.5/§2.11.
    touch(reviewer)
    return assignment


def replacement_candidate(team, role_on_team):
    """Next-ranked eligible candidate not already assigned to this team."""
    cycle = STORE.review_cycles.get(team["review_cycle_id"])
    already = {a["reviewer_id"] for a in STORE.team_assignments.values()
               if a["review_team_id"] == team["id"]}
    pool = [r for r in eligible_candidates(cycle) if r["id"] not in already]
    if not pool:
        return None
    return sorted(pool, key=_member_key)[0]
