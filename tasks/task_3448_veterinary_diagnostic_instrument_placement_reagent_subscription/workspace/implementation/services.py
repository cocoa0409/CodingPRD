"""Business logic: pricing resolution, clock sweep, uptime recompute,
and system cascades (breach, recovery, proficiency remediation)."""
import uuid
from datetime import timedelta
from decimal import Decimal

import db
import util
from constants import (
    CALIBRATION_FREE_HOURS_PER_YEAR,
    MIN_MONTHLY_MINIMUM_CENTS,
    PRICE_TABLE,
    QC_VALIDITY_DAYS,
    RESPONSE_SLA_HOURS,
    SHORTFALL_BREACH_THRESHOLD_CENTS,
    UPTIME_BREACH_THRESHOLD_PCT,
    UPTIME_SERVICE_CREDIT_CENTS,
    UPTIME_WINDOW_DAYS,
    UPTIME_WINDOW_HOURS,
)


def new_id():
    return str(uuid.uuid4())


def stamp(e):
    """Set creation-time audit fields on a fresh entity."""
    now = db.now()
    e["id"] = new_id()
    e["created_at"] = util.iso_ms(now)
    e["updated_at"] = util.iso_ms(now)
    e["version"] = 1
    e["_created"] = now
    e["_seq"] = db.next_seq()
    return e


def bump(e):
    """Every mutation: version +1 and updated_at refreshed."""
    e["version"] += 1
    e["updated_at"] = util.iso_ms(db.now())


# ---------------------------------------------------------------- pricing
def resolve_gpa(clinic, now):
    """Candidate selection by clinic membership (corporate precedence), then
    half-open coverage: status ACTIVE and effective_from <= now < effective_to."""
    if clinic.get("corporate_group_code"):
        gtype, code = "CORPORATE", clinic["corporate_group_code"]
    elif clinic.get("buying_group_code"):
        gtype, code = "BUYING", clinic["buying_group_code"]
    else:
        return None
    for g in db.gpas.values():
        if (g["group_type"] == gtype and g["group_code"] == code
                and g["status"] == "ACTIVE"
                and g["_from"] <= now < g["_to"]):
            return g
    return None


def price_order(clinic, agreement, lines, now):
    """Layered per-line price resolution, locked at creation.
    Returns (pricing_detail, final_total_cents, list_total_cents)."""
    gpa = resolve_gpa(clinic, now)
    detail_lines = []
    final_total = 0
    list_total = 0
    for ln in lines:
        sku = ln["sku"]
        qty = ln["quantity"]
        info = PRICE_TABLE[sku]
        lp = info["list_price_cents"]
        if (info["family"] == "QC_MATERIAL"
                and agreement["program_type"] == "REAGENT_COMMITMENT"):
            unit, src = 0, "PROGRAM_INCLUDED"
        elif gpa is not None and sku in gpa["_overrides"]:
            unit, src = gpa["_overrides"][sku], "OVERRIDE"
        elif gpa is not None:
            unit = util.round_cents(util.dec(lp) * (Decimal(1) - gpa["_discount_dec"]))
            src = ("CORPORATE_DISCOUNT" if gpa["group_type"] == "CORPORATE"
                   else "BUYING_DISCOUNT")
        else:
            unit, src = lp, "LIST"
        line_total = unit * qty
        final_total += line_total
        list_total += lp * qty
        detail_lines.append({
            "sku": sku,
            "quantity": qty,
            "unit_price_cents": unit,
            "price_source": src,
            "line_total_cents": line_total,
        })
    return {"lines": detail_lines}, final_total, list_total


# -------------------------------------------------------------- clock sweep
def sweep(now):
    """Pinned order: (1) GPA DRAFT->ACTIVE / ACTIVE->EXPIRED,
    (2) PlacementAgreement term completion/breach, (3) Analyzer QC lapse."""
    for g in util.sorted_items(db.gpas.values()):
        if g["status"] == "DRAFT" and g["_from"] <= now:
            g["status"] = "ACTIVE"
            bump(g)
    for g in util.sorted_items(db.gpas.values()):
        if g["status"] == "ACTIVE" and g["_to"] <= now:
            g["status"] = "EXPIRED"
            bump(g)
    for a in util.sorted_items(db.agreements.values()):
        if a["status"] in ("ACTIVE", "RENEGOTIATION") and now > a["_end"]:
            if a["cumulative_unpaid_billed_cents"] == 0:
                a["proposed_minimum_cents"] = None
                a["status"] = "COMPLETED"
                bump(a)
            elif a["status"] == "ACTIVE":
                a["status"] = "BREACHED"
                bump(a)
                clinic = db.clinics.get(a["clinic_id"])
                if clinic is not None and clinic["status"] == "ACTIVE":
                    clinic["status"] = "SUSPENDED"
                    bump(clinic)
    for an in util.sorted_items(db.analyzers.values()):
        if (an["proficiency_standing"] == "CURRENT"
                and an["_qc_valid_until"] is not None
                and now > an["_qc_valid_until"]):
            an["proficiency_standing"] = "LAPSED"
            bump(an)


# ------------------------------------------------- uptime & service credit
def recompute_uptime(an, now):
    """Recompute both uptime variants over the trailing 90-day window of
    RESOLVED cases (resolved_at >= now - 90d, boundary inclusive).
    Returns the breach variant as a Decimal for the credit comparison."""
    window_start = now - timedelta(days=UPTIME_WINDOW_DAYS)
    qualifying = 0
    calibration = 0
    for c in db.cases.values():
        if (c["analyzer_id"] == an["id"] and c["status"] == "RESOLVED"
                and c["_resolved_at"] is not None
                and c["_resolved_at"] >= window_start):
            qualifying += c["downtime_hours"]
            if c["case_type"] == "PREVENTIVE_CALIBRATION":
                calibration += c["downtime_hours"]
    w = Decimal(UPTIME_WINDOW_HOURS)
    breach = util.round4((w - min(qualifying, UPTIME_WINDOW_HOURS)) / w)
    reported_down = min(
        max(0, qualifying - min(calibration, CALIBRATION_FREE_HOURS_PER_YEAR)),
        UPTIME_WINDOW_HOURS,
    )
    reported = util.round4((w - reported_down) / w)
    an["breach_uptime_pct"] = float(breach)
    an["reported_uptime_pct"] = float(reported)
    return breach


def maybe_credit(an, breach_dec):
    """If the resolve left breach uptime strictly below the threshold, credit
    the analyzer's agreement once. Returns True when a credit landed."""
    if breach_dec < UPTIME_BREACH_THRESHOLD_PCT:
        ag = db.agreements.get(an["agreement_id"])
        if ag is not None:
            ag["service_credit_cents"] += UPTIME_SERVICE_CREDIT_CENTS
            bump(ag)
            return True
    return False


# ---------------------------------------------------- proficiency cascades
def create_remediation_case(an):
    """PROFICIENCY FAIL cascade: system-created ServiceCase, OPEN. Does NOT
    move the analyzer's operational status (only API REPAIR /
    PREVENTIVE_CALIBRATION creation does)."""
    now = db.now()
    c = stamp({
        "analyzer_id": an["id"],
        "case_type": "PROFICIENCY_REMEDIATION",
        "loaner_analyzer_id": None,
        "status": "OPEN",
        "opened_at": util.iso_z(now),
        "_opened_at": now,
        "response_due_at": util.iso_z(now + timedelta(hours=RESPONSE_SLA_HOURS)),
        "_response_due_at": now + timedelta(hours=RESPONSE_SLA_HOURS),
        "_resolved_at": None,
        "downtime_hours": None,
        "sla_met": None,
        "resolution_note": None,
    })
    db.cases[c["id"]] = c
    return c


# ---------------------------------------------------------- period factory
def create_periods(agreement):
    """One OPEN CommitmentPeriod per term month at activation."""
    for ym in util.term_months(agreement["_start"], agreement["term_months"]):
        p = stamp({
            "agreement_id": agreement["id"],
            "period_month": ym,
            "minimum_cents": agreement["monthly_minimum_cents"],
            "fulfilled_cents": None,
            "shortfall_cents": None,
            "billed_cents": None,
            "period_status": "OPEN",
            "billing_status": "NONE",
        })
        db.periods[p["id"]] = p
