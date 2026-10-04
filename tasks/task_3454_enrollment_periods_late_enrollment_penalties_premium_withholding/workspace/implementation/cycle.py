"""POST /_ops/run_monthly_cycle — the monthly batch for the clock month.

Order (pinned by PRD §3.7): activation -> window-status recompute ->
invoice issuance -> withholding waterfall -> delinquency/cure/termination ->
election effectivity -> time-based payer recompute -> PROVISIONAL safety net.
"""
from __future__ import annotations

import db
from calcs import PAST_DUE_TERMINATION_THRESHOLD
from clock import (add_months, clock_date, clock_month, days_after,
                   last_day_of_month, month_diff, month_str, parse_due_date,
                   parse_month)
from db import find, find_one, get, make_entity, touch
from domain import (activate_enrollment, invoice_amount_cents,
                    maybe_stop_arrangement, open_payer_record, payer_role_at,
                    apply_payer_role_change, refresh_window_status,
                    tax_record_for, finalize_provisional,
                    terminate_enrollment)


def _issue_invoice(ent: dict, service_ym, amount: int, is_arrears: bool,
                   due) -> None:
    make_entity("invoices", {
        "beneficiary_id": ent["beneficiary_id"],
        "part": ent["part"],
        "service_month": month_str(service_ym),
        "amount_cents": amount,
        "paid_cents": 0,
        "applied_cents": 0,
        "outstanding_cents": amount,
        "due_date": due.isoformat(),
        "is_arrears": is_arrears,
        "status": "ISSUED",
        "_enrollment_id": ent["id"],
    })


def _withholding_waterfall(cm, cdate) -> None:
    """calc_withholding_waterfall: pinned allocation order [PART_B, PART_D]."""
    benef_ids = sorted(
        {a["beneficiary_id"] for a in find(
            "arrangements", lambda a: a["status"] == "ACTIVE")})
    for bid in benef_ids:
        arr = next(a for a in find("arrangements",
                                   lambda a: a["beneficiary_id"] == bid
                                   and a["status"] == "ACTIVE"))
        withholding = [e for e in find(
            "enrollments",
            lambda e: e["beneficiary_id"] == bid
            and e["collection_status"] == "WITHHOLDING"
            and e["enrollment_status"] == "ACTIVE")]
        if not withholding:
            continue
        due = {}
        ent_of = {}
        for e in withholding:
            amt = invoice_amount_cents(bid, e["part"], cm)
            due[e["part"]] = amt if amt is not None else 0
            ent_of[e["part"]] = e
        remaining = arr["monthly_benefit_cents"]
        shortfall = {}
        for part in ("PART_B", "PART_D"):
            if part not in due:
                continue
            pay = min(remaining, due[part])
            remaining -= pay
            short = due[part] - pay
            if short > 0:
                shortfall[part] = short
        if not shortfall:
            continue
        # shortfall cascade: suspend, flip ALL WITHHOLDING enrollments, arrears
        arr["status"] = "SUSPENDED"
        touch(arr)
        for e in withholding:
            e["collection_status"] = "DIRECT_BILL"
            touch(e)
        for part, amount in shortfall.items():
            _issue_invoice(ent_of[part], cm, amount, True,
                           days_after(cdate, 30))


def _delinquency(cm, cdate) -> int:
    """calc_delinquency. Returns count of enrollments terminated."""
    terminated = 0
    targets = find("enrollments",
                   lambda e: e["collection_status"] in ("DIRECT_BILL",
                                                        "DELINQUENT"))
    for ent in targets:
        invs = find("invoices", lambda i: i.get("_enrollment_id") == ent["id"])
        for inv in invs:
            if (inv["status"] == "ISSUED"
                    and parse_due_date(inv["due_date"]) < cdate
                    and inv["outstanding_cents"] > 0):
                inv["status"] = "PAST_DUE"
                touch(inv)
        past_due = [i for i in invs if i["status"] == "PAST_DUE"]
        if len(past_due) >= PAST_DUE_TERMINATION_THRESHOLD:
            terminate_enrollment(ent, cm, write_off=True)
            terminated += 1
        elif len(past_due) >= 1:
            if ent["collection_status"] == "DIRECT_BILL":
                ent["collection_status"] = "DELINQUENT"
                touch(ent)
        else:
            if ent["collection_status"] == "DELINQUENT":
                ent["collection_status"] = "DIRECT_BILL"  # cure
                touch(ent)
    return terminated


def _election_effectivity(cm) -> int:
    """calc_election_effectivity: GOVERNING -> EFFECTIVE with coverage cascade."""
    effectuated = 0
    for el in db.sort_entities(find("elections",
                                    lambda e: e["status"] == "GOVERNING")):
        if month_diff(parse_month(el["effective_month"]), cm) > 0:
            continue
        el["status"] = "EFFECTIVE"
        touch(el)
        effectuated += 1
        bid = el["beneficiary_id"]
        eff_ym = parse_month(el["effective_month"])
        if el["target_coverage"] == "MA":
            make_entity("enrollments", {
                "beneficiary_id": bid,
                "part": "PART_C",
                "enrollment_status": "ACTIVE",
                "collection_status": "NOT_REQUIRED",
                "effective_month": el["effective_month"],
                "end_month": None,
                "enrolled_via_window": el["election_window"],
            })
            for d in find("enrollments",
                          lambda e: e["beneficiary_id"] == bid
                          and e["part"] == "PART_D"
                          and e["enrollment_status"] == "ACTIVE"):
                terminate_enrollment(d, eff_ym)
        else:  # target ORIGINAL
            for c in find("enrollments",
                          lambda e: e["beneficiary_id"] == bid
                          and e["part"] == "PART_C"
                          and e["enrollment_status"] == "ACTIVE"):
                terminate_enrollment(c, eff_ym)
    return effectuated


def run_monthly_cycle() -> dict:
    cm = clock_month()
    cdate = clock_date()
    activated = 0
    issued = 0

    # 1. Activation of due enrollments (with collection resolution)
    for ent in db.sort_entities(find(
            "enrollments", lambda e: e["enrollment_status"] == "PENDING")):
        if month_diff(parse_month(ent["effective_month"]), cm) <= 0:
            activate_enrollment(ent)
            activated += 1

    # 2. Recompute every stored EnrollmentPeriod's status
    for period in find("enrollment_periods", lambda e: True):
        refresh_window_status(period, cm)

    # 3. Invoice issuance: each ACTIVE enrollment being direct-billed.
    # NOTE: DELINQUENT is included — a DIRECT_BILL-only reading makes the
    # pinned ">= 3 PAST_DUE -> termination" rule unreachable (the first
    # PAST_DUE already flips DIRECT_BILL -> DELINQUENT, freezing the count
    # at 1). calc_delinquency only makes sense with continued billing.
    for ent in db.sort_entities(find(
            "enrollments",
            lambda e: e["enrollment_status"] == "ACTIVE"
            and e["collection_status"] in ("DIRECT_BILL", "DELINQUENT"))):
        exists = find_one(
            "invoices",
            lambda i: i["beneficiary_id"] == ent["beneficiary_id"]
            and i["part"] == ent["part"]
            and i["service_month"] == month_str(cm)
            and i["status"] != "CANCELLED")
        if exists:
            continue
        amount = invoice_amount_cents(ent["beneficiary_id"], ent["part"], cm)
        if amount is None:
            continue  # no RateSchedule for the year: skip silently
        _issue_invoice(ent, cm, amount, False, last_day_of_month(cm))
        issued += 1

    # 4. Withholding waterfall (suspension + arrears cascade)
    _withholding_waterfall(cm, cdate)

    # 5. Delinquency advancement, cure, termination
    terminated = _delinquency(cm, cdate)

    # 6. Election effectivity
    effectuated = _election_effectivity(cm)

    # 7. Time-based payer-role recomputation
    for benef in find("beneficiaries", lambda b: True):
        role, basis = payer_role_at(benef["id"], cm)
        open_rec = open_payer_record(benef["id"])
        if open_rec and (open_rec["role"] != role
                         or open_rec["basis"] != basis):
            apply_payer_role_change(benef["id"], role, basis, cm)

    # 8. PROVISIONAL -> FINAL safety-net re-check
    for det in find("determinations", lambda d: d["status"] == "PROVISIONAL"):
        tax_rec = tax_record_for(det["beneficiary_id"], det["coverage_year"] - 2)
        if tax_rec:
            finalize_provisional(det, tax_rec)

    return {
        "cycle_month": month_str(cm),
        "enrollments_activated": activated,
        "invoices_issued": issued,
        "enrollments_terminated": terminated,
        "elections_effectuated": effectuated,
    }
