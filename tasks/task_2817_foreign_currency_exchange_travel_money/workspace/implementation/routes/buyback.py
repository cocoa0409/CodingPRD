"""Buy-back guarantees: issuance (a reserve-and-truncate write), redemption and cancellation."""
from datetime import timedelta

from flask import Blueprint

import calc
from core import (
    RATE_LOCK_DAYS,
    S,
    all_rows,
    body,
    clock,
    endpoint,
    fail,
    fmt_dt,
    listing,
    need,
    need_currency,
    new_row,
    ok,
    opt_str,
    parse_note_lines,
    public,
    req_int,
    req_list,
    req_str,
    require_not_frozen,
    require_standard_denominations,
    rhu,
    sort_created_asc,
    store,
    touch,
)

bp = Blueprint("buyback", __name__)

READERS = ("PlatformAdmin", "TreasuryOfficer", "BranchManager", "BranchTeller", "ComplianceOfficer")


@bp.post("/buyback-contracts")
@endpoint(["BranchTeller", "BranchManager"])
def issue_contract():
    b = body()
    customer = need("Customer", req_str(b, "customer_id"))
    origin = need("ExchangeTransaction", req_str(b, "origin_transaction_id"))
    expected_customer_version = req_int(b, "expected_customer_version", minimum=1)
    # rank 5 - at most one contract per origin transaction
    for other in all_rows("BuybackContract"):
        if other["origin_transaction_id"] == origin["id"]:
            fail("ERR_CONTRACT_ALREADY_ISSUED")
    # rank 6
    if expected_customer_version != customer["version"]:
        fail("ERR_STALE_CUSTOMER_VERSION")
    # rank 8
    if customer["compliance_hold_active"]:
        fail("ERR_CUSTOMER_COMPLIANCE_HOLD")
    # rank 11
    profile = need_currency(origin["currency_code"])
    if (
        origin["settlement_status"] != "SETTLED"
        or origin["direction"] != "SELL_FX_TO_CUSTOMER"
        or not profile["buyback_eligible"]
    ):
        fail("ERR_BUYBACK_NOT_ELIGIBLE")

    branch = need("Branch", origin["branch_id"])
    card = need("RateCard", origin["rate_card_id"])
    locked_rate, locked_fx, fee, liability = calc.buyback_pricing(origin, card)

    row = new_row("BuybackContract")
    row["customer_id"] = customer["id"]
    row["branch_id"] = branch["id"]
    row["origin_transaction_id"] = origin["id"]
    row["currency_code"] = origin["currency_code"]
    row["locked_buy_rate_micros"] = locked_rate
    row["locked_fx_minor_units"] = locked_fx
    row["remaining_fx_minor_units"] = locked_fx
    row["fee_usd_cents"] = fee
    row["liability_usd_cents"] = liability
    row["rate_lock_expires_at"] = fmt_dt(clock() + timedelta(days=RATE_LOCK_DAYS))
    row["status"] = "ISSUED"
    row["redemption_count"] = 0
    row["superseded_by_contract_id"] = None
    store(row)

    # the contract row is written first, then the origin's back-pointer
    origin["buyback_contract_id"] = row["id"]
    touch(origin)

    # supersede the customer's incumbent lock in the same currency
    for incumbent in sort_created_asc(all_rows("BuybackContract")):
        if incumbent["id"] == row["id"]:
            continue
        if incumbent["customer_id"] != customer["id"]:
            continue
        if incumbent["currency_code"] != row["currency_code"]:
            continue
        if incumbent["status"] not in ("ISSUED", "PARTIALLY_REDEEMED"):
            continue
        incumbent["status"] = "CANCELLED"
        incumbent["remaining_fx_minor_units"] = 0
        incumbent["liability_usd_cents"] = 0
        incumbent["superseded_by_contract_id"] = row["id"]
        touch(incumbent)
        older_origin = S["ExchangeTransaction"].get(incumbent["origin_transaction_id"])
        if older_origin is not None:
            older_origin["buyback_contract_id"] = None
            touch(older_origin)
        older_branch = S["Branch"].get(incumbent["branch_id"])
        if older_branch is not None:
            calc.reconcile_branch_liability(older_branch)

    calc.reconcile_branch_liability(branch)
    touch(customer)
    return ok(public(row), 201)


@bp.post("/buyback-contracts/<contract_id>/redeem")
@endpoint(["BranchTeller"])
def redeem_contract(contract_id):
    contract = need("BuybackContract", contract_id)
    b = body()
    profile = need_currency(contract["currency_code"])
    lines = parse_note_lines(
        req_list(b, "returned_denominations"), "returned_denominations", min_count=1
    )
    require_standard_denominations(lines, profile, "returned_denominations")
    # rank 5
    if contract["status"] not in ("ISSUED", "PARTIALLY_REDEEMED"):
        fail("ERR_CONTRACT_NOT_REDEEMABLE")
    branch = need("Branch", contract["branch_id"])
    # rank 7
    require_not_frozen(branch)
    returned_total = calc.fx_gross(lines)
    # rank 11
    if returned_total > contract["remaining_fx_minor_units"]:
        fail("ERR_REDEEM_EXCEEDS_REMAINING")
    # rank 12
    calc.require_effective_card(branch["id"], contract["currency_code"], clock())
    # rank 13
    position = calc.branch_position(branch["id"], contract["currency_code"])
    if position is not None:
        projected = calc.projected_vault_after(branch, position, returned_total)
    else:
        projected = branch["vault_usd_equivalent_cents"] + rhu(
            returned_total * 1000000, calc.wholesale_mid(contract["currency_code"])
        )
    if projected > branch["vault_limit_usd_cents"]:
        fail("ERR_VAULT_LIMIT_WOULD_EXCEED")

    contract["remaining_fx_minor_units"] -= returned_total
    contract["redemption_count"] += 1
    if contract["remaining_fx_minor_units"] > 0:
        contract["status"] = "PARTIALLY_REDEEMED"
        contract["liability_usd_cents"] = rhu(
            contract["remaining_fx_minor_units"] * 1000000, contract["locked_buy_rate_micros"]
        )
    else:
        contract["status"] = "REDEEMED"
        contract["remaining_fx_minor_units"] = 0
        contract["liability_usd_cents"] = 0
    touch(contract)
    calc.reconcile_branch_liability(branch)

    if position is not None:
        for line in lines:
            entry = calc.ensure_mix_entry(position, line["denomination_minor_units"])
            entry["available_note_count"] += line["note_count"]
        calc.inventory_cascade(position, branch)
    touch(branch)
    return ok(public(contract))


@bp.post("/buyback-contracts/<contract_id>/cancel")
@endpoint(["BranchManager", "TreasuryOfficer"])
def cancel_contract(contract_id):
    contract = need("BuybackContract", contract_id)
    b = body()
    opt_str(b, "cancellation_reason")
    if contract["status"] not in ("ISSUED", "PARTIALLY_REDEEMED"):
        fail("ERR_CONTRACT_NOT_CANCELLABLE")
    contract["status"] = "CANCELLED"
    contract["remaining_fx_minor_units"] = 0
    contract["liability_usd_cents"] = 0
    touch(contract)
    origin = S["ExchangeTransaction"].get(contract["origin_transaction_id"])
    if origin is not None:
        origin["buyback_contract_id"] = None
        touch(origin)
    branch = S["Branch"].get(contract["branch_id"])
    if branch is not None:
        calc.reconcile_branch_liability(branch)
    return ok(public(contract))


@bp.get("/buyback-contracts/<contract_id>")
@endpoint(READERS)
def read_contract(contract_id):
    return ok(public(need("BuybackContract", contract_id)))


@bp.get("/buyback-contracts")
@endpoint(READERS)
def list_contracts():
    return listing(
        "BuybackContract",
        {
            "customer_id": "customer_id",
            "branch_id": "branch_id",
            "origin_transaction_id": "origin_transaction_id",
            "superseded_by_contract_id": "superseded_by_contract_id",
            "status": "status",
        },
    )
