"""Resource serialisation.

Derived fields are part of every resource representation and are returned on
reads as well as on writes (PRD 2.12).  Reads recompute the roll-ups they
report without advancing the stored version.
"""

import calc
import db


def project_view(project):
    project["contract_value_cents"] = calc.settled_contract_value_cents(project)
    project["total_bid_cents"] = calc.total_bid_cents(project)
    project["unbalanced_bid_score"] = float(calc.unbalanced_bid_score(project))
    project["dbe_participation_pct"] = calc.dbe_participation_pct(project)
    reconciliation = calc.latest_reconciliation(project)
    if reconciliation is not None:
        project["retention_balance_cents"] = (
            reconciliation["retention_held_cents"] - reconciliation["retention_released_cents"]
        )
    else:
        project["retention_balance_cents"] = calc.retention_held_cents(project)
    project["claim_window_open"] = (project["project_status"] == "ACTIVE")
    return db.public(project)


def item_view(item):
    measured, variance, renegotiation = calc.item_ledger(item)
    item["measured_quantity"] = float(measured)
    item["variance_pct"] = calc.f2(variance)
    item["renegotiation_required"] = bool(renegotiation)
    return db.public(item)


def quote_view(quote):
    quote["dbe_credit_cents"] = calc.quote_dbe_credit_cents(quote)
    quote["carried_in_bid"] = quote["quote_status"] in ("CARRIED", "SELECTED")
    return db.public(quote)


def bond_view(bond):
    project = db.find("project", bond["project_id"])
    if project is not None:
        bond["required_bond_cents"] = calc.required_bond_cents(bond, project)
        bond["lien_claim_amount_cents"] = calc.lien_claim_amount_cents(bond, project)
    bond["capacity_consumed_cents"] = (
        bond["bond_amount_cents"] if bond["bond_status"] in ("ISSUED", "EXECUTED") else 0
    )
    return db.public(bond)


def surety_view(surety):
    consumed = calc.surety_consumed_cents(surety)
    surety["capacity_consumed_cents"] = consumed
    surety["available_capacity_cents"] = max(0, surety["aggregate_capacity_cents"] - consumed)
    surety["unavailable_capacity_cents"] = consumed
    return db.public(surety)


def commitment_view(commitment):
    return db.public(commitment)


def measurement_view(measurement):
    if measurement["measurement_status"] in ("APPROVED", "PAYABLE"):
        measurement["payable_amount_cents"] = calc.payable_amount_cents(
            measurement, measurement["applied_unit_price_cents"])
    return db.public(measurement)


def reconciliation_view(reconciliation):
    project = db.find("project", reconciliation["project_id"])
    if project is not None and reconciliation["reconciliation_status"] != "CLOSED":
        overrun, underrun = calc.variance_counts(project)
        reconciliation["overrun_item_count"] = overrun
        reconciliation["underrun_item_count"] = underrun
        reconciliation["net_adjustment_cents"] = calc.net_adjustment_cents(project)
        reconciliation["final_contract_value_cents"] = (
            calc.awarded_value_cents(project) + reconciliation["net_adjustment_cents"]
        )
        reconciliation["retention_held_cents"] = calc.retention_held_cents(project)
        reconciliation["pace_basis_retention_cents"] = calc.pace_basis_retention_cents(project)
        reconciliation["retention_released_cents"] = 0
    return db.public(reconciliation)


def condition_view(condition):
    condition["notice_days_elapsed"] = calc.notice_days_elapsed(condition)
    return db.public(condition)


def determination_view(determination):
    determination["entitles_adjustment"] = determination["determination_type"] in (
        "COST_EQUITABLE_ADJUSTMENT", "QUANTITY_ADJUSTMENT")
    return db.public(determination)
