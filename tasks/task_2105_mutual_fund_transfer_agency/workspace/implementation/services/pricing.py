"""Trade pricing: breakpoints/rights of accumulation, CDSC waterfall, exchanges."""
from decimal import Decimal

import dates
import db
from constants import (CDSC_FREE_ALLOWANCE_PCT, CDSC_TIER_1_DAYS, CDSC_TIER_1_PCT,
                       CDSC_TIER_2_DAYS, CDSC_TIER_2_PCT, CDSC_TIER_3_PCT)
from money import q2, q3
from services import household, positions as positions_service


def price_purchase(trade, share_class, nav):
    """calculation purchase_trade_pricing -- the tier is never re-derived."""
    account = db.store.accounts[trade["account_id"]]
    basis = household.compute_basis(account, trade["trade_date"])
    qualifying = q2(basis + trade["gross_amount"])
    load_pct = household.tier_pct(share_class, qualifying)
    load_amount = q2(trade["gross_amount"] * load_pct)
    net_invested = q2(trade["gross_amount"] - load_amount)
    shares = q3(net_invested / nav)

    trade["roa_qualifying_amount"] = qualifying
    trade["roa_basis_variant"] = account["household_basis_variant"]
    trade["sales_load_pct"] = load_pct
    trade["sales_load_amount"] = load_amount
    trade["net_invested_amount"] = net_invested
    trade["shares_transacted"] = shares
    trade["gross_proceeds_amount"] = None
    trade["cdsc_amount"] = None
    trade["net_proceeds_amount"] = None
    trade["exchange_target_shares"] = None


def cdsc_pct_for(holding_days):
    if holding_days < CDSC_TIER_1_DAYS:
        return CDSC_TIER_1_PCT
    if holding_days < CDSC_TIER_2_DAYS:
        return CDSC_TIER_2_PCT
    return CDSC_TIER_3_PCT


def price_redemption(trade, share_class, nav):
    """calculation redemption_proceeds_with_cdsc."""
    position = positions_service.find(trade["account_id"], trade["share_class_id"])
    gross_proceeds = q2(trade["shares_requested"] * nav)

    if not share_class["cdsc_enabled"] or position is None or not position["first_purchase_date"]:
        cdsc = Decimal("0.00")
    else:
        first = dates.parse_date(position["first_purchase_date"])
        trade_date = dates.parse_date(trade["trade_date"])
        holding_days = (trade_date - first).days
        pct = cdsc_pct_for(holding_days)
        free_allowance = q3(position["shares"] * CDSC_FREE_ALLOWANCE_PCT)
        reinvest_exclusion = min(position["reinvested_shares"], trade["shares_requested"])
        chargeable = trade["shares_requested"] - free_allowance - reinvest_exclusion
        if chargeable < 0:
            chargeable = Decimal("0.000")
        charge_basis = min(positions_service.avg_cost_per_share(position), nav)
        cdsc = q2(chargeable * charge_basis * pct)

    trade["gross_proceeds_amount"] = gross_proceeds
    trade["cdsc_amount"] = cdsc
    trade["net_proceeds_amount"] = q2(gross_proceeds - cdsc)
    trade["shares_transacted"] = q3(-1 * trade["shares_requested"])
    trade["sales_load_pct"] = None
    trade["sales_load_amount"] = None
    trade["net_invested_amount"] = None
    trade["exchange_target_shares"] = None


def price_exchange(trade, source_class, target_class, source_nav, target_nav):
    """calculation exchange_settlement_pricing."""
    account = db.store.accounts[trade["account_id"]]
    gross_proceeds = q2(trade["shares_requested"] * source_nav)

    if source_class["fund_id"] == target_class["fund_id"]:
        target_load_pct = Decimal("0.0000")
        trade["roa_qualifying_amount"] = None
        trade["roa_basis_variant"] = None
    else:
        qualifying = q2(account["household_basis_amount"] + gross_proceeds)
        target_load_pct = household.tier_pct(target_class, qualifying)
        trade["roa_qualifying_amount"] = qualifying
        trade["roa_basis_variant"] = account["household_basis_variant"]

    load_amount = q2(gross_proceeds * target_load_pct)

    trade["gross_proceeds_amount"] = gross_proceeds
    trade["cdsc_amount"] = Decimal("0.00")
    trade["net_proceeds_amount"] = gross_proceeds
    trade["sales_load_pct"] = target_load_pct
    trade["sales_load_amount"] = load_amount
    trade["net_invested_amount"] = None
    trade["exchange_target_shares"] = q3((gross_proceeds - load_amount) / target_nav)
    trade["shares_transacted"] = q3(-1 * trade["shares_requested"])


def clear_pricing_fields(trade):
    for field in ("pricing_variant", "nav_per_share_applied", "sales_load_pct",
                  "sales_load_amount", "net_invested_amount", "shares_transacted",
                  "roa_qualifying_amount", "roa_basis_variant"):
        trade[field] = None
