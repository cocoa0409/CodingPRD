"""Advisor lifecycle transitions (SCAFFOLD section 1.2 Advisor / PRD section 3.7).

Precondition order follows PRD 2.10 where it binds, otherwise the order stated
in the workflow section that owns the transition.
"""

from db import (account_retentions, accounts, advisors, clock_dt, iso_now,
                loan_amortization_entries, new_id, next_created_seq,
                payout_loans, revenue_entries, transition_records)
from errors import fail
from services import advisors as advisor_service
from services import branches as branch_service
from services import calc, common


def _accounts_of(advisor_code, status=None):
    rows = [row for row in accounts.values() if row["advisor_code"] == advisor_code]
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return rows


def _entries_of(advisor_code, status=None):
    rows = [row for row in revenue_entries.values() if row["advisor_code"] == advisor_code]
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return rows


def _loans_of(advisor_code):
    return [row for row in payout_loans.values() if row["advisor_code"] == advisor_code]


def _branch_of(advisor):
    return branch_service.find_by_code(advisor["primary_branch_code"])


# ---------------------------------------------------------------------------
# POST /advisors/{id}/enrollment  (AdvisorOps)
# ---------------------------------------------------------------------------

def enrollment(advisor, data):
    common.required_version(data, "expected_advisor_version")
    common.check_occ(advisor, "expected_advisor_version", data.get("expected_advisor_version"))
    if not advisor.get("crd_number"):
        fail("ERR_INVALID_REQUEST", "The advisor has no registration number.")
    branch = _branch_of(advisor)
    if branch is None:
        fail("ERR_BRANCH_NOT_FOUND")
    if advisor["status"] != "PROSPECT":
        fail("ERR_INVALID_STATE")
    loans = [loan for loan in _loans_of(advisor["advisor_code"])
             if loan["status"] in ("REQUESTED", "ACTIVE")]
    if not loans:
        fail("ERR_NO_TRANSITION_LOAN")
    advisor["status"] = "ONBOARDING"
    return advisor_service.bump(advisor)


# ---------------------------------------------------------------------------
# POST /advisors/{id}/affiliation  (AdvisorOps)
# ---------------------------------------------------------------------------

def affiliation(advisor, data):
    common.required_version(data, "expected_advisor_version")
    common.check_occ(advisor, "expected_advisor_version", data.get("expected_advisor_version"))
    if advisor["status"] != "ONBOARDING":
        fail("ERR_INVALID_STATE")
    # Coverage precedes portability in the binding global order (PRD 2.10).
    if advisor["eo_coverage_level"] == "LIMITED":
        fail("ERR_EO_COVERAGE_INSUFFICIENT")
    portability = advisor["book_portability_pct"]
    if portability < calc.AFFILIATION_PORTABILITY_MIN_BPS:
        fail("ERR_BOOK_PORTABILITY_BELOW_MINIMUM")
    if not advisor["protocol_eligible"] and portability < calc.NON_PROTOCOL_PORTABILITY_MIN_BPS:
        fail("ERR_PORTABILITY_PROTOCOL_FAILURE")
    branch = _branch_of(advisor)
    if branch is None:
        fail("ERR_BRANCH_NOT_FOUND")
    if branch["status"] != "ACTIVE":
        fail("ERR_BRANCH_NOT_ACTIVE")
    requested_model = data.get("affiliation_model")
    if requested_model is not None:
        if requested_model not in ("IC", "EMPLOYEE", "HYBRID", "INSTITUTIONAL"):
            fail("ERR_INVALID_REQUEST", "affiliation_model is not a declared value.")
        advisor["affiliation_model"] = requested_model
    advisor["status"] = "ACTIVE"
    advisor["retention_status"] = "NOT_AT_RISK"
    for loan in _loans_of(advisor["advisor_code"]):
        if loan["status"] == "REQUESTED":
            loan["status"] = "ACTIVE"
            common.touch(loan)
    return advisor_service.bump(advisor)


# ---------------------------------------------------------------------------
# POST /advisors/{id}/state  (ComplianceOfficer) — suspension / reinstatement
# ---------------------------------------------------------------------------

def move_state(advisor, data):
    to_status = common.require_field(data, "to_status")
    common.required_version(data, "expected_advisor_version")
    common.check_occ(advisor, "expected_advisor_version", data.get("expected_advisor_version"))
    if to_status not in ("ACTIVE", "SUSPENDED"):
        fail("ERR_INVALID_REQUEST", "to_status must be ACTIVE or SUSPENDED.")
    branch = _branch_of(advisor)
    if branch is None or not branch_service.is_supervised(branch):
        fail("ERR_INVALID_STATE")
    if to_status == "SUSPENDED":
        if advisor["status"] != "ACTIVE":
            fail("ERR_INVALID_STATE")
        if _entries_of(advisor["advisor_code"], "DRAFT"):
            fail("ERR_INVALID_STATE")
        advisor["status"] = "SUSPENDED"
        for account in _accounts_of(advisor["advisor_code"], "OPEN"):
            account["status"] = "FROZEN"
            common.touch(account)
        return advisor_service.bump(advisor)
    # Reinstatement.
    if advisor["status"] != "SUSPENDED":
        fail("ERR_INVALID_STATE")
    advisor["status"] = "ACTIVE"
    for account in _accounts_of(advisor["advisor_code"], "FROZEN"):
        account["status"] = "OPEN"
        common.touch(account)
    return advisor_service.bump(advisor)


# ---------------------------------------------------------------------------
# POST /advisors/{id}/departure  (AdvisorOps)
# ---------------------------------------------------------------------------

def departure(advisor, data):
    common.required_version(data, "expected_advisor_version")
    common.check_occ(advisor, "expected_advisor_version", data.get("expected_advisor_version"))
    branch = _branch_of(advisor)
    if branch is None:
        fail("ERR_BRANCH_NOT_FOUND")
    if branch_service.open_periods_of(advisor["primary_branch_code"]):
        fail("ERR_PERIOD_NOT_CLOSED")
    if int(advisor.get("outstanding_loan_balance_cents") or 0) != 0:
        fail("ERR_LOAN_BALANCE_OUTSTANDING")
    if advisor["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE")
    advisor["status"] = "DEPARTING"
    for account in _accounts_of(advisor["advisor_code"], "OPEN"):
        account["status"] = "FROZEN"
        common.touch(account)
    for entry in _entries_of(advisor["advisor_code"], "DRAFT"):
        entry["status"] = "RELEASED"
        common.touch(entry)
    return advisor_service.bump(advisor)


# ---------------------------------------------------------------------------
# POST /advisors/{id}/departure/reinstate  (AdvisorOps)
# ---------------------------------------------------------------------------

def departure_reinstate(advisor, data):
    common.required_version(data, "expected_advisor_version")
    common.check_occ(advisor, "expected_advisor_version", data.get("expected_advisor_version"))
    for transition in transition_records.values():
        if transition["advisor_code"] == advisor["advisor_code"] and transition["status"] == "SETTLED":
            fail("ERR_TRANSITION_ALREADY_SETTLED")
    if advisor["status"] != "DEPARTING":
        fail("ERR_INVALID_STATE")
    advisor["status"] = "ACTIVE"
    advisor["retention_status"] = "RETAINED"
    for account in _accounts_of(advisor["advisor_code"]):
        if account["status"] in ("FROZEN", "RETENTION_CONTESTED"):
            account["status"] = "OPEN"
            common.touch(account)
    return advisor_service.bump(advisor)


# ---------------------------------------------------------------------------
# POST /advisors/{id}/departure/settle  (ComplianceOfficer)
# ---------------------------------------------------------------------------

def departure_settle(advisor, data):
    common.required_version(data, "expected_advisor_version")
    common.check_occ(advisor, "expected_advisor_version", data.get("expected_advisor_version"))
    if advisor["eo_coverage_level"] == "LIMITED":
        fail("ERR_EO_COVERAGE_INSUFFICIENT")
    branch = _branch_of(advisor)
    if branch is None:
        fail("ERR_BRANCH_NOT_FOUND")
    if not branch.get("osj_enabled"):
        fail("ERR_EO_COVERAGE_INSUFFICIENT")
    transition = None
    for row in transition_records.values():
        if row["advisor_code"] == advisor["advisor_code"]:
            transition = row
    if transition is None or transition["status"] != "SETTLED":
        fail("ERR_TRANSITION_NOT_SETTLED")
    if advisor["status"] != "DEPARTING":
        fail("ERR_INVALID_STATE")
    for row in account_retentions.values():
        if row["transition_record_id"] != transition["id"]:
            continue
        if row["status"] not in ("POSTED", "RETAINED", "LOST"):
            fail("ERR_FROZEN_ACCOUNTS_REMAIN")
    advisor["status"] = "DEPARTED"
    advisor["retention_status"] = "DEPARTED_CONFIRMED"
    for row in account_retentions.values():
        if row["transition_record_id"] == transition["id"] and row["status"] == "POSTED":
            row["status"] = "RETAINED"
            common.touch(row)
    for loan in _loans_of(advisor["advisor_code"]):
        if loan["status"] in ("ACTIVE", "AMORTIZING"):
            _discharge_loan(loan)
    for entry in _entries_of(advisor["advisor_code"], "RELEASED"):
        entry["status"] = "TRUE_UP_APPLIED"
        common.touch(entry)
    return advisor_service.bump(advisor)


def _discharge_loan(loan):
    residual = int(loan["remaining_balance_cents"] or 0)
    entry = {
        "id": new_id(),
        "created_at": iso_now(),
        "updated_at": iso_now(),
        "version": 1,
        "_seq": next_created_seq(),
        "payout_loan_id": loan["id"],
        "payout_period_id": None,
        "amortization_amount_cents": 0,
        "forgiveness_amount_cents": residual,
        "status": "POSTED",
    }
    loan_amortization_entries[entry["id"]] = entry
    loan["remaining_balance_cents"] = 0
    loan["status"] = "DISCHARGED"
    common.touch(loan)


# ---------------------------------------------------------------------------
# POST /advisors/{id}/book-transfer  (AdvisorOps)
# ---------------------------------------------------------------------------

def book_transfer(advisor, data):
    common.required_version(data, "expected_advisor_version")
    common.check_occ(advisor, "expected_advisor_version", data.get("expected_advisor_version"))
    if advisor["status"] not in ("DEPARTING", "DEPARTED"):
        fail("ERR_INVALID_STATE")
    if advisor["book_portability_pct"] < calc.BOOK_TRANSFER_PORTABILITY_MIN_BPS:
        fail("ERR_BOOK_PORTABILITY_BELOW_MINIMUM")
    moved = []
    for account in _accounts_of(advisor["advisor_code"], "OPEN"):
        account["status"] = "PENDING_TRANSFER"
        account["pending_transfer_at"] = clock_dt().isoformat()
        common.touch(account)
        moved.append(account)
    advisor_service.bump(advisor)
    return moved