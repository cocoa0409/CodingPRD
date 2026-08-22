"""Resource serialisation with the declared numeric precisions."""
import db
from money import num

MONEY = 2
SHARES = 3
PRICE = 4
PCT = 4


def _common(record, versioned=True):
    db.flush()
    out = {"id": record["id"], "created_at": record["created_at"]}
    if versioned:
        out["updated_at"] = record["updated_at"]
        out["version"] = record["version"]
    return out


def fund(record):
    out = {
        "name": record["name"],
        "fund_family_code": record["fund_family_code"],
        "cutoff_time_utc": record["cutoff_time_utc"],
        "status": record["status"],
    }
    out.update(_common(record))
    return out


def share_class(record):
    out = {
        "fund_id": record["fund_id"],
        "class_code": record["class_code"],
        "seed_nav_per_share": num(record["seed_nav_per_share"], PRICE),
        "breakpoint_tiers": [
            {
                "min_qualifying_amount": num(tier["min_qualifying_amount"], MONEY),
                "load_pct": num(tier["load_pct"], PCT),
            }
            for tier in record["breakpoint_tiers"]
        ],
        "cdsc_enabled": record["cdsc_enabled"],
        "twelve_b_one_fee_pct": num(record["twelve_b_one_fee_pct"], PCT),
        "total_shares_outstanding": num(record["total_shares_outstanding"], SHARES),
    }
    out.update(_common(record))
    return out


def account(record):
    out = {
        "registration_type": record["registration_type"],
        "account_channel": record["account_channel"],
        "state_code": record["state_code"],
        "tax_id": record["tax_id"],
        "primary_owner_name": record["primary_owner_name"],
        "dealer_firm_code": record["dealer_firm_code"],
        "dividend_option": record["dividend_option"],
        "linked_primary_account_id": record["linked_primary_account_id"],
        "tin_certified": record["tin_certified"],
        "status": record["status"],
        "restriction_reason": record["restriction_reason"],
        "household_basis_amount": num(record["household_basis_amount"], MONEY),
        "household_basis_variant": record["household_basis_variant"],
        "closed_at": record["closed_at"],
    }
    out.update(_common(record))
    return out


def position(record):
    import services.positions as positions_service

    out = {
        "account_id": record["account_id"],
        "share_class_id": record["share_class_id"],
        "shares": num(record["shares"], SHARES),
        "cost_basis_amount": num(record["cost_basis_amount"], MONEY),
        "reinvested_shares": num(record["reinvested_shares"], SHARES),
        "avg_cost_per_share": num(positions_service.avg_cost_per_share(record), PRICE),
        "first_purchase_date": record["first_purchase_date"],
        "current_roa_tier_pct": num(record["current_roa_tier_pct"], PCT),
        "market_value_amount": num(positions_service.market_value_amount(record), MONEY),
    }
    out.update(_common(record))
    return out


def nav_record(record):
    out = {
        "share_class_id": record["share_class_id"],
        "valuation_date": record["valuation_date"],
        "total_net_assets": num(record["total_net_assets"], MONEY),
        "shares_outstanding_snapshot": num(record["shares_outstanding_snapshot"], SHARES),
        "nav_per_share": num(record["nav_per_share"], PRICE),
        "original_nav_per_share": num(record["original_nav_per_share"], PRICE),
        "status": record["status"],
        "finalized_at": record["finalized_at"],
    }
    out.update(_common(record))
    return out


def trade(record):
    out = {
        "account_id": record["account_id"],
        "share_class_id": record["share_class_id"],
        "exchange_target_share_class_id": record["exchange_target_share_class_id"],
        "parent_distribution_id": record["parent_distribution_id"],
        "originating_plan_id": record["originating_plan_id"],
        "blue_sky_registration_id": record["blue_sky_registration_id"],
        "trade_type": record["trade_type"],
        "gross_amount": num(record["gross_amount"], MONEY),
        "shares_requested": num(record["shares_requested"], SHARES),
        "as_of_date": record["as_of_date"],
        "dealer_reference": record["dealer_reference"],
        "received_at": record["received_at"],
        "trade_date": record["trade_date"],
        "execution_status": record["execution_status"],
        "settlement_status": record["settlement_status"],
        "pricing_variant": record["pricing_variant"],
        "nav_per_share_applied": num(record["nav_per_share_applied"], PRICE),
        "roa_qualifying_amount": num(record["roa_qualifying_amount"], MONEY),
        "roa_basis_variant": record["roa_basis_variant"],
        "sales_load_pct": num(record["sales_load_pct"], PCT),
        "sales_load_amount": num(record["sales_load_amount"], MONEY),
        "net_invested_amount": num(record["net_invested_amount"], MONEY),
        "shares_transacted": num(record["shares_transacted"], SHARES),
        "gross_proceeds_amount": num(record["gross_proceeds_amount"], MONEY),
        "cdsc_amount": num(record["cdsc_amount"], MONEY),
        "net_proceeds_amount": num(record["net_proceeds_amount"], MONEY),
        "exchange_target_shares": num(record["exchange_target_shares"], SHARES),
        "restated_share_delta": num(record["restated_share_delta"], SHARES),
        "captured_by_user_id": record["captured_by_user_id"],
        "approved_by_user_id": record["approved_by_user_id"],
        "cancel_reason": record["cancel_reason"],
        "reversal_reason": record["reversal_reason"],
    }
    out.update(_common(record))
    return out


def distribution(record):
    out = {
        "share_class_id": record["share_class_id"],
        "distribution_type": record["distribution_type"],
        "rate_per_share": num(record["rate_per_share"], PRICE),
        "record_date": record["record_date"],
        "ex_date": record["ex_date"],
        "pay_date": record["pay_date"],
        "status": record["status"],
        "payment_count": record["payment_count"],
        "total_gross_amount": num(record["total_gross_amount"], MONEY),
        "total_withholding_amount": num(record["total_withholding_amount"], MONEY),
        "total_cash_amount": num(record["total_cash_amount"], MONEY),
        "total_reinvested_amount": num(record["total_reinvested_amount"], MONEY),
        "reinvest_nav_per_share": num(record["reinvest_nav_per_share"], PRICE),
    }
    out.update(_common(record))
    return out


def payment(record):
    out = {
        "distribution_id": record["distribution_id"],
        "account_id": record["account_id"],
        "position_id": record["position_id"],
        "reinvestment_trade_id": record["reinvestment_trade_id"],
        "shares_of_record": num(record["shares_of_record"], SHARES),
        "gross_amount": num(record["gross_amount"], MONEY),
        "withholding_amount": num(record["withholding_amount"], MONEY),
        "net_amount": num(record["net_amount"], MONEY),
        "cash_amount": num(record["cash_amount"], MONEY),
        "reinvested_shares": num(record["reinvested_shares"], SHARES),
        "payout_option": record["payout_option"],
        "status": record["status"],
    }
    out.update(_common(record))
    return out


def plan(record):
    out = {
        "account_id": record["account_id"],
        "source_share_class_id": record["source_share_class_id"],
        "target_share_class_id": record["target_share_class_id"],
        "plan_type": record["plan_type"],
        "amount": num(record["amount"], MONEY),
        "frequency": record["frequency"],
        "next_run_date": record["next_run_date"],
        "status": record["status"],
        "executed_count": record["executed_count"],
        "last_run_date": record["last_run_date"],
        "suspension_reason": record["suspension_reason"],
    }
    out.update(_common(record))
    return out


def registration(record):
    out = {
        "share_class_id": record["share_class_id"],
        "state_code": record["state_code"],
        "registered_amount": num(record["registered_amount"], MONEY),
        "effective_date": record["effective_date"],
        "expiration_date": record["expiration_date"],
        "reserved_amount": num(record["reserved_amount"], MONEY),
        "consumed_amount": num(record["consumed_amount"], MONEY),
        "remaining_amount": num(
            record["registered_amount"] - record["reserved_amount"] - record["consumed_amount"],
            MONEY,
        ),
        "status": record["status"],
    }
    out.update(_common(record))
    return out


def case(record):
    out = {
        "nav_record_id": record["nav_record_id"],
        "corrected_nav_per_share": num(record["corrected_nav_per_share"], PRICE),
        "error_reason": record["error_reason"],
        "original_nav_per_share": num(record["original_nav_per_share"], PRICE),
        "error_bps": num(record["error_bps"], MONEY),
        "materiality": record["materiality"],
        "status": record["status"],
        "detected_by_user_id": record["detected_by_user_id"],
        "approved_by_user_id": record["approved_by_user_id"],
        "reprocessed_by_user_id": record["reprocessed_by_user_id"],
        "restated_trade_count": record["restated_trade_count"],
        "invalidated_nav_record_count": record["invalidated_nav_record_count"],
    }
    out.update(_common(record))
    return out


def reconciliation(record):
    out = {
        "account_id": record["account_id"],
        "as_of_date": record["as_of_date"],
        "dealer_reported_purchase_amount": num(record["dealer_reported_purchase_amount"], MONEY),
        "dealer_reported_redemption_amount": num(record["dealer_reported_redemption_amount"], MONEY),
        "dealer_reported_net_shares": num(record["dealer_reported_net_shares"], SHARES),
        "ta_purchase_amount": num(record["ta_purchase_amount"], MONEY),
        "ta_redemption_amount": num(record["ta_redemption_amount"], MONEY),
        "ta_net_shares": num(record["ta_net_shares"], SHARES),
        "break_amount": num(record["break_amount"], MONEY),
        "tolerance_amount": num(record["tolerance_amount"], MONEY),
        "status": record["status"],
        "adjustment_trade_id": record["adjustment_trade_id"],
        "resolution_note": record["resolution_note"],
        "dispute_note": record["dispute_note"],
    }
    out.update(_common(record))
    return out


def ledger_entry(record):
    out = {
        "position_id": record["position_id"],
        "trade_id": record["trade_id"],
        "share_delta": num(record["share_delta"], SHARES),
        "entry_reason": record["entry_reason"],
        "effective_date": record["effective_date"],
        "resulting_share_balance": num(record["resulting_share_balance"], SHARES),
    }
    out.update(_common(record, versioned=False))
    return out
