"""Derived values: water-quality statistics, eligibility, husbandry currency,
counter recomputation, time-to-temperature, the vibrio allowance, lease
settlement and the illness traceback scope.  All of PRD 2.9 / 3.2 / 3.6 / 3.8.
"""

from datetime import timedelta
from decimal import Decimal

from core import (
    ADVERSE_WINDOW_HOURS,
    GEOMEAN_APPROVED_LIMIT,
    GEOMEAN_RESTRICTED_LIMIT,
    INSPECTION_FEE_CENTS,
    INSPECTION_FEE_WAIVER_CENTS,
    INSPECTION_MAX_AGE_DAYS,
    INTERTIDAL_PENALTY_MINUTES,
    MIN_FLOOR_MINUTES,
    MIN_SAMPLES_FOR_DECISION,
    P90_APPROVED_LIMIT,
    P90_RESTRICTED_LIMIT,
    P90_Z,
    PREDATOR_CONTROL_MAX_AGE_DAYS,
    REFRIGERATION_CREDIT_MINUTES,
    SAMPLE_WINDOW_SIZE,
    SURCHARGE_RATE,
    TIER1_MAX_BUSHELS,
    TIER1_RATE_CENTS,
    TIER2_MAX_BUSHELS,
    TIER2_RATE_CENTS,
    TIER3_RATE_CENTS,
    TRACEBACK_DAY_WINDOW,
    apply_changes,
    clock,
    db,
    q,
    truncated_minutes,
)

# --------------------------------------------------------------------------
# Collection helpers
# --------------------------------------------------------------------------
def area_samples(area_id):
    return [s for s in db.water_samples.values() if s["growing_area_id"] == area_id]


def area_rainfall_events(area_id):
    return [r for r in db.rainfall_events.values() if r["growing_area_id"] == area_id]


def lease_units(lease_id):
    return [u for u in db.growout_units.values() if u["lease_id"] == lease_id]


def seed_lot_units(seed_lot_id):
    return [u for u in db.growout_units.values() if u["seed_lot_id"] == seed_lot_id]


def unit_logs(unit_id):
    return [l for l in db.husbandry_logs.values() if l["growout_unit_id"] == unit_id]


def unit_authorizations(unit_id):
    return [
        a for a in db.authorizations.values() if a["growout_unit_id"] == unit_id
    ]


def authorization_lots(authorization_id):
    return [
        l
        for l in db.harvest_lots.values()
        if l["harvest_authorization_id"] == authorization_id
    ]


def lease_lots(lease_id):
    rows = []
    for lot in db.harvest_lots.values():
        auth = db.authorizations.get(lot["harvest_authorization_id"])
        if auth is not None and auth["lease_id"] == lease_id:
            rows.append(lot)
    return rows


def dealer_shipments(dealer_id):
    return [s for s in db.shipments.values() if s["dealer_id"] == dealer_id]


def shipment_lots(shipment_id):
    return [l for l in db.harvest_lots.values() if l["shipment_id"] == shipment_id]


def area_authorizations(area_id):
    return [
        a for a in db.authorizations.values() if a["growing_area_id"] == area_id
    ]


def lot_lease(lot):
    auth = db.authorizations.get(lot["harvest_authorization_id"])
    if auth is None:
        return None
    return db.leases.get(auth["lease_id"])


def lot_area(lot):
    auth = db.authorizations.get(lot["harvest_authorization_id"])
    if auth is None:
        return None
    return db.growing_areas.get(auth["growing_area_id"])


# --------------------------------------------------------------------------
# Per-sample derived flags (PRD 3.2)
# --------------------------------------------------------------------------
def is_adverse_condition(sample):
    """True when the sample sits inside the 120-hour window after a
    closure-triggering rainfall event for the same area."""
    collected = sample["collected_at"].replace(microsecond=0)
    for event in area_rainfall_events(sample["growing_area_id"]):
        if not event["triggered_closure"]:
            continue
        observed = event["observed_at"].replace(microsecond=0)
        if observed <= collected <= observed + timedelta(hours=ADVERSE_WINDOW_HOURS):
            return True
    return False


def counted_clean(sample, area=None):
    if area is None:
        area = db.growing_areas.get(sample["growing_area_id"])
    if area is None:
        return False
    if sample["sample_status"] != "ACCEPTED":
        return False
    closure = area["last_closure_started_at"]
    if closure is None:
        return False
    if not (
        sample["collected_at"].replace(microsecond=0)
        > closure.replace(microsecond=0)
    ):
        return False
    return sample["fecal_coliform_mpn"] <= area["clean_sample_mpn_limit"]


# --------------------------------------------------------------------------
# The statistics window and the six computation steps (PRD 3.2, 2.9)
# --------------------------------------------------------------------------
def _sample_order_key(sample):
    return (sample["collected_at"], sample["created_at"], sample["id"])


def statistics_window(area, variant="SYSTEMATIC_RANDOM"):
    rows = [
        s
        for s in area_samples(area["id"])
        if s["sample_status"] == "ACCEPTED"
    ]
    if variant == "ADVERSE_CONDITION":
        rows = [s for s in rows if is_adverse_condition(s)]
    rows.sort(key=_sample_order_key)
    if len(rows) > SAMPLE_WINDOW_SIZE:
        rows = rows[-SAMPLE_WINDOW_SIZE:]
    return rows


def eligible_from_statistics(window_count, geometric_mean, p90):
    if window_count < MIN_SAMPLES_FOR_DECISION:
        return "INSUFFICIENT_DATA"
    if geometric_mean <= GEOMEAN_APPROVED_LIMIT and p90 <= P90_APPROVED_LIMIT:
        return "APPROVED"
    if geometric_mean <= GEOMEAN_RESTRICTED_LIMIT and p90 <= P90_RESTRICTED_LIMIT:
        return "RESTRICTED"
    return "PROHIBITED"


def compute_statistics(area, variant="SYSTEMATIC_RANDOM"):
    """Returns the eight-field statistics bundle for the requested variant."""
    window = statistics_window(area, variant)
    count = len(window)
    if count == 0:
        return {
            "variant": variant,
            "sample_count": 0,
            "mean_log10": None,
            "geometric_mean_mpn": None,
            "p90_mpn": None,
            "eligible_classification": "INSUFFICIENT_DATA",
            "window_start_at": None,
            "window_end_at": None,
        }
    # Step 2: per-sample log10 rounded half-up to 4 places.
    logs = [q(Decimal(s["fecal_coliform_mpn"]).log10(), 4) for s in window]
    # Step 3: mean of those logarithms, rounded half-up to 4 places.
    total = Decimal(0)
    for value in logs:
        total = total + value
    mean_log = q(total / Decimal(count), 4)
    # Step 4: geometric mean, rounded half-up to 1 place.
    geometric_mean = q(Decimal(10) ** mean_log, 1)
    # Step 5: sample standard deviation of the rounded logarithms, 4 places.
    if count < 2:
        sd = Decimal("0.0000")
    else:
        acc = Decimal(0)
        for value in logs:
            diff = value - mean_log
            acc = acc + (diff * diff)
        sd = q((acc / Decimal(count - 1)).sqrt(), 4)
    # Step 6: estimated 90th percentile, rounded half-up to 1 place.
    p90 = q(Decimal(10) ** (mean_log + (P90_Z * sd)), 1)
    return {
        "variant": variant,
        "sample_count": count,
        "mean_log10": mean_log,
        "geometric_mean_mpn": geometric_mean,
        "p90_mpn": p90,
        "eligible_classification": eligible_from_statistics(
            count, geometric_mean, p90
        ),
        "window_start_at": window[0]["collected_at"],
        "window_end_at": window[-1]["collected_at"],
    }


def consecutive_clean_run(area):
    """The clean-sample run measured backwards from the newest post-closure
    sample (PRD 3.3)."""
    closure = area["last_closure_started_at"]
    if closure is None:
        return 0
    closure = closure.replace(microsecond=0)
    rows = [
        s
        for s in area_samples(area["id"])
        if s["sample_status"] == "ACCEPTED"
        and s["collected_at"].replace(microsecond=0) > closure
    ]
    rows.sort(key=_sample_order_key)
    limit = area["clean_sample_mpn_limit"]
    run = 0
    for sample in reversed(rows):
        if sample["fecal_coliform_mpn"] <= limit:
            run += 1
        else:
            break
    return run


def accepted_sample_count(area):
    return len(
        [s for s in area_samples(area["id"]) if s["sample_status"] == "ACCEPTED"]
    )


def recompute_area_statistics(area):
    """Refresh the persisted SYSTEMATIC_RANDOM statistics and counters."""
    stats = compute_statistics(area, "SYSTEMATIC_RANDOM")
    return apply_changes(
        area,
        {
            "accepted_sample_count": accepted_sample_count(area),
            "geometric_mean_mpn": stats["geometric_mean_mpn"],
            "p90_mpn": stats["p90_mpn"],
            "eligible_classification": stats["eligible_classification"],
            "consecutive_clean_samples": consecutive_clean_run(area),
        },
    )


def recompute_open_authorization_count(area):
    count = 0
    for auth in area_authorizations(area["id"]):
        if auth["status"] in ("ISSUED", "ACTIVE"):
            count += 1
    return apply_changes(area, {"open_authorization_count": count})


# --------------------------------------------------------------------------
# Husbandry currency (PRD 3.6)
# --------------------------------------------------------------------------
def recompute_unit_husbandry(unit):
    logs = unit_logs(unit["id"])
    inspections = [l for l in logs if l["log_type"] == "INSPECTION"]
    predator = [l for l in logs if l["log_type"] == "PREDATOR_CONTROL"]
    last_inspection = None
    if inspections:
        last_inspection = max(l["performed_at"] for l in inspections)
    last_predator = None
    if predator:
        last_predator = max(l["performed_at"] for l in predator)
    total = 0
    for entry in logs:
        total += entry["mortality_count"]
    return apply_changes(
        unit,
        {
            "last_inspection_at": last_inspection,
            "last_predator_control_at": last_predator,
            "mortality_count_total": total,
        },
    )


def inspection_current(unit):
    moment = unit["last_inspection_at"]
    if moment is None:
        return False
    elapsed = clock.now().replace(microsecond=0) - moment.replace(microsecond=0)
    return elapsed <= timedelta(days=INSPECTION_MAX_AGE_DAYS)


def predator_control_current(unit):
    if unit["gear_type"] != "BOTTOM":
        return True
    moment = unit["last_predator_control_at"]
    if moment is None:
        return False
    elapsed = clock.now().replace(microsecond=0) - moment.replace(microsecond=0)
    return elapsed <= timedelta(days=PREDATOR_CONTROL_MAX_AGE_DAYS)


def husbandry_current(unit):
    return inspection_current(unit) and predator_control_current(unit)


# --------------------------------------------------------------------------
# Lease, seed-lot, vessel and authorization counters
# --------------------------------------------------------------------------
def recompute_lease_gear(lease):
    total = 0
    for unit in lease_units(lease["id"]):
        if unit["status"] in ("DEPLOYED", "HARVESTING"):
            total += unit["gear_units"]
    return apply_changes(lease, {"deployed_gear_units": total})


def recompute_lease_royalty(lease):
    total = 0
    for lot in lease_lots(lease["id"]):
        if lot["status"] != "VOIDED":
            total += lot["lot_settlement_cents"] or 0
    return apply_changes(lease, {"royalty_accrued_cents": total})


def recompute_seed_allocation(seed_lot):
    """Allocation counters plus the READY_FOR_PLANTING <-> PLANTED bubble-up."""
    allocated = 0
    for unit in seed_lot_units(seed_lot["id"]):
        if unit["status"] in ("DEPLOYED", "HARVESTING", "RETRIEVED"):
            allocated += unit["seed_count_planted"]
    surviving = seed_lot["surviving_seed_count"]
    if surviving is None:
        unallocated = 0
    else:
        unallocated = surviving - allocated
    changes = {
        "allocated_seed_count": allocated,
        "unallocated_seed_count": unallocated,
    }
    status = seed_lot["status"]
    if status == "READY_FOR_PLANTING" and unallocated == 0 and surviving is not None:
        changes["status"] = "PLANTED"
    elif status == "PLANTED" and unallocated > 0:
        changes["status"] = "READY_FOR_PLANTING"
    return apply_changes(seed_lot, changes)


def recompute_authorization_volume(authorization):
    total = 0
    for lot in authorization_lots(authorization["id"]):
        if lot["status"] != "VOIDED":
            total += lot["bushels"]
    return apply_changes(authorization, {"harvested_bushels": total})


def vessel_load(vessel_id, window_start, window_end):
    """Aggregate count of live authorizations on the vessel whose half-open
    windows overlap [window_start, window_end) (PRD 3.7)."""
    count = 0
    for auth in db.authorizations.values():
        if auth["vessel_id"] != vessel_id:
            continue
        if auth["status"] not in ("ISSUED", "ACTIVE"):
            continue
        if (
            auth["window_start"].replace(microsecond=0) < window_end.replace(microsecond=0)
            and window_start.replace(microsecond=0) < auth["window_end"].replace(microsecond=0)
        ):
            count += 1
    return count


# --------------------------------------------------------------------------
# Plot occupancy and the fallow window (PRD 3.6)
# --------------------------------------------------------------------------
def unit_effective_end(unit):
    if unit["status"] == "RETRIEVED":
        return unit["retrieved_on"]
    return unit["planned_retrieval_on"]


def plot_occupants(lease_id, plot_code):
    rows = []
    for unit in lease_units(lease_id):
        if unit["plot_code"] != plot_code:
            continue
        if unit["status"] not in ("DEPLOYED", "HARVESTING", "RETRIEVED"):
            continue
        rows.append(unit)
    return rows


# --------------------------------------------------------------------------
# Time-to-temperature and the vibrio allowance (PRD 3.8)
# --------------------------------------------------------------------------
def active_plan_for_month(month):
    candidates = [
        p
        for p in db.vibrio_plans.values()
        if p["season_month"] == month and p["status"] == "ACTIVE"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p["created_at"], p["id"]))
    return candidates[-1]


def allowed_ttt_minutes(plan, water_temp_c, gear_type, refrigeration_type):
    """Four sequential adjustments, then the hard floor."""
    minutes = plan["max_time_to_temperature_minutes"]
    # The temperature trigger is an inclusive comparison at one decimal place.
    if q(water_temp_c, 1) >= q(plan["high_water_temp_c"], 1):
        minutes = minutes - plan["high_temp_reduction_minutes"]
    if gear_type in ("BOTTOM", "RACK_AND_BAG"):
        minutes = minutes - INTERTIDAL_PENALTY_MINUTES
    if refrigeration_type == "MECHANICAL":
        minutes = minutes + REFRIGERATION_CREDIT_MINUTES
    if minutes < MIN_FLOOR_MINUTES:
        minutes = MIN_FLOOR_MINUTES
    return minutes


def ttt_bases(first_out, last_out, placed):
    first_basis = truncated_minutes(first_out, placed)
    last_basis = truncated_minutes(last_out, placed)
    return first_basis, last_basis


def ttt_basis_variant(classification):
    if classification == "APPROVED":
        return "FIRST_HARVEST_BASIS"
    return "LAST_HARVEST_BASIS"


# --------------------------------------------------------------------------
# Lease settlement — the six ordered steps (PRD 3.8)
# --------------------------------------------------------------------------
SETTLEMENT_LOT_STATUSES = ("HARVESTED", "TAGGED", "SHIPPED", "EMBARGOED", "RECALLED")


def season_total_bushels(lease_id, bushels, first_out_of_water_at):
    total = bushels
    year = first_out_of_water_at.year
    for lot in lease_lots(lease_id):
        if lot["status"] not in SETTLEMENT_LOT_STATUSES:
            continue
        if lot["first_out_of_water_at"].year != year:
            continue
        total += lot["bushels"]
    return total


def royalty_rate_for_total(season_total):
    if season_total <= TIER1_MAX_BUSHELS:
        return TIER1_RATE_CENTS
    if season_total <= TIER2_MAX_BUSHELS:
        return TIER2_RATE_CENTS
    return TIER3_RATE_CENTS


def settle_lot(lease_id, bushels, first_out_of_water_at):
    season_total = season_total_bushels(lease_id, bushels, first_out_of_water_at)
    rate = royalty_rate_for_total(season_total)
    royalty_cents = rate * bushels
    if royalty_cents >= INSPECTION_FEE_WAIVER_CENTS:
        inspection_fee_cents = 0
    else:
        inspection_fee_cents = INSPECTION_FEE_CENTS
    surcharge = int(
        q(SURCHARGE_RATE * Decimal(royalty_cents + inspection_fee_cents), 0)
    )
    return {
        "season_total_bushels_at_creation": season_total,
        "royalty_rate_cents_per_bushel": rate,
        "royalty_cents": royalty_cents,
        "inspection_fee_cents": inspection_fee_cents,
        "conservation_surcharge_cents": surcharge,
        "lot_settlement_cents": royalty_cents + inspection_fee_cents + surcharge,
    }


# --------------------------------------------------------------------------
# Illness traceback scope (PRD 3.9)
# --------------------------------------------------------------------------
TRACEABLE_LOT_STATUSES = ("TAGGED", "SHIPPED", "EMBARGOED")


def traceback_lots(investigation, scope_variant):
    seed = [
        lot
        for lot in shipment_lots(investigation["source_shipment_id"])
        if lot["status"] in TRACEABLE_LOT_STATUSES
    ]
    traced = {}
    for lot in seed:
        traced[lot["id"]] = lot
    if scope_variant == "BROAD":
        window = timedelta(days=TRACEBACK_DAY_WINDOW)
        for seed_lot in seed:
            area_code = seed_lot["tag_area_code"]
            seed_date = seed_lot["tag_harvest_date"]
            if area_code is None or seed_date is None:
                continue
            for candidate in db.harvest_lots.values():
                if candidate["id"] in traced:
                    continue
                if candidate["status"] not in TRACEABLE_LOT_STATUSES:
                    continue
                if candidate["tag_area_code"] != area_code:
                    continue
                if candidate["tag_harvest_date"] is None:
                    continue
                delta = candidate["tag_harvest_date"] - seed_date
                if -window <= delta <= window:
                    traced[candidate["id"]] = candidate
    rows = list(traced.values())
    rows.sort(
        key=lambda l: (
            l["tag_harvest_date"].toordinal() if l["tag_harvest_date"] else 0,
            l["created_at"],
            l["id"],
        )
    )
    return rows
