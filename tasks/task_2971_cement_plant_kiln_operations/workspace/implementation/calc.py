"""The nine calculations of PRD 3, plus every derived (computed) field.

Precision contract (PRD 2.5): ROUND_HALF_UP everywhere; tonnages/percentages/
energies to 2 decimals, oxide contents to 4, emission intensities to 3.  Where a
formula names a rounding step, the rounded value is what later steps consume.
"""

from datetime import timedelta
from decimal import Decimal

from core import D, ZERO, rnd, r2, r3, r4, now, rows, get_row, ordered

# --- PRD 2.11: the four cement types are constants of the system ------------
CEMENT_TYPES = ["TYPE_I", "TYPE_IL", "TYPE_II", "TYPE_III"]
CEMENT_TYPE_SPECS = {
    "TYPE_I": {"limestone_max_pct": D("5.00"), "so3_max_pct": D("3.00"),
               "blaine_min": 340, "blaine_max": 420, "strength_min": D("28.0")},
    "TYPE_IL": {"limestone_max_pct": D("15.00"), "so3_max_pct": D("3.00"),
                "blaine_min": 380, "blaine_max": 460, "strength_min": D("28.0")},
    "TYPE_II": {"limestone_max_pct": D("5.00"), "so3_max_pct": D("3.00"),
                "blaine_min": 320, "blaine_max": 400, "strength_min": D("28.0")},
    "TYPE_III": {"limestone_max_pct": D("5.00"), "so3_max_pct": D("4.50"),
                 "blaine_min": 500, "blaine_max": 600, "strength_min": D("24.0")},
}

# PRD 2.11 proportioning constants
GYPSUM_MIN_PCT = D("2.00")
GYPSUM_MAX_PCT = D("7.00")
SO3_CLINKER_PCT = D("0.60")
SO3_GYPSUM_PCT = D("46.50")
SO3_LIMESTONE_PCT = D("0.05")

# PRD 3.1 lime saturation coefficients
LSF_COEFF_SIO2 = D("2.8")
LSF_COEFF_AL2O3 = D("1.18")
LSF_COEFF_FE2O3 = D("0.65")

# PRD 3.5 tiered specific heat consumption + kiln feed factor
SHC_TIER_1_MAX = D("600.00")
SHC_TIER_1 = D("4.00")
SHC_TIER_2_MAX = D("900.00")
SHC_TIER_2 = D("3.70")
SHC_TIER_3 = D("3.45")
KILN_FEED_FACTOR = D("1.55")

# PRD 3.6 rolling NOx window
ROLLING_WINDOW_DAYS = 30

# PRD 3.1 revision budget
MAX_DESIGN_REVISIONS = 3

# PRD 3.9 seasonality
PEAK_SEASON_FACTOR = D("1.25")
SHOULDER_SEASON_FACTOR = D("1.00")
OFF_SEASON_FACTOR = D("0.70")
OFF_SEASON_MONTHS = [12, 1, 2]

CATEGORIES_RAW = ["LIMESTONE", "CLAY", "IRON_ORE", "SAND", "ALT_RAW"]
CATEGORIES_FUEL = ["COAL", "PETCOKE", "NATURAL_GAS", "RDF", "TDF", "BIOMASS"]
MATERIAL_KINDS = ["CLINKER", "CEMENT"]
OUTAGE_SCOPES = ["REFRACTORY", "MECHANICAL", "COMBINED"]
TEST_TYPES = ["FREE_LIME", "BLAINE", "COMPRESSIVE_STRENGTH_28D"]
CONTRACT_STATES = ["ACTIVE", "SUSPENDED"]
SILO_STATUSES = ["OPEN", "BLOCKED"]
BURN_DECISIONS = ["AUTHORIZED", "REJECTED"]

OXIDES = ["cao_pct", "sio2_pct", "al2o3_pct", "fe2o3_pct"]


# ===========================================================================
# Calculation 1 — raw_mix_chemical_modules (PRD 3.1 / 3.2)
# ===========================================================================
def _modules_from_oxides(cao, sio2, al2o3, fe2o3):
    """Step 2: the three modules, computed FROM the 4-decimal oxide figures."""
    lsf = sm = am = None
    denom = LSF_COEFF_SIO2 * sio2 + LSF_COEFF_AL2O3 * al2o3 + LSF_COEFF_FE2O3 * fe2o3
    if denom != ZERO:
        lsf = r2(cao / denom * D(100))
    if (al2o3 + fe2o3) != ZERO:
        sm = r2(sio2 / (al2o3 + fe2o3))
    if fe2o3 != ZERO:
        am = r2(al2o3 / fe2o3)
    return lsf, sm, am


def as_designed_chemistry(components):
    """Weighted by mass_fraction_pct, divided by 100, 4 decimals."""
    out = {}
    if not components:
        for oxide in OXIDES:
            out["as_designed_" + oxide] = None
        out["as_designed_lsf"] = None
        out["as_designed_sm"] = None
        out["as_designed_am"] = None
        return out
    quantised = {}
    for oxide in OXIDES:
        total = ZERO
        for comp in components:
            material = get_row("raw_materials", comp.get("raw_material_id"))
            if material is None:
                continue
            total += D(comp["mass_fraction_pct"]) * D(material[oxide])
        value = rnd(total / D(100), 4)
        quantised[oxide] = value
        out["as_designed_" + oxide] = float(value)
    lsf, sm, am = _modules_from_oxides(
        quantised["cao_pct"], quantised["sio2_pct"],
        quantised["al2o3_pct"], quantised["fe2o3_pct"],
    )
    out["as_designed_lsf"] = lsf
    out["as_designed_sm"] = sm
    out["as_designed_am"] = am
    return out


def addition_dry_tonnes(addition):
    """PRD 3.2: per-addition dry tonnage, rounded to 2 decimals at this step."""
    return rnd(
        D(addition["tonnes_as_received"]) * (D(1) - D(addition["moisture_pct"]) / D(100)),
        2,
    )


def pile_chemistry(additions):
    """PRD 3.2: as-received / dry tonnages, alternative share, as-blended oxides."""
    out = {}
    as_received = ZERO
    dry_total = ZERO
    alt_as_received = ZERO
    per_addition = []
    for addition in additions:
        material = get_row("raw_materials", addition["raw_material_id"])
        dry = addition_dry_tonnes(addition)
        per_addition.append((addition, material, dry))
        as_received += D(addition["tonnes_as_received"])
        dry_total += dry
        if material is not None and material.get("is_alternative"):
            alt_as_received += D(addition["tonnes_as_received"])
    as_received_r = rnd(as_received, 2)
    dry_total_r = rnd(dry_total, 2)
    out["as_received_tonnes"] = float(as_received_r)
    out["dry_tonnes"] = float(dry_total_r)
    out["alt_raw_share_pct"] = (
        r2(alt_as_received / as_received_r * D(100)) if as_received_r != ZERO else 0.0
    )
    if dry_total_r == ZERO:
        for oxide in OXIDES:
            out["as_blended_" + oxide] = None
        out["as_blended_lsf"] = None
        out["as_blended_sm"] = None
        out["as_blended_am"] = None
        return out
    quantised = {}
    for oxide in OXIDES:
        total = ZERO
        for addition, material, dry in per_addition:
            if material is None:
                continue
            total += dry * D(material[oxide])
        value = rnd(total / dry_total_r, 4)
        quantised[oxide] = value
        out["as_blended_" + oxide] = float(value)
    lsf, sm, am = _modules_from_oxides(
        quantised["cao_pct"], quantised["sio2_pct"],
        quantised["al2o3_pct"], quantised["fe2o3_pct"],
    )
    out["as_blended_lsf"] = lsf
    out["as_blended_sm"] = sm
    out["as_blended_am"] = am
    return out


def recompute_pile(pile):
    """Recompute every derived figure on a pile from its additions array."""
    pile.update(pile_chemistry(pile["additions"]))
    design = get_row("designs", pile["raw_mix_design_id"])
    if design is not None and pile.get("as_blended_lsf") is not None:
        pile["lsf_deviation"] = r2(
            abs(D(pile["as_blended_lsf"]) - D(design["target_lsf"]))
        )
    else:
        pile["lsf_deviation"] = None
    return pile


# ===========================================================================
# Calculation 3 — clinker_output_from_fuel_energy (PRD 3.5)
# Calculation 4 — thermal_substitution_rate (PRD 3.5)
# Calculation 2 — nox_emission_intensity (PRD 3.5 / 3.6)
# ===========================================================================
def select_effective_shc(provisional):
    provisional = D(provisional)
    if provisional < SHC_TIER_1_MAX:
        return SHC_TIER_1
    if provisional < SHC_TIER_2_MAX:
        return SHC_TIER_2
    return SHC_TIER_3


def charge_energy_gj(tonnes, fuel):
    """Per-charge energy, rounded at this step; all aggregation consumes it."""
    return rnd(D(tonnes) * D(fuel["lhv_gj_per_tonne"]), 2)


def recompute_run_thermal(run, kiln, charges=None):
    """Recompute the whole thermal picture of a run from its fuel charges."""
    charges = run["fuel_charges"] if charges is None else charges
    gross = ZERO
    alt_energy = ZERO
    nox = ZERO
    chlorine = ZERO
    for charge in charges:
        fuel = get_row("fuels", charge["fuel_id"])
        energy = D(charge["energy_gj"])
        gross += energy
        if fuel is not None and fuel.get("is_alternative"):
            alt_energy += energy
        if fuel is not None:
            nox += rnd(
                D(charge["tonnes"]) * D(fuel["lhv_gj_per_tonne"]) * D(fuel["nox_kg_per_gj"]),
                2,
            )
            chlorine += rnd(
                D(charge["tonnes"]) * D(fuel["chlorine_pct"]) / D(100) * D(1000), 2
            )
    gross_r = rnd(gross, 2)
    provisional = rnd(gross_r / D(kiln["nominal_shc_gj_per_tonne"]), 2)
    effective = select_effective_shc(provisional)
    clinker = rnd(gross_r / effective, 2)
    nox_r = rnd(nox, 2)
    chlorine_r = rnd(chlorine, 2)
    tsr = r2(alt_energy / gross_r * D(100)) if gross_r != ZERO else 0.0
    run["gross_energy_gj"] = float(gross_r)
    run["provisional_clinker_tonnes"] = float(provisional)
    run["effective_shc_gj_per_tonne"] = float(effective)
    run["clinker_tonnes"] = float(clinker)
    run["tsr_pct"] = tsr
    run["nox_emitted_kg"] = float(nox_r)
    run["chlorine_input_kg"] = float(chlorine_r)
    return run


def run_nox_intensity(run, plant):
    """Per-run diagnostic intensity + breach flag (never gates anything)."""
    clinker = D(run.get("clinker_tonnes") or 0)
    if clinker == ZERO:
        intensity = 0.0
    else:
        intensity = r3(D(run.get("nox_emitted_kg") or 0) / clinker)
    breach = False
    if plant is not None:
        breach = D(intensity) > D(plant["permit_nox_kg_per_tonne_clinker_cap"])
    return intensity, breach


def plant_kiln_ids(plant_id):
    return set(k["id"] for k in rows("kilns") if k["plant_id"] == plant_id)


def plant_runs(plant_id):
    kiln_ids = plant_kiln_ids(plant_id)
    return [r for r in rows("kiln_runs") if r["kiln_id"] in kiln_ids]


def rolling_nox_intensity(plant):
    """PRD 3.6: 30-day lookback over COMPLETED runs, 3 decimals."""
    horizon = now() - timedelta(days=ROLLING_WINDOW_DAYS)
    clock = now()
    nox_sum = ZERO
    clinker_sum = ZERO
    for run in plant_runs(plant["id"]):
        if run["process_state"] != "COMPLETED":
            continue
        window_end = run["window_end"]
        if window_end < horizon or window_end > clock:
            continue
        nox_sum += D(run.get("nox_emitted_kg") or 0)
        clinker_sum += D(run.get("clinker_tonnes") or 0)
    if clinker_sum == ZERO:
        return 0.0
    return r3(nox_sum / clinker_sum)


def nox_budget_remaining(plant):
    """PRD 2.10 / 3.5: annual allowance minus SCHEDULED+BURNING+COMPLETED runs."""
    consumed = ZERO
    for run in plant_runs(plant["id"]):
        if run["process_state"] in ("SCHEDULED", "BURNING", "COMPLETED"):
            consumed += D(run.get("nox_emitted_kg") or 0)
    return r2(D(plant["permit_annual_nox_budget_kg"]) - consumed)


def applicable_authorization(plant_id, fuel_id):
    """PRD 3.3: AUTHORIZED rows whose window covers the clock; latest valid_from,
    tie broken on the latest created_at."""
    clock = now()
    candidates = []
    for test in rows("burn_tests"):
        if test["plant_id"] != plant_id or test["fuel_id"] != fuel_id:
            continue
        if test["status"] != "AUTHORIZED":
            continue
        if test["valid_from"] is None or test["valid_until"] is None:
            continue
        if test["valid_from"] <= clock < test["valid_until"]:
            candidates.append(test)
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t["valid_from"], t["created_at"]))
    return candidates[-1]


def authorized_rows_exist(plant_id, fuel_id):
    return any(
        t["plant_id"] == plant_id and t["fuel_id"] == fuel_id and t["status"] == "AUTHORIZED"
        for t in rows("burn_tests")
    )


def effective_tsr_ceiling(plant, charges):
    """Tightest of the plant permit and every distinct authorised alt fuel."""
    ceiling = D(plant["permit_max_tsr_pct"])
    seen = set()
    for charge in charges:
        if charge["fuel_id"] in seen:
            continue
        fuel = get_row("fuels", charge["fuel_id"])
        if fuel is None or not fuel.get("is_alternative"):
            continue
        seen.add(charge["fuel_id"])
        auth = applicable_authorization(plant["id"], charge["fuel_id"])
        if auth is None:
            continue
        ceiling = min(ceiling, D(auth["authorized_max_tsr_pct"]))
    return ceiling


# ===========================================================================
# Calculation 5 — cement_additive_proportioning (PRD 3.7)
# ===========================================================================
def proportion_batch(clinker_drawn, gypsum_pct, limestone_pct):
    clinker = D(clinker_drawn)
    gyp = D(gypsum_pct)
    lime = D(limestone_pct)
    denom = D(1) - (gyp + lime) / D(100)
    if denom <= ZERO:
        return None
    total = rnd(clinker / denom, 2)
    gypsum_tonnes = rnd(total * gyp / D(100), 2)
    limestone_tonnes = rnd(total * lime / D(100), 2)
    cement_tonnes = rnd(clinker + gypsum_tonnes + limestone_tonnes, 2)
    if cement_tonnes == ZERO:
        so3 = 0.0
    else:
        so3 = r2(
            (clinker * SO3_CLINKER_PCT
             + gypsum_tonnes * SO3_GYPSUM_PCT
             + limestone_tonnes * SO3_LIMESTONE_PCT) / cement_tonnes
        )
    return {
        "total_batch_tonnes": float(total),
        "gypsum_tonnes": float(gypsum_tonnes),
        "limestone_tonnes": float(limestone_tonnes),
        "cement_tonnes": float(cement_tonnes),
        "so3_pct": so3,
    }


# ===========================================================================
# Calculation 6 — lab_spec_bounds (PRD 3.6)
# ===========================================================================
def lab_spec_bounds(test_type, value, plant=None, batch=None):
    if test_type == "FREE_LIME":
        spec_max = D(plant["clinker_free_lime_max_pct"])
        return {
            "unit": "PCT",
            "spec_min": None,
            "spec_max": float(spec_max),
            "in_spec": D(value) <= spec_max,
        }
    spec = CEMENT_TYPE_SPECS[batch["cement_type"]]
    if test_type == "BLAINE":
        return {
            "unit": "M2_PER_KG",
            "spec_min": spec["blaine_min"],
            "spec_max": spec["blaine_max"],
            "in_spec": D(spec["blaine_min"]) <= D(value) <= D(spec["blaine_max"]),
        }
    return {
        "unit": "MPA",
        "spec_min": float(spec["strength_min"]),
        "spec_max": None,
        "in_spec": D(value) >= spec["strength_min"],
    }


# ===========================================================================
# Calculation 7 — cement_tonne_conservation (PRD 2.9 / 3.9)
# ===========================================================================
def cement_tonne_balance(plant_id):
    silo_ids = set()
    total = ZERO
    for silo in rows("silos"):
        if silo["plant_id"] == plant_id and silo["material_kind"] == "CEMENT":
            silo_ids.add(silo["id"])
            total += D(silo["tonnes_on_hand"])
    for order in rows("orders"):
        if order["cement_silo_id"] in silo_ids and order["status"] == "COMPLETED":
            total += D(order.get("loaded_tonnes") or 0)
    return r2(total)


# ===========================================================================
# Calculation 9 — distribution_plan_waterfall (PRD 3.9)
# ===========================================================================
def seasonal_factor(plant, as_of_month):
    if as_of_month in (plant.get("peak_season_months") or []):
        return PEAK_SEASON_FACTOR
    if as_of_month in OFF_SEASON_MONTHS:
        return OFF_SEASON_FACTOR
    return SHOULDER_SEASON_FACTOR


def eligible_customers(plant):
    return [
        c for c in rows("customers")
        if c["contract_state"] == "ACTIVE"
        and not c["credit_hold"]
        and c["region_code"] == plant["region_code"]
    ]


def available_pool_tonnes(plant_id):
    total = ZERO
    for silo in rows("silos"):
        if (silo["plant_id"] == plant_id
                and silo["material_kind"] == "CEMENT"
                and silo["status"] == "OPEN"):
            total += D(silo_available(silo))
    return r2(total)


def distribution_plan(plant, as_of_month, customers):
    factor = seasonal_factor(plant, as_of_month)
    pool = D(available_pool_tonnes(plant["id"]))
    ranked = sorted(
        customers,
        key=lambda c: (
            -D(c["contract_priority"]),
            -D(c["contract_monthly_tonnes"]),
            c["created_at"],
        ),
    )
    remaining = pool
    allocations = []
    total_allocated = ZERO
    total_shortfall = ZERO
    for customer in ranked:
        demand = rnd(D(customer["contract_monthly_tonnes"]) * factor, 2)
        allocated = rnd(min(demand, remaining), 2)
        shortfall = rnd(demand - allocated, 2)
        remaining = remaining - allocated
        total_allocated += allocated
        total_shortfall += shortfall
        allocations.append({
            "customer_id": customer["id"],
            "contract_priority": customer["contract_priority"],
            "demand_tonnes": float(demand),
            "allocated_tonnes": float(allocated),
            "shortfall_tonnes": float(shortfall),
        })
    return {
        "plant_id": plant["id"],
        "as_of_month": as_of_month,
        "seasonal_factor": float(factor),
        "available_pool_tonnes": float(pool),
        "allocations": allocations,
        "total_allocated_tonnes": r2(total_allocated),
        "total_shortfall_tonnes": r2(total_shortfall),
    }


# ===========================================================================
# Derived (computed) fields on the remaining entities
# ===========================================================================
def silo_available(silo):
    """PRD 2.9: physical minus reserved minus unreleased, 2 decimals."""
    return r2(
        D(silo["tonnes_on_hand"]) - D(silo["reserved_tonnes"]) - D(silo["unreleased_tonnes"])
    )


def kiln_availability_state(kiln):
    """PRD 3.4: derived, never set by a caller."""
    for outage in rows("outages"):
        if outage["kiln_id"] == kiln["id"] and outage["status"] == "IN_PROGRESS":
            return "IN_OUTAGE"
    if kiln["refractory_hours_since_reline"] >= kiln["reline_due_hours"]:
        return "RELINE_DUE"
    return "AVAILABLE"


def active_pile_count(design_id):
    return sum(
        1 for p in rows("piles")
        if p["raw_mix_design_id"] == design_id and p["status"] in ("OPEN", "SEALED")
    )


def newest_lab_test(subject_key, subject_id, test_type):
    matches = [
        t for t in rows("lab_tests")
        if t.get(subject_key) == subject_id and t["test_type"] == test_type
    ]
    if not matches:
        return None
    return ordered(matches)[-1]


def newest_in_spec_lab_test(batch_id, test_type):
    matches = [
        t for t in rows("lab_tests")
        if t.get("cement_batch_id") == batch_id
        and t["test_type"] == test_type
        and t["in_spec"]
    ]
    if not matches:
        return None
    return ordered(matches)[-1]


def run_free_lime_pct(run_id):
    test = newest_lab_test("kiln_run_id", run_id, "FREE_LIME")
    return None if test is None else test["value"]


def customer_open_reserved(customer_id):
    total = ZERO
    for order in rows("orders"):
        if order["customer_id"] == customer_id and order["status"] in ("RESERVED", "LOADING"):
            total += D(order["tonnes"])
    return r2(total)


def customer_lifetime_loaded(customer_id):
    total = ZERO
    for order in rows("orders"):
        if order["customer_id"] == customer_id and order["status"] == "COMPLETED":
            total += D(order.get("loaded_tonnes") or 0)
    return r2(total)


def certificate_allocated(certificate_id):
    """PRD 3.9: sum of tonnes over RESERVED / LOADING / COMPLETED orders."""
    total = ZERO
    for order in rows("orders"):
        if order["mill_certificate_id"] == certificate_id and order["status"] in (
                "RESERVED", "LOADING", "COMPLETED"):
            total += D(order["tonnes"])
    return r2(total)


def batch_certified_allocated(batch):
    """PRD 3.7: sum of certified_tonnes over the batch's DRAFT or ISSUED
    certificates.  PRD 3.9 hop one drops it to 0.00 on decertification."""
    if batch["status"] == "DECERTIFIED":
        return 0.0
    total = ZERO
    for cert in rows("certificates"):
        if cert["cement_batch_id"] == batch["id"] and cert["status"] in ("DRAFT", "ISSUED"):
            total += D(cert["certified_tonnes"])
    return r2(total)


def production_posture(plant_id):
    """PRD 2.12: CONSTRAINED while any batch of the plant is FEED_SHORT."""
    for batch in rows("batches"):
        if batch["plant_id"] == plant_id and batch["feed_state"] == "FEED_SHORT":
            return "CONSTRAINED"
    return "NORMAL"


def demand_season_class(plant, window_start, window_end):
    """PRD 3.4: worst (highest-demand) class among the months the window
    intersects."""
    months = intersected_months(window_start, window_end)
    peak = set(plant.get("peak_season_months") or [])
    if any(m in peak for m in months):
        return "PEAK"
    if months and all(m in OFF_SEASON_MONTHS for m in months):
        return "OFF"
    return "SHOULDER"


def intersected_months(window_start, window_end):
    """Calendar months the [start, end] window touches."""
    months = []
    year, month = window_start.year, window_start.month
    while (year, month) <= (window_end.year, window_end.month):
        months.append(month)
        month += 1
        if month > 12:
            month = 1
            year += 1
    return months
