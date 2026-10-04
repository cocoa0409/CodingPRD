"""Trade submission, comparison and the parallel state dimensions.

Three independent dimensions coexist on one row (PRD 2.6):
  lock_status      OPEN | LOCKED_IN | DISPUTED | CANCELLED
  match_status     UNMATCHED | MATCHED | ALLEGED | UNRESOLVED
  affirmation_status UNCONFIRMED | AFFIRMED | UNCONFIRMED_BREACH
Comparison identity is the five-term tuple (party pair, instrument, opposite
side, exact quantity, exact trade_date); it is the tuple, never the row
identity, that drives matching, disputing, reverting and cancelling as a pair.
"""

from db import db, new_record, touch
from errors import (
    api_error,
    ERR_INVALID_STATE,
    ERR_NOT_MATCHED,
    ERR_TRADE_ENTRY_DEADLINE_PASSED,
    ERR_WINDOW_ALREADY_NETTED,
    ERR_WINDOW_NOT_FOUND,
    ERR_PARTICIPANT_NOT_ACTIVE,
)
from lookups import contras_of, find_window, tuple_rows
from timeutil import instant_lt, normalize_iso, settlement_date_for

SIDES = ("BUY", "SELL")


def apply_comparison(trade, *, cascade_lock=True):
    """Run the comparison sweep for one trade.

    Returns the resolved match_status. Matching propagates across the pair:
    when the trade becomes MATCHED every contra row is also locked in, and
    allegations_received is recomputed on every row the cascade touches.
    """
    counterparty = db.participants.get(trade["counterparty_participant_id"])
    contras = contras_of(trade)
    contra_exists = len(contras) > 0
    counterparty_active = (
        counterparty is not None and counterparty["membership_status"] == "ACTIVE"
    )
    if contra_exists and counterparty_active:
        trade["match_status"] = "MATCHED"
        if cascade_lock:
            for contra in contras:
                contra["lock_status"] = "LOCKED_IN"
                # Matching propagates across the pair: the contra ceases to be
                # UNMATCHED once its counterpart confirms the comparison.
                if contra["match_status"] == "UNMATCHED":
                    contra["match_status"] = "MATCHED"
                touch(contra)
    elif contra_exists and not counterparty_active:
        trade["match_status"] = "ALLEGED"
    else:
        trade["match_status"] = "UNMATCHED"
    recompute_tuple_allegations(trade)
    return trade["match_status"]


def recompute_tuple_allegations(trade):
    """Recompute allegations_received on the trade and on every contra row."""
    trade["allegations_received"] = len(contras_of(trade))
    for contra in contras_of(trade):
        contra["allegations_received"] = len(contras_of(contra))


def set_pair(trade, lock_status, match_status):
    """Apply one dimension pair to the trade and to every non-CANCELLED contra."""
    trade["lock_status"] = lock_status
    trade["match_status"] = match_status
    touch(trade)
    for row in tuple_rows(trade):
        if row["id"] == trade["id"]:
            continue
        row["lock_status"] = lock_status
        row["match_status"] = match_status
        touch(row)
    recompute_tuple_allegations(trade)


def create_trade(participant_id, counterparty_id, security_id, side, quantity,
                 trade_price_cents, trade_date):
    record = new_record(
        participant_id=participant_id,
        counterparty_participant_id=counterparty_id,
        security_id=security_id,
        side=side,
        quantity=quantity,
        trade_price_cents=trade_price_cents,
        trade_date=normalize_iso(trade_date),
        settlement_date=settlement_date_for(trade_date),
        lock_status="OPEN",
        match_status="UNMATCHED",
        affirmation_status="UNCONFIRMED",
        allegations_received=0,
    )
    db.trade_submissions[record["id"]] = record
    # Submission runs the same comparison the lock-in step runs. Creation is
    # the row's first write, so the derived fields are resolved in place and
    # the version stays at its initial value of 1 — a separate touch() here
    # would double-increment it before any client call.
    contras = contras_of(record)
    counterparty = db.participants.get(counterparty_id)
    if contras and counterparty is not None and counterparty["membership_status"] == "ACTIVE":
        record["match_status"] = "MATCHED"
        for contra in contras:
            contra["lock_status"] = "LOCKED_IN"
            if contra["match_status"] == "UNMATCHED":
                contra["match_status"] = "MATCHED"
            touch(contra)
    recompute_tuple_allegations(record)
    return record


def lock_in(trade):
    """PRD 3.3: four gates, in order, then the comparison sweep."""
    if trade["lock_status"] != "OPEN":
        raise api_error(ERR_INVALID_STATE)

    window = find_window(
        trade["security_id"], trade["settlement_date"], only_open=True
    )
    if window is None:
        raise api_error(ERR_WINDOW_NOT_FOUND)

    if not instant_lt(trade["trade_date"], window["trade_entry_deadline"]):
        raise api_error(ERR_TRADE_ENTRY_DEADLINE_PASSED)

    participant = db.participants.get(trade["participant_id"])
    if participant is None or participant["membership_status"] != "ACTIVE":
        raise api_error(ERR_PARTICIPANT_NOT_ACTIVE)

    trade["lock_status"] = "LOCKED_IN"
    apply_comparison(trade, cascade_lock=True)
    touch(trade)
    return trade


def dispute(trade):
    if trade["lock_status"] != "OPEN":
        raise api_error(ERR_INVALID_STATE)
    if trade["match_status"] != "MATCHED":
        raise api_error(ERR_NOT_MATCHED)
    trade["lock_status"] = "DISPUTED"
    trade["match_status"] = "UNRESOLVED"
    touch(trade)
    for contra in contras_of(trade):
        contra["match_status"] = "UNRESOLVED"
        touch(contra)
    recompute_tuple_allegations(trade)
    return trade


def resolve_dispute(trade):
    if trade["lock_status"] != "DISPUTED":
        raise api_error(ERR_INVALID_STATE)
    window = find_window(trade["security_id"], trade["settlement_date"], only_open=True)
    if window is None:
        raise api_error(ERR_WINDOW_NOT_FOUND)
    lower_id = min(trade["participant_id"], trade["counterparty_participant_id"])
    if trade["participant_id"] != lower_id:
        from errors import ERR_DISPUTE_RESOLUTION_NOT_OWNER

        raise api_error(ERR_DISPUTE_RESOLUTION_NOT_OWNER)
    set_pair(trade, "LOCKED_IN", "MATCHED")
    return trade


def unmatch(trade):
    if trade["lock_status"] != "LOCKED_IN":
        raise api_error(ERR_INVALID_STATE)
    window = find_window(trade["security_id"], trade["settlement_date"])
    if window is None or window["status"] != "OPEN":
        raise api_error(ERR_WINDOW_ALREADY_NETTED)
    if trade["match_status"] != "MATCHED":
        raise api_error(ERR_NOT_MATCHED)
    set_pair(trade, "OPEN", "UNMATCHED")
    return trade


def cancel(trade, allow_privileged):
    """PRD 3.4: three entry states, two acting roles, different outcomes."""
    state = trade["lock_status"]
    if state not in ("OPEN", "LOCKED_IN", "DISPUTED"):
        raise api_error(ERR_INVALID_STATE)
    if state in ("LOCKED_IN", "DISPUTED") and not allow_privileged:
        from errors import ERR_UNAUTHORIZED

        raise api_error(ERR_UNAUTHORIZED)
    window = find_window(trade["security_id"], trade["settlement_date"])
    if state in ("LOCKED_IN", "DISPUTED"):
        if window is None or window["status"] != "OPEN":
            raise api_error(ERR_WINDOW_ALREADY_NETTED)
    contras = contras_of(trade)
    trade["lock_status"] = "CANCELLED"
    trade["match_status"] = "UNRESOLVED"
    touch(trade)
    for contra in contras:
        if state == "DISPUTED":
            contra["lock_status"] = "LOCKED_IN"
            contra["match_status"] = "MATCHED"
        else:
            contra["lock_status"] = "OPEN"
            contra["match_status"] = "UNMATCHED"
        touch(contra)
    recompute_tuple_allegations(trade)
    return trade


def affirm(participant_id, security_id, settlement_date):
    """Member self-service affirmation for one security and settlement date."""
    changed = 0
    for trade in db.trade_submissions.values():
        if trade["participant_id"] != participant_id:
            continue
        if trade["security_id"] != security_id:
            continue
        if trade["settlement_date"] != settlement_date:
            continue
        if trade["affirmation_status"] == "UNCONFIRMED":
            trade["affirmation_status"] = "AFFIRMED"
            touch(trade)
            changed += 1
    return changed