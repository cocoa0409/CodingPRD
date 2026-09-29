"""Calculations, rollups and cascade helpers (PRD 2.6, 2.9, 3.1-3.9)."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import store
from auth import touch
from errors import fail

# --- constants (SCAFFOLD 1.3) --------------------------------------------
PCR_BONUS_STEP_PCT = 5
PCR_BONUS_CAP_PCT = 25
REUSE_BONUS_PCT = 15
MAX_NET_BONUS_PCT = -30
MAX_NET_MALUS_PCT = 60
MALUS_BY_CLASS = {
    "READILY_RECYCLABLE": 0,
    "LIMITED": 20,
    "NOT_RECYCLABLE": 60,
}
ADMIN_TIER_BREAK_CENTS = 40000
MEMBERSHIP_FREE_TONNAGE_KG = 500
MEMBERSHIP_SURCHARGE_PER_1000KG_CENTS = 50000
VERIFIER_BUFFER_DAYS = 2
VERIFIER_MAX_CONCURRENT_ENGAGEMENTS = 2

YTD_COUNTED = ("SUBMITTED", "UNDER_VERIFICATION", "VERIFIED", "FINALIZED")
LIVE_MEMBERSHIP = ("ACTIVE", "PROBATION")

ZERO_KG = Decimal("0.000")
ZERO_GRAMS = Decimal("0.00")
ZERO_EXACT = Decimal("0.0000")


def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rh(value, places):
    """Round half up to `places` decimals (PRD 2.6)."""
    quant = Decimal(1).scaleb(-places)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def kg(value):
    return rh(value, 3)


def grams(value):
    return rh(value, 2)


def exact4(value):
    return rh(value, 4)


def whole_cents(value):
    return int(rh(value, 0))


# --- reverse-reachability helpers ----------------------------------------


def skus_of(producer_id):
    return store.by_created([s for s in store.values("skus") if s["producer_id"] == producer_id])


def active_components(sku):
    return [c for c in sku["components"] if c["status"] == "ACTIVE"]


def registrations_of(producer_id):
    return store.by_created(
        [r for r in store.values("registrations") if r["producer_id"] == producer_id]
    )


def reports_of(registration_id):
    return store.by_created(
        [r for r in store.values("reports") if r["registration_id"] == registration_id]
    )


def lines_of(report_id):
    return store.by_created(
        [l for l in store.values("report_lines") if l["packaging_report_id"] == report_id]
    )


def memberships_of(registration_id):
    return store.by_created(
        [m for m in store.values("memberships") if m["registration_id"] == registration_id]
    )


def engagements_of(report_id):
    return store.by_created(
        [e for e in store.values("engagements") if e["packaging_report_id"] == report_id]
    )


def invoices_of(report_id):
    return store.by_created(
        [i for i in store.values("invoices") if i["packaging_report_id"] == report_id]
    )


def live_membership(registration_id):
    """PRD 3.8 eligibility filter with its documented tie-break."""
    rows = [
        m
        for m in store.values("memberships")
        if m["registration_id"] == registration_id and m["status"] in LIVE_MEMBERSHIP
    ]
    if not rows:
        return None
    rows.sort(key=lambda m: (m["created_at"], m["version"]), reverse=True)
    return rows[0]


# --- weight rollups (PRD 3.1, 3.2) ---------------------------------------


def sku_unit_weight(sku):
    total = ZERO_GRAMS
    for comp in active_components(sku):
        total += D(comp["unit_weight_grams"])
    return grams(total)


def recompute_sku_weight(sku):
    sku["unit_packaging_weight_grams"] = sku_unit_weight(sku)
    return sku["unit_packaging_weight_grams"]


def producer_weight(producer_id):
    total = ZERO_KG
    for sku in skus_of(producer_id):
        if sku["status"] != "ACTIVE":
            continue
        contribution = kg(
            D(sku["units_sold_annual_estimate"]) * D(sku["unit_packaging_weight_grams"]) / D(1000)
        )
        total += contribution
    return kg(total)


def recompute_producer_weight(producer):
    """Recompute-from-set; touches the producer only when it is a real mutation."""
    producer["annual_packaging_weight_kg"] = producer_weight(producer["id"])
    touch(producer)
    return producer["annual_packaging_weight_kg"]


def mark_determination_stale(producer):
    if producer["status"] == "OBLIGATION_DETERMINED":
        producer["determination_stale"] = True
    touch(producer)


def line_weight(sku, units_sold):
    total = ZERO_KG
    for comp in active_components(sku):
        total += kg(D(units_sold) * D(comp["unit_weight_grams"]) / D(1000))
    return kg(total)


def recompute_report_rollups(report):
    lines = lines_of(report["id"])
    total = ZERO_KG
    basis = ZERO_KG
    for line in lines:
        total += D(line["line_weight_kg"])
        if not line["fee_exempt"]:
            basis += D(line["line_weight_kg"])
    report["total_weight_kg"] = kg(total)
    report["fee_basis_weight_kg"] = kg(basis)
    report["line_count"] = len(lines)
    return lines


def recompute_ytd(registration):
    total = ZERO_KG
    for report in reports_of(registration["id"]):
        if report["submission_status"] in YTD_COUNTED:
            total += D(report["total_weight_kg"])
    registration["reported_weight_kg_ytd"] = kg(total)
    touch(registration)
    return registration["reported_weight_kg_ytd"]


def recompute_producer_balance(producer):
    total = 0
    reg_ids = set()
    for reg in registrations_of(producer["id"]):
        reg_ids.add(reg["id"])
    for invoice in store.by_created(store.values("invoices")):
        if invoice["status"] != "ISSUED":
            continue
        report = store.get("reports", invoice["packaging_report_id"])
        if report is None or report["registration_id"] not in reg_ids:
            continue
        total += int(invoice["total_cents"])
    producer["assessed_fee_balance_cents"] = total
    touch(producer)
    return total


# --- compliance posture (PRD 3.5) ----------------------------------------


def posture_of(registration):
    status = registration["status"]
    if status in ("DRAFT", "SUBMITTED", "REJECTED", "WITHDRAWN"):
        return "UNDETERMINED"
    if status == "SUSPENDED":
        return "DELINQUENT"
    now = store.clock()
    reports = reports_of(registration["id"])
    for report in reports:
        if report["submission_status"] in ("DRAFT", "BLOCKED"):
            period = store.get("reporting_periods", report["reporting_period_id"])
            if period is not None and period["_submission_deadline"] < now:
                return "DELINQUENT"
    for report in reports:
        if report["submission_status"] == "CORRECTION_REQUIRED":
            return "AT_RISK"
    for report in reports:
        if report["fee_status"] == "VOIDED":
            return "AT_RISK"
    return "COMPLIANT"


def reconcile_memberships(registration):
    verdict = registration["compliance_posture"]
    if verdict == "DELINQUENT":
        return
    for membership in memberships_of(registration["id"]):
        if verdict == "AT_RISK" and membership["status"] == "ACTIVE":
            membership["status"] = "PROBATION"
            touch(membership)
        elif verdict == "COMPLIANT" and membership["status"] == "PROBATION":
            membership["status"] = "ACTIVE"
            touch(membership)


def set_posture(registration):
    verdict = posture_of(registration)
    if registration["compliance_posture"] != verdict:
        registration["compliance_posture"] = verdict
        touch(registration)
    reconcile_memberships(registration)
    return verdict


# --- exemption analysis (PRD 3.5) ----------------------------------------


def group_set(producer):
    """The one-level group of PRD 3.5 GROUP_LEVEL."""
    everyone = store.by_created(store.values("producers"))
    members = {producer["id"]: producer}
    for row in everyone:
        if row["parent_producer_id"] == producer["id"]:
            members[row["id"]] = row
    parent_id = producer["parent_producer_id"]
    if parent_id is not None:
        for row in everyone:
            if row["id"] == parent_id or row["parent_producer_id"] == parent_id:
                members[row["id"]] = row
    return [row for row in everyone if row["id"] in members]


def run_exemption(registration, producer, program):
    basis = program["obligation_basis"]
    actives = [s for s in skus_of(producer["id"]) if s["status"] == "ACTIVE"]
    exempt_categories = program["exempt_product_categories"]
    if actives and all(s["product_category"] in exempt_categories for s in actives):
        registration["exemption_status"] = "EXEMPT_CATEGORY"
        registration["assessed_group_revenue_usd"] = 0
        registration["assessed_group_weight_kg"] = ZERO_KG
        registration["exemption_basis_applied"] = basis
        return
    if basis == "ENTITY_LEVEL":
        revenue = int(producer["annual_gross_revenue_usd"])
        weight = kg(producer["annual_packaging_weight_kg"])
    else:
        revenue = 0
        weight = ZERO_KG
        for row in group_set(producer):
            revenue += int(row["annual_gross_revenue_usd"])
            weight += D(row["annual_packaging_weight_kg"])
        weight = kg(weight)
    if revenue < int(program["small_producer_revenue_threshold_usd"]) and weight < D(
        program["small_producer_tonnage_threshold_kg"]
    ):
        registration["exemption_status"] = "EXEMPT_SMALL_PRODUCER"
    else:
        registration["exemption_status"] = "OBLIGATED"
    registration["assessed_group_revenue_usd"] = revenue
    registration["assessed_group_weight_kg"] = weight
    registration["exemption_basis_applied"] = basis


# --- membership fee (PRD 3.6) --------------------------------------------


def membership_fee(producer, schedule):
    weight = D(producer["annual_packaging_weight_kg"])
    remainder = (weight - D(MEMBERSHIP_FREE_TONNAGE_KG)) / D(1000)
    units = int(math.ceil(remainder))
    if units < 0:
        units = 0
    return int(schedule["membership_fee_cents"]) + units * MEMBERSHIP_SURCHARGE_PER_1000KG_CENTS


# --- eco-modulation and tier selection (PRD 3.8) -------------------------


def eco_modulation(component, comp_weight_kg, rate_cents_per_kg, eco_mod_policy):
    malus_pct = MALUS_BY_CLASS[component["recyclability_class"]]
    pcr_bonus = min(
        PCR_BONUS_CAP_PCT, (int(component["pcr_content_pct"]) // 10) * PCR_BONUS_STEP_PCT
    )
    reuse_bonus = REUSE_BONUS_PCT if component["is_reusable"] else 0
    bonus_pct = pcr_bonus + reuse_bonus
    net_pct = malus_pct - bonus_pct
    net_pct = max(MAX_NET_BONUS_PCT, min(MAX_NET_MALUS_PCT, net_pct))
    if eco_mod_policy == "DISCOUNT_ONLY":
        net_pct = min(net_pct, 0)
    comp_fee_exact = (
        D(comp_weight_kg) * D(rate_cents_per_kg) * (D(1) + D(net_pct) / D(100))
    )
    detail = {
        "material_type": component["material_type"],
        "comp_weight_kg": kg(comp_weight_kg),
        "rate_cents_per_kg": D(rate_cents_per_kg),
        "malus_pct": malus_pct,
        "bonus_pct": bonus_pct,
        "net_pct": net_pct,
        "comp_fee_exact_cents": exact4(comp_fee_exact),
    }
    return comp_fee_exact, detail


def select_rate(schedule, material_type, tier_basis_kg):
    basis = D(tier_basis_kg)
    for row in schedule["material_rates"]:
        if row["material_type"] != material_type:
            continue
        floor_ok = D(row["tier_min_kg"]) <= basis
        ceiling = row["tier_max_kg"]
        ceiling_ok = ceiling is None or basis < D(ceiling)
        if floor_ok and ceiling_ok:
            return row
    return None


# --- report pricing (PRD 3.8) --------------------------------------------


def priced_materials(lines):
    """Material types that must have a rate row: ACTIVE components of non-exempt lines."""
    wanted = []
    for line in lines:
        if line["fee_exempt"]:
            continue
        sku = store.get("skus", line["sku_id"])
        if sku is None:
            continue
        for comp in active_components(sku):
            if comp["material_type"] not in wanted:
                wanted.append(comp["material_type"])
    return wanted


def check_material_rates(schedule, lines, tier_basis_kg):
    for material in priced_materials(lines):
        if select_rate(schedule, material, tier_basis_kg) is None:
            fail(
                "ERR_MATERIAL_RATE_MISSING",
                "The pinned fee schedule has no rate band covering material %s." % material,
            )


def tier_basis_for(variant, registration, report):
    ytd = D(registration["reported_weight_kg_ytd"])
    if variant == "PROVISIONAL":
        return kg(ytd - D(report["total_weight_kg"]))
    return kg(ytd)


def assess_report(report, variant, registration, program, schedule):
    lines = store.by_created(lines_of(report["id"]))
    tier_basis = tier_basis_for(variant, registration, report)
    exact_values = []
    for line in lines:
        if line["fee_exempt"]:
            line["line_fee_exact_cents"] = ZERO_EXACT
            line["line_fee_cents"] = 0
            line["eco_mod_detail"] = []
            exact_values.append(ZERO_EXACT)
            touch(line)
            continue
        sku = store.get("skus", line["sku_id"])
        line_exact = Decimal(0)
        detail_rows = []
        components = sorted(active_components(sku), key=lambda c: c["component_seq"])
        for comp in components:
            comp_weight = kg(D(line["units_sold"]) * D(comp["unit_weight_grams"]) / D(1000))
            row = select_rate(schedule, comp["material_type"], tier_basis)
            if row is None:
                fail("ERR_MATERIAL_RATE_MISSING")
            contribution, detail = eco_modulation(
                comp, comp_weight, row["rate_cents_per_kg"], program["eco_mod_policy"]
            )
            line_exact += contribution
            detail_rows.append(detail)
        line["line_fee_exact_cents"] = exact4(line_exact)
        line["line_fee_cents"] = whole_cents(line["line_fee_exact_cents"])
        line["eco_mod_detail"] = detail_rows
        exact_values.append(line["line_fee_exact_cents"])
        touch(line)
    if program["fee_rounding_order"] == "PER_LINE_THEN_SUM":
        subtotal = 0
        for value in exact_values:
            subtotal += whole_cents(value)
    else:
        running = Decimal(0)
        for value in exact_values:
            running += value
        subtotal = whole_cents(running)
    report["tier_basis_kg"] = tier_basis
    report["fee_subtotal_cents"] = subtotal
    report["fee_variant_applied"] = variant
    report["fee_status"] = variant
    touch(report)
    return report


def fee_breakdown(report, program):
    lines = store.by_created(lines_of(report["id"]))
    line_rows = []
    sum_of_lines = 0
    for line in lines:
        sum_of_lines += int(line["line_fee_cents"])
        line_rows.append(
            {
                "report_line_id": line["id"],
                "sku_id": line["sku_id"],
                "fee_exempt": line["fee_exempt"],
                "line_fee_exact_cents": exact4(line["line_fee_exact_cents"]),
                "line_fee_cents": int(line["line_fee_cents"]),
            }
        )
    return {
        "packaging_report_id": report["id"],
        "tier_basis_kg": kg(report["tier_basis_kg"]),
        "fee_variant_applied": report["fee_variant_applied"],
        "fee_rounding_order_applied": program["fee_rounding_order"],
        "fee_subtotal_cents": int(report["fee_subtotal_cents"]),
        "line_count": len(lines),
        "lines": line_rows,
        "sum_of_line_fee_cents": sum_of_lines,
        "reconciliation_delta_cents": sum_of_lines - int(report["fee_subtotal_cents"]),
    }


# --- invoicing (PRD 3.9) -------------------------------------------------


def admin_fee(fee_subtotal_cents, schedule):
    subtotal = int(fee_subtotal_cents)
    if subtotal < ADMIN_TIER_BREAK_CENTS:
        bps = int(schedule["admin_fee_bps_low"])
    else:
        bps = int(schedule["admin_fee_bps_high"])
    cents = whole_cents(D(subtotal) * D(bps) / D(10000))
    return bps, cents, subtotal + cents


# --- redesign projection (PRD 3.9, non-mutating) --------------------------


def _price_component_set(components, units, schedule, tier_basis_kg, eco_mod_policy):
    total_exact = Decimal(0)
    weight_kg = ZERO_KG
    unit_grams = ZERO_GRAMS
    details = []
    for comp in components:
        comp_weight = kg(D(units) * D(comp["unit_weight_grams"]) / D(1000))
        weight_kg += comp_weight
        unit_grams += D(comp["unit_weight_grams"])
        row = select_rate(schedule, comp["material_type"], tier_basis_kg)
        if row is None:
            fail(
                "ERR_MATERIAL_RATE_MISSING",
                "The named fee schedule has no rate band covering material %s."
                % comp["material_type"],
            )
        contribution, detail = eco_modulation(
            comp, comp_weight, row["rate_cents_per_kg"], eco_mod_policy
        )
        total_exact += contribution
        details.append(detail)
    return {
        "fee_cents": whole_cents(total_exact),
        "line_weight_kg": kg(weight_kg),
        "unit_weight_grams": grams(unit_grams),
        "eco_mod_detail": details,
    }


def redesign_projection(sku, program, schedule, tier_basis_kg, units, candidate_components):
    policy = program["eco_mod_policy"]
    baseline = _price_component_set(
        active_components(sku), units, schedule, tier_basis_kg, policy
    )
    projected = _price_component_set(
        candidate_components, units, schedule, tier_basis_kg, policy
    )
    return {
        "sku_id": sku["id"],
        "state_program_id": program["id"],
        "fee_schedule_id": schedule["id"],
        "tier_basis_kg": kg(tier_basis_kg),
        "eco_mod_policy_applied": policy,
        "projected_units": int(units),
        "baseline_unit_weight_grams": baseline["unit_weight_grams"],
        "baseline_line_weight_kg": baseline["line_weight_kg"],
        "projected_unit_weight_grams": projected["unit_weight_grams"],
        "projected_line_weight_kg": projected["line_weight_kg"],
        "baseline_line_fee_cents": baseline["fee_cents"],
        "projected_line_fee_cents": projected["fee_cents"],
        "fee_delta_cents": projected["fee_cents"] - baseline["fee_cents"],
        "baseline_eco_mod_detail": baseline["eco_mod_detail"],
        "projected_eco_mod_detail": projected["eco_mod_detail"],
        "eco_mod_detail": projected["eco_mod_detail"],
    }


# --- correction cascade helper (PRD 3.7) ---------------------------------


def correction_deadline(period):
    return store.clock() + timedelta(days=int(period["correction_window_days"]))
