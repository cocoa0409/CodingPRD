"""Payout period, payout line, true-up and net-settlement services.

Covers the PayoutPeriod state machine (OPEN -> CLOSED -> PAID -> REOPENED ->
PAID, CLOSED -> VOID), the AdvisorPayoutLine release/true-up transitions, the
payout grid, and the settlement waterfall of PRD 3.5.
"""

from db import (advisor_payout_lines, advisors, advisory_revenue_splits,
                clock_dt, expense_pass_throughs, iso_now, loan_amortization_entries,
                new_id, next_created_seq, parse_date, payout_loans,
                payout_periods, revenue_entries)
from errors import dec, fail, round_half_up
from services import advisors as advisor_service
from services import branches as branch_service
from services import calc, common


def serialize(row):
    return {key: value for key, value in row.items() if not key.startswith("_")}


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def find_period_or_fail(period_id):
    row = payout_periods.get(period_id)
    if row is None:
        fail("ERR_NOT_FOUND")
    return row


def find_line_or_fail(line_id):
    row = advisor_payout_lines.get(line_id)
    if row is None:
        fail("ERR_NOT_FOUND")
    return row


def lines_of_period(period_id):
    return [row for row in advisor_payout_lines.values() if row["payout_period_id"] == period_id]


def entries_of_month(period):
    """Entries of advisors whose primary branch is the period's branch, in the
    period's calendar month (PRD 3.3)."""
    out = []
    for entry in revenue_entries.values():
        advisor = advisor_service.find_by_code(entry["advisor_code"])
        if advisor is None or advisor["primary_branch_code"] != period["branch_code"]:
            continue
        when = parse_date(entry["production_date"])
        if when.year == period["year"] and when.month == period["month"]:
            out.append(entry)
    return out


def entries_of_month_for_advisor(period, advisor_code):
    return [entry for entry in entries_of_month(period) if entry["advisor_code"] == advisor_code]


def _entry_order(entry):
    return (entry["production_date"], entry["created_at"], entry.get("_seq", 0))


def cumulative_year_production_through(entry):
    """Sum of released gross for the advisor in the entry's calendar year, in
    production_date then creation order, up to and including the entry."""
    advisor_code = entry["advisor_code"]
    year = parse_date(entry["production_date"]).year
    released = [row for row in revenue_entries.values()
                if row["advisor_code"] == advisor_code
                and row["status"] in ("RELEASED", "TRUE_UP_APPLIED")
                and parse_date(row["production_date"]).year == year]
    released.sort(key=_entry_order)
    total = 0
    for row in released:
        total += int(row["gross_commission_cents"])
        if row["id"] == entry["id"]:
            break
    return total


def recompute_period(period):
    released = [entry for entry in entries_of_month(period)
                if entry["status"] in ("RELEASED", "TRUE_UP_APPLIED")]
    period["period_gross_cents"] = sum(int(entry["gross_commission_cents"]) for entry in released)
    lines = lines_of_period(period["id"])
    period["period_payout_cents"] = sum(
        int(line.get("release_amount_cents") or 0) for line in lines
        if line["status"] in ("RELEASED", "TRUE_UP_APPLIED"))
    period["true_up_amount_cents"] = sum(
        int(line.get("true_up_amount_cents") or 0) for line in lines
        if line["status"] == "TRUE_UP_APPLIED")
    return period


# ---------------------------------------------------------------------------
# PayoutPeriod creation (BranchManager, PlatformAdmin)
# ---------------------------------------------------------------------------

def create_period(data):
    branch_code = common.require_field(data, "branch_code")
    year = common.require_field(data, "year")
    month = common.require_field(data, "month")
    period_index = common.require_field(data, "period_index")
    branch = branch_service.get_by_code_or_fail(branch_code)
    if int(month) < 1 or int(month) > 12:
        fail("ERR_INVALID_REQUEST", "month must be between 1 and 12.")
    # Periods are numbered from one; five periods are permitted within a
    # calendar month, so an index outside 1-5 cannot name one of them
    # (PRD 3.3).
    if int(period_index) < 1 or int(period_index) > 5:
        fail("ERR_INVALID_REQUEST", "period_index must be between 1 and 5.")
    for row in payout_periods.values():
        if row["branch_code"] == branch_code and row["year"] == int(year) \
                and row["month"] == int(month) and row["period_index"] == int(period_index):
            fail("ERR_PERIOD_ALREADY_EXISTS")
    row = {
        "id": new_id(),
        "created_at": iso_now(),
        "updated_at": iso_now(),
        "version": 1,
        "_seq": next_created_seq(),
        "branch_code": branch_code,
        "year": int(year),
        "month": int(month),
        "period_index": int(period_index),
        "state": "OPEN",
        "status": "OPEN",
        "period_gross_cents": 0,
        "period_payout_cents": 0,
        "true_up_amount_cents": 0,
    }
    payout_periods[row["id"]] = row
    branch["current_payout_period_id"] = row["id"]
    common.touch(branch)
    return row


# ---------------------------------------------------------------------------
# PayoutPeriod state machine (BranchManager, ComplianceOfficer)
# ---------------------------------------------------------------------------

def _guard_branch_version(period, data):
    common.required_version(data, "expected_branch_version")
    branch = branch_service.get_by_code_or_fail(period["branch_code"])
    common.check_occ(branch, "expected_branch_version", data.get("expected_branch_version"))
    return branch


def move_state(period, data):
    to_state = common.require_field(data, "to_state")
    branch = _guard_branch_version(period, data)
    if to_state not in ("CLOSED", "PAID", "REOPENED", "VOID"):
        fail("ERR_INVALID_REQUEST", "to_state is not a declared payout period state.")
    if to_state == "CLOSED":
        _close(period)
    elif to_state == "PAID":
        _post(period)
    elif to_state == "REOPENED":
        _reopen(period)
    elif to_state == "VOID":
        _void(period)
    common.touch(branch)
    recompute_period(period)
    return period


def _close(period):
    if period["state"] != "OPEN":
        fail("ERR_INVALID_STATE")
    month_entries = entries_of_month(period)
    if not any(entry["status"] == "RELEASED" for entry in month_entries):
        fail("ERR_PERIOD_HAS_NO_RELEASED_PRODUCTION")
    if any(entry["status"] == "DRAFT" for entry in month_entries):
        fail("ERR_PERIOD_HAS_DRAFT_ENTRIES")
    period["state"] = "CLOSED"
    period["status"] = "CLOSED"
    common.touch(period)


def _post(period):
    if period["state"] not in ("CLOSED", "REOPENED"):
        fail("ERR_INVALID_STATE")
    month_entries = entries_of_month(period)
    if any(entry["status"] == "DRAFT" for entry in month_entries):
        fail("ERR_PERIOD_HAS_DRAFT_ENTRIES")
    # Every line's provisional base rate must match the grid base rate for its
    # projected basis (PRD 3.3 / SCAFFOLD 1.2 PayoutPeriod).
    for line in lines_of_period(period["id"]):
        expected = calc.grid_tier_base_bps(line["projected_annual_production_cents"])
        if int(line["provisional_base_rate_bps"]) != expected:
            fail("ERR_PERIOD_PROVISIONAL_BASIS_MISMATCH")

    period["state"] = "PAID"
    period["status"] = "PAID"
    common.touch(period)

    for line in lines_of_period(period["id"]):
        if line["status"] != "DRAFT":
            continue
        advisor = advisor_service.get_by_code_or_fail(line["advisor_code"])
        if advisor["status"] not in ("ACTIVE", "ONBOARDING", "DEPARTING"):
            continue
        line["release_amount_cents"] = _release_amount_at_provisional(line, advisor)
        line["status"] = "RELEASED"
        common.touch(line)
        advisor_service.derive(advisor)

    # Amortization follows the release of a paid line.  A reopen restores the
    # balance and voids the period's amortization entries, so a re-post must
    # re-apply the draw for the lines this period settles - "the period is
    # re-posted exactly as the CLOSED -> PAID transition posts it".
    for line in lines_of_period(period["id"]):
        if line["status"] not in ("RELEASED", "TRUE_UP_APPLIED"):
            continue
        advisor = advisor_service.get_by_code_or_fail(line["advisor_code"])
        _amortize_on_release(advisor, line, period)
        advisor_service.derive(advisor)

    _compute_settlement_for_period(period)
    for advisor_code in {row["advisor_code"] for row in expense_pass_throughs.values()
                         if row["payout_period_id"] == period["id"]}:
        advisor_service.derive(advisor_service.get_by_code_or_fail(advisor_code))

    for split in advisory_revenue_splits.values():
        if split["payout_period_id"] == period["id"] and split["status"] == "PENDING":
            split["status"] = "POSTED"
            common.touch(split)
    recompute_period(period)


def _reopen(period):
    if period["state"] != "PAID":
        fail("ERR_INVALID_STATE")
    period["state"] = "REOPENED"
    period["status"] = "REOPENED"
    common.touch(period)
    for line in lines_of_period(period["id"]):
        if line["status"] == "TRUE_UP_APPLIED":
            line["status"] = "RELEASED"
            line["true_up_amount_cents"] = 0
            advisor = advisor_service.get_by_code_or_fail(line["advisor_code"])
            line["release_amount_cents"] = _release_amount_at_provisional(line, advisor)
            common.touch(line)
            advisor_service.derive(advisor)
    for entry in loan_amortization_entries.values():
        if entry.get("payout_period_id") == period["id"] and entry["status"] == "POSTED":
            loan = payout_loans.get(entry["payout_loan_id"])
            if loan is not None:
                # Forward application was `remaining -= amount`, so the reversal
                # restores the balance with `remaining += amount`; the posted
                # amount may be signed (a negative true-up raised the balance).
                loan["remaining_balance_cents"] = int(loan["remaining_balance_cents"] or 0) \
                    + int(entry.get("amortization_amount_cents") or 0)
                common.touch(loan)
            entry["status"] = "VOID"
            common.touch(entry)
    for row in expense_pass_throughs.values():
        if row["payout_period_id"] == period["id"] and row["status"] == "POSTED":
            row["status"] = "PENDING"
            common.touch(row)
    for split in advisory_revenue_splits.values():
        if split["payout_period_id"] == period["id"] and split["status"] == "POSTED":
            split["status"] = "VOID"
            common.touch(split)
    recompute_period(period)


def _void(period):
    if period["state"] != "CLOSED":
        fail("ERR_INVALID_STATE")
    for line in lines_of_period(period["id"]):
        if line["status"] in ("RELEASED", "TRUE_UP_APPLIED"):
            fail("ERR_PERIOD_ALREADY_POSTED")
    period["state"] = "VOID"
    period["status"] = "VOID"
    common.touch(period)
    for line in lines_of_period(period["id"]):
        if line["status"] == "DRAFT":
            line["status"] = "VOID"
            common.touch(line)


# ---------------------------------------------------------------------------
# Payout grid application
# ---------------------------------------------------------------------------

def _provisional_applied_rate(line, advisor, entry):
    return min(calc.MAX_RATE_BPS, max(calc.MIN_RATE_BPS,
               int(line["provisional_base_rate_bps"])
               + calc.PRODUCT_RATE_DELTA_BPS.get(entry["product_type"], 0)
               - calc.AFFILIATION_MODEL_OFFSET_BPS.get(advisor["affiliation_model"], 0)))


def _release_amount_at_provisional(line, advisor):
    period = payout_periods[line["payout_period_id"]]
    entries = [entry for entry in entries_of_month_for_advisor(period, line["advisor_code"])
               if entry["status"] in ("RELEASED", "TRUE_UP_APPLIED")]
    entries.sort(key=_entry_order)
    return calc.sum_entry_amounts(entries, lambda e: _provisional_applied_rate(line, advisor, e))


def _final_applied_rate(advisor, entry):
    basis = cumulative_year_production_through(entry)
    return calc.rate_for(basis, entry["product_type"], advisor["affiliation_model"])


# ---------------------------------------------------------------------------
# POST /advisors/{id}/payout-lines  (AdvisorOps, BranchManager)
# ---------------------------------------------------------------------------

def create_line(advisor, data):
    period_id = common.require_field(data, "payout_period_id")
    projected = common.require_field(data, "projected_annual_production_cents")
    period = find_period_or_fail(period_id)
    if period["branch_code"] != advisor["primary_branch_code"]:
        fail("ERR_PAYOUT_CAP_REACHED")
    if advisor.get("annual_payout_cap_hit"):
        fail("ERR_PAYOUT_CAP_REACHED")
    row = {
        "id": new_id(),
        "created_at": iso_now(),
        "updated_at": iso_now(),
        "version": 1,
        "_seq": next_created_seq(),
        "payout_period_id": period_id,
        "advisor_code": advisor["advisor_code"],
        "period_gross_cents": 0,
        "projected_annual_production_cents": int(projected),
        "provisional_base_rate_bps": calc.grid_tier_base_bps(int(projected)),
        "release_amount_cents": 0,
        "true_up_amount_cents": 0,
        "net_settlement_cents": 0,
        "status": "DRAFT",
    }
    advisor_payout_lines[row["id"]] = row
    return row


# ---------------------------------------------------------------------------
# POST /payout-periods/{id}/true-up  (BranchManager, AdvisorOps)
# ---------------------------------------------------------------------------

def true_up(period, data):
    branch = _guard_branch_version(period, data)
    if period["state"] not in ("CLOSED", "PAID", "REOPENED"):
        fail("ERR_PERIOD_NOT_CLOSED")
    lines = lines_of_period(period["id"])
    if not lines:
        fail("ERR_INVALID_STATE")
    for line in lines:
        if line["status"] != "RELEASED":
            fail("ERR_INVALID_STATE")
        expected = calc.grid_tier_base_bps(line["projected_annual_production_cents"])
        if int(line["provisional_base_rate_bps"]) != expected:
            fail("ERR_PERIOD_PROVISIONAL_BASIS_MISMATCH")

    for line in lines:
        advisor = advisor_service.get_by_code_or_fail(line["advisor_code"])
        entries = [entry for entry in entries_of_month_for_advisor(period, line["advisor_code"])
                   if entry["status"] in ("RELEASED", "TRUE_UP_APPLIED")]
        entries.sort(key=_entry_order)
        final_income = calc.sum_entry_amounts(entries, lambda e: _final_applied_rate(advisor, e))
        provisional_income = calc.sum_entry_amounts(
            entries, lambda e: _provisional_applied_rate(line, advisor, e))
        line["true_up_amount_cents"] = final_income - provisional_income
        line["release_amount_cents"] = final_income
        line["status"] = "TRUE_UP_APPLIED"
        common.touch(line)
        if line["true_up_amount_cents"] < 0:
            _apply_negative_true_up(advisor, line, period)
        advisor_service.derive(advisor)
    for entry in entries_of_month(period):
        if entry["status"] == "RELEASED":
            entry["status"] = "TRUE_UP_APPLIED"
            common.touch(entry)
    common.touch(branch)
    recompute_period(period)
    return period


def _apply_negative_true_up(advisor, line, period):
    """A negative true-up is added back to the loan as a signed amortization row."""
    target = None
    for loan in advisor_service.loans_of(advisor["advisor_code"]):
        if loan["status"] in ("ACTIVE", "AMORTIZING"):
            target = loan
            break
    if target is None:
        for loan in advisor_service.loans_of(advisor["advisor_code"]):
            if loan["status"] == "REQUESTED":
                target = loan
                break
    if target is None:
        return
    entry = {
        "id": new_id(),
        "created_at": iso_now(),
        "updated_at": iso_now(),
        "version": 1,
        "_seq": next_created_seq(),
        "payout_loan_id": target["id"],
        "payout_period_id": period["id"],
        "amortization_amount_cents": int(line["true_up_amount_cents"]),
        "forgiveness_amount_cents": 0,
        "status": "POSTED",
    }
    loan_amortization_entries[entry["id"]] = entry
    # remaining_balance_cents -= (negative true-up) => the balance RISES by the
    # shortfall magnitude; the conservation identity still holds because the
    # posted amortization amount is itself signed (PRD 3.2).
    target["remaining_balance_cents"] = int(target["remaining_balance_cents"] or 0) \
        - int(line["true_up_amount_cents"])
    if target["remaining_balance_cents"] < 0:
        target["remaining_balance_cents"] = 0
    common.touch(target)


# ---------------------------------------------------------------------------
# Loan amortization on release (SCAFFOLD 1.3 loan_amortization)
# ---------------------------------------------------------------------------

def _amortize_on_release(advisor, line, period):
    """A released line draws against the advisor's loan.

    A reopen restores the balance but leaves the loan AMORTIZING, so both ACTIVE
    and AMORTIZING loans are drawn against on (re-)posting.
    """
    release_amount = int(line.get("release_amount_cents") or 0)
    for loan in advisor_service.loans_of(advisor["advisor_code"]):
        if loan["status"] not in ("ACTIVE", "AMORTIZING"):
            continue
        draw = round_half_up(dec(release_amount) * dec(loan["amortization_rate_bps"]) / dec(10000))
        draw = min(draw, int(loan["remaining_balance_cents"] or 0))
        entry = {
            "id": new_id(),
            "created_at": iso_now(),
            "updated_at": iso_now(),
            "version": 1,
            "_seq": next_created_seq(),
            "payout_loan_id": loan["id"],
            "payout_period_id": period["id"],
            "amortization_amount_cents": draw,
            "forgiveness_amount_cents": 0,
            "status": "POSTED",
        }
        loan_amortization_entries[entry["id"]] = entry
        loan["remaining_balance_cents"] = int(loan["remaining_balance_cents"] or 0) - draw
        loan["status"] = "AMORTIZING"
        common.touch(loan)


# ---------------------------------------------------------------------------
# Expense pass-through and the net settlement waterfall (PRD 3.5)
# ---------------------------------------------------------------------------

def pass_through_rows(advisor_code, period_id):
    return [row for row in expense_pass_throughs.values()
            if row["advisor_code"] == advisor_code and row["payout_period_id"] == period_id
            and row["status"] in ("PENDING", "POSTED")]


def compute_settlement(advisor, period):
    """The strictly ordered waterfall of PRD 3.5.

    Step 1  payout basis = period_payout_cents + period_true_up_amount_cents.
    Step 2  expense pool, rows walked in ascending category order; each row's
            amount is clipped so it never exceeds what the basis can still
            absorb after the rows already processed.
    Step 3  errors-and-omissions pool, computed on the *gross* basis before the
            expense pool is subtracted; only REGULATORY rows are clipable.
    Step 4  net floored at zero, and only then the supervisory override.
    """
    payout_basis = int(period.get("period_payout_cents") or 0) \
        + int(period.get("true_up_amount_cents") or 0)

    rows = sorted(pass_through_rows(advisor["advisor_code"], period["id"]),
                  key=lambda row: row["category"])

    # Step 2 - expense pool.
    pass_pool = 0
    for row in rows:
        category = row["category"]
        if category not in calc.PASS_THROUGH_FLAT_CENTS:
            # E_AND_O is settled only through the errors-and-omissions pool.
            row["_pass_cents"] = 0
            continue
        # A row already pinned to POSTED keeps its settled amount: re-walking
        # the waterfall must reproduce the pools it recorded, not recompute a
        # different figure now that the period's payout has moved (PRD 3.5).
        if row["status"] == "POSTED":
            amount = int(row.get("amount_cents") or 0)
            row["_pass_cents"] = amount
            pass_pool += amount
            continue
        if row["billing_model"] == "PCT_OF_GROSS":
            amount = round_half_up(dec(payout_basis)
                                   * dec(calc.PASS_THROUGH_PCT_BPS[category]) / dec(10000))
        else:
            amount = calc.PASS_THROUGH_FLAT_CENTS[category]
        amount = min(amount, max(0, payout_basis - pass_pool))
        row["_pass_cents"] = amount
        pass_pool += amount

    # Step 3 - errors-and-omissions pool on the pre-expense basis.
    eo_pool = 0
    eo_rate = calc.EO_RATE_BPS[advisor["eo_coverage_level"]]
    for row in [r for r in rows if r["category"] in ("E_AND_O", "REGULATORY")]:
        if row["status"] == "POSTED":
            amount = int(row.get("_eo_cents") or 0)
            row["_eo_cents"] = amount
            eo_pool += amount
            continue
        amount = round_half_up(dec(payout_basis) * dec(eo_rate) / dec(10000))
        if row["category"] == "REGULATORY":
            amount = min(amount, max(0, payout_basis - pass_pool - eo_pool))
        row["_eo_cents"] = amount
        eo_pool += amount

    # The row's pinned charge is the sum of the pools it participates in.
    for row in rows:
        row["amount_cents"] = int(row.get("_pass_cents") or 0) + int(row.get("_eo_cents") or 0)

    net = payout_basis - pass_pool - eo_pool
    if net < 0:
        net = 0
    override = round_half_up(
        dec(net) * dec(calc.SUPERVISORY_OVERRIDE_BPS[advisor["affiliation_model"]]) / dec(10000))
    return {
        "net_settlement_cents": net,
        "pass_through_cents": pass_pool,
        "eo_charge_cents": eo_pool,
        "supervisory_override_cents": override,
    }


def _compute_settlement_for_period(period):
    codes = {row["advisor_code"] for row in expense_pass_throughs.values()
             if row["payout_period_id"] == period["id"]}
    codes |= {line["advisor_code"] for line in lines_of_period(period["id"])}
    for code in codes:
        advisor = advisor_service.get_by_code_or_fail(code)
        compute_settlement(advisor, period)


def net_settlement(period, data):
    advisor_code = common.require_field(data, "advisor_code")
    advisor = advisor_service.get_by_code_or_fail(advisor_code)
    result = compute_settlement(advisor, period)
    for row in pass_through_rows(advisor_code, period["id"]):
        common.touch(row)
    recompute_period(period)
    return result


# ---------------------------------------------------------------------------
# POST /advisor-payout-lines/{id}/settlement  (BranchManager, AdvisorOps)
# ---------------------------------------------------------------------------

def settle_line(advisor, line, data):
    common.required_version(data, "expected_advisor_version")
    common.check_occ(advisor, "expected_advisor_version", data.get("expected_advisor_version"))
    period = payout_periods.get(line["payout_period_id"])
    if period is None:
        fail("ERR_NOT_FOUND")
    result = compute_settlement(advisor, period)
    line["net_settlement_cents"] = result["net_settlement_cents"]
    common.touch(line)
    advisor_service.bump(advisor)
    return line