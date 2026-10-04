"""The seven-step clock sweep, applied once per crossed day boundary + at target.

Order pinned by PRD 2.4:
  1. posting availability (incl. DORMANT reactivation)
  2. disaster expiry (FIFO unspent)
  3. expungement notices + expungement (incl. DORMANT cascade, card deactivation)
  4. card mailing
  5. provisional-credit auto-issuance
  6. settlement cutoff batches + daily transaction files
  7. monthly integrity reports
"""
from datetime import timedelta

from state import DB
from domain import (
    touch, post_entry, ledger_balance, fifo_unspent, case_purses, case_postings,
    purse_program, contract_of_purse, claim_target_purse, case_cards,
    new_entity,
)
from state import new_id


# ------------------------------------------------------------------ helpers
def _contract_cases(contract_id):
    return [c for c in DB.cases.values() if c["contract_id"] == contract_id]


def _contract_purses(contract_id):
    ids = {c["id"] for c in _contract_cases(contract_id)}
    return [p for p in DB.purses.values() if p["case_account_id"] in ids]


def _contract_txns(contract_id):
    rids = {r["id"] for r in DB.retailers.values() if r["contract_id"] == contract_id}
    return [t for t in DB.txns.values() if t["retailer_id"] in rids]


def _contract_claims(contract_id):
    ids = {c["id"] for c in _contract_cases(contract_id)}
    return [c for c in DB.claims.values() if c["case_account_id"] in ids]


def _month_start(dt):
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _add_month(m):
    year, month = m.year, m.month + 1
    if month > 12:
        year, month = year + 1, 1
    return m.replace(year=year, month=month)


# ------------------------------------------------------------------ steps 1-5
def step1_availability(now):
    postings = [p for p in DB.postings.values() if p["posting_status"] == "SCHEDULED"]
    postings.sort(key=lambda p: (p["available_at"], p["created_at"], p["_seq"]))
    for posting in postings:
        if now < posting["available_at"]:
            continue
        purse = DB.purses[posting["purse_id"]]
        if purse["purse_status"] == "CLOSED":
            posting["posting_status"] = "FORFEITED"
            posting["resolved_at"] = now
            touch(posting)
            post_entry(purse["id"], "FORFEIT_DEBIT", posting["amount_cents"],
                       posting_id=posting["id"], memo="forfeiture", at=now)
            continue
        posting["posting_status"] = "AVAILABLE"
        posting["_reached_available"] = True
        touch(posting)
        case = DB.cases[purse["case_account_id"]]
        if case["account_status"] == "DORMANT":
            case["account_status"] = "OPEN"
            touch(case)


def step2_disaster_expiry(now):
    postings = [p for p in DB.postings.values() if p["posting_status"] == "AVAILABLE"]
    postings.sort(key=lambda p: (p["available_at"], p["created_at"], p["_seq"]))
    for posting in postings:
        purse = DB.purses[posting["purse_id"]]
        prog = purse_program(purse)
        if prog is None or prog["program_type"] != "DISASTER":
            continue
        contract = DB.contracts[prog["contract_id"]]
        days = prog["disaster_expiry_days"] if prog["disaster_expiry_days"] is not None \
            else contract["default_disaster_expiry_days"]
        if now < posting["available_at"] + timedelta(days=days):
            continue
        unspent = fifo_unspent(purse["id"], posting)
        posting["posting_status"] = "EXPIRED"
        posting["resolved_at"] = now
        touch(posting)
        if unspent > 0:
            post_entry(purse["id"], "EXPIRY_DEBIT", unspent,
                       posting_id=posting["id"], memo="disaster expiry", at=now)


def step3_expungement(now):
    touched_cases = []
    purses = sorted(DB.purses.values(), key=lambda p: p["_seq"])
    for purse in purses:
        if purse["purse_status"] == "CLOSED":
            continue
        prog = purse_program(purse)
        if prog is None or prog["program_type"] not in ("FOOD", "CASH"):
            continue
        if purse["last_activity_at"] is None:
            continue
        contract = DB.contracts[prog["contract_id"]]
        inactivity = prog["expungement_inactivity_days"] \
            if prog["expungement_inactivity_days"] is not None \
            else contract["default_expungement_inactivity_days"]
        lead = contract["expungement_notice_lead_days"]
        eligible_at = purse["last_activity_at"] + timedelta(days=inactivity)
        notice_at = eligible_at - timedelta(days=lead)
        if purse["expungement_notice_sent_at"] is None and notice_at <= now < eligible_at:
            purse["expungement_notice_sent_at"] = now
            touch(purse)
        if now >= eligible_at:
            for posting in DB.postings.values():
                if posting["purse_id"] == purse["id"] and posting["posting_status"] == "AVAILABLE":
                    posting["posting_status"] = "EXPUNGED"
                    posting["resolved_at"] = now
                    touch(posting)
            balance = ledger_balance(purse["id"])
            if balance > 0:
                post_entry(purse["id"], "EXPUNGE_DEBIT", balance,
                           memo="expungement sweep", at=now)
            elif purse["expungement_notice_sent_at"] is not None:
                purse["expungement_notice_sent_at"] = None
                touch(purse)
            touched_cases.append(purse["case_account_id"])
    # Dormancy cascade
    for case_id in touched_cases:
        case = DB.cases[case_id]
        if case["account_status"] != "OPEN":
            continue
        purses_of_case = case_purses(case_id)
        if any(ledger_balance(p["id"]) != 0 for p in purses_of_case):
            continue
        if any(pp["posting_status"] in ("SCHEDULED", "AVAILABLE")
               for pp in case_postings(case_id)):
            continue
        case["account_status"] = "DORMANT"
        touch(case)
        for card in case_cards(case_id):
            if card["card_status"] in ("ISSUED", "MAILED", "ACTIVE", "PIN_LOCKED"):
                card["card_status"] = "DEACTIVATED"
                touch(card)


def step4_card_mailing(now):
    for card in sorted(DB.cards.values(), key=lambda c: c["_seq"]):
        if card["card_status"] != "ISSUED":
            continue
        case = DB.cases[card["case_account_id"]]
        contract = DB.contracts[case["contract_id"]]
        delay = contract["card_mail_delay_hours"]
        if now >= card["created_at"] + timedelta(hours=delay):
            card["card_status"] = "MAILED"
            card["mailed_at"] = now
            touch(card)


def step5_provisional_credit(now):
    claims = [c for c in DB.claims.values()
              if c["investigation_status"] == "UNDER_INVESTIGATION"
              and c["credit_status"] == "NONE"
              and c["investigated_at"] is not None]
    claims.sort(key=lambda c: c["_seq"])
    for claim in claims:
        case = DB.cases[claim["case_account_id"]]
        contract = DB.contracts[case["contract_id"]]
        due = claim["investigated_at"] + timedelta(days=contract["provisional_credit_delay_days"])
        if now < due:
            continue
        amount = min(claim["claimed_amount_cents"], contract["provisional_credit_cap_cents"])
        purse = claim_target_purse(claim)
        if purse is not None and amount > 0:
            post_entry(purse["id"], "PROVISIONAL_CREDIT", amount,
                       reference_id=claim["id"], memo="provisional credit", at=now)
        claim["provisional_credit_cents"] = amount
        claim["provisional_credited_at"] = now
        claim["credit_status"] = "PROVISIONAL"
        touch(claim)


# ------------------------------------------------------------------ step 6
def _settle_contract_boundary(contract, boundary, now):
    """Close the settlement day [boundary-24h, boundary) for one contract."""
    from domain import ser_batch  # noqa: F401  (kept local to avoid cycles)
    cutoff_prev = boundary - timedelta(days=1)
    rids = {r["id"]: r for r in DB.retailers.values()
            if r["contract_id"] == contract["id"]}
    txns = [t for t in DB.txns.values()
            if t["retailer_id"] in rids
            and t["txn_status"] == "AUTHORIZED"
            and cutoff_prev <= t["created_at"] < boundary]
    txns.sort(key=lambda t: (t["created_at"], t["_seq"]))
    bp = contract["acquirer_fee_basis_points"]
    by_acquirer = {}
    for t in txns:
        by_acquirer.setdefault(rids[t["retailer_id"]]["acquirer_reference"], []).append(t)
    for acquirer, group in sorted(by_acquirer.items()):
        gross = sum(t["total_cents"] for t in group)
        fee = sum(_round_half_up(t["total_cents"] * bp, 10000) for t in group)
        batch = new_entity()
        batch.update({
            "contract_id": contract["id"],
            "acquirer_reference": acquirer,
            "settlement_date": cutoff_prev.date(),
            "cutoff_at": boundary,
            "batch_status": "CUTOFF",
            "gross_settled_cents": gross,
            "txn_count": len(group),
            "acquirer_fee_cents": fee,
            "settled_authorization_ids": [t["id"] for t in group],
            "actual_settled_cents": None,
            "reconciled_at": None,
        })
        DB.batches[batch["id"]] = batch
        for t in group:
            t["txn_status"] = "SETTLED"
            t["batch_id"] = batch["id"]
            touch(t)
    # Daily transaction file (per contract per closed settlement day)
    delivery = new_entity()
    delivery.update({
        "contract_id": contract["id"],
        "delivery_type": "DAILY_TRANSACTION_FILE",
        "period": cutoff_prev.date().isoformat(),
        "delivery_status": "DELIVERED",
        "txn_count": len(txns),
        "settled_food_cents": sum(t["food_charge_cents"] for t in txns),
        "settled_cash_cents": sum(t["cash_charge_cents"] for t in txns),
        "expunged_cents": None,
        "expired_cents": None,
        "substantiated_claims_count": None,
        "provisional_credits_outstanding_cents": None,
        "retailer_suspensions_count": None,
        "lenient_exceptions_count": None,
    })
    DB.deliveries[delivery["id"]] = delivery


def _round_half_up(numer, denom):
    from decimal import Decimal, ROUND_HALF_UP
    return int((Decimal(numer) / Decimal(denom)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def step6_settlement(now):
    for contract in sorted(DB.contracts.values(), key=lambda c: c["_seq"]):
        cursor = contract["_last_cutoff"]
        while cursor + timedelta(days=1) <= now:
            boundary = cursor + timedelta(days=1)
            _settle_contract_boundary(contract, boundary, now)
            contract["_last_cutoff"] = boundary
            cursor = boundary


# ------------------------------------------------------------------ step 7
def _monthly_report(contract, month_start, month_end):
    purse_ids = {p["id"] for p in _contract_purses(contract["id"])}
    entries = [e for e in DB.entries.values()
               if e["purse_id"] in purse_ids
               and month_start <= e["created_at"] < month_end]
    claims = _contract_claims(contract["id"])
    retailers = [r for r in DB.retailers.values() if r["contract_id"] == contract["id"]]
    txns = _contract_txns(contract["id"])
    delivery = new_entity()
    delivery.update({
        "contract_id": contract["id"],
        "delivery_type": "MONTHLY_INTEGRITY_REPORT",
        "period": f"{month_start.year:04d}-{month_start.month:02d}",
        "delivery_status": "DELIVERED",
        "txn_count": None,
        "settled_food_cents": None,
        "settled_cash_cents": None,
        "expunged_cents": sum(e["amount_cents"] for e in entries
                              if e["entry_type"] == "EXPUNGE_DEBIT"),
        "expired_cents": sum(e["amount_cents"] for e in entries
                             if e["entry_type"] == "EXPIRY_DEBIT"),
        "substantiated_claims_count": sum(
            1 for c in claims
            if c["investigation_status"] == "SUBSTANTIATED"
            and c["decided_at"] is not None
            and month_start <= c["decided_at"] < month_end),
        "provisional_credits_outstanding_cents": sum(
            c["provisional_credit_cents"] for c in claims
            if c["credit_status"] == "PROVISIONAL"),
        "retailer_suspensions_count": sum(
            1 for r in retailers
            if r.get("_suspended_at") is not None
            and month_start <= r["_suspended_at"] < month_end),
        "lenient_exceptions_count": sum(
            t["exception_flag_count"] for t in txns
            if month_start <= t["created_at"] < month_end),
    })
    DB.deliveries[delivery["id"]] = delivery


def step7_reports(now):
    for contract in sorted(DB.contracts.values(), key=lambda c: c["_seq"]):
        cursor = contract["_last_month"]
        while _add_month(cursor) <= now:
            nxt = _add_month(cursor)
            _monthly_report(contract, cursor, nxt)
            contract["_last_month"] = nxt
            cursor = nxt


# ------------------------------------------------------------------ driver
def run_sweep(old, new):
    """Apply the full pipeline once per crossed day boundary, then at `new`.

    Day boundaries are the union of every contract's settlement-cutoff
    boundaries (each contract's cutoff hour, per day) in (old, new]."""
    instants = set()
    for contract in DB.contracts.values():
        cursor = contract["_last_cutoff"]
        while cursor + timedelta(days=1) <= new:
            cursor = cursor + timedelta(days=1)
            if cursor > old:
                instants.add(cursor)
    instants.add(new)
    for instant in sorted(instants):
        step1_availability(instant)
        step2_disaster_expiry(instant)
        step3_expungement(instant)
        step4_card_mailing(instant)
        step5_provisional_credit(instant)
        step6_settlement(instant)
        step7_reports(instant)
