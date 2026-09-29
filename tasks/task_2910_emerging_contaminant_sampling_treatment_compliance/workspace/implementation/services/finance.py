"""Capital-project funding ledger, the seven-step rate-impact ladder, bill
impact and the cost-recovery waterfall (PRD section 3.9).
"""

from decimal import Decimal

import constants as C
import db
from db import store
from numeric import cents, divide, q2


def applications_for(project_id):
    return [
        application
        for application in db.sorted_rows("applications")
        if application["capital_project_id"] == project_id
    ]


def derive_funding_status(project):
    applications = applications_for(project["id"])
    if any(a["status"] == "AWARDED" for a in applications):
        return "AWARDED"
    if any(a["status"] == "SUBMITTED" for a in applications):
        return "APPLIED"
    if applications and all(a["status"] in ("DENIED", "WITHDRAWN") for a in applications):
        return "DENIED"
    return "NOT_APPLIED"


def awarded_totals(project):
    awarded = 0
    forgiven = 0
    for application in applications_for(project["id"]):
        if application["status"] != "AWARDED":
            continue
        awarded += application["awarded_cents"] or 0
        forgiven += application["forgiven_cents"] or 0
    return awarded, forgiven


def surcharge_bp_for(provisional_pct):
    if provisional_pct < Decimal("5.00"):
        return 0
    if provisional_pct < Decimal("15.00"):
        return 150
    return 400


def recompute_project(project):
    """The pinned seven-step ladder, recomputed end to end from the current
    ledger.  Callers are responsible for touching the row."""
    # Step 1 — the funding ledger and the local share.
    awarded, forgiven = awarded_totals(project)
    project["funding_awarded_cents"] = awarded
    project["grant_equivalent_cents"] = forgiven
    project["loan_principal_cents"] = awarded - forgiven
    project["local_share_cents"] = (
        project["capital_cost_cents"] - awarded - project["recovered_cents"]
    )

    # Step 2 — borrowing and annual debt service.
    project["borrowed_cents"] = project["local_share_cents"] + project["loan_principal_cents"]
    project["annual_debt_service_cents"] = cents(
        Decimal(project["borrowed_cents"]) * C.ANNUITY_FACTOR_20Y_2PCT
    )

    # Step 3 — base annual revenue requirement.
    base = project["annual_debt_service_cents"] + project["annual_om_cost_cents"]
    project["base_annual_requirement_cents"] = base

    revenue = project["current_annual_revenue_cents"]

    # Step 4 — provisional rate impact.
    project["provisional_rate_impact_pct"] = q2(divide(Decimal(base) * 100, revenue))

    # Step 5 — surcharge tier from the provisional impact.
    project["surcharge_bp"] = surcharge_bp_for(project["provisional_rate_impact_pct"])

    # Step 6 — final annual requirement including the surcharge.
    surcharge = cents(divide(Decimal(base) * project["surcharge_bp"], 10000))
    final = base + surcharge
    project["final_annual_requirement_cents"] = final

    # Step 7 — final rate impact.
    project["rate_impact_pct"] = q2(divide(Decimal(final) * 100, revenue))

    # Bill impact.
    accounts = project["served_account_count"]
    kgal = project["annual_billed_kgal"]
    project["uniform_monthly_increase_cents"] = cents(
        divide(Decimal(final), Decimal(accounts) * C.MONTHS_PER_YEAR)
    )
    volumetric_rate = cents(divide(Decimal(final), kgal))
    project["volumetric_rate_increase_cents_per_kgal"] = volumetric_rate
    project["volumetric_monthly_increase_cents"] = cents(
        divide(Decimal(volumetric_rate) * divide(kgal, accounts), C.MONTHS_PER_YEAR)
    )
    if project["rate_design"] == "VOLUMETRIC":
        project["monthly_bill_increase_cents"] = project["volumetric_monthly_increase_cents"]
    else:
        project["monthly_bill_increase_cents"] = project["uniform_monthly_increase_cents"]

    project["funding_status"] = derive_funding_status(project)
    return project


def forgiveness_pct_for(program, disadvantaged):
    if program == "EC_GRANT":
        return Decimal("100.00")
    if program == "BIL_SUPPLEMENTAL":
        return Decimal("100.00") if disadvantaged else Decimal("25.00")
    return Decimal("49.00") if disadvantaged else Decimal("0.00")


def allocate_recovery(claim, project, recovered):
    """Waterfall in fixed order; the four buckets always sum to recovered."""
    remaining = recovered
    investigation_cap = max(0, claim["investigation_cost_cents"])
    alloc_investigation = min(remaining, investigation_cap)
    remaining -= alloc_investigation

    capital_cap = max(0, project["local_share_cents"])
    alloc_capital = min(remaining, capital_cap)
    remaining -= alloc_capital

    reserve_cap = max(
        0, cents(divide(Decimal(project["annual_om_cost_cents"]) * C.OM_RESERVE_PCT, 100))
    )
    alloc_reserve = min(remaining, reserve_cap)
    remaining -= alloc_reserve

    return alloc_investigation, alloc_capital, alloc_reserve, remaining
