"""Shared domain operations: windows, activation, payer coordination,
penalty sync, premium computation, invoice repricing cascades."""
from __future__ import annotations

import db
from calcs import (PARTS_BILLABLE, bracket_for_tier, calc_irmaa_tier,
                   calc_part_b_lep_cents, calc_part_b_periods,
                   calc_part_d_lep_cents)
from clock import (add_months, clock_month, iter_months, month_diff,
                   month_str, parse_month)
from db import find, find_one, get, make_entity, public, touch


# ---------------------------------------------------------------------------
# Enrollment windows
# ---------------------------------------------------------------------------
def derive_window_status(start_ym, end_ym, clock_m) -> str:
    if month_diff(clock_m, start_ym) < 0:
        return "UPCOMING"
    if month_diff(clock_m, end_ym) > 0:
        return "EXPIRED"
    return "OPEN"


def refresh_window_status(period: dict, clock_m) -> None:
    """Clock-derived, never moves backwards (EXPIRED terminal)."""
    if period["status"] == "EXPIRED":
        return
    new = derive_window_status(parse_month(period["window_start_month"]),
                               parse_month(period["window_end_month"]),
                               clock_m)
    if period["status"] == "OPEN" and new == "UPCOMING":
        return
    if new != period["status"]:
        period["status"] = new
        touch(period)


def sep_qualified(beneficiary_id: str, clock_m) -> bool:
    """OPEN SEP row OR a VERIFIED employer record still covering the clock."""
    for p in find("enrollment_periods",
                  lambda e: e["beneficiary_id"] == beneficiary_id
                  and e["window_type"] == "SEP"):
        if (month_diff(clock_m, parse_month(p["window_start_month"])) >= 0
                and month_diff(clock_m, parse_month(p["window_end_month"])) <= 0):
            return True
    for r in find("employer_coverages",
                  lambda e: e["beneficiary_id"] == beneficiary_id
                  and e["verification_status"] == "VERIFIED"):
        if month_diff(clock_m, parse_month(r["coverage_start_month"])) < 0:
            continue
        if r["coverage_end_month"] is None:
            return True
        if month_diff(clock_m, parse_month(r["coverage_end_month"])) <= 0:
            return True
    return False


def governing_window(benef: dict, clock_m):
    """Precedence IEP > SEP > GEP; None when no window governs."""
    if (month_diff(clock_m, parse_month(benef["iep_start_month"])) >= 0
            and month_diff(clock_m, parse_month(benef["iep_end_month"])) <= 0):
        return "IEP"
    if sep_qualified(benef["id"], clock_m):
        return "SEP"
    if clock_m[1] in (1, 2, 3):  # GEP: January 1 through March 31
        return "GEP"
    return None


# ---------------------------------------------------------------------------
# CoverageEnrollment lifecycle
# ---------------------------------------------------------------------------
def active_arrangement(beneficiary_id: str):
    return find_one("arrangements",
                    lambda a: a["beneficiary_id"] == beneficiary_id
                    and a["status"] == "ACTIVE")


def non_stopped_arrangement(beneficiary_id: str):
    rows = find("arrangements",
                lambda a: a["beneficiary_id"] == beneficiary_id
                and a["status"] != "STOPPED")
    rows.sort(key=lambda e: e["_seq"])
    return rows[-1] if rows else None


def resolve_collection(ent: dict) -> str:
    """PENDING_SETUP resolution at activation time."""
    if ent["part"] in ("PART_A", "PART_C"):
        return "NOT_REQUIRED"
    if active_arrangement(ent["beneficiary_id"]):
        return "WITHHOLDING"
    return "DIRECT_BILL"


def activate_enrollment(ent: dict) -> None:
    ent["enrollment_status"] = "ACTIVE"
    ent["collection_status"] = resolve_collection(ent)
    touch(ent)


def maybe_stop_arrangement(beneficiary_id: str) -> None:
    """When the last billable enrollment terminates, arrangement -> STOPPED."""
    arr = non_stopped_arrangement(beneficiary_id)
    if not arr:
        return
    billable = find("enrollments",
                    lambda e: e["beneficiary_id"] == beneficiary_id
                    and e["part"] in PARTS_BILLABLE
                    and e["enrollment_status"] in ("PENDING", "ACTIVE"))
    if not billable:
        arr["status"] = "STOPPED"
        touch(arr)


def terminate_enrollment(ent: dict, end_ym, write_off: bool = False) -> None:
    """ACTIVE -> TERMINATED with the pinned side effects."""
    ent["enrollment_status"] = "TERMINATED"
    ent["end_month"] = month_str(end_ym)
    ent["collection_status"] = "CLOSED"
    touch(ent)
    if write_off:
        for inv in find("invoices",
                        lambda i: i.get("_enrollment_id") == ent["id"]
                        and i["status"] in ("ISSUED", "PAST_DUE")):
            inv["status"] = "WRITTEN_OFF"
            touch(inv)
    maybe_stop_arrangement(ent["beneficiary_id"])


# ---------------------------------------------------------------------------
# Payer coordination (calc_payer_role)
# ---------------------------------------------------------------------------
def payer_role_at(beneficiary_id: str, ym):
    """(role, basis) holding at month ym from VERIFIED employer records."""
    active = []
    for r in find("employer_coverages",
                  lambda e: e["beneficiary_id"] == beneficiary_id
                  and e["verification_status"] == "VERIFIED"):
        if month_diff(ym, parse_month(r["coverage_start_month"])) < 0:
            continue
        if r["coverage_end_month"] is not None and \
                month_diff(ym, parse_month(r["coverage_end_month"])) > 0:
            continue
        active.append(r)
    from calcs import LARGE_EMPLOYER_MIN_SIZE
    if any(r["employer_size"] >= LARGE_EMPLOYER_MIN_SIZE for r in active):
        return ("MEDICARE_SECONDARY", "LARGE_EMPLOYER")
    if active:
        return ("MEDICARE_PRIMARY", "SMALL_EMPLOYER")
    return ("MEDICARE_PRIMARY", "NO_EMPLOYER_COVERAGE")


def open_payer_record(beneficiary_id: str):
    rows = find("payer_records",
                lambda e: e["beneficiary_id"] == beneficiary_id
                and e["effective_end_month"] is None)
    rows.sort(key=lambda e: e["_seq"])
    return rows[-1] if rows else None


def apply_payer_role_change(beneficiary_id: str, role: str, basis: str, ym) -> None:
    """Close the open interval at m-1 (delete if that precedes its start)
    and open the new interval at m — only on an actual change."""
    open_rec = open_payer_record(beneficiary_id)
    if open_rec and open_rec["role"] == role and open_rec["basis"] == basis:
        return
    if open_rec:
        end = add_months(ym, -1)
        if month_diff(end, parse_month(open_rec["effective_start_month"])) < 0:
            db.remove("payer_records", open_rec["id"])
        else:
            open_rec["effective_end_month"] = month_str(end)
            touch(open_rec)
    make_entity("payer_records", {
        "beneficiary_id": beneficiary_id,
        "role": role,
        "basis": basis,
        "effective_start_month": month_str(ym),
        "effective_end_month": None,
    })


# ---------------------------------------------------------------------------
# Late-enrollment penalty basis (calc_lep_gap_months)
# ---------------------------------------------------------------------------
def lep_gap_months(beneficiary_id: str, part: str, effective_ym,
                   exclude_enrollment_id=None) -> int:
    benef = get("beneficiaries", beneficiary_id)
    span_start = add_months(parse_month(benef["iep_end_month"]), 1)
    span_end = add_months(effective_ym, -1)
    if month_diff(span_end, span_start) < 0:
        return 0
    span = list(iter_months(span_start, span_end))
    credit = set()
    # (a) prior same-part CoverageEnrollment half-open intervals [eff, end)
    for e in find("enrollments",
                  lambda x: x["beneficiary_id"] == beneficiary_id
                  and x["part"] == part
                  and x["id"] != exclude_enrollment_id
                  and x["enrollment_status"] != "CANCELLED"):
        s = parse_month(e["effective_month"])
        en = parse_month(e["end_month"]) if e["end_month"] else None
        for m in span:
            if month_diff(m, s) >= 0 and (en is None or month_diff(m, en) < 0):
                credit.add(m)
    # (b) VERIFIED employer coverage months (closed interval); PART_D counts
    #     only records with creditable drug coverage
    for r in find("employer_coverages",
                  lambda x: x["beneficiary_id"] == beneficiary_id
                  and x["verification_status"] == "VERIFIED"):
        if part == "PART_D" and not r["is_drug_coverage_creditable"]:
            continue
        s = parse_month(r["coverage_start_month"])
        en = parse_month(r["coverage_end_month"]) if r["coverage_end_month"] else None
        for m in span:
            if month_diff(m, s) >= 0 and (en is None or month_diff(m, en) <= 0):
                credit.add(m)
    return max(0, len(span) - len(credit))


def active_assessment(beneficiary_id: str, part: str):
    rows = find("penalties",
                lambda p: p["beneficiary_id"] == beneficiary_id
                and p["part"] == part and p["status"] == "ACTIVE")
    rows.sort(key=lambda e: e["_seq"])
    return rows[-1] if rows else None


def sync_penalty(beneficiary_id: str, part: str, effective_ym,
                 exclude_enrollment_id=None) -> None:
    """Create / update-in-place / void the ACTIVE assessment for (b, part)."""
    gap = lep_gap_months(beneficiary_id, part, effective_ym,
                         exclude_enrollment_id=exclude_enrollment_id)
    existing = active_assessment(beneficiary_id, part)
    if part == "PART_B":
        periods, pct = calc_part_b_periods(gap)
        nonzero = pct > 0
    else:
        periods, pct = None, None
        nonzero = gap > 0
    if existing:
        if not nonzero:
            existing["status"] = "VOIDED"
            touch(existing)
        else:
            existing["gap_months"] = gap
            existing["full_12month_periods"] = periods
            existing["penalty_pct"] = pct
            touch(existing)
    elif nonzero:
        make_entity("penalties", {
            "beneficiary_id": beneficiary_id,
            "part": part,
            "gap_months": gap,
            "full_12month_periods": periods,
            "penalty_pct": pct,
            "status": "ACTIVE",
        })


def active_lep_cents(beneficiary_id: str, part: str, schedule: dict) -> int:
    a = active_assessment(beneficiary_id, part)
    if not a:
        return 0
    if part == "PART_B":
        return calc_part_b_lep_cents(a["penalty_pct"],
                                     schedule["part_b_standard_cents"])
    return calc_part_d_lep_cents(a["gap_months"],
                                 schedule["part_d_national_base_cents"])


# ---------------------------------------------------------------------------
# Rate schedules, determinations, invoice amounts
# ---------------------------------------------------------------------------
def rate_schedule_for_year(coverage_year: int):
    return find_one("rate_schedules",
                    lambda r: r["coverage_year"] == coverage_year)


def tax_record_for(beneficiary_id: str, tax_year: int):
    return find_one("tax_records",
                    lambda t: t["beneficiary_id"] == beneficiary_id
                    and t["tax_year"] == tax_year)


def live_determination(beneficiary_id: str, part: str, coverage_year: int):
    rows = find("determinations",
                lambda d: d["beneficiary_id"] == beneficiary_id
                and d["part"] == part
                and d["coverage_year"] == coverage_year
                and d["status"] != "SUPERSEDED")
    rows.sort(key=lambda e: e["_seq"])
    return rows[-1] if rows else None


def invoice_amount_cents(beneficiary_id: str, part: str, service_ym):
    """calc_invoice_amount: determination total, else IRMAA-free base+LEP,
    else None (skip silently when no RateSchedule for the year)."""
    det = live_determination(beneficiary_id, part, service_ym[0])
    if det:
        return det["total_premium_cents"]
    sched = rate_schedule_for_year(service_ym[0])
    if not sched:
        return None
    base = (sched["part_b_standard_cents"] if part == "PART_B"
            else sched["part_d_national_base_cents"])
    return base + active_lep_cents(beneficiary_id, part, sched)


def compute_determination_fields(beneficiary_id: str, part: str,
                                 coverage_year: int, schedule: dict,
                                 magi_override=None):
    """calc_irmaa_tier + calc_total_premium. Pinned evaluation order:
    base -> lep (from base only) -> irmaa surcharge -> exact sum."""
    tax2 = tax_record_for(beneficiary_id, coverage_year - 2)
    tax3 = tax_record_for(beneficiary_id, coverage_year - 3)
    basis = tax2 if tax2 else tax3
    status = "FINAL" if tax2 else "PROVISIONAL"
    tier = calc_irmaa_tier(schedule["irmaa_brackets"], basis["filing_status"],
                           magi_override if magi_override is not None
                           else basis["magi_cents"])
    base = (schedule["part_b_standard_cents"] if part == "PART_B"
            else schedule["part_d_national_base_cents"])
    lep = active_lep_cents(beneficiary_id, part, schedule)
    bracket = bracket_for_tier(schedule["irmaa_brackets"], tier)
    surcharge = (bracket["part_b_surcharge_cents"] if part == "PART_B"
                 else bracket["part_d_surcharge_cents"])
    total = base + surcharge + lep
    return {
        "status": status,
        "tax_year_used": basis["tax_year"],
        "irmaa_tier": tier,
        "base_premium_cents": base,
        "irmaa_surcharge_cents": surcharge,
        "lep_cents": lep,
        "total_premium_cents": total,
    }


def finalize_provisional(det: dict, tax_rec: dict) -> None:
    """PROVISIONAL -> FINAL in place when the coverage_year-2 record arrives.
    tax_year_used / tier / surcharge / total recomputed; lep unchanged."""
    schedule = rate_schedule_for_year(det["coverage_year"])
    tier = calc_irmaa_tier(schedule["irmaa_brackets"],
                           tax_rec["filing_status"], tax_rec["magi_cents"])
    bracket = bracket_for_tier(schedule["irmaa_brackets"], tier)
    surcharge = (bracket["part_b_surcharge_cents"] if det["part"] == "PART_B"
                 else bracket["part_d_surcharge_cents"])
    det["status"] = "FINAL"
    det["tax_year_used"] = tax_rec["tax_year"]
    det["irmaa_tier"] = tier
    det["irmaa_surcharge_cents"] = surcharge
    det["total_premium_cents"] = (det["base_premium_cents"] + surcharge
                                  + det["lep_cents"])
    touch(det)


# ---------------------------------------------------------------------------
# Invoice repricing (shared by equitable relief and appeal redetermination)
# ---------------------------------------------------------------------------
def reprice_invoices(beneficiary_id: str, part: str, affected, amount_for) -> None:
    """affected(service_ym) -> bool; amount_for(service_ym) -> cents | None.

    Unpaid (ISSUED/PAST_DUE) -> CANCELLED + replacement ISSUED at the
    corrected amount. PAID -> applied_cents reduced, difference credited to
    Beneficiary.credit_cents. Conservation invariant preserved per step.
    Arrears invoices (withholding shortfalls) are not premium bills for the
    service month and are left untouched.
    """
    benef = get("beneficiaries", beneficiary_id)
    invoices = db.sort_entities(find(
        "invoices",
        lambda i: i["beneficiary_id"] == beneficiary_id
        and i["part"] == part
        and not i["is_arrears"]
        and i["status"] in ("ISSUED", "PAST_DUE", "PAID")
        and affected(parse_month(i["service_month"]))))
    for inv in invoices:
        corrected = amount_for(parse_month(inv["service_month"]))
        if corrected is None or corrected == inv["amount_cents"]:
            continue
        if inv["status"] in ("ISSUED", "PAST_DUE"):
            inv["status"] = "CANCELLED"
            touch(inv)
            make_entity("invoices", {
                "beneficiary_id": beneficiary_id,
                "part": part,
                "service_month": inv["service_month"],
                "amount_cents": corrected,
                "paid_cents": 0,
                "applied_cents": 0,
                "outstanding_cents": corrected,
                "due_date": inv["due_date"],
                "is_arrears": inv["is_arrears"],
                "status": "ISSUED",
                "_enrollment_id": inv.get("_enrollment_id"),
            })
        else:  # PAID
            new_applied = min(inv["applied_cents"], inv["paid_cents"], corrected)
            if new_applied < inv["applied_cents"]:
                delta = inv["applied_cents"] - new_applied
                inv["applied_cents"] = new_applied
                touch(inv)
                benef["credit_cents"] += delta
                touch(benef)


def reprice_beneficiary_part_invoices(beneficiary_id: str, part: str,
                                      cutoff_ym=None) -> None:
    """Relief invoice rule: service months >= the new effective month (or all
    months for a pure waiver), priced at the replacement determination or the
    IRMAA-free fallback."""
    def affected(ym):
        return cutoff_ym is None or month_diff(ym, cutoff_ym) >= 0

    def amount_for(ym):
        return invoice_amount_cents(beneficiary_id, part, ym)

    reprice_invoices(beneficiary_id, part, affected, amount_for)
