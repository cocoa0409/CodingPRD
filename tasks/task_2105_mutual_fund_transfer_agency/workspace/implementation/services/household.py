"""Rights-of-accumulation households and breakpoint tier selection."""
from decimal import Decimal

import clock
import dates
import db
from constants import ACCOUNT_PARTICIPATING
from money import ZERO, q2, q4
from services import positions as positions_service


def primary_of(account):
    link = account.get("linked_primary_account_id")
    if not link:
        return account
    primary = db.store.accounts.get(link)
    return primary if primary is not None else account


def members(account):
    """The account's household: its primary plus every account linked into it."""
    primary = primary_of(account)
    household = [primary]
    for other in db.store.accounts.values():
        if other["id"] == primary["id"]:
            continue
        if other.get("linked_primary_account_id") == primary["id"]:
            household.append(other)
    return household


def compute_basis(account, on_date):
    """roa_household_basis under the account's own basis variant.

    on_date is an ISO YYYY-MM-DD string: the trade_date when a trade is being
    priced, otherwise the logical clock date."""
    variant = account["household_basis_variant"]
    total = ZERO
    for member in members(account):
        if member["status"] not in ACCOUNT_PARTICIPATING:
            continue
        for position in positions_service.for_account(member["id"]):
            if position["shares"] <= 0:
                continue
            if variant == "MARKET_VALUE_BASIS":
                price = positions_service.latest_price(position["share_class_id"], on_date)
                if price is None:
                    total += position["cost_basis_amount"]
                else:
                    total += q2(position["shares"] * price)
            else:
                total += position["cost_basis_amount"]
    return q2(total)


def tier_pct(share_class, qualifying_amount):
    chosen = None
    for tier in share_class["breakpoint_tiers"]:
        if tier["min_qualifying_amount"] <= qualifying_amount:
            if chosen is None or tier["min_qualifying_amount"] >= chosen["min_qualifying_amount"]:
                chosen = tier
    if chosen is None:
        return Decimal("0.0000")
    return q4(chosen["load_pct"])


def refresh_tiers(account):
    for position in positions_service.for_account(account["id"]):
        share_class = db.store.share_classes.get(position["share_class_id"])
        if share_class is None:
            continue
        db.set_field(
            position,
            "current_roa_tier_pct",
            tier_pct(share_class, account["household_basis_amount"]),
        )


def recompute(account):
    """Recompute the household basis of every member and every member position's tier."""
    if account is None:
        return
    on_date = dates.fmt_date(clock.today())
    for member in members(account):
        db.set_field(member, "household_basis_amount", compute_basis(member, on_date))
        refresh_tiers(member)


def recompute_many(accounts):
    seen = set()
    for account in accounts:
        if account is None or account["id"] in seen:
            continue
        for member in members(account):
            seen.add(member["id"])
        recompute(account)
