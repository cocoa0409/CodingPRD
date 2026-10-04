"""Domain primitives: entity creation, ledger posting, balances, FIFO, serializers."""
from datetime import timedelta, date

import state
from state import DB, new_id, next_seq
from util import iso3, now_dt, iso_date

CREDIT_TYPES = {"POST_CREDIT", "VOID_CREDIT", "PROVISIONAL_CREDIT", "CLAIM_CREDIT"}
DEBIT_TYPES = {
    "PURCHASE_DEBIT", "WITHDRAWAL_DEBIT", "FEE_DEBIT", "FORFEIT_DEBIT",
    "EXPIRY_DEBIT", "EXPUNGE_DEBIT", "PROVISIONAL_REVERSAL_DEBIT",
    "CLAIM_REVERSAL_DEBIT",
}
CONSUMING_TYPES = {"PURCHASE_DEBIT", "WITHDRAWAL_DEBIT", "FEE_DEBIT"}
FAR_FUTURE_DATE = date(9999, 12, 31)


def new_entity():
    now = now_dt()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(e):
    e["updated_at"] = now_dt()
    e["version"] += 1


# ------------------------------------------------------------------ ledger
def post_entry(purse_id, entry_type, amount_cents, posting_id=None,
               reference_id=None, memo=None, at=None):
    e = {
        "id": new_id(),
        "purse_id": purse_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "posting_id": posting_id,
        "reference_id": reference_id,
        "memo": memo,
        "created_at": at if at is not None else now_dt(),
        "_seq": next_seq(),
    }
    DB.entries[e["id"]] = e
    purse = DB.purses[purse_id]
    purse["last_activity_at"] = e["created_at"]
    purse["expungement_notice_sent_at"] = None
    touch(purse)
    return e


def purse_entries(purse_id):
    rows = [e for e in DB.entries.values() if e["purse_id"] == purse_id]
    return sorted(rows, key=lambda e: (e["created_at"], e["_seq"]))


def _signed(e):
    return e["amount_cents"] if e["entry_type"] in CREDIT_TYPES else -e["amount_cents"]


def ledger_balance(purse_id):
    return sum(_signed(e) for e in purse_entries(purse_id))


def spendable_balance(purse_id):
    total = 0
    for e in purse_entries(purse_id):
        if e["entry_type"] == "POST_CREDIT":
            posting = DB.postings.get(e["posting_id"]) if e["posting_id"] else None
            if posting is not None and posting["posting_status"] in ("SCHEDULED", "FORFEITED"):
                continue
        if e["entry_type"] == "FORFEIT_DEBIT":
            continue
        total += _signed(e)
    return total


def fifo_unspent(purse_id, posting):
    """Unspent portion of a posting by FIFO allocation of consuming debits.

    Debits replay in created_at ASC against postings that ever reached AVAILABLE,
    ordered (available_at ASC, created_at ASC)."""
    postings = [p for p in DB.postings.values()
                if p["purse_id"] == purse_id and p.get("_reached_available")]
    postings.sort(key=lambda p: (p["available_at"], p["created_at"], p["_seq"]))
    remaining = {p["id"]: p["amount_cents"] for p in postings}
    debits = [e for e in purse_entries(purse_id) if e["entry_type"] in CONSUMING_TYPES]
    for d in debits:
        amt = d["amount_cents"]
        for p in postings:
            if amt == 0:
                break
            take = min(remaining[p["id"]], amt)
            remaining[p["id"]] -= take
            amt -= take
    return remaining.get(posting["id"], posting["amount_cents"])


# ------------------------------------------------------------------ lookups
def case_purses(case_id):
    return sorted((p for p in DB.purses.values() if p["case_account_id"] == case_id),
                  key=lambda p: p["_seq"])


def purse_program(purse):
    return DB.programs.get(purse["program_id"])


def case_purse_by_type(case_id, program_type, include_closed=False):
    for p in case_purses(case_id):
        prog = purse_program(p)
        if prog and prog["program_type"] == program_type:
            if include_closed or p["purse_status"] != "CLOSED":
                return p
    return None


def contract_of_case(case):
    return DB.contracts.get(case["contract_id"])


def contract_of_purse(purse):
    case = DB.cases.get(purse["case_account_id"])
    return DB.contracts.get(case["contract_id"]) if case else None


def case_postings(case_id):
    out = []
    for p in case_purses(case_id):
        out.extend(pp for pp in DB.postings.values() if pp["purse_id"] == p["id"])
    return out


def case_cards(case_id):
    return sorted((c for c in DB.cards.values() if c["case_account_id"] == case_id),
                  key=lambda c: c["_seq"])


def case_claims(case_id):
    return sorted((c for c in DB.claims.values() if c["case_account_id"] == case_id),
                  key=lambda c: c["_seq"])


def replacements_in_window(case_id):
    cutoff = now_dt() - timedelta(days=365)
    return sum(1 for c in DB.cards.values()
               if c["case_account_id"] == case_id
               and c["replacement_of_card_id"] is not None
               and c["created_at"] >= cutoff)


def item_status(item):
    today = now_dt().date()
    eff_to = item["effective_to"] if item["effective_to"] is not None else FAR_FUTURE_DATE
    return "ACTIVE" if item["effective_from"] <= today < eff_to else "EXPIRED"


def covering_item(retailer_id, upc):
    """The RetailerItem of (retailer_id, upc) covering the current clock date."""
    today = now_dt().date()
    for it in DB.items.values():
        if it["retailer_id"] != retailer_id or it["upc"] != upc:
            continue
        eff_to = it["effective_to"] if it["effective_to"] is not None else FAR_FUTURE_DATE
        if it["effective_from"] <= today < eff_to:
            return it
    return None


def batch_open_disputes(batch_id):
    return [d for d in DB.disputes.values()
            if d["settlement_batch_id"] == batch_id and d["dispute_status"] == "OPEN"]


def batch_adjustment_total(batch_id):
    return sum(d["adjustment_cents"] for d in DB.disputes.values()
               if d["settlement_batch_id"] == batch_id
               and d["dispute_status"] == "UPHELD")


def claim_target_purse(claim):
    txns = [DB.txns.get(t) for t in claim["authorization_ids"]]
    food_sum = sum(t["food_charge_cents"] for t in txns if t)
    cash_sum = sum(t["cash_charge_cents"] for t in txns if t)
    case_id = claim["case_account_id"]
    if cash_sum >= food_sum:
        p = case_purse_by_type(case_id, "CASH", include_closed=True)
        if p is not None:
            return p
        return case_purse_by_type(case_id, "FOOD", include_closed=True)
    p = case_purse_by_type(case_id, "FOOD", include_closed=True)
    if p is not None:
        return p
    return case_purse_by_type(case_id, "CASH", include_closed=True)


# ------------------------------------------------------------------ serializers
def ser_contract(c):
    return {
        "id": c["id"],
        "state_code": c["state_code"],
        "contract_status": c["contract_status"],
        "default_posting_modulus": c["default_posting_modulus"],
        "default_availability_hour_utc": c["default_availability_hour_utc"],
        "default_expungement_inactivity_days": c["default_expungement_inactivity_days"],
        "expungement_notice_lead_days": c["expungement_notice_lead_days"],
        "default_disaster_expiry_days": c["default_disaster_expiry_days"],
        "default_replacement_fee_cents": c["default_replacement_fee_cents"],
        "free_replacements_per_365d": c["free_replacements_per_365d"],
        "pin_max_failures": c["pin_max_failures"],
        "claim_window_days": c["claim_window_days"],
        "provisional_credit_delay_days": c["provisional_credit_delay_days"],
        "provisional_credit_cap_cents": c["provisional_credit_cap_cents"],
        "skimming_suspend_threshold": c["skimming_suspend_threshold"],
        "dispute_window_days": c["dispute_window_days"],
        "acquirer_fee_basis_points": c["acquirer_fee_basis_points"],
        "cash_withdrawal_daily_limit_cents": c["cash_withdrawal_daily_limit_cents"],
        "cash_withdrawal_multiple_cents": c["cash_withdrawal_multiple_cents"],
        "settlement_cutoff_hour_utc": c["settlement_cutoff_hour_utc"],
        "card_mail_delay_hours": c["card_mail_delay_hours"],
        "created_at": iso3(c["created_at"]),
        "updated_at": iso3(c["updated_at"]),
        "version": c["version"],
    }


def ser_program(p):
    return {
        "id": p["id"],
        "contract_id": p["contract_id"],
        "program_type": p["program_type"],
        "program_status": p["program_status"],
        "item_restriction_mode": p["item_restriction_mode"],
        "posting_modulus": p["posting_modulus"],
        "availability_hour_utc": p["availability_hour_utc"],
        "expungement_inactivity_days": p["expungement_inactivity_days"],
        "disaster_expiry_days": p["disaster_expiry_days"],
        "replacement_fee_cents": p["replacement_fee_cents"],
        "disaster_window_start": iso_date(p["disaster_window_start"]),
        "disaster_window_end": iso_date(p["disaster_window_end"]),
        "created_at": iso3(p["created_at"]),
        "updated_at": iso3(p["updated_at"]),
        "version": p["version"],
    }


def ser_retailer(r):
    return {
        "id": r["id"],
        "contract_id": r["contract_id"],
        "retailer_name": r["retailer_name"],
        "acquirer_reference": r["acquirer_reference"],
        "retailer_status": r["retailer_status"],
        "skimming_incident_count": r["skimming_incident_count"],
        "created_at": iso3(r["created_at"]),
        "updated_at": iso3(r["updated_at"]),
        "version": r["version"],
    }


def ser_item(it):
    return {
        "id": it["id"],
        "retailer_id": it["retailer_id"],
        "upc": it["upc"],
        "food_eligible": it["food_eligible"],
        "effective_from": iso_date(it["effective_from"]),
        "effective_to": iso_date(it["effective_to"]),
        "item_status": item_status(it),
        "created_at": iso3(it["created_at"]),
        "updated_at": iso3(it["updated_at"]),
        "version": it["version"],
    }


def ser_case(c):
    return {
        "id": c["id"],
        "contract_id": c["contract_id"],
        "case_identifier": c["case_identifier"],
        "head_of_household_name": c["head_of_household_name"],
        "account_status": c["account_status"],
        "replacements_in_window": replacements_in_window(c["id"]),
        "created_at": iso3(c["created_at"]),
        "updated_at": iso3(c["updated_at"]),
        "version": c["version"],
    }


def ser_purse(p):
    return {
        "id": p["id"],
        "case_account_id": p["case_account_id"],
        "program_id": p["program_id"],
        "purse_status": p["purse_status"],
        "last_activity_at": iso3(p["last_activity_at"]),
        "expungement_notice_sent_at": iso3(p["expungement_notice_sent_at"]),
        "ledger_balance_cents": ledger_balance(p["id"]),
        "spendable_balance_cents": spendable_balance(p["id"]),
        "created_at": iso3(p["created_at"]),
        "updated_at": iso3(p["updated_at"]),
        "version": p["version"],
    }


def ser_entry(e):
    return {
        "id": e["id"],
        "purse_id": e["purse_id"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "posting_id": e["posting_id"],
        "reference_id": e["reference_id"],
        "memo": e["memo"],
        "created_at": iso3(e["created_at"]),
    }


def ser_posting(p):
    return {
        "id": p["id"],
        "purse_id": p["purse_id"],
        "benefit_month": p["benefit_month"],
        "amount_cents": p["amount_cents"],
        "prorated": p["prorated"],
        "scheduled_date": iso_date(p["scheduled_date"]),
        "available_at": iso3(p["available_at"]),
        "posting_status": p["posting_status"],
        "resolved_at": iso3(p["resolved_at"]),
        "created_at": iso3(p["created_at"]),
        "updated_at": iso3(p["updated_at"]),
        "version": p["version"],
    }


def ser_card(c):
    return {
        "id": c["id"],
        "case_account_id": c["case_account_id"],
        "pan_token": c["pan_token"],
        "card_status": c["card_status"],
        "pin_secret": "****" if c["pin_secret"] is not None else None,
        "pin_fail_count": c["pin_fail_count"],
        "replacement_of_card_id": c["replacement_of_card_id"],
        "fee_charged_cents": c["fee_charged_cents"],
        "fee_waived": c["fee_waived"],
        "mailed_at": iso3(c["mailed_at"]),
        "activated_at": iso3(c["activated_at"]),
        "created_at": iso3(c["created_at"]),
        "updated_at": iso3(c["updated_at"]),
        "version": c["version"],
    }


def ser_txn(t):
    return {
        "id": t["id"],
        "retailer_id": t["retailer_id"],
        "case_account_id": t["case_account_id"],
        "card_id": t["card_id"],
        "authorization_type": t["authorization_type"],
        "items": t["items"],
        "withdrawal_amount_cents": t["withdrawal_amount_cents"],
        "food_charge_cents": t["food_charge_cents"],
        "cash_charge_cents": t["cash_charge_cents"],
        "disaster_charge_cents": t["disaster_charge_cents"],
        "total_cents": t["total_cents"],
        "exception_flag_count": t["exception_flag_count"],
        "txn_status": t["txn_status"],
        "batch_id": t["batch_id"],
        "voided_at": iso3(t["voided_at"]),
        "created_at": iso3(t["created_at"]),
        "updated_at": iso3(t["updated_at"]),
        "version": t["version"],
    }


def ser_claim(c):
    return {
        "id": c["id"],
        "case_account_id": c["case_account_id"],
        "card_id": c["card_id"],
        "authorization_ids": c["authorization_ids"],
        "claimed_amount_cents": c["claimed_amount_cents"],
        "incident_description": c["incident_description"],
        "freeze_purse": c["freeze_purse"],
        "investigation_status": c["investigation_status"],
        "credit_status": c["credit_status"],
        "provisional_credit_cents": c["provisional_credit_cents"],
        "provisional_credited_at": iso3(c["provisional_credited_at"]),
        "substantiated_amount_cents": c["substantiated_amount_cents"],
        "filed_by_user_id": c["filed_by_user_id"],
        "filed_by_role": c["filed_by_role"],
        "decided_by_user_id": c["decided_by_user_id"],
        "investigated_at": iso3(c["investigated_at"]),
        "decided_at": iso3(c["decided_at"]),
        "created_at": iso3(c["created_at"]),
        "updated_at": iso3(c["updated_at"]),
        "version": c["version"],
    }


def ser_batch(b):
    adj = batch_adjustment_total(b["id"])
    return {
        "id": b["id"],
        "contract_id": b["contract_id"],
        "acquirer_reference": b["acquirer_reference"],
        "settlement_date": iso_date(b["settlement_date"]),
        "cutoff_at": iso3(b["cutoff_at"]),
        "batch_status": b["batch_status"],
        "gross_settled_cents": b["gross_settled_cents"],
        "txn_count": b["txn_count"],
        "acquirer_fee_cents": b["acquirer_fee_cents"],
        "adjustment_total_cents": adj,
        "net_position_cents": b["gross_settled_cents"] - b["acquirer_fee_cents"] + adj,
        "settled_authorization_ids": list(b["settled_authorization_ids"]),
        "actual_settled_cents": b["actual_settled_cents"],
        "reconciled_at": iso3(b["reconciled_at"]),
        "created_at": iso3(b["created_at"]),
        "updated_at": iso3(b["updated_at"]),
        "version": b["version"],
    }


def ser_dispute(d):
    return {
        "id": d["id"],
        "settlement_batch_id": d["settlement_batch_id"],
        "dispute_type": d["dispute_type"],
        "retailer_id": d["retailer_id"],
        "dispute_status": d["dispute_status"],
        "disputed_amount_cents": d["disputed_amount_cents"],
        "adjustment_cents": d["adjustment_cents"],
        "reason": d["reason"],
        "filed_by_user_id": d["filed_by_user_id"],
        "decided_at": iso3(d["decided_at"]),
        "created_at": iso3(d["created_at"]),
        "updated_at": iso3(d["updated_at"]),
        "version": d["version"],
    }


def ser_delivery(d):
    return {
        "id": d["id"],
        "contract_id": d["contract_id"],
        "delivery_type": d["delivery_type"],
        "period": d["period"],
        "delivery_status": d["delivery_status"],
        "txn_count": d["txn_count"],
        "settled_food_cents": d["settled_food_cents"],
        "settled_cash_cents": d["settled_cash_cents"],
        "expunged_cents": d["expunged_cents"],
        "expired_cents": d["expired_cents"],
        "substantiated_claims_count": d["substantiated_claims_count"],
        "provisional_credits_outstanding_cents": d["provisional_credits_outstanding_cents"],
        "retailer_suspensions_count": d["retailer_suspensions_count"],
        "lenient_exceptions_count": d["lenient_exceptions_count"],
        "created_at": iso3(d["created_at"]),
        "updated_at": iso3(d["updated_at"]),
        "version": d["version"],
    }
