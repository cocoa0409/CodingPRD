"""Resource views: the exact JSON shape each entity exposes.

Field names come from SCAFFOLD.yaml `entities` and PRD sections 2.4/2.6.  The
common field set (id, created_at, updated_at, version) is present on all
sixteen resource types; the PortfolioLedger singleton carries it too.
"""

from store import store
from calc import (component_allocation, car_is_enrolled, program_cost,
                  lessee_outstanding)


def _base(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def car_type(row):
    out = _base(row)
    out.update({
        "model_code": row["model_code"],
        "car_class": row["car_class"],
        "build_hours": row["build_hours"],
        "regulatory_life_years": row["regulatory_life_years"],
        "line_count_family": row["line_count_family"],
        "status": row["status"],
    })
    return out


def component(row):
    out = _base(row)
    reserved, shortfall = component_allocation(row)
    out.update({
        "part_number": row["part_number"],
        "component_class": row["component_class"],
        "unit_cost_cents": row["unit_cost_cents"],
        "lead_time_days": row["lead_time_days"],
        "on_hand_qty": row["on_hand_qty"],
        "reserved_qty": reserved,
        "shortfall_qty": shortfall,
    })
    return out


def bom_row(row):
    out = _base(row)
    out.update({
        "car_type_id": row["car_type_id"],
        "component_id": row["component_id"],
        "qty_per_car": row["qty_per_car"],
    })
    return out


def production_order(row):
    out = _base(row)
    out.update({
        "car_type_id": row["car_type_id"],
        "quantity": row["quantity"],
        "completed_qty": row["completed_qty"],
        "unit_price_cents": row["unit_price_cents"],
        "planned_shop_days": row["planned_shop_days"],
        "disposition": row["disposition"],
        "priority_rank": row["priority_rank"],
        "order_date": row["order_date"],
        "required_delivery_date": row["required_delivery_date"],
        "status": row["status"],
        "supersedes_production_order_id": row.get("supersedes_production_order_id"),
        "retention_reason": row.get("retention_reason"),
        "lessee_id": row.get("lessee_id"),
    })
    return out


def endorsement(row):
    out = _base(row)
    out.update({
        "production_order_id": row["production_order_id"],
        "original_component_id": row["original_component_id"],
        "substitute_component_id": row["substitute_component_id"],
        "substitute_qty_per_car": row["substitute_qty_per_car"],
        "status": row["status"],
        "decides_material": row["decides_material"],
        "created_by_user_id": row.get("created_by_user_id"),
    })
    return out


def lease_contract(row):
    out = _base(row)
    out.update({
        "lessee_id": row["lessee_id"],
        "lease_type": row["lease_type"],
        "per_diem_rate_cents": row["per_diem_rate_cents"],
        "liability_bearer": row["liability_bearer"],
        "term_start_date": row["term_start_date"],
        "term_end_date": row["term_end_date"],
        "status": row["status"],
        "amendment_seq": row["amendment_seq"],
        "capital_allocation_cents": row["capital_allocation_cents"],
        "fleet_car_cap": row["fleet_car_cap"],
        "draft_per_diem_rate_cents": row.get("draft_per_diem_rate_cents"),
        "draft_liability_bearer": row.get("draft_liability_bearer"),
    })
    return out


def lessee(row):
    out = _base(row)
    out.update({
        "legal_name": row["legal_name"],
        "credit_tier": row["credit_tier"],
        "utilization_threshold_pct": row["utilization_threshold_pct"],
        "credit_ceiling_cents": row["credit_ceiling_cents"],
        "outstanding_balance_cents": row["outstanding_balance_cents"],
        "status": row["status"],
    })
    return out


def fleet_car(row):
    out = _base(row)
    out.update({
        "car_type_id": row["car_type_id"],
        "production_order_id": row.get("production_order_id"),
        "lease_contract_id": row.get("lease_contract_id"),
        "acquisition_cost_cents": row["acquisition_cost_cents"],
        "accumulated_mileage": row.get("accumulated_mileage", 0),
        "status": row["status"],
        "built_date": row["built_date"],
        "regulatory_life_end_date": row.get("regulatory_life_end_date"),
        # stored flag: PRD section 3.8 has the program-start and work-order
        # writes set it directly, and the named re-derivations refresh it.
        "retrofit_required": bool(row.get("retrofit_required")),
    })
    return out


def car_assignment(row):
    out = _base(row)
    out.update({
        "lease_fleet_car_id": row["lease_fleet_car_id"],
        "lease_contract_id": row["lease_contract_id"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "per_diem_rate_cents": row["per_diem_rate_cents"],
        "mileage_allowance": row["mileage_allowance"],
        "mileage_used": row["mileage_used"],
        "per_diem_accrued_cents": row["per_diem_accrued_cents"],
        "mileage_charge_cents": row["mileage_charge_cents"],
        "maintenance_cost_cents": row["maintenance_cost_cents"],
        "status": row["status"],
    })
    return out


def car_return(row):
    out = _base(row)
    out.update({
        "lease_fleet_car_id": row["lease_fleet_car_id"],
        "car_assignment_id": row["car_assignment_id"],
        "return_date": row["return_date"],
        "mileage_since_last": row["mileage_since_last"],
        "condition_grade": row["condition_grade"],
        "maintenance_parts_cents": row["maintenance_parts_cents"],
        "mileage_overage_cents": row["mileage_overage_cents"],
        "settlement_status": row["settlement_status"],
    })
    return out


def retrofit_program(row):
    out = _base(row)
    out.update({
        "mandate_code": row["mandate_code"],
        "description": row["description"],
        "compliance_deadline_date": row["compliance_deadline_date"],
        "required_shop_days_per_car": row["required_shop_days_per_car"],
        "required_component_id": row.get("required_component_id"),
        "program_cost_cents": program_cost(row),
        "status": row["status"],
    })
    return out


def program_car_type(row):
    out = _base(row)
    out.update({
        "retrofit_program_id": row["retrofit_program_id"],
        "car_type_id": row["car_type_id"],
    })
    return out


def retrofit_work_order(row):
    out = _base(row)
    out.update({
        "retrofit_program_id": row["retrofit_program_id"],
        "lease_fleet_car_id": row["lease_fleet_car_id"],
        "shop_line": row["shop_line"],
        "scheduled_start_date": row["scheduled_start_date"],
        "scheduled_end_date": row["scheduled_end_date"],
        "shop_days": row["shop_days"],
        "component_qty_consumed": row["component_qty_consumed"],
        "status": row["status"],
    })
    return out


def purchase_order(row):
    out = _base(row)
    out.update({
        "component_id": row["component_id"],
        "qty_ordered": row["qty_ordered"],
        "unit_cost_cents": row["unit_cost_cents"],
        "order_date": row["order_date"],
        "expected_receipt_date": row["expected_receipt_date"],
        "status": row["status"],
    })
    return out


def component_receipt(row):
    out = _base(row)
    out.update({
        "component_purchase_order_id": row["component_purchase_order_id"],
        "component_id": row["component_id"],
        "qty_received": row["qty_received"],
        "receipt_date": row["receipt_date"],
    })
    return out


def fleet_sale(row):
    out = _base(row)
    out.update({
        "lease_fleet_car_id": row["lease_fleet_car_id"],
        "lease_contract_id": row.get("lease_contract_id"),
        "lessee_id": row.get("lessee_id"),
        "buyer_name": row["buyer_name"],
        "sale_price_cents": row["sale_price_cents"],
        "net_book_value_cents": row["net_book_value_cents"],
        "writeback_liability_cents": row["writeback_liability_cents"],
        "sale_date": row["sale_date"],
        "status": row["status"],
        "gain_loss_cents": row["gain_loss_cents"],
    })
    return out


def portfolio_ledger(row):
    from calc import fleet_nbv_cents
    out = _base(row)
    out.update({
        "status": row["status"],
        "committed_capital_cents": row["committed_capital_cents"],
        "realized_gain_cents": row["realized_gain_cents"],
        # derived from scratch: the live fleet's depreciated value moves with
        # the logical clock even when no write has touched the ledger.
        "fleet_nbv_cents": fleet_nbv_cents(),
    })
    return out


def ledger_reconciliation():
    from calc import oldest_basis_cents, fleet_nbv_cents, drift_cents
    ledger = store.ledger
    return {
        "oldest_basis_cents": oldest_basis_cents(),
        "newest_basis_cents": fleet_nbv_cents(),
        "drift_cents": drift_cents(),
        "committed_capital_cents": ledger["committed_capital_cents"],
        "realized_gain_cents": ledger["realized_gain_cents"],
    }


def lessee_balance(lessee_id):
    outstanding, charges, credits = lessee_outstanding(lessee_id)
    return {
        "outstanding_balance_cents": outstanding,
        "settled_charges_cents": charges,
        "credits_applied_cents": credits,
    }


VIEWS = {
    "car_types": car_type,
    "components": component,
    "bom_rows": bom_row,
    "production_orders": production_order,
    "endorsements": endorsement,
    "lease_contracts": lease_contract,
    "lessees": lessee,
    "fleet_cars": fleet_car,
    "car_assignments": car_assignment,
    "car_returns": car_return,
    "retrofit_programs": retrofit_program,
    "program_car_types": program_car_type,
    "retrofit_work_orders": retrofit_work_order,
    "purchase_orders": purchase_order,
    "component_receipts": component_receipt,
    "fleet_sales": fleet_sale,
}


def view(collection, row):
    return VIEWS[collection](row)
