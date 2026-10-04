"""Business engine: calculations (homogeneity, value assignment, uncertainty
budget, shortage allocation, pricing, calibration fees, PT/KC evaluation,
standing) and the multi-resource cascades (publish / withdraw / expire).

Pinned rounding orders (PRD section 2.6):
  * u_c is rounded to 6dp BEFORE being doubled into the expanded uncertainty.
  * the per-unit price is rounded to whole cents BEFORE any quantity multiply.
  * verdict/flag comparisons use the STORED, rounded value.
"""

from datetime import timedelta
from decimal import Decimal

from db import STORE, get_clock
from domain import bump, recompute_standing, units_available
from util import D, q3, q6, round_cents

# Calculation constants (SCAFFOLD calculations table / PRD prose)
F_CRITICAL = Decimal("3.0")
COVERAGE_K = 2
Z_PASS_THRESHOLD = Decimal("2.0")
MIN_KC_RESULTS = 2
TIER_WEIGHTS = {"FEDERAL": 3, "ACCREDITED_LAB": 2, "GENERAL": 1}

ACTIVE_BOOKING_STATES = ("SCHEDULED", "IN_MEASUREMENT", "MEASUREMENT_HOLD")


def first_program():
    """Calibration capacity / expedite multiplier live on 'the program'. The
    calibration order carries no program FK; the configuration context is the
    earliest-created program (tests exercise a single program)."""
    progs = list(STORE["programs"].values())
    if not progs:
        return None
    return min(progs, key=lambda p: p["_seq"])


# ---------------------------------------------------------------------------
# order_pricing / calibration_fee
# ---------------------------------------------------------------------------

def _discount_field(tier):
    return {
        "FEDERAL": "discount_pct_federal",
        "ACCREDITED_LAB": "discount_pct_accredited_lab",
        "GENERAL": "discount_pct_general",
    }[tier]


def unit_price_cents(program, tier):
    """Per-unit price rounded half up to whole cents FIRST (pinned order)."""
    pct = program[_discount_field(tier)]
    raw = D(program["material_unit_price_cents"]) * D(100 - pct) / D(100)
    return round_cents(raw)


def final_fee_cents(order, program):
    if order["expedite_requested"] and program is not None:
        raw = (
            D(order["quoted_fee_cents"])
            * D(program["expedite_multiplier_pct"])
            / D(100)
        )
        return round_cents(raw)
    return order["quoted_fee_cents"]


# ---------------------------------------------------------------------------
# homogeneity_assessment
# ---------------------------------------------------------------------------

def run_homogeneity(lot, bottle_means, within_bottle_std, replicates_per_bottle):
    means = [D(m) for m in bottle_means]
    n = len(means)
    grand_mean = sum(means) / D(n)
    between_var = sum((m - grand_mean) ** 2 for m in means) / D(n - 1)
    within = D(within_bottle_std)
    f_ratio = between_var / (within ** 2)
    f_stored = q6(f_ratio)
    diff = between_var - (within ** 2) / D(replicates_per_bottle)
    u_hom = Decimal(0) if diff <= 0 else diff.sqrt()
    lot["homogeneity_f_ratio"] = f_stored
    lot["homogeneity_u_hom"] = q6(u_hom)
    # comparison against F_CRITICAL uses the stored, rounded value
    lot["homogeneity_verdict"] = "PASS" if f_stored <= F_CRITICAL else "FAIL"
    lot["qc_units_consumed"] += n
    return lot["homogeneity_verdict"]


# ---------------------------------------------------------------------------
# certified_value_assignment + combined_uncertainty_budget
# ---------------------------------------------------------------------------

def accepted_methods(lot_id):
    return [
        m
        for m in STORE["methods"].values()
        if m["lot_id"] == lot_id and m["status"] == "ACCEPTED"
    ]


def compute_certificate_numbers(lot, variant, components):
    methods = accepted_methods(lot["id"])
    if variant == "WEIGHTED_MEAN":
        weights = [Decimal(1) / (D(m["method_std_uncertainty"]) ** 2) for m in methods]
        sw = sum(weights)
        cv = sum(D(m["method_mean"]) * w for m, w in zip(methods, weights)) / sw
        u_char = (Decimal(1) / sw).sqrt()
    else:  # UNWEIGHTED_MEAN
        n = len(methods)
        cv = sum(D(m["method_mean"]) for m in methods) / D(n)
        var = sum((D(m["method_mean"]) - cv) ** 2 for m in methods) / D(n - 1)
        u_char = (var.sqrt() if var > 0 else Decimal(0)) / D(n).sqrt()
    cv_stored = q6(cv)
    u_char_stored = q6(u_char)
    u_hom = lot["homogeneity_u_hom"]
    if u_hom is None:
        u_hom = Decimal(0)
    comp_sq = sum(D(c["std_uncertainty"]) ** 2 for c in components)
    u_c = (u_char_stored ** 2 + D(u_hom) ** 2 + comp_sq).sqrt()
    # pinned rounding order: round u_c to 6dp, store, THEN double
    u_c_stored = q6(u_c)
    expanded = q6(u_c_stored * COVERAGE_K)
    return {
        "certified_value": cv_stored,
        "characterization_uncertainty": u_char_stored,
        "combined_standard_uncertainty": u_c_stored,
        "expanded_uncertainty": expanded,
    }


def published_certificate(lot_id):
    for c in STORE["certificates"].values():
        if c["lot_id"] == lot_id and c["status"] == "PUBLISHED":
            return c
    return None


# ---------------------------------------------------------------------------
# shortage_allocation sweep
# ---------------------------------------------------------------------------

def allocation_sweep(lot, exclude_id=None, include=None):
    """Run the shortage-allocation sweep over the lot's BACKORDERED orders.
    Returns the list of orders the sweep mutated. The sweep only allocates
    while the lot is IN_DISTRIBUTION; a release-triggered sweep excludes the
    released order itself from candidacy."""
    mutated = []
    if lot["status"] != "IN_DISTRIBUTION":
        return mutated
    pool = units_available(lot)
    if pool <= 0:
        return mutated

    def open_need(o):
        return o["quantity"] - o["allocated_quantity"]

    cands = [
        o
        for o in STORE["sales_orders"].values()
        if o["lot_id"] == lot["id"]
        and o["status"] == "BACKORDERED"
        and open_need(o) > 0
        and o["id"] != exclude_id
    ]
    if include is not None and include["id"] != exclude_id and open_need(include) > 0:
        cands.append(include)
    if not cands:
        return mutated

    if lot["allocation_policy"] == "PRO_RATA":
        def weight(o):
            cust = STORE["customers"].get(o["customer_id"])
            return TIER_WEIGHTS.get(cust["tier"], 1) if cust else 1

        total_weighted = sum(weight(o) * open_need(o) for o in cands)
        total_share = 0
        for o in cands:
            share = min(
                open_need(o),
                (pool * weight(o) * open_need(o)) // total_weighted,
            )
            if share > 0:
                o["allocated_quantity"] += share
                lot["units_reserved"] += share
                total_share += share
                if o not in mutated:
                    mutated.append(o)
        leftover = pool - total_share
        cycle = sorted(
            cands,
            key=lambda o: (-weight(o), o["created_at"], o["quantity"], o["_seq"]),
        )
        while leftover > 0:
            progressed = False
            for o in cycle:
                if leftover <= 0:
                    break
                if open_need(o) > 0:
                    o["allocated_quantity"] += 1
                    lot["units_reserved"] += 1
                    leftover -= 1
                    progressed = True
                    if o not in mutated:
                        mutated.append(o)
            if not progressed:
                break
    else:  # FIFO
        cands.sort(key=lambda o: (o["created_at"], o["quantity"], o["_seq"]))
        for o in cands:
            if pool <= 0:
                break
            take = min(open_need(o), pool)
            if take > 0:
                o["allocated_quantity"] += take
                lot["units_reserved"] += take
                pool -= take
                if o not in mutated:
                    mutated.append(o)

    # promotion: any candidate whose allocation reached its full quantity
    for o in cands:
        if o["status"] in ("PLACED", "BACKORDERED") and open_need(o) == 0:
            o["status"] = "ALLOCATED"
            if o not in mutated:
                mutated.append(o)
    return mutated


def sweep_and_bump(lot, exclude_id=None, include=None, include_is_new=False):
    """Run the sweep and bump every pre-existing order it touched (the
    universal mutation rule). Returns (mutated_orders, reserved_changed); the
    caller owns the lot's version bump so each request bumps it exactly once.
    A freshly created order keeps its creation version (the sweep outcome is
    its birth state)."""
    reserved_before = lot["units_reserved"]
    mutated = allocation_sweep(lot, exclude_id=exclude_id, include=include)
    for o in mutated:
        if include_is_new and include is not None and o["id"] == include["id"]:
            continue
        bump(o)
    return mutated, lot["units_reserved"] != reserved_before


# ---------------------------------------------------------------------------
# Certificate lifecycle cascades
# ---------------------------------------------------------------------------

def publish_certificate(cert, actor_user_id):
    now = get_clock()
    cert["published_at"] = now
    cert["expiration_date"] = now + timedelta(days=cert["validity_days"])
    cert["publisher_user_id"] = actor_user_id
    for other in STORE["certificates"].values():
        if (
            other["lot_id"] == cert["lot_id"]
            and other["status"] == "PUBLISHED"
            and other["id"] != cert["id"]
        ):
            other["status"] = "SUPERSEDED"
            bump(other)
            cert["supersedes_certificate_id"] = other["id"]
    cert["status"] = "PUBLISHED"
    bump(cert)
    lot = STORE["lots"][cert["lot_id"]]
    if lot["status"] == "CERTIFICATION_PENDING":
        lot["status"] = "CERTIFIED"
        bump(lot)
    elif lot["status"] == "DISTRIBUTION_HOLD":
        lot["status"] = "IN_DISTRIBUTION"
        lot["hold_reason"] = None
        mutated = allocation_sweep(lot)
        bump(lot)
        for o in mutated:
            bump(o)
    else:
        # publication advances the lot version even when its state stays put
        bump(lot)


def withdraw_certificate(cert):
    was = cert["status"]
    cert["status"] = "WITHDRAWN"
    bump(cert)
    lot = STORE["lots"][cert["lot_id"]]
    if was == "DRAFT":
        if lot["status"] == "CERTIFICATION_PENDING":
            lot["status"] = "VALUE_ASSIGNMENT"
            bump(lot)
    elif was == "PUBLISHED":
        if lot["status"] == "IN_DISTRIBUTION":
            lot["status"] = "DISTRIBUTION_HOLD"
            lot["hold_reason"] = "CERTIFICATE_WITHDRAWN"
            bump(lot)


def expiration_sweep():
    """PUBLISHED certificates whose expiration_date has been reached become
    EXPIRED; a lot caught IN_DISTRIBUTION drops to DISTRIBUTION_HOLD with
    hold_reason CERTIFICATE_EXPIRED. Returns (expired_count, lot_hold_count)."""
    now = get_clock()
    expired = 0
    held = 0
    for cert in list(STORE["certificates"].values()):
        if (
            cert["status"] == "PUBLISHED"
            and cert["expiration_date"] is not None
            and cert["expiration_date"] <= now
        ):
            cert["status"] = "EXPIRED"
            bump(cert)
            expired += 1
            lot = STORE["lots"][cert["lot_id"]]
            if lot["status"] == "IN_DISTRIBUTION":
                lot["status"] = "DISTRIBUTION_HOLD"
                lot["hold_reason"] = "CERTIFICATE_EXPIRED"
                bump(lot)
                held += 1
    return expired, held


# ---------------------------------------------------------------------------
# PT / KC evaluation and reopen compensation
# ---------------------------------------------------------------------------

def evaluate_round(rnd):
    results = [
        r
        for r in STORE["pt_results"].values()
        if r["round_id"] == rnd["id"] and r["status"] == "SUBMITTED"
    ]
    results.sort(key=lambda r: (r["created_at"], r["_seq"]))
    if rnd["round_type"] == "PROFICIENCY_TEST":
        cert = published_certificate(rnd["lot_id"])
        assigned = D(cert["certified_value"])
        ref_unc = D(cert["expanded_uncertainty"])
        rnd["assigned_value"] = q6(assigned)
        rnd["reference_uncertainty"] = q6(ref_unc)
        rnd["chi_squared"] = None
        rnd["consistency_verdict"] = None
        for r in results:
            diff = D(r["measured_value"]) - assigned
            if ref_unc == 0:
                z = Decimal(0) if diff == 0 else Decimal("999999.999") * (
                    1 if diff > 0 else -1
                )
            else:
                z = diff / ref_unc
            z_stored = q3(z)
            r["z_score"] = z_stored
            r["degree_of_equivalence"] = None
            r["equivalence_uncertainty"] = None
            # flag compares the stored, rounded z_score against the threshold
            flag = "PASS" if abs(z_stored) <= Z_PASS_THRESHOLD else "FAIL"
            r["performance_flag"] = flag
            r["status"] = "EVALUATED"
            bump(r)
            if flag == "FAIL":
                cust = STORE["customers"].get(r["customer_id"])
                if cust is not None:
                    cust["pt_fail_count"] += 1
                    recompute_standing(cust)
                    bump(cust)
        rnd["evaluated_count"] = len(results)
    else:  # KEY_COMPARISON
        weights = [Decimal(1) / (D(r["measurement_uncertainty"]) ** 2) for r in results]
        sw = sum(weights)
        x_ref = sum(D(r["measured_value"]) * w for r, w in zip(results, weights)) / sw
        u_ref = (Decimal(1) / sw).sqrt()
        x_ref_stored = q6(x_ref)
        u_ref_stored = q6(u_ref)
        chi = sum(
            ((D(r["measured_value"]) - x_ref_stored) / D(r["measurement_uncertainty"])) ** 2
            for r in results
        )
        chi_stored = q6(chi)
        n = len(results)
        rnd["assigned_value"] = x_ref_stored
        rnd["reference_uncertainty"] = u_ref_stored
        rnd["chi_squared"] = chi_stored
        # consistency compares the stored, rounded chi-squared
        rnd["consistency_verdict"] = (
            "CONSISTENT" if chi_stored <= D(n - 1) else "INCONSISTENT"
        )
        for r in results:
            ui = D(r["measurement_uncertainty"])
            d_stored = q6(D(r["measured_value"]) - x_ref_stored)
            u_stored = q6(D(COVERAGE_K) * (ui ** 2 + u_ref_stored ** 2).sqrt())
            r["z_score"] = None
            r["degree_of_equivalence"] = d_stored
            r["equivalence_uncertainty"] = u_stored
            r["performance_flag"] = (
                "PASS" if abs(d_stored) <= u_stored else "FAIL"
            )
            r["status"] = "EVALUATED"
            bump(r)
        rnd["evaluated_count"] = n


def reopen_round(rnd):
    results = [
        r
        for r in STORE["pt_results"].values()
        if r["round_id"] == rnd["id"] and r["status"] == "EVALUATED"
    ]
    for r in results:
        was_fail = r["performance_flag"] == "FAIL"
        r["status"] = "SUBMITTED"
        r["z_score"] = None
        r["degree_of_equivalence"] = None
        r["equivalence_uncertainty"] = None
        r["performance_flag"] = None
        bump(r)
        if rnd["round_type"] == "PROFICIENCY_TEST" and was_fail:
            cust = STORE["customers"].get(r["customer_id"])
            if cust is not None:
                cust["pt_fail_count"] -= 1
                recompute_standing(cust)
                bump(cust)
    rnd["assigned_value"] = None
    rnd["reference_uncertainty"] = None
    rnd["chi_squared"] = None
    rnd["consistency_verdict"] = None
    rnd["evaluated_count"] = 0
