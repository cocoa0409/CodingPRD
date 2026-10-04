"""Multilateral netting.

Calculation `multilateral_netting` (SCAFFOLD section 1.3), net-position convention:

  T = trades of the participant that are LOCKED_IN, on the window's security and
      settlement date, carrying match_status MATCHED or UNRESOLVED
  visited trade_date ASC, tie-break created_at ASC
  signed_qty         += BUY ? +quantity : -quantity
  signed_gross_cents += BUY ? +quantity*trade_price_cents : -quantity*trade_price_cents
  net_quantity                = signed_qty
  cash_delta_cents            = signed_gross_cents
  settlement_obligation_cents = max(cash_delta_cents, 0)
  mark_to_market_cents seed   = signed_gross_cents - signed_qty * prev_settlement_price_cents

No division and no rounding occurs anywhere in this calculation.
"""

from db import db, new_record, touch
from lookups import is_settled_trade, net_positions_of_window, trade_sort_key
from services.deposit import deposit_of_participant, derive_coverage
from services.marks import recompute_marks


def nettable_trades(window, participant_id):
    rows = [
        t for t in db.trade_submissions.values()
        if t["participant_id"] == participant_id
        and t["security_id"] == window["security_id"]
        and t["settlement_date"] == window["settlement_date"]
        and is_settled_trade(t)
    ]
    rows.sort(key=trade_sort_key)
    return rows


def compute_position(window, participant):
    signed_qty = 0
    signed_gross = 0
    for trade in nettable_trades(window, participant["id"]):
        gross = trade["quantity"] * trade["trade_price_cents"]
        if trade["side"] == "BUY":
            signed_qty += trade["quantity"]
            signed_gross += gross
        else:
            signed_qty -= trade["quantity"]
            signed_gross -= gross
    return {
        "net_quantity": signed_qty,
        "cash_delta_cents": signed_gross,
        "settlement_obligation_cents": max(signed_gross, 0),
    }


def qualifying_participants(window):
    """Every ACTIVE participant with at least one settled trade on the window."""
    participant_ids = []
    for trade in db.trade_submissions.values():
        if trade["security_id"] != window["security_id"]:
            continue
        if trade["settlement_date"] != window["settlement_date"]:
            continue
        if not is_settled_trade(trade):
            continue
        participant = db.participants.get(trade["participant_id"])
        if participant is None or participant["membership_status"] != "ACTIVE":
            continue
        if trade["participant_id"] not in participant_ids:
            participant_ids.append(trade["participant_id"])
    return [db.participants[pid] for pid in participant_ids]


def resolve_affirmation(window):
    """Advance every UNCONFIRMED trade for the window's date to AFFIRMED.

    A trade already UNCONFIRMED_BREACH retains that value; a trade already
    AFFIRMED is left unchanged.
    """
    for trade in db.trade_submissions.values():
        if trade["security_id"] != window["security_id"]:
            continue
        if trade["settlement_date"] != window["settlement_date"]:
            continue
        if trade["affirmation_status"] == "UNCONFIRMED":
            trade["affirmation_status"] = "AFFIRMED"
            touch(trade)


def reopen_funds_for_security(security_id):
    """System event: a fresh net position reopens the sizing cycle."""
    for fund in db.clearing_funds.values():
        if fund["security_id"] == security_id:
            fund["status"] = "OPEN"
            touch(fund)


def run_cycle(window, *, reopen_funds=True, resolve=True):
    """Create or replace one net position per qualifying participant."""
    security = db.securities.get(window["security_id"])
    if resolve:
        resolve_affirmation(window)

    existing = {
        row["participant_id"]: row for row in net_positions_of_window(window["id"])
    }
    for participant in qualifying_participants(window):
        computed = compute_position(window, participant)
        quantity = computed["net_quantity"]
        previous = existing.pop(participant["id"], None)
        seed = (
            computed["cash_delta_cents"]
            - quantity * security["prev_settlement_price_cents"]
        )
        if previous is not None:
            previous["net_quantity"] = quantity
            previous["cash_delta_cents"] = computed["cash_delta_cents"]
            previous["settlement_obligation_cents"] = computed["settlement_obligation_cents"]
            if previous["dvp_status"] != "FAILED":
                previous["mark_to_market_cents"] = seed
            touch(previous)
        else:
            record = new_record(
                window_id=window["id"],
                participant_id=participant["id"],
                security_id=window["security_id"],
                net_quantity=quantity,
                cash_delta_cents=computed["cash_delta_cents"],
                settlement_obligation_cents=computed["settlement_obligation_cents"],
                dvp_status="FUNDED",
                funded_amount_cents=0,
                failed_at=None,
                failed_at_price_cents=None,
                mark_to_market_cents=seed,
            )
            db.net_positions[record["id"]] = record

    # A participant that no longer qualifies loses its row for this window.
    for stale in existing.values():
        del db.net_positions[stale["id"]]

    rows = net_positions_of_window(window["id"])
    for net_position in rows:
        net_position["settlement_obligation_cents"] = max(
            net_position["cash_delta_cents"], 0
        )
        touch(net_position)

    for participant_id in {row["participant_id"] for row in rows}:
        deposit = deposit_of_participant(participant_id)
        if deposit is not None:
            # deposit_posted_balance: "the cycle-close sweep and the netting run
            # assign this value" - the under-funded standing is assigned here
            # rather than surfaced as an error.
            derive_coverage(deposit)
            touch(deposit)

    if reopen_funds:
        reopen_funds_for_security(window["security_id"])
    return rows


def auto_close_open_windows():
    """System event: no ACTIVE participant remains, so every OPEN window closes."""
    for participant in db.participants.values():
        if participant["membership_status"] == "ACTIVE":
            return
    for window in list(db.settlement_windows.values()):
        if window["status"] != "OPEN":
            continue
        window["status"] = "CLOSED"
        recompute_marks(net_positions_of_window(window["id"]))
        touch(window)