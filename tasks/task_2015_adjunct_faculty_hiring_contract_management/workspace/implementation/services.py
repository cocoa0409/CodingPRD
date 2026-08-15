"""Business logic: calculations (Table 3), state-machine cascades (Table 2),
and cross-entity side effects. All functions operate on the in-memory STORE."""

from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

import helpers
from helpers import (
    LATE_FLOOR_PCT,
    ONBOARDING_STIPEND_CENTS,
    PRE_CENSUS_PCT,
    TIER_RANK,
    W_COMPLIANCE,
    W_SERVICE,
    W_TEACHING,
    overlap_days,
    parse_date,
    term_by_code,
    today,
    touch,
)
from store import STORE, now_dt, now_iso


def round_half_up_int(value):
    """Round a Decimal to the nearest integer, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Load aggregates (calc: term_load_units)
# ---------------------------------------------------------------------------

def recompute_faculty_load(fac):
    """Recompute current_term_load_units (ACTUAL variant) and benefits_eligible.

    These are computed fields; recomputation does not mutate version.
    """
    term = helpers.current_term()
    if term is None:
        fac["current_term_load_units"] = 0
        fac["benefits_eligible"] = False
        return
    load, eligible = compute_load(fac["id"], term, "actual")
    fac["current_term_load_units"] = load
    fac["benefits_eligible"] = eligible


def compute_load(faculty_id, term, variant):
    """Return (load_units_2dp, benefits_eligible) for a faculty in a term."""
    statuses = ("ISSUED", "ACTIVE") if variant == "scheduled" else ("ACTIVE",)
    total = Decimal("0")
    for c in STORE["contracts"].values():
        if c["faculty_id"] != faculty_id or c["contract_status"] not in statuses:
            continue
        section = STORE["sections"].get(c["section_id"])
        if section is None or section["term_code"] != term["code"]:
            continue
        total += Decimal(str(c["load_units"]))
    load = round_half_up_2dp(total)
    eligible = Decimal(str(load)) >= Decimal(str(term["load_cap_units"]))
    return load, eligible


# ---------------------------------------------------------------------------
# Gross pay (calc: contract_gross_pay)
# ---------------------------------------------------------------------------

def compute_gross_pay(fac, section, term, schedule):
    steps = min(fac["completed_terms"], schedule["longevity_step_cap"])
    effective_rate = schedule["base_rate_cents"] + steps * schedule["longevity_step_cents"]
    if schedule["rate_basis"] == "PER_CONTACT_HOUR":
        days = (parse_date(term["end_date"]) - parse_date(term["start_date"])).days
        term_weeks = days // 7  # whole weeks only
        units = Decimal(str(section["weekly_contact_hours"])) * Decimal(term_weeks)
        gross = Decimal(effective_rate) * units
    else:  # PER_COURSE
        gross = Decimal(effective_rate) * Decimal(1)
    return round_half_up_int(gross)


# ---------------------------------------------------------------------------
# Partial pay on cancellation (calc: cancellation_partial_pay)
# ---------------------------------------------------------------------------

def compute_cancellation_pay(contract, term, cancel_dt):
    """Return (new_status, payable_cents) for a contract being cancelled now."""
    cancel_date = cancel_dt.date()
    early = parse_date(term["early_census_date"])
    gross = contract["gross_pay_cents"]
    if cancel_date < early:
        base = round_half_up_int(Decimal(gross) * Decimal(str(PRE_CENSUS_PCT)))
        return "CANCELLED_PRE_CENSUS", base + ONBOARDING_STIPEND_CENTS
    start = parse_date(term["start_date"])
    end = parse_date(term["end_date"])
    total_days = (end - start).days + 1
    elapsed_days = (cancel_date - start).days + 1
    if elapsed_days < 1:
        elapsed_days = 1
    fraction = Decimal(elapsed_days) / Decimal(total_days)
    earned = round_half_up_int(Decimal(gross) * fraction)
    floor_amt = round_half_up_int(Decimal(gross) * Decimal(str(LATE_FLOOR_PCT)))
    return "CANCELLED_LATE", max(earned, floor_amt)


# ---------------------------------------------------------------------------
# Compliance auto-transition (AdjunctFaculty ONBOARDING -> COMPLIANT)
# ---------------------------------------------------------------------------

def try_auto_compliance(fac):
    if fac["compliance_status"] != "ONBOARDING":
        return
    creds = [
        c for c in STORE["credentials"].values()
        if c["application_id"] == fac["application_id"]
    ]
    has_bg = any(
        c["kind"] == "BACKGROUND_CHECK" and c["verification_status"] == "VERIFIED"
        for c in creds
    )
    has_tr = any(
        c["kind"] == "TRAINING" and c["verification_status"] == "VERIFIED"
        for c in creds
    )
    if has_bg and has_tr:
        fac["compliance_status"] = "COMPLIANT"
        touch(fac)


# ---------------------------------------------------------------------------
# Payroll split schedule (calc: payroll_accrual_split)
# ---------------------------------------------------------------------------

def sorted_overlapping_periods(term):
    start = parse_date(term["start_date"])
    end = parse_date(term["end_date"])
    periods = [
        p for p in STORE["payroll_periods"].values()
        if overlap_days(
            parse_date(p["start_date"]), parse_date(p["end_date"]), start, end
        ) > 0
    ]
    periods.sort(key=lambda p: (p["start_date"], p["_seq"]))
    return periods


def split_variant_for(contract):
    schedule = STORE["rate_schedules"].get(contract["rate_schedule_id"])
    if schedule is not None and schedule["rate_basis"] == "PER_CONTACT_HOUR":
        return "DAYS_WEIGHTED"
    return "EQUAL_SPLIT"


def split_schedule(contract, term, periods):
    """Return (variant, {period_id: cents}) — the full allocation schedule."""
    variant = split_variant_for(contract)
    payable = contract["payable_cents"]
    amounts = {}
    if not periods:
        return variant, amounts
    if variant == "EQUAL_SPLIT":
        n = len(periods)
        base = payable // n  # integer division, discards fractional cents
        remainder = payable - base * n
        for i, p in enumerate(periods):
            amounts[p["id"]] = base + (1 if i < remainder else 0)
    else:  # DAYS_WEIGHTED
        start = parse_date(term["start_date"])
        end = parse_date(term["end_date"])
        days = {
            p["id"]: overlap_days(
                parse_date(p["start_date"]), parse_date(p["end_date"]), start, end
            )
            for p in periods
        }
        total_days = sum(days.values())
        running = 0
        for i, p in enumerate(periods):
            if i == len(periods) - 1:
                amounts[p["id"]] = payable - running
            else:
                if total_days > 0:
                    amt = round_half_up_int(
                        Decimal(payable) * Decimal(days[p["id"]]) / Decimal(total_days)
                    )
                else:
                    amt = 0
                amounts[p["id"]] = amt
                running += amt
    return variant, amounts


def new_payroll_entry(contract_id, period_id, kind, amount, variant, reversal_of=None):
    rec = helpers.new_record(common=False)
    rec.update(
        {
            "contract_id": contract_id,
            "payroll_period_id": period_id,
            "entry_kind": kind,
            "amount_cents": int(amount),
            "split_variant": variant,
            "posted_at": now_iso(),
            "reversal_of_entry_id": reversal_of,
        }
    )
    STORE["payroll_entries"][rec["id"]] = rec
    return rec


def earliest_open_period():
    opens = [
        p for p in STORE["payroll_periods"].values()
        if p["period_status"] == "OPEN"
    ]
    if not opens:
        return None
    opens.sort(key=lambda p: (p["start_date"], p["_seq"]))
    return opens[0]


def reverse_excess_accruals(contract, into_period_id=None):
    """Post CLAWBACK entries reversing prior accruals above the new payable.

    Targets the earliest OPEN period; if none exists and into_period_id is
    given (a period being closed), posts there.
    """
    entries = [
        e for e in STORE["payroll_entries"].values()
        if e["contract_id"] == contract["id"]
    ]
    accruals = [e for e in entries if e["entry_kind"] == "ACCRUAL"]
    total_accrued = sum(e["amount_cents"] for e in accruals)
    excess = total_accrued - contract["payable_cents"]
    if excess <= 0 or not accruals:
        return
    target = earliest_open_period()
    if target is None and into_period_id is not None:
        target = STORE["payroll_periods"].get(into_period_id)
    if target is None:
        return
    variant = split_variant_for(contract)
    accruals.sort(key=lambda e: (e["posted_at"], e["_seq"]))
    remaining = excess
    for acc in reversed(accruals):
        if remaining <= 0:
            break
        take = min(acc["amount_cents"], remaining)
        if take > 0:
            new_payroll_entry(
                contract["id"], target["id"], "CLAWBACK", -take, variant,
                reversal_of=acc["id"],
            )
            remaining -= take


# ---------------------------------------------------------------------------
# Contract cascades (section cancel / complete / activation)
# ---------------------------------------------------------------------------

def cancel_contract(contract, term, cancel_dt, clawback_into_period=None):
    new_status, payable = compute_cancellation_pay(contract, term, cancel_dt)
    contract["contract_status"] = new_status
    contract["cancelled_at"] = now_iso()
    contract["payable_cents"] = payable
    touch(contract)
    if new_status == "CANCELLED_LATE":
        # running-section path: claw back accrued excess
        reverse_excess_accruals(contract, into_period_id=clawback_into_period)


def complete_contract(contract):
    contract["contract_status"] = "COMPLETED"
    contract["payable_cents"] = contract["gross_pay_cents"]
    touch(contract)
    fac = STORE["faculty"].get(contract["faculty_id"])
    if fac is not None:
        fac["completed_terms"] += 1
        fac["updated_at"] = now_iso()  # data mutation without version bump


def void_contract(contract):
    contract["contract_status"] = "VOIDED"
    contract["payable_cents"] = 0
    touch(contract)
    reverse_excess_accruals(contract)
    fac = STORE["faculty"].get(contract["faculty_id"])
    if fac is not None:
        recompute_faculty_load(fac)


def activate_section(section):
    """SCHEDULED -> RUNNING cascade: guarded contract activation."""
    for c in STORE["contracts"].values():
        if c["section_id"] == section["id"] and c["contract_status"] == "ISSUED":
            fac = STORE["faculty"].get(c["faculty_id"])
            if fac is not None and fac["compliance_status"] == "COMPLIANT":
                c["contract_status"] = "ACTIVE"
                touch(c)
                recompute_faculty_load(fac)


def complete_section(section):
    """RUNNING -> COMPLETED cascade."""
    affected = set()
    for c in STORE["contracts"].values():
        if c["section_id"] == section["id"] and c["contract_status"] == "ACTIVE":
            complete_contract(c)
            affected.add(c["faculty_id"])
    for fid in affected:
        fac = STORE["faculty"].get(fid)
        if fac is not None:
            recompute_faculty_load(fac)


def cancel_section(section):
    """Section -> CANCELLED cascade at the census-appropriate tier."""
    term = term_by_code(section["term_code"])
    now = now_dt()
    affected = set()
    for c in STORE["contracts"].values():
        if c["section_id"] == section["id"] and c["contract_status"] in (
            "ISSUED",
            "ACTIVE",
        ):
            cancel_contract(c, term, now)
            affected.add(c["faculty_id"])
    for fid in affected:
        fac = STORE["faculty"].get(fid)
        if fac is not None:
            recompute_faculty_load(fac)


# ---------------------------------------------------------------------------
# Posting close cascade
# ---------------------------------------------------------------------------

def close_posting_cascade(posting):
    for app in STORE["applications"].values():
        if app["posting_id"] == posting["id"] and app["application_status"] == "SUBMITTED":
            app["application_status"] = "EXPIRED"
            touch(app)


# ---------------------------------------------------------------------------
# Clock advancement: auto-close postings, auto-activate sections
# ---------------------------------------------------------------------------

def advance_clock_effects():
    now = now_dt()
    # postings whose close_date final millisecond has passed
    for posting in list(STORE["postings"].values()):
        if posting["posting_status"] in ("OPEN", "SUSPENDED"):
            close_eod = datetime.combine(
                parse_date(posting["close_date"]), time(23, 59, 59, 999000),
                tzinfo=timezone.utc,
            )
            if now > close_eod:
                posting["posting_status"] = "CLOSED"
                touch(posting)
                close_posting_cascade(posting)
    # sections whose term has started
    for section in list(STORE["sections"].values()):
        if section["section_status"] == "SCHEDULED":
            term = term_by_code(section["term_code"])
            if term is None:
                continue
            term_start = datetime.combine(
                parse_date(term["start_date"]), time(0, 0, 0), tzinfo=timezone.utc
            )
            if now >= term_start:
                section["section_status"] = "RUNNING"
                touch(section)
                activate_section(section)


# ---------------------------------------------------------------------------
# Term rollover checkpoint
# ---------------------------------------------------------------------------

def run_rollover(term):
    today_d = today()
    end = parse_date(term["end_date"])
    if today_d > end:
        for section in list(STORE["sections"].values()):
            if (
                section["term_code"] == term["code"]
                and section["section_status"] == "RUNNING"
            ):
                section["section_status"] = "COMPLETED"
                touch(section)
                complete_section(section)
    # lapse idle COMPLIANT faculty
    for fac in list(STORE["faculty"].values()):
        if fac["compliance_status"] != "COMPLIANT":
            continue
        has_contract = False
        for c in STORE["contracts"].values():
            if c["faculty_id"] != fac["id"]:
                continue
            if c["contract_status"] not in ("ACTIVE", "COMPLETED"):
                continue
            section = STORE["sections"].get(c["section_id"])
            if section is not None and section["term_code"] == term["code"]:
                has_contract = True
                break
        if not has_contract:
            fac["compliance_status"] = "LAPSED"
            touch(fac)
    # recompute load aggregates for all faculty
    for fac in list(STORE["faculty"].values()):
        recompute_faculty_load(fac)
    term["rollover_status"] = "ROLLED_OVER"
    touch(term)


# ---------------------------------------------------------------------------
# Payroll close checkpoint
# ---------------------------------------------------------------------------

def run_payroll_close(period):
    p_start = parse_date(period["start_date"])
    p_end = parse_date(period["end_date"])
    for contract in list(STORE["contracts"].values()):
        if contract["contract_status"] not in (
            "ISSUED",
            "ACTIVE",
            "CANCELLED_PRE_CENSUS",
            "CANCELLED_LATE",
            "COMPLETED",
        ):
            continue
        section = STORE["sections"].get(contract["section_id"])
        if section is None:
            continue
        term = term_by_code(section["term_code"])
        if term is None:
            continue
        t_start = parse_date(term["start_date"])
        t_end = parse_date(term["end_date"])
        if overlap_days(p_start, p_end, t_start, t_end) <= 0:
            continue
        periods = sorted_overlapping_periods(term)
        variant, schedule = split_schedule(contract, term, periods)
        # ACCRUAL: this period's slice, if not yet accrued for this period
        already_accrued = any(
            e["contract_id"] == contract["id"]
            and e["payroll_period_id"] == period["id"]
            and e["entry_kind"] == "ACCRUAL"
            for e in STORE["payroll_entries"].values()
        )
        if not already_accrued and period["id"] in schedule:
            slice_amt = schedule[period["id"]]
            posted = sum(
                e["amount_cents"]
                for e in STORE["payroll_entries"].values()
                if e["contract_id"] == contract["id"]
                and e["payroll_period_id"] == period["id"]
                and e["entry_kind"] == "ACCRUAL"
            )
            amt = slice_amt - posted
            if amt != 0:
                new_payroll_entry(
                    contract["id"], period["id"], "ACCRUAL", amt, variant
                )
        # CANCELLATION_PAYOUT for contracts cancelled before this close:
        # payable minus prior accruals minus prior clawbacks. Reconciled at
        # every close (netting prior payouts too) so the running ledger
        # converges to payable_cents exactly even when cancelled contracts
        # keep accruing slices in later-closing periods.
        if contract["contract_status"] in ("CANCELLED_PRE_CENSUS", "CANCELLED_LATE"):
            entries = [
                e
                for e in STORE["payroll_entries"].values()
                if e["contract_id"] == contract["id"]
            ]
            accr = sum(
                e["amount_cents"] for e in entries if e["entry_kind"] == "ACCRUAL"
            )
            claw = sum(
                -e["amount_cents"] for e in entries if e["entry_kind"] == "CLAWBACK"
            )
            prior_payouts = sum(
                e["amount_cents"]
                for e in entries
                if e["entry_kind"] == "CANCELLATION_PAYOUT"
            )
            payout = contract["payable_cents"] - accr + claw - prior_payouts
            if payout != 0:
                new_payroll_entry(
                    contract["id"],
                    period["id"],
                    "CANCELLATION_PAYOUT",
                    payout,
                    variant,
                )


# ---------------------------------------------------------------------------
# Retention (calc: retention_composite_score + retention_list_rank)
# ---------------------------------------------------------------------------

def compute_composite(teaching, service, compliance):
    t = round_half_up_int(Decimal(str(teaching)) * Decimal(str(W_TEACHING)) * 100)
    s = round_half_up_int(Decimal(str(service)) * Decimal(str(W_SERVICE)) * 100)
    c = round_half_up_int(Decimal(str(compliance)) * Decimal(str(W_COMPLIANCE)) * 100)
    return (t + s + c) / 100.0


def latest_prior_evaluation(faculty_id, list_term_code):
    """Most recent evaluation of the faculty whose term_code < list_term_code."""
    cands = [
        e for e in STORE["evaluations"].values()
        if e["faculty_id"] == faculty_id and e["term_code"] < list_term_code
    ]
    if not cands:
        return None
    cands.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return cands[-1]


def rerank_retention_scope(department_id, list_term_code):
    scope = [
        e for e in STORE["retention_entries"].values()
        if e["department_id"] == department_id
        and e["list_term_code"] == list_term_code
        and e["entry_status"] == "LISTED"
    ]

    def sort_key(entry):
        ev = latest_prior_evaluation(entry["faculty_id"], list_term_code)
        fac = STORE["faculty"].get(entry["faculty_id"])
        fac_created = (fac["created_at"], fac["_seq"]) if fac else ("", 0)
        if ev is None:
            return (1, 0.0, 0.0, "", fac_created[0], fac_created[1])
        return (
            0,
            -ev["composite_score"],
            -ev["teaching_score"],
            ev["created_at"],
            ev["_seq"],
            0,
        )

    scope.sort(key=sort_key)
    for i, entry in enumerate(scope):
        entry["rank_position"] = i + 1
        entry["updated_at"] = now_iso()  # computed-field rewrite; no version bump
