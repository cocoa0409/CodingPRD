"""Shared derived-value engine: rolls, support, assessment arithmetic, payment status."""
from decimal import Decimal

import config
import store
from store import rhu_cents, rhu4, set_if_changed, touch


# ---------------------------------------------------------------------------
# collection helpers
# ---------------------------------------------------------------------------
def businesses_of_district(district_id):
    return [b for b in store.state.businesses.values() if b["district_id"] == district_id]


def drives_of_district(district_id):
    return [d for d in store.state.drives.values() if d["district_id"] == district_id]


def open_drives_of_district(district_id):
    return [d for d in drives_of_district(district_id) if d["status"] == "OPEN"]


def signatures_of_drive(drive_id):
    return [s for s in store.state.signatures.values() if s["petition_drive_id"] == drive_id]


def signatures_of_business(business_id):
    return [s for s in store.state.signatures.values() if s["lodging_business_id"] == business_id]


def periods_of_district(district_id):
    return [p for p in store.state.periods.values() if p["district_id"] == district_id]


def statements_of_period(period_id):
    return [s for s in store.state.statements.values() if s["assessment_period_id"] == period_id]


def statements_of_business(business_id):
    return [s for s in store.state.statements.values() if s["lodging_business_id"] == business_id]


def statements_of_district(district_id):
    ids = set(p["id"] for p in periods_of_district(district_id))
    return [s for s in store.state.statements.values() if s["assessment_period_id"] in ids]


def remittances_of_statement(statement_id):
    return [r for r in store.state.remittances.values()
            if r["assessment_statement_id"] == statement_id]


def disputes_of_statement(statement_id):
    return [d for d in store.state.disputes.values()
            if d["assessment_statement_id"] == statement_id]


def disputes_of_business(business_id):
    return [d for d in store.state.disputes.values() if d["lodging_business_id"] == business_id]


def plans_of_district(district_id):
    return [p for p in store.state.plans.values() if p["district_id"] == district_id]


def programs_of_plan(plan_id):
    return [p for p in store.state.programs.values() if p["annual_work_plan_id"] == plan_id]


def programs_of_district(district_id):
    ids = set(p["id"] for p in plans_of_district(district_id))
    return [p for p in store.state.programs.values() if p["annual_work_plan_id"] in ids]


def claims_of_program(program_id):
    return [c for c in store.state.claims.values() if c["marketing_program_id"] == program_id]


def claims_of_business(business_id):
    return [c for c in store.state.claims.values() if c["lodging_business_id"] == business_id]


def records_of_district(district_id):
    return [r for r in store.state.records.values() if r["district_id"] == district_id]


def district_of_plan(plan):
    return store.state.districts[plan["district_id"]]


def plan_of_program(program):
    return store.state.plans[program["annual_work_plan_id"]]


def district_of_program(program):
    return district_of_plan(plan_of_program(program))


def period_of_statement(statement):
    return store.state.periods[statement["assessment_period_id"]]


def business_of_statement(statement):
    return store.state.businesses[statement["lodging_business_id"]]


def district_of_statement(statement):
    return store.state.districts[period_of_statement(statement)["district_id"]]


def statement_of_dispute(dispute):
    return store.state.statements[dispute["assessment_statement_id"]]


# ---------------------------------------------------------------------------
# the assessable set (PRD 3.1)
# ---------------------------------------------------------------------------
def is_assessable_member(business, district):
    return (business["status"] == "ASSESSABLE"
            and business["exempt_status"] == "NONE"
            and business["boundary_zone"] in district["included_zones"])


def assessable_members(district):
    return [b for b in businesses_of_district(district["id"])
            if is_assessable_member(b, district)]


def recompute_district_aggregates(district):
    members = assessable_members(district)
    set_if_changed(district, {
        "assessable_basis_cents": sum(b["prior_year_gross_room_revenue_cents"] for b in members),
        "assessable_business_count": len(members),
    })


def recompute_lodging_tax_committed(district):
    total = sum(p["lodging_tax_matched_cents"] for p in programs_of_district(district["id"])
                if p["status"] != "CANCELLED")
    set_if_changed(district, {"lodging_tax_match_committed_cents": total})


def recompute_district_money(district):
    """collected_to_date_cents and delinquent_charges_cents (PRD 2.12)."""
    statements = statements_of_district(district["id"])
    collected = sum(s["interest_paid_cents"] + s["penalty_paid_cents"]
                    + s["principal_paid_cents"] + s["credit_balance_cents"] for s in statements)
    charges = sum(s["penalty_cents"] + s["interest_cents"] for s in statements)
    set_if_changed(district, {
        "collected_to_date_cents": collected,
        "delinquent_charges_cents": charges,
    })


def rederive_transparency_standing(district):
    """COMPLIANT only when no ANNUAL_REPORT and no FINANCIAL_AUDIT record is OVERDUE."""
    overdue = any(r["status"] == "OVERDUE"
                  and r["record_type"] in ("ANNUAL_REPORT", "FINANCIAL_AUDIT")
                  for r in records_of_district(district["id"]))
    set_if_changed(district, {"transparency_standing": "DEFICIENT" if overdue else "COMPLIANT"})


# ---------------------------------------------------------------------------
# petition support (PRD 3.2)
# ---------------------------------------------------------------------------
def recompute_support(drive):
    district = store.state.districts[drive["district_id"]]
    members = assessable_members(district)
    basis_snapshot = sum(b["prior_year_gross_room_revenue_cents"] for b in members)
    count_snapshot = len(members)

    valid = [s for s in signatures_of_drive(drive["id"]) if s["status"] == "VALID"]
    signed_basis = sum(s["weight_basis_revenue_cents"] for s in valid)
    valid_count = len(valid)

    weighted = (rhu4(Decimal(signed_basis) / Decimal(basis_snapshot))
                if basis_snapshot else Decimal("0.0000"))
    headcount = (rhu4(Decimal(valid_count) / Decimal(count_snapshot))
                 if count_snapshot else Decimal("0.0000"))

    set_if_changed(drive, {
        "assessable_basis_snapshot_cents": basis_snapshot,
        "assessable_count_snapshot": count_snapshot,
        "signed_basis_cents": signed_basis,
        "valid_signature_count": valid_count,
        "weighted_support_pct": weighted,
        "headcount_support_pct": headcount,
    })


def rescore_open_drives(district):
    for drive in open_drives_of_district(district["id"]):
        recompute_support(drive)


def disqualify_signatures(business, reason):
    """Move a property's VALID signatures on OPEN drives to DISQUALIFIED."""
    affected = []
    for sig in signatures_of_business(business["id"]):
        if sig["status"] != "VALID":
            continue
        drive = store.state.drives.get(sig["petition_drive_id"])
        if drive is None or drive["status"] != "OPEN":
            continue
        sig["status"] = "DISQUALIFIED"
        sig["disqualification_reason"] = reason
        touch(sig)
        if drive["id"] not in [d["id"] for d in affected]:
            affected.append(drive)
    for drive in affected:
        recompute_support(drive)


# ---------------------------------------------------------------------------
# property status resolution (PRD 3.1)
# ---------------------------------------------------------------------------
def resolve_business_status(district, exempt_status, room_count, zone):
    """Server-resolved status; the three tests run in the order PRD 3.1 states."""
    if exempt_status != "NONE":
        return "EXEMPT", exempt_status
    if room_count < config.MIN_ROOM_COUNT:
        return "EXEMPT", "UNDER_MINIMUM_ROOMS"
    if zone not in district["included_zones"]:
        return "OUTSIDE_BOUNDARY", exempt_status
    return "ASSESSABLE", exempt_status


def apply_status_cascade(business, district, previous_status):
    """Signature disqualification driven by a property leaving the assessable set."""
    new_status = business["status"]
    if previous_status == "ASSESSABLE" and new_status == "EXEMPT":
        disqualify_signatures(business, "BUSINESS_EXEMPT")
    elif previous_status == "ASSESSABLE" and new_status == "OUTSIDE_BOUNDARY":
        disqualify_signatures(business, "OUTSIDE_BOUNDARY")
    recompute_district_aggregates(district)
    rescore_open_drives(district)


# ---------------------------------------------------------------------------
# assessment arithmetic (PRD 3.3)
# ---------------------------------------------------------------------------
def compute_assessment(method, zone_basis, class_basis, revenue_basis, nights_basis,
                       adjustment_basis):
    revenue_basis = revenue_basis or 0
    nights_basis = nights_basis or 0
    if method == "PCT_OF_ROOM_REVENUE":
        revenue_component = rhu_cents(
            Decimal(revenue_basis) * config.ZONE_RATE[zone_basis]
            * config.CLASS_MULTIPLIER[class_basis])
        floor = nights_basis * config.MIN_FLOOR_PER_NIGHT_CENTS
        gross = max(revenue_component, floor)
    elif method == "PER_OCCUPIED_ROOM_NIGHT":
        gross = rhu_cents(Decimal(nights_basis) * config.PER_NIGHT_RATE_CENTS
                          * config.CLASS_MULTIPLIER[class_basis])
    else:
        gross = rhu_cents(Decimal(config.FLAT_FEE_CENTS[class_basis])
                          * config.ZONE_FACTOR[zone_basis])
    capped = min(gross, config.MAX_ASSESSMENT_CENTS)
    return max(capped - (adjustment_basis or 0), 0)


def compute_provisional(statement):
    """Live zone/classification, reported figures, adjustment basis zero."""
    business = business_of_statement(statement)
    return compute_assessment(
        statement["assessment_method_at_period_start"],
        business["boundary_zone"],
        business["classification"],
        statement["reported_gross_room_revenue_cents"],
        statement["reported_room_nights"],
        0,
    )


def compute_final(statement):
    """Period-start snapshots, audited-else-reported figures, granted adjustment."""
    revenue = statement["audited_gross_room_revenue_cents"]
    if revenue is None:
        revenue = statement["reported_gross_room_revenue_cents"]
    nights = statement["audited_room_nights"]
    if nights is None:
        nights = statement["reported_room_nights"]
    return compute_assessment(
        statement["assessment_method_at_period_start"],
        statement["zone_at_period_start"],
        statement["classification_at_period_start"],
        revenue,
        nights,
        statement["granted_adjustment_cents"],
    )


# ---------------------------------------------------------------------------
# the payment dimension (PRD 3.4)
# ---------------------------------------------------------------------------
def derive_payment_status(statement):
    if statement["final_assessment_cents"] is not None:
        effective = statement["final_assessment_cents"]
    else:
        effective = max(statement["provisional_assessment_cents"]
                        - statement["granted_adjustment_cents"], 0)
    statement["effective_assessment_cents"] = effective

    overpaid = statement["principal_paid_cents"] - effective
    if overpaid > 0:
        statement["credit_balance_cents"] = statement["credit_balance_cents"] + overpaid
        statement["principal_paid_cents"] = effective

    total_due = (effective + statement["penalty_cents"] + statement["interest_cents"]
                 - statement["principal_paid_cents"] - statement["penalty_paid_cents"]
                 - statement["interest_paid_cents"])
    total_due = max(total_due, 0)
    statement["total_due_cents"] = total_due

    if statement["credit_balance_cents"] > 0 and total_due == 0:
        status = "REFUND_DUE"
    elif total_due == 0:
        status = "PAID_IN_FULL"
    elif statement["delinquency_stage"] != "NONE":
        status = "DELINQUENT"
    elif (statement["principal_paid_cents"] + statement["penalty_paid_cents"]
            + statement["interest_paid_cents"]) > 0:
        status = "PARTIALLY_PAID"
    else:
        status = "UNPAID"
    statement["payment_status"] = status
    return status


def recompute_period_billed(period):
    total = sum(s["effective_assessment_cents"] for s in statements_of_period(period["id"]))
    set_if_changed(period, {"billed_total_cents": total})


def recompute_period_totals(period):
    """Used at closure: billed from effective assessments, collected from principal."""
    statements = statements_of_period(period["id"])
    set_if_changed(period, {
        "billed_total_cents": sum(s["effective_assessment_cents"] for s in statements),
        "collected_total_cents": sum(s["principal_paid_cents"] for s in statements),
    })


def grace_deadline(period):
    return store.add_days(period["due_date"], period["grace_days"])


# ---------------------------------------------------------------------------
# the transparency gate (PRD 3.2 / 3.9)
# ---------------------------------------------------------------------------
def transparency_gate(district, require_no_overdue=False):
    """PUBLISHED annual report and financial audit for current_fiscal_year, standing not DEFICIENT."""
    from errors import fail

    if district["transparency_standing"] == "DEFICIENT":
        fail("ERR_TRANSPARENCY_REQUIREMENTS_UNMET",
             "The district's transparency standing is DEFICIENT.")
    records = records_of_district(district["id"])
    for kind in ("ANNUAL_REPORT", "FINANCIAL_AUDIT"):
        if not any(r["record_type"] == kind and r["status"] == "PUBLISHED"
                   and r["fiscal_year"] == district["current_fiscal_year"] for r in records):
            fail("ERR_TRANSPARENCY_REQUIREMENTS_UNMET",
                 "A PUBLISHED %s for fiscal year %s is required."
                 % (kind, district["current_fiscal_year"]))
    if require_no_overdue and any(r["status"] == "OVERDUE" for r in records):
        fail("ERR_TRANSPARENCY_REQUIREMENTS_UNMET",
             "A transparency artifact of this district stands OVERDUE.")


def formation_drive(district_id):
    for drive in sorted(drives_of_district(district_id), key=lambda d: (d["created_at"], d["_seq"])):
        if drive["drive_type"] == "FORMATION":
            return drive
    return None


def withdraw_open_drives(district):
    for drive in open_drives_of_district(district["id"]):
        drive["status"] = "WITHDRAWN"
        touch(drive)
