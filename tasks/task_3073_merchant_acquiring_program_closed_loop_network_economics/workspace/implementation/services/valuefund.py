"""Annual fee statements, the value fund and the append-only ledger (PRD §3.6)."""

from decimal import Decimal

from errors import ERR_INVALID_STATE, ApiError
from services import pricing

VALUE_FUND_SHARE_BPS = 4000
LOUNGE_PASS_COST_CENTS = 3500


def assess(store, statement):
    if statement["statement_status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE)
    statement["statement_status"] = "ASSESSED"
    statement["gross_fee_assessed_cents"] = (
        statement["principal_fee_cents"]
        + statement["authorised_user_count"] * statement["per_user_fee_cents"])
    # The assessed allocation applies the configured share to the full gross fee,
    # including the principal portion.
    statement["value_fund_allocation_cents"] = pricing.apply_bps(
        statement["gross_fee_assessed_cents"], VALUE_FUND_SHARE_BPS)
    statement["version"] = statement["version"] + 1
    statement["updated_at"] = store.clock.now()
    return statement


def disbursed_allocation_cents(statement):
    """The DISBURSED variant: the share applies to the per-authorised-user
    portion only.  The principal fee is retained as network revenue, so this
    differs from the assessed allocation by exactly
    round_half_up(principal_fee_cents * VALUE_FUND_SHARE_BPS / 10000)."""
    per_user_total = statement["authorised_user_count"] * statement["per_user_fee_cents"]
    return pricing.apply_bps(per_user_total, VALUE_FUND_SHARE_BPS)


def disburse(store, statement):
    if statement["statement_status"] != "ASSESSED":
        raise ApiError(ERR_INVALID_STATE)
    statement["statement_status"] = "DISBURSED"
    amount = disbursed_allocation_cents(statement)
    _write_entry(store, statement, "FEE_ALLOCATION", amount)
    _fund_member_rewards(store, statement, amount)
    statement["version"] = statement["version"] + 1
    statement["updated_at"] = store.clock.now()
    return statement


def void(store, statement):
    if statement["statement_status"] != "ASSESSED":
        raise ApiError(ERR_INVALID_STATE)
    statement["statement_status"] = "VOIDED"
    # Equal magnitude to the entry the statement would have produced.
    amount = disbursed_allocation_cents(statement)
    _write_entry(store, statement, "FEE_ALLOCATION_REVERSAL", -amount)
    statement["version"] = statement["version"] + 1
    statement["updated_at"] = store.clock.now()
    return statement


def grant_lounge_pass(store, member, pass_count):
    entry = _append_entry(store, member["id"], None, "LOUNGE_PASS_GRANT", 0)
    return entry


def _write_entry(store, statement, entry_kind, amount_cents):
    return _append_entry(store, statement["cardmember_id"], statement["id"],
                         entry_kind, amount_cents)


def _append_entry(store, cardmember_id, source_statement_id, entry_kind, amount_cents):
    entry_id = store.new_id()
    now = store.clock.now()
    seq = store.next_created_seq()
    entry = {
        "id": entry_id,
        "created_at": now,
        "updated_at": now,
        "version": 0,
        "_seq": seq,
        "source_statement_id": source_statement_id,
        "entry_kind": entry_kind,
        "amount_cents": amount_cents,
        "created_seq": seq,
        "_cardmember_id": cardmember_id,
    }
    store.value_fund_ledger_entries[entry_id] = entry
    return entry


def _fund_member_rewards(store, statement, amount_cents):
    member = store.cardmembers.get(statement["cardmember_id"])
    if member is None:
        return
    points = pricing.round_half_up(Decimal(amount_cents) / Decimal(100))
    member["reward_points_balance"] = member["reward_points_balance"] + points
    member["version"] = member["version"] + 1
    member["updated_at"] = store.clock.now()