"""Shared domain helpers: ownership, version bumping, cross-entity cascades."""

from flask import g

import calc
from errors import ApiError
from store import all_rows, db, get, touch


def touched():
    if not hasattr(g, "touched_rows"):
        g.touched_rows = set()
    return g.touched_rows


def bump(row):
    """Advance a row's version by 1 (at most once per request)."""
    touch(row, touched())


def check_owner(agreement_row):
    """Ladder step 6 — ConcessionaireOperator ownership through the agreement."""
    if g.role == "ConcessionaireOperator":
        if agreement_row["concessionaire_id"] != g.user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")


def facility_of_agreement(agreement_row):
    return db.facilities[agreement_row["facility_id"]]


def rows_of(collection, **filters):
    result = []
    for row in all_rows(collection):
        match = True
        for key, value in filters.items():
            if value is None:
                continue
            if row.get(key) != value:
                match = False
                break
        if match:
            result.append(row)
    return result


# --------------------------------------------------------------------------
# Capital project release (PRD 3.8)
# --------------------------------------------------------------------------

def _project_gate_clear(project_row, facility):
    if project_row["status"] != "APPROVED":
        return False
    if facility["funded_obligation_count"] < 1:
        return False
    if facility["bond_coverage_status"] != "SATISFIED":
        return False
    predecessor_id = project_row.get("predecessor_project_id")
    if predecessor_id is not None:
        predecessor = db.projects.get(predecessor_id)
        if predecessor is None or predecessor["status"] != "CLOSED":
            return False
    return True


def release_facility_projects(facility):
    """Release every eligible APPROVED project of the facility, created_at ASC."""
    for project_row in all_rows("projects"):
        if project_row["facility_id"] != facility["id"]:
            continue
        if not project_row.get("funding_hold", True):
            continue
        if _project_gate_clear(project_row, facility):
            project_row["funding_hold"] = False
            project_row["status"] = "FUNDED"
            bump(project_row)


def release_successor_projects(closed_project, facility):
    """Cascade triggered by a project reaching CLOSED."""
    for project_row in all_rows("projects"):
        if project_row.get("predecessor_project_id") != closed_project["id"]:
            continue
        if project_row["status"] != "APPROVED" or not project_row.get("funding_hold", True):
            continue
        if facility["funded_obligation_count"] < 1:
            continue
        if facility["bond_coverage_status"] != "SATISFIED":
            continue
        project_row["funding_hold"] = False
        project_row["status"] = "FUNDED"
        bump(project_row)


# --------------------------------------------------------------------------
# Debt service funding (PRD 3.7)
# --------------------------------------------------------------------------

def apply_funding(facility, obligation_row, auto):
    obligation_row["funded_from_reserve_cents"] = obligation_row["amount_due_cents"]
    obligation_row["auto_funded"] = bool(auto)
    obligation_row["coverage_ratio_at_funding"] = calc.ratio_4dp(
        calc.coverage_available(facility), obligation_row["amount_due_cents"])
    obligation_row["status"] = "FUNDED"
    facility["trust_debt_service_reserve_cents"] -= obligation_row["amount_due_cents"]
    facility["trust_debt_service_funded_cents"] += obligation_row["amount_due_cents"]
    calc.recompute_bond_coverage(facility)
    facility["funded_obligation_count"] += 1
    bump(obligation_row)
    release_facility_projects(facility)


def auto_fund_one(facility):
    """Cascade hop 4 of a remittance receipt: fund at most one obligation."""
    if facility["bond_coverage_status"] != "SATISFIED":
        return None
    candidates = [o for o in all_rows("obligations")
                  if o["facility_id"] == facility["id"]
                  and o["status"] == "SCHEDULED"
                  and calc.coverage_passes(facility, o)]
    if not candidates:
        return None
    candidates.sort(key=lambda o: (o["due_date"], o["created_at"], o["_seq"]))
    winner = candidates[0]
    apply_funding(facility, winner, auto=True)
    return winner


# --------------------------------------------------------------------------
# Counter space / agreement helpers
# --------------------------------------------------------------------------

def agreement_or_404(agreement_id):
    return get("agreements", agreement_id, "ERR_AGREEMENT_NOT_FOUND")


def facility_or_404(facility_id):
    return get("facilities", facility_id, "ERR_FACILITY_NOT_FOUND")
