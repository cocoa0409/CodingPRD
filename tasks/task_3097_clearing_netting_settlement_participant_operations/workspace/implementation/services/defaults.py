"""Default management: declaration, auction, liquidation and loss allocation.

Calculations (SCAFFOLD section 1.3):
  default_liquidation_and_loss  - Vickrey second-price silent auction
  loss_allocation_waterfall     - pro rata over CURRENT component balances
  loss_allocation_remainder_repair - pairing term returned to the largest balance
"""

from decimal import Decimal, ROUND_HALF_UP

from db import db, new_ledger_row, new_record, touch
from errors import (
    api_error,
    ERR_CLEARING_FUND_DEFICIT,
    ERR_INVALID_STATE,
    ERR_NO_ALLOCATABLE_DEFICIT,
    ERR_PROCEEDING_NOT_LIQUIDATING,
)
from lookups import net_positions_of_participant
from services.deposit import posted_amount_cents
from services.funds import refresh_fund_totals
from services.netting import auto_close_open_windows

ONE = Decimal("1")


def declare(participant, reason_code):
    record = new_record(
        participant_id=participant["id"],
        reason_code=reason_code,
        status="DECLARED",
        liquidation_proceeds_cents=0,
        deficit_amount_cents=0,
        defaulter_resources_cents=0,
        allocated_total_cents=0,
    )
    db.default_proceedings[record["id"]] = record
    return record


def advance(proceeding, reason_code=None):
    """Move a DECLARED proceeding to LIQUIDATING so the auction may be run."""
    if proceeding["status"] != "DECLARED":
        raise api_error(ERR_PROCEEDING_NOT_LIQUIDATING)
    if reason_code is not None:
        proceeding["reason_code"] = reason_code
    proceeding["status"] = "LIQUIDATING"
    touch(proceeding)
    return proceeding


# ---------------------------------------------------------------------------
# Sealed-bid auction
# ---------------------------------------------------------------------------
def bid_sort_key(bid):
    participant = db.participants.get(bid["participant_id"])
    legal_name = participant["legal_name"] if participant else ""
    return (-bid["bid_price_cents"], bid["placed_at"], legal_name)


def open_bids(proceeding_id):
    rows = [
        bid for bid in db.bids.values()
        if bid["default_proceeding_id"] == proceeding_id and not bid["withdrawn"]
    ]
    rows.sort(key=bid_sort_key)
    return rows


def place_bid(proceeding, participant_id, bid_price_cents, quantity, placed_at,
              fund_component_id):
    record = new_record(
        default_proceeding_id=proceeding["id"],
        participant_id=participant_id,
        bid_price_cents=bid_price_cents,
        quantity=quantity,
        placed_at=placed_at,
        fund_component_id=fund_component_id,
        withdrawn=False,
    )
    db.bids[record["id"]] = record
    _refresh_reservations(proceeding["id"])
    return record


def _refresh_reservations(proceeding_id):
    """Only the standing high bid keeps a reservation; the rest are released."""
    rows = open_bids(proceeding_id)
    standing = rows[0] if rows else None
    for bid in db.bids.values():
        if bid["default_proceeding_id"] != proceeding_id:
            continue
        component = db.fund_components.get(bid["fund_component_id"])
        if component is None:
            continue
        if standing is not None and bid["id"] == standing["id"]:
            component["reserved_cents"] = min(
                bid["bid_price_cents"], component["component_balance_cents"]
            )
        else:
            component["reserved_cents"] = 0


def auction_proceeds(proceeding_id):
    """Vickrey second-price settlement over the non-withdrawn sealed bids."""
    rows = open_bids(proceeding_id)
    if not rows:
        return 0
    if len(rows) == 1:
        return rows[0]["bid_price_cents"] * rows[0]["quantity"]
    prices = []
    for bid in rows:
        if bid["bid_price_cents"] not in prices:
            prices.append(bid["bid_price_cents"])
    prices.sort(reverse=True)
    uniform_price = prices[1] if len(prices) > 1 else prices[0]
    return uniform_price * rows[0]["quantity"]


def defaulter_resources(participant_id):
    """Posted deposit balance, saturating at the member's full obligations."""
    deposit = None
    for candidate in db.deposits.values():
        if candidate["participant_id"] == participant_id:
            deposit = candidate
            break
    if deposit is None:
        return 0
    balance = posted_amount_cents(deposit)
    obligations = sum(
        np["settlement_obligation_cents"]
        for np in net_positions_of_participant(participant_id)
    )
    return min(balance, obligations)


def liquidate(proceeding):
    if proceeding["status"] != "LIQUIDATING":
        raise api_error(ERR_PROCEEDING_NOT_LIQUIDATING)
    participant = db.participants[proceeding["participant_id"]]

    proceeds = auction_proceeds(proceeding["id"])
    resources = defaulter_resources(participant["id"])
    loss = resources - proceeds
    deficit = max(loss, 0)

    proceeding["liquidation_proceeds_cents"] = proceeds
    proceeding["defaulter_resources_cents"] = resources
    proceeding["deficit_amount_cents"] = deficit

    involved_funds = []
    for component in db.fund_components.values():
        if component["participant_id"] != participant["id"]:
            continue
        component["status"] = "RELEASED"
        component["reserved_cents"] = 0
        touch(component)
        if component["clearing_fund_id"] not in involved_funds:
            involved_funds.append(component["clearing_fund_id"])

    proceeding["status"] = "LIQUIDATED"
    touch(proceeding)

    for fund_id in involved_funds:
        fund = db.clearing_funds.get(fund_id)
        if fund is not None:
            refresh_fund_totals(fund)
            touch(fund)

    participant["membership_status"] = "EXPELLED"
    touch(participant)

    auto_close_open_windows()
    return proceeding


# ---------------------------------------------------------------------------
# Loss allocation
# ---------------------------------------------------------------------------
def candidates(participant_class, defaulter_id):
    """Non-RELEASED components of the class, excluding the defaulter.

    Each surviving participant is represented by its latest component on the
    class's funds; a participant with no non-RELEASED component is excluded.
    """
    entries = []
    for component in db.fund_components.values():
        if component["status"] == "RELEASED":
            continue
        if component["participant_id"] == defaulter_id:
            continue
        fund = db.clearing_funds.get(component["clearing_fund_id"])
        if fund is None or fund["participant_class"] != participant_class:
            continue
        existing = None
        for entry in entries:
            if entry["participant_id"] == component["participant_id"]:
                existing = entry
                break
        if existing is None:
            entries.append(
                {
                    "participant_id": component["participant_id"],
                    "component": component,
                }
            )
        elif component["created_at"] > existing["component"]["created_at"]:
            existing["component"] = component
    def order_key(entry):
        participant = db.participants.get(entry["participant_id"])
        legal_name = participant["legal_name"] if participant else ""
        return (entry["component"]["created_at"], legal_name)

    entries.sort(key=order_key)
    return entries


def allocate_loss(proceeding):
    if proceeding["status"] != "LIQUIDATED":
        raise api_error(ERR_INVALID_STATE)
    deficit = proceeding["deficit_amount_cents"]
    if deficit <= 0:
        raise api_error(ERR_NO_ALLOCATABLE_DEFICIT)

    participant = db.participants[proceeding["participant_id"]]
    entries = candidates(participant["participant_class"], participant["id"])
    total_balance = sum(entry["component"]["component_balance_cents"] for entry in entries)
    if total_balance <= 0:
        raise api_error(ERR_CLEARING_FUND_DEFICIT)

    debits = []
    for entry in entries:
        component = entry["component"]
        share = (
            Decimal(deficit) * Decimal(component["component_balance_cents"])
            / Decimal(total_balance)
        ).quantize(ONE, rounding=ROUND_HALF_UP)
        debits.append((-int(share), component))

    correction = (-deficit) - sum(amount for amount, _ in debits)

    # The correction is posted on the single component with the largest
    # post-debit balance; ties break on legal_name ASC then created_at ASC.
    largest = max(
        component["component_balance_cents"] + amount for amount, component in debits
    )
    target_index = None
    target_key = None
    for index, (amount, component) in enumerate(debits):
        post_debit = component["component_balance_cents"] + amount
        if post_debit != largest:
            continue
        owner = db.participants.get(component["participant_id"])
        legal_name = owner["legal_name"] if owner else ""
        key = (legal_name, component["created_at"])
        if target_key is None or key < target_key:
            target_key = key
            target_index = index

    rows = []
    for index, (amount, component) in enumerate(debits):
        final = amount + correction if index == target_index else amount
        component["component_balance_cents"] = component["component_balance_cents"] + final
        if component["component_balance_cents"] == 0:
            component["status"] = "RELEASED"
        else:
            component["status"] = "ASSESSED"
        touch(component)
        rows.append((final, component))

    posted_at = db.now_iso()
    for amount, component in rows:
        record = new_ledger_row(
            default_proceeding_id=proceeding["id"],
            fund_component_id=component["id"],
            amount_cents=amount,
            posted_at=posted_at,
        )
        db.loss_allocations[record["id"]] = record

    involved_funds = []
    for _amount, component in rows:
        if component["clearing_fund_id"] not in involved_funds:
            involved_funds.append(component["clearing_fund_id"])
    for fund_id in involved_funds:
        fund = db.clearing_funds.get(fund_id)
        if fund is not None:
            refresh_fund_totals(fund)
            touch(fund)

    proceeding["allocated_total_cents"] = deficit
    proceeding["status"] = "ALLOCATED"
    touch(proceeding)

    participant["membership_status"] = "EXPELLED"
    touch(participant)
    return proceeding