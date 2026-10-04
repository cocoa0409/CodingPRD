"""Entity serializers — expose exactly the scaffold §1.1 fields plus the
common system fields (id, created_at, updated_at, version)."""

import calc
import store
from util import fmt_dt, fmt_dt_echo


def _common(entity):
    return {
        "id": entity["id"],
        "created_at": fmt_dt(entity["created_at"]),
        "updated_at": fmt_dt(entity["updated_at"]),
        "version": entity["version"],
    }


def ser_case(case):
    out = {
        "case_number": case["case_number"],
        "judicial_district": case["judicial_district"],
        "forfeiture_type": case["forfeiture_type"],
        "lead_agency_code": case["lead_agency_code"],
        "status": case["status"],
        "forfeited_at": fmt_dt_echo(case["forfeited_at"]),
        "gross_proceeds_cents": case["gross_proceeds_cents"],
        "auction_fees_cents": case["auction_fees_cents"],
        "lien_payments_cents": case["lien_payments_cents"],
        "cost_reimbursements_cents": case["cost_reimbursements_cents"],
        "sharing_pool_gross_basis_cents": case["sharing_pool_gross_basis_cents"],
        "sharing_pool_net_basis_cents": case["sharing_pool_net_basis_cents"],
        "equitable_shares_paid_cents": case["equitable_shares_paid_cents"],
        "available_proceeds_cents": case["available_proceeds_cents"],
    }
    out.update(_common(case))
    return out


def ser_asset(asset):
    provisional, final = calc.retention_values(
        asset, store.valuations_of_asset(asset["id"])
    )
    out = {
        "seizure_case_id": asset["seizure_case_id"],
        "asset_type": asset["asset_type"],
        "description": asset["description"],
        "seized_on": fmt_dt_echo(asset["seized_on"]),
        "seizure_condition_grade": asset["seizure_condition_grade"],
        "current_condition_grade": asset["current_condition_grade"],
        "appraised_value_cents": asset["appraised_value_cents"],
        "appraised_at": fmt_dt_echo(asset["appraised_at"]),
        "accumulated_net_holding_cost_cents": asset["accumulated_net_holding_cost_cents"],
        "custody_state": asset["custody_state"],
        "legal_state": asset["legal_state"],
        "retention_decision": asset["retention_decision"],
        "provisional_net_retention_value_cents": provisional,
        "final_net_retention_value_cents": final,
        "returned_at": fmt_dt_echo(asset["returned_at"]),
        "computed_depreciation_cents": asset["computed_depreciation_cents"],
        "dispute_claimed_depreciation_cents": asset["dispute_claimed_depreciation_cents"],
        "final_depreciation_cents": asset["final_depreciation_cents"],
    }
    out.update(_common(asset))
    return out


def ser_transfer(transfer):
    out = {
        "asset_id": transfer["asset_id"],
        "from_location_ref": transfer["from_location_ref"],
        "to_location_ref": transfer["to_location_ref"],
        "to_location_kind": transfer["to_location_kind"],
        "window_start": fmt_dt_echo(transfer["window_start"]),
        "window_end": fmt_dt_echo(transfer["window_end"]),
        "status": transfer["status"],
        "condition_on_arrival": transfer["condition_on_arrival"],
    }
    out.update(_common(transfer))
    return out


def ser_valuation(valuation):
    out = {
        "asset_id": valuation["asset_id"],
        "method": valuation["method"],
        "raw_value_cents": valuation["raw_value_cents"],
        "assessed_condition_grade": valuation["assessed_condition_grade"],
        "annual_net_revenues_cents": valuation["annual_net_revenues_cents"],
        "adjusted_value_cents": valuation["adjusted_value_cents"],
        "status": valuation["status"],
        "submitted_by_user_id": valuation["submitted_by_user_id"],
    }
    out.update(_common(valuation))
    return out


def ser_expense(entry):
    out = {
        "asset_id": entry["asset_id"],
        "entry_kind": entry["entry_kind"],
        "expense_type": entry["expense_type"],
        "amount_cents": entry["amount_cents"],
        "incurred_on": fmt_dt_echo(entry["incurred_on"]),
        "source": entry["source"],
        "posted_by_user_id": entry["posted_by_user_id"],
    }
    out.update(_common(entry))
    return out


def ser_isr(isr):
    out = {
        "asset_id": isr["asset_id"],
        "justification": isr["justification"],
        "requested_by_user_id": isr["requested_by_user_id"],
        "status": isr["status"],
        "adjudicated_by_user_id": isr["adjudicated_by_user_id"],
        "accumulated_costs_snapshot_cents": isr["accumulated_costs_snapshot_cents"],
        "projected_burden_cents": isr["projected_burden_cents"],
        "appraised_value_snapshot_cents": isr["appraised_value_snapshot_cents"],
    }
    out.update(_common(isr))
    return out


def ser_interest(interest):
    out = {
        "asset_id": interest["asset_id"],
        "kind": interest["kind"],
        "petitioner_ref": interest["petitioner_ref"],
        "lienholder_name": interest["lienholder_name"],
        "amount_cents": interest["amount_cents"],
        "priority_position": interest["priority_position"],
        "status": interest["status"],
        "appeal_count": interest["appeal_count"],
        "satisfied_amount_cents": interest["satisfied_amount_cents"],
        "adjudicated_by_user_id": interest["adjudicated_by_user_id"],
    }
    out.update(_common(interest))
    return out


def ser_sale(sale):
    out = {
        "asset_id": sale["asset_id"],
        "sale_method": sale["sale_method"],
        "auctioneer_ref": sale["auctioneer_ref"],
        "slot_start": fmt_dt_echo(sale["slot_start"]),
        "slot_end": fmt_dt_echo(sale["slot_end"]),
        "reserve_price_cents": sale["reserve_price_cents"],
        "winning_bid_cents": sale["winning_bid_cents"],
        "gross_proceeds_cents": sale["gross_proceeds_cents"],
        "auction_fee_cents": sale["auction_fee_cents"],
        "net_proceeds_cents": sale["net_proceeds_cents"],
        "status": sale["status"],
    }
    out.update(_common(sale))
    return out


def ser_distribution(distribution):
    out = {
        "seizure_case_id": distribution["seizure_case_id"],
        "distribution_kind": distribution["distribution_kind"],
        "payee_ref": distribution["payee_ref"],
        "amount_cents": distribution["amount_cents"],
        "usage_restriction": distribution["usage_restriction"],
        "status": distribution["status"],
        "created_by_user_id": distribution["created_by_user_id"],
        "approved_by_user_id": distribution["approved_by_user_id"],
    }
    out.update(_common(distribution))
    return out
