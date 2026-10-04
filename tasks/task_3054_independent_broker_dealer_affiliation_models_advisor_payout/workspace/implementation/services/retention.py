"""TransitionRecord and AccountRetention services (PRD 3.8)."""

from db import (account_retentions, accounts, clock_dt, clock_is_set, iso_now,
                new_id, next_created_seq, payout_periods, transition_records)
from errors import dec, fail, round_half_up
from services import accounts as account_service
from services import advisors as advisor_service
from services import calc, common

CONTEST_STATUSES = ("FROZEN", "PENDING_TRANSFER", "RETENTION_CONTESTED")


def serialize_transition(row):
    derive(row)
    return {key: value for key, value in row.items() if not key.startswith("_")}


def serialize_retention(row):
    return {key: value for key, value in row.items() if not key.startswith("_")}


def find_transition_or_fail(transition_id):
    row = transition_records.get(transition_id)
    if row is None:
        fail("ERR_NOT_FOUND")
    return row


def rows_of(transition_id):
    return [row for row in account_retentions.values()
            if row["transition_record_id"] == transition_id]


def find_retention_or_fail(retention_id):
    row = account_retentions.get(retention_id)
    if row is None:
        fail("ERR_NOT_FOUND")
    return row


# ---------------------------------------------------------------------------
# Derived fields
# ---------------------------------------------------------------------------

def derive(transition):
    advisor_code = transition["advisor_code"]
    if transition["status"] == "CONTESTED":
        transition["accounts_retained_count"] = sum(
            1 for row in accounts.values()
            if row["advisor_code"] == advisor_code and row["status"] == "RETENTION_CONTESTED")
    settled = 0
    for row in rows_of(transition["id"]):
        if row["status"] == "VOID":
            continue
        settled += int(row.get("credit_amount_cents") or 0)
    # retention_credit_cents records the contest credit granted to the advisor
    # and settled_amount_cents is the same book credit excluding VOID rows.
    transition["settled_amount_cents"] = settled
    transition["retention_credit_cents"] = settled
    transition["retention_ratio_bps"] = calc.retention_ratio_bps(
        transition.get("accounts_retained_count") or 0,
        transition.get("accounts_in_contest_count") or 0)
    return transition


# ---------------------------------------------------------------------------
# POST /transitions  (AdvisorOps, BranchManager)
# ---------------------------------------------------------------------------

def create(data):
    advisor_code = common.require_field(data, "advisor_code")
    period_id = common.require_field(data, "payout_period_id")
    common.required_version(data, "expected_advisor_version")
    if not clock_is_set():
        fail("ERR_CLOCK_NOT_SET")
    advisor = advisor_service.get_by_code_or_fail(advisor_code)
    common.check_occ(advisor, "expected_advisor_version", data.get("expected_advisor_version"))
    if payout_periods.get(period_id) is None:
        fail("ERR_NOT_FOUND")
    if int(advisor.get("outstanding_loan_balance_cents") or 0) != 0:
        fail("ERR_LOAN_BALANCE_OUTSTANDING")

    # The accounts the contest can actually reach are those the book transfer has
    # released into the transfer window, so the contest book is counted from
    # that population (PRD 3.8).
    contestable = [row for row in accounts.values()
                   if row["advisor_code"] == advisor_code
                   and row["status"] == "PENDING_TRANSFER"]
    if advisor["status"] == "DEPARTING" and contestable:
        status = "CONTESTED"
    else:
        status = "PENDING"
    row = {
        "id": new_id(),
        "created_at": iso_now(),
        "updated_at": iso_now(),
        "version": 1,
        "_seq": next_created_seq(),
        "advisor_code": advisor_code,
        "payout_period_id": period_id,
        "retention_credit_cents": 0,
        "accounts_in_contest_count": len(contestable),
        "accounts_retained_count": 0,
        "settled_amount_cents": 0,
        "retention_ratio_bps": 0,
        "status": status,
    }
    transition_records[row["id"]] = row
    advisor["retention_status"] = "CONTESTED"
    advisor_service.derive(advisor)
    derive(row)
    return row


# ---------------------------------------------------------------------------
# POST /transitions/{id}/retention/contest  (BranchManager)
# ---------------------------------------------------------------------------

def contest(transition, data):
    account_id = common.require_field(data, "account_id")
    retention_rate_bps = common.require_field(data, "retention_rate_bps")
    if int(retention_rate_bps) <= 0:
        fail("ERR_INVALID_REQUEST", "retention_rate_bps must be strictly positive.")

    account = accounts.get(account_id)
    if account is None:
        fail("ERR_NOT_FOUND")

    # A contest may only be opened for an account sitting in PENDING_TRANSFER.
    if account["status"] != "PENDING_TRANSFER":
        fail("ERR_INVALID_STATE")

    if transition["status"] != "CONTESTED":
        fail("ERR_TRANSITION_NOT_CONTESTED")

    period = payout_periods.get(transition["payout_period_id"])
    if period is not None and period["state"] in ("PAID", "VOID"):
        fail("ERR_PERIOD_ALREADY_POSTED")

    advisor = advisor_service.get_by_code_or_fail(transition["advisor_code"])
    cap = calc.retention_credit_cap_cents(advisor["book_transferred_cents"])
    running = 0
    for row in rows_of(transition["id"]):
        if row["status"] == "VOID" or row["status"] != "POSTED":
            continue
        running += int(row.get("credit_amount_cents") or 0)
    if running >= cap:
        fail("ERR_RETENTION_CREDIT_EXHAUSTED")

    credit = calc.retention_credit_amount(account["balance_cents"], retention_rate_bps)
    credit = min(credit, max(0, cap - running))

    row = {
        "id": new_id(),
        "created_at": iso_now(),
        "updated_at": iso_now(),
        "version": 1,
        "_seq": next_created_seq(),
        "transition_record_id": transition["id"],
        "account_id": account_id,
        "retention_rate_bps": int(retention_rate_bps),
        "credit_amount_cents": credit,
        "status": "POSTED",
    }
    account_retentions[row["id"]] = row
    account["status"] = "RETENTION_CONTESTED"
    common.touch(account)
    derive(transition)
    advisor_service.derive(advisor)
    return row


# ---------------------------------------------------------------------------
# POST /transitions/{id}/retention/settle  (BranchManager)
# ---------------------------------------------------------------------------

def _guard_advisor_version(transition, data):
    common.required_version(data, "expected_advisor_version")
    advisor = advisor_service.get_by_code_or_fail(transition["advisor_code"])
    common.check_occ(advisor, "expected_advisor_version", data.get("expected_advisor_version"))
    return advisor


def _restamp_transfer(account):
    account["status"] = "PENDING_TRANSFER"
    account["pending_transfer_at"] = clock_dt().isoformat()
    common.touch(account)


def settle(transition, data):
    retained_ids = common.require_field(data, "account_ids_retained")
    advisor = _guard_advisor_version(transition, data)
    if not isinstance(retained_ids, list):
        fail("ERR_INVALID_REQUEST", "account_ids_retained must be an array.")
    if transition["status"] != "CONTESTED":
        fail("ERR_INVALID_STATE")

    in_contest = int(transition["accounts_in_contest_count"] or 0)
    ratio = calc.retention_ratio_bps(len(retained_ids), in_contest)
    if ratio < calc.RETENTION_TARGET_BPS:
        fail("ERR_RETENTION_TARGET_MISSED")

    rows = {row["account_id"]: row for row in rows_of(transition["id"])}
    for account_id in retained_ids:
        row = rows.get(account_id)
        if row is None or row["status"] != "POSTED":
            fail("ERR_INVALID_STATE")

    transition["status"] = "SETTLED"
    transition["accounts_retained_count"] = len(retained_ids)
    common.touch(transition)

    retained_set = set(retained_ids)
    for row in rows.values():
        account = accounts.get(row["account_id"])
        if row["account_id"] in retained_set:
            row["status"] = "RETAINED"
            if account is not None:
                account["status"] = "RETAINED"
                common.touch(account)
        else:
            row["status"] = "LOST"
            if account is not None:
                _restamp_transfer(account)
        common.touch(row)

    for account in account_service.accounts_of(advisor["advisor_code"], "FROZEN"):
        account["status"] = "OPEN"
        common.touch(account)

    advisor["retention_status"] = "RETAINED"
    advisor_service.derive(advisor)
    derive(transition)
    return transition


# ---------------------------------------------------------------------------
# POST /transitions/{id}/retention/lose  (BranchManager)
# ---------------------------------------------------------------------------

def lose(transition, data):
    lost_ids = common.require_field(data, "account_ids_lost")
    advisor = _guard_advisor_version(transition, data)
    if not isinstance(lost_ids, list):
        fail("ERR_INVALID_REQUEST", "account_ids_lost must be an array.")
    if transition["status"] != "CONTESTED":
        fail("ERR_INVALID_STATE")

    in_contest = int(transition["accounts_in_contest_count"] or 0)
    lost_ratio = calc.retention_ratio_bps(len(lost_ids), in_contest)
    if lost_ratio > (10000 - calc.RETENTION_TARGET_BPS):
        fail("ERR_RETENTION_TARGET_MET")

    rows = {row["account_id"]: row for row in rows_of(transition["id"])}
    for account_id in lost_ids:
        row = rows.get(account_id)
        if row is None or row["status"] != "POSTED":
            fail("ERR_INVALID_STATE")

    transition["status"] = "SETTLED"
    transition["accounts_retained_count"] = in_contest - len(lost_ids)
    common.touch(transition)

    lost_set = set(lost_ids)
    for row in rows.values():
        account = accounts.get(row["account_id"])
        if row["account_id"] in lost_set:
            row["status"] = "LOST"
            if account is not None:
                _restamp_transfer(account)
        else:
            row["status"] = "RETAINED"
            if account is not None:
                account["status"] = "RETAINED"
                common.touch(account)
        common.touch(row)

    advisor["retention_status"] = "DEPARTED_CONFIRMED"
    advisor_service.derive(advisor)
    derive(transition)
    return transition


# ---------------------------------------------------------------------------
# POST /account-retentions/{id}/state  (BranchManager)
# ---------------------------------------------------------------------------

def move_retention_state(row, data):
    to_status = common.require_field(data, "to_status")
    if to_status != "VOID":
        fail("ERR_INVALID_REQUEST", "to_status must be VOID.")
    if row["status"] != "PENDING":
        fail("ERR_INVALID_STATE")
    row["status"] = "VOID"
    common.touch(row)
    account = accounts.get(row["account_id"])
    if account is not None:
        _restamp_transfer(account)
    transition = transition_records.get(row["transition_record_id"])
    if transition is not None:
        derive(transition)
    return row