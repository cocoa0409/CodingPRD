"""Account and RevenueEntry services, plus the delayed transfer confirmation."""

from datetime import timedelta

from db import (accounts, advisors, clock_dt, iso_now, new_id, next_created_seq,
                parse_date, revenue_entries)
from errors import fail
from services import advisors as advisor_service
from services import branches as branch_service
from services import common


def serialize(row):
    return {key: value for key, value in row.items() if not key.startswith("_")}


# ---------------------------------------------------------------------------
# Account (parent: Advisor)
# ---------------------------------------------------------------------------

def find_account_or_fail(account_id):
    row = accounts.get(account_id)
    if row is None:
        fail("ERR_NOT_FOUND")
    return row


def create_account(data):
    advisor_code = common.require_field(data, "advisor_code")
    account_number = common.require_field(data, "account_number")
    account_type = common.require_field(data, "account_type")
    advisor_service.get_by_code_or_fail(advisor_code)
    if account_type not in ("ADVISORY", "BROKERAGE"):
        fail("ERR_INVALID_REQUEST", "account_type must be ADVISORY or BROKERAGE.")
    for row in accounts.values():
        if row["account_number"] == account_number:
            fail("ERR_INVALID_REQUEST", "account_number is already in use.")
    row = {
        "id": new_id(),
        "created_at": iso_now(),
        "updated_at": iso_now(),
        "version": 1,
        "_seq": next_created_seq(),
        "advisor_code": advisor_code,
        "account_number": account_number,
        "account_type": account_type,
        "balance_cents": int(data.get("balance_cents") or 0),
        "annual_fee_cents": int(data.get("annual_fee_cents") or 0),
        "base_annual_fee_cents": None,
        "rafee_effective_bps": None,
        "held_away": bool(data.get("held_away", False)),
        "fee_levelized": False,
        "pending_transfer_at": None,
        "status": "OPEN",
    }
    accounts[row["id"]] = row
    return row


def accounts_of(advisor_code, status=None):
    rows = [row for row in accounts.values() if row["advisor_code"] == advisor_code]
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return rows


def confirm_transfer(account, data):
    if not account.get("pending_transfer_at"):
        fail("ERR_INVALID_STATE")
    if account["status"] != "PENDING_TRANSFER":
        fail("ERR_INVALID_STATE")
    advisor = advisor_service.get_by_code_or_fail(account["advisor_code"])
    # The clock must have been set for 24-hour window arithmetic (PRD 2.10.11).
    from db import clock_is_set
    if not clock_is_set():
        fail("ERR_CLOCK_NOT_SET")
    if advisor["eo_coverage_level"] == "LIMITED":
        fail("ERR_EO_COVERAGE_INSUFFICIENT")
    branch = branch_service.find_by_code(advisor["primary_branch_code"])
    if branch is None:
        fail("ERR_BRANCH_NOT_FOUND")
    if not branch.get("osj_enabled"):
        fail("ERR_EO_COVERAGE_INSUFFICIENT")
    opening = parse_date(account["pending_transfer_at"])
    if clock_dt() < opening + timedelta(hours=24):
        fail("ERR_TRANSFER_HOLD_PERIOD")
    account["status"] = "TRANSFERRED_OUT"
    account["fee_levelized"] = True
    common.touch(account)
    for entry in revenue_entries.values():
        if entry["advisor_code"] == advisor["advisor_code"] and entry["status"] == "DRAFT":
            entry["status"] = "VOID"
            common.touch(entry)
    advisor_service.bump(advisor)
    return account


# ---------------------------------------------------------------------------
# RevenueEntry (parent: Advisor)
# ---------------------------------------------------------------------------

def find_entry_or_fail(entry_id):
    row = revenue_entries.get(entry_id)
    if row is None:
        fail("ERR_NOT_FOUND")
    return row


def create_entry(data):
    advisor_code = common.require_field(data, "advisor_code")
    account_id = common.require_field(data, "account_id")
    product_type = common.require_field(data, "product_type")
    gross_commission_cents = common.require_field(data, "gross_commission_cents")
    production_date = common.require_field(data, "production_date")
    advisor = advisor_service.get_by_code_or_fail(advisor_code)
    account = accounts.get(account_id)
    if account is None:
        fail("ERR_NOT_FOUND")
    if product_type not in ("EQUITY", "MUTUAL_FUND", "ANNUITY", "BROKERAGE_TRAIL", "ADVISORY"):
        fail("ERR_INVALID_REQUEST", "product_type is not a declared value.")
    if int(gross_commission_cents) <= 0:
        fail("ERR_INVALID_REQUEST", "gross_commission_cents must be strictly positive.")
    # A frozen or transferred account can no longer earn (PRD 3.3).
    if account["status"] in ("FROZEN", "TRANSFERRED_OUT", "PENDING_TRANSFER",
                             "RETENTION_CONTESTED", "RETAINED"):
        fail("ERR_INVALID_STATE")
    row = {
        "id": new_id(),
        "created_at": iso_now(),
        "updated_at": iso_now(),
        "version": 1,
        "_seq": next_created_seq(),
        "advisor_code": advisor_code,
        "account_id": account_id,
        "product_type": product_type,
        "gross_commission_cents": int(gross_commission_cents),
        "production_date": production_date,
        "status": "DRAFT",
    }
    revenue_entries[row["id"]] = row
    advisor_service.derive(advisor)
    return row


def release_entry(entry, data):
    if entry["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    account = accounts.get(entry["account_id"])
    if account is None:
        fail("ERR_NOT_FOUND")
    if account["status"] not in ("OPEN", "FROZEN"):
        fail("ERR_INVALID_STATE")
    entry["status"] = "RELEASED"
    common.touch(entry)
    advisor = advisor_service.get_by_code_or_fail(entry["advisor_code"])
    advisor_service.derive(advisor)
    return entry