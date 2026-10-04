"""Advisor service: entity, derived fields and the advisor lifecycle."""

from datetime import timedelta

from db import (account_retentions, accounts, advisor_payout_lines, advisors,
                clock_dt, expense_pass_throughs, iso_now, loan_amortization_entries,
                new_id, next_created_seq, payout_loans, payout_periods,
                revenue_entries, transition_records)
from errors import dec, fail, round_half_up
from services import calc, common


def serialize(row):
    return {key: value for key, value in row.items() if not key.startswith("_")}


def find_by_code(advisor_code):
    for row in advisors.values():
        if row["advisor_code"] == advisor_code:
            return row
    return None


def find_by_id(advisor_id):
    return advisors.get(advisor_id)


def get_by_code_or_fail(advisor_code):
    row = find_by_code(advisor_code)
    if row is None:
        fail("ERR_ADVISOR_NOT_FOUND")
    return row


def get_by_id_or_fail(advisor_id):
    row = find_by_id(advisor_id)
    if row is None:
        fail("ERR_NOT_FOUND")
    return row


def entries_of(advisor_code):
    return [row for row in revenue_entries.values() if row["advisor_code"] == advisor_code]


def released_entries_of(advisor_code):
    return [row for row in entries_of(advisor_code)
            if row["status"] in ("RELEASED", "TRUE_UP_APPLIED")]


def accounts_of(advisor_code):
    return [row for row in accounts.values() if row["advisor_code"] == advisor_code]


def loans_of(advisor_code):
    return [row for row in payout_loans.values() if row["advisor_code"] == advisor_code]


def lines_of(advisor_code):
    return [row for row in advisor_payout_lines.values() if row["advisor_code"] == advisor_code]


def transitions_of(advisor_code):
    return [row for row in transition_records.values() if row["advisor_code"] == advisor_code]


def current_year_of(advisor):
    from services import branches as branch_service
    branch = branch_service.find_by_code(advisor["primary_branch_code"])
    if branch is not None and branch.get("current_payout_period_id"):
        period = payout_periods.get(branch["current_payout_period_id"])
        if period is not None:
            return period["year"]
    return clock_dt().year


# ---------------------------------------------------------------------------
# Derived fields (SCAFFOLD section 1.1 Advisor)
# ---------------------------------------------------------------------------

def derive(advisor):
    advisor["book_portability_pct"] = calc.book_portability_pct(
        advisor["ingested_book_total_cents"], advisor["book_transferred_cents"])

    window_start = clock_dt() - timedelta(days=365)
    window_end = clock_dt()
    t12 = 0
    for entry in released_entries_of(advisor["advisor_code"]):
        when = db_parse_date(entry["production_date"])
        if window_start <= when <= window_end:
            t12 += int(entry["gross_commission_cents"])
    advisor["t12_production_cents"] = t12

    year = current_year_of(advisor)
    earned = 0
    for line in lines_of(advisor["advisor_code"]):
        if line["status"] not in ("RELEASED", "TRUE_UP_APPLIED"):
            continue
        period = payout_periods.get(line["payout_period_id"])
        if period is None or period["year"] != year:
            continue
        earned += int(line.get("release_amount_cents") or 0)
    advisor["ytd_payout_earned_cents"] = earned
    advisor["annual_payout_cap_hit"] = earned >= calc.ANNUAL_PAYOUT_CAP_CENTS

    # retention_status is owned by the lifecycle and contest transitions, never
    # re-derived here, so a context refresh cannot roll a transition back.

    # The outstanding transition-assistance balance is the residual on the
    # advisor's live, not-yet-drawn loans.  A loan that has reached AMORTIZING has
    # had its draws posted against released production and is settled by the
    # departure discharge (PRD 3.2), so it does not stand against the departure
    # gate of PRD 3.7.
    advisor["outstanding_loan_balance_cents"] = sum(
        int(loan["remaining_balance_cents"] or 0)
        for loan in loans_of(advisor["advisor_code"])
        if loan["status"] == "ACTIVE")

    paid = 0
    for loan in loans_of(advisor["advisor_code"]):
        for row in loan_amortization_entries.values():
            if row["payout_loan_id"] != loan["id"] or row["status"] != "POSTED":
                continue
            if not row.get("amortization_amount_cents"):
                continue
            period = payout_periods.get(row.get("payout_period_id"))
            if period is not None and period["year"] != year:
                continue
            amount = int(row["amortization_amount_cents"])
            if amount > 0:
                paid += amount
    advisor["ytd_payout_paid_cents"] = paid

    locked_eo = 0
    locked_pt = 0
    for row in expense_pass_throughs.values():
        if row["advisor_code"] != advisor["advisor_code"] or row["status"] != "POSTED":
            continue
        period = payout_periods.get(row["payout_period_id"])
        if period is None or period["year"] != year:
            continue
        if row["category"] == "E_AND_O":
            locked_eo += int(row["amount_cents"] or 0)
        if row["category"] in ("TECHNOLOGY", "CLEARING"):
            locked_pt += int(row["amount_cents"] or 0)
    advisor["eo_charge_locked_cents"] = locked_eo
    advisor["pass_through_locked_cents"] = locked_pt
    return advisor


def db_parse_date(value):
    from db import parse_date
    return parse_date(value)


def bump(advisor):
    """A business mutation of the advisor record."""
    common.touch(advisor)
    derive(advisor)
    return advisor


# ---------------------------------------------------------------------------
# Creation and update
# ---------------------------------------------------------------------------

def require_unique(advisor_code, crd_number, exclude_id=None):
    for row in advisors.values():
        if row["id"] == exclude_id:
            continue
        if row["advisor_code"] == advisor_code:
            fail("ERR_INVALID_REQUEST", "advisor_code is already in use.")
        if row["crd_number"] == crd_number:
            fail("ERR_INVALID_REQUEST", "crd_number is already in use.")


def build(data):
    advisor_code = common.require_field(data, "advisor_code")
    crd_number = common.require_field(data, "crd_number")
    full_name = common.require_field(data, "full_name")
    affiliation_model = common.require_field(data, "affiliation_model")
    primary_branch_code = common.require_field(data, "primary_branch_code")
    if affiliation_model not in ("IC", "EMPLOYEE", "HYBRID", "INSTITUTIONAL"):
        fail("ERR_INVALID_REQUEST", "affiliation_model is not a declared value.")
    eo_level = data.get("eo_coverage_level", "STANDARD")
    if eo_level not in ("STANDARD", "PREMIUM", "LIMITED"):
        fail("ERR_INVALID_REQUEST", "eo_coverage_level is not a declared value.")
    require_unique(advisor_code, crd_number)
    from services import branches as branch_service
    branch_service.get_by_code_or_fail(primary_branch_code)
    row = {
        "id": new_id(),
        "created_at": iso_now(),
        "updated_at": iso_now(),
        "version": 1,
        "_seq": next_created_seq(),
        "advisor_code": advisor_code,
        "crd_number": crd_number,
        "full_name": full_name,
        "affiliation_model": affiliation_model,
        "primary_branch_code": primary_branch_code,
        "ingested_book_total_cents": int(data.get("ingested_book_total_cents") or 0),
        "book_transferred_cents": int(data.get("book_transferred_cents") or 0),
        "book_portability_pct": 0,
        "protocol_eligible": bool(data.get("protocol_eligible", False)),
        "t12_production_cents": 0,
        "ytd_payout_earned_cents": 0,
        "ytd_payout_paid_cents": 0,
        "outstanding_loan_balance_cents": 0,
        "eo_coverage_level": eo_level,
        "eo_charge_locked_cents": 0,
        "pass_through_locked_cents": 0,
        "annual_payout_cap_hit": False,
        "retention_status": "NOT_AT_RISK",
        "status": "PROSPECT",
    }
    derive(row)
    return row


def create(data):
    row = build(data)
    advisors[row["id"]] = row
    return row


def bulk_import(data):
    """A row whose branch or advisor code does not resolve is skipped without
    rolling back the accepted rows (PRD 3.1)."""
    rows = common.require_field(data, "advisors")
    if not isinstance(rows, list):
        fail("ERR_INVALID_REQUEST", "advisors must be an array.")
    created_codes = []
    skipped_codes = []
    from services import branches as branch_service
    from errors import ApiError
    for entry in rows:
        code = entry.get("advisor_code") if isinstance(entry, dict) else None
        if not isinstance(entry, dict) or not code \
                or branch_service.find_by_code(entry.get("primary_branch_code")) is None \
                or find_by_code(code) is not None:
            if isinstance(code, str) and code:
                skipped_codes.append(code)
            continue
        try:
            row = build(entry)
        except ApiError:
            skipped_codes.append(code)
            continue
        advisors[row["id"]] = row
        created_codes.append(row["advisor_code"])
    return {
        "created_count": len(created_codes),
        "skipped_count": len(skipped_codes),
        "created_advisor_codes": created_codes,
        "skipped_advisor_codes": skipped_codes,
    }


def update(advisor, data):
    if "book_transferred_cents" in data and data["book_transferred_cents"] is not None:
        advisor["book_transferred_cents"] = int(data["book_transferred_cents"])
    if "protocol_eligible" in data and data["protocol_eligible"] is not None:
        advisor["protocol_eligible"] = bool(data["protocol_eligible"])
    if "eo_coverage_level" in data and data["eo_coverage_level"] is not None:
        if data["eo_coverage_level"] not in ("STANDARD", "PREMIUM", "LIMITED"):
            fail("ERR_INVALID_REQUEST", "eo_coverage_level is not a declared value.")
        advisor["eo_coverage_level"] = data["eo_coverage_level"]
    common.touch(advisor)
    derive(advisor)
    return advisor


def crd_change(advisor, data):
    crd_number = common.require_field(data, "crd_number")
    require_unique(advisor["advisor_code"], crd_number, exclude_id=advisor["id"])
    advisor["crd_number"] = crd_number
    common.touch(advisor)
    derive(advisor)
    return advisor