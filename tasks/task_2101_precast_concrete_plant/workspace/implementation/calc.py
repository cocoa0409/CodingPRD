"""Pinned calculations (PRD 2.7 and 3.3-3.9, SCAFFOLD 1.3).

All money and every rounded quantity is Decimal arithmetic with ROUND_HALF_UP -
"a value exactly on the midpoint rounds away from zero" (PRD 2.7).
"""
from decimal import Decimal, ROUND_HALF_UP

import constants
import db


def round_half_up(value, places=0):
    quant = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def round_int(value):
    return int(round_half_up(value, 0))


# ---------------------------------------------------------------------------
# cylinder_break_strength_psi (PRD 3.5)
# ---------------------------------------------------------------------------
def cylinder_area(diameter_in):
    area = constants.AREA_BY_DIAMETER.get(diameter_in)
    if area is None:
        area = constants.PI * (Decimal(diameter_in) / 2) ** 2
    return area


def computed_psi(load_lbf, diameter_in):
    return round_int(Decimal(load_lbf) / cylinder_area(diameter_in))


def age_hours(break_at, cast_at):
    seconds = Decimal(str((break_at - cast_at).total_seconds()))
    return round_half_up(seconds / Decimal(3600), 2)


# ---------------------------------------------------------------------------
# cylinder_set_qualified_strength (PRD 3.5)
# ---------------------------------------------------------------------------
def set_breaks(cylinder_set):
    """Breaks of one set ordered by break_at ASC, then created_at ASC."""
    rows = [b for b in db.store.cylinder_breaks.values()
            if b["cylinder_set_id"] == cylinder_set["id"]]
    return sorted(rows, key=lambda b: (b["break_at"], b["created_at"], b["_seq"]))


def recompute_cylinder_set(cylinder_set):
    """Recompute the whole set from scratch, including earlier inclusion_status.

    Returns the list of break rows whose inclusion_status changed.
    """
    breaks = set_breaks(cylinder_set)
    changed = []
    if not breaks:
        cylinder_set["raw_mean_psi"] = None
        cylinder_set["qualified_strength_psi"] = None
        cylinder_set["strength_variant"] = None
        return changed

    total = sum(Decimal(b["computed_psi"]) for b in breaks)
    raw_mean = round_half_up(total / Decimal(len(breaks)), 2)
    cylinder_set["raw_mean_psi"] = raw_mean

    if cylinder_set["specimen_count"] == 2:
        variant = "SET_AVERAGE"
        for b in breaks:
            if b["inclusion_status"] != "VALID":
                b["inclusion_status"] = "VALID"
                changed.append(b)
        included = list(breaks)
    else:
        variant = "TRIMMED_AVERAGE"
        lo = raw_mean * (1 - constants.OUTLIER_TOLERANCE_PCT / 100)
        hi = raw_mean * (1 + constants.OUTLIER_TOLERANCE_PCT / 100)
        included = []
        for b in breaks:
            psi = Decimal(b["computed_psi"])
            status = "VALID" if (lo <= psi <= hi) else "DISCARDED_OUTLIER"
            if b["inclusion_status"] != status:
                b["inclusion_status"] = status
                changed.append(b)
            if status == "VALID":
                included.append(b)

    cylinder_set["strength_variant"] = variant
    if len(included) < 2:
        cylinder_set["qualified_strength_psi"] = None
    else:
        incl_total = sum(Decimal(b["computed_psi"]) for b in included)
        cylinder_set["qualified_strength_psi"] = round_int(
            incl_total / Decimal(len(included)))
    return changed


def cylinder_set_counts(cylinder_set):
    breaks = set_breaks(cylinder_set)
    valid = [b for b in breaks if b["inclusion_status"] == "VALID"]
    return len(breaks), len(valid)


def cylinder_set_status(cylinder_set, required_release_psi):
    """One rule with three outcomes (PRD 3.5)."""
    _recorded, valid = cylinder_set_counts(cylinder_set)
    if valid < 2:
        return "TESTING"
    qualified = cylinder_set["qualified_strength_psi"]
    if qualified is not None and qualified >= required_release_psi:
        return "RELEASE_MET"
    return "RELEASE_NOT_MET"


# ---------------------------------------------------------------------------
# curing_energy_accounting (PRD 3.4)
# ---------------------------------------------------------------------------
def modeled_therms(soak_temp_f, ramp_rate_f_per_hr, soak_hours, steam_demand_bhp):
    delta = Decimal(soak_temp_f) - constants.AMBIENT_F
    ramp_hours = delta / Decimal(ramp_rate_f_per_hr)
    cooldown_hours = delta / constants.COOLDOWN_RATE_F_PER_HR
    weighted = (Decimal("0.5") * ramp_hours + Decimal(soak_hours)
                + Decimal("0.25") * cooldown_hours)
    return round_half_up(
        Decimal(steam_demand_bhp) * constants.THERM_PER_BHP_HOUR * weighted, 2)


def complete_energy(cycle, zone, metered):
    """Write the completion outputs of curing_energy_accounting onto `cycle`."""
    modeled = cycle["modeled_therms"]
    if metered is None:
        cycle["metered_therms"] = None
        cycle["energy_source"] = "MODELED"
        cycle["energy_therms"] = modeled
        cycle["energy_variance_pct"] = None
    else:
        metered = round_half_up(metered, 2)
        cycle["metered_therms"] = metered
        cycle["energy_source"] = "METERED"
        cycle["energy_therms"] = metered
        cycle["energy_variance_pct"] = round_half_up(
            (metered - modeled) / modeled * 100, 2)
    variance = cycle["energy_variance_pct"]
    cycle["variance_flagged"] = bool(
        variance is not None
        and abs(variance) > constants.ENERGY_VARIANCE_TOLERANCE_PCT)
    cycle["energy_cost_cents"] = round_int(
        cycle["energy_therms"] * Decimal(zone["therm_rate_cents_per_therm"]))


# ---------------------------------------------------------------------------
# steam_zone_peak_concurrent_demand (PRD 3.4)
# ---------------------------------------------------------------------------
def steam_peak_demand(zone_id, candidate):
    """Peak concurrent bhp on a zone, candidate included.

    Every cycle occupies the half-open interval [planned_start, planned_end);
    demand is evaluated at each candidate's planned_start.
    """
    candidates = [c for c in db.store.curing_cycles.values()
                  if c["steam_zone_id"] == zone_id
                  and c["status"] in ("SCHEDULED", "RUNNING")]
    candidates.append(candidate)
    peak = Decimal(0)
    for probe in candidates:
        t = db.parse_iso8601(probe["planned_start"])
        demand = Decimal(0)
        for c in candidates:
            start = db.parse_iso8601(c["planned_start"])
            end = db.parse_iso8601(c["planned_end"])
            if start <= t < end:
                demand += Decimal(c["steam_demand_bhp"])
        if demand > peak:
            peak = demand
    return peak


# ---------------------------------------------------------------------------
# bed occupancy (PRD 3.3)
# ---------------------------------------------------------------------------
def bed_occupancy_conflict(bed, start, end, exclude_run_id=None):
    """True when [start, end + turnaround_buffer_hours) intersects another
    non-STRIPPED run's extended window on the same bed."""
    from datetime import timedelta
    buffer_hours = timedelta(hours=int(bed["turnaround_buffer_hours"]))
    new_end = end + buffer_hours
    for run in db.store.bed_runs.values():
        if run["bed_id"] != bed["id"] or run["id"] == exclude_run_id:
            continue
        if run["status"] == "STRIPPED":
            continue
        other_start = db.parse_iso8601(run["scheduled_start"])
        other_end = db.parse_iso8601(run["scheduled_end"]) + buffer_hours
        if start < other_end and other_start < new_end:
            return True
    return False


# ---------------------------------------------------------------------------
# strand_jacking_force (PRD 3.3)
# ---------------------------------------------------------------------------
def strand_jacking_force(bed, mix, strand_count, strand_diameter_in,
                         measured_elongation_in):
    area = constants.STRAND_AREA_IN2[strand_diameter_in]
    per_strand_base = area * constants.F_PU_KSI * constants.JACK_FRACTION
    adjustment_pct = (constants.SEATING_LOSS_PCT[bed["bed_type"]]
                      + constants.STRENGTH_CLASS_TEMP_ADJ_PCT[mix["strength_class"]])
    scaled = per_strand_base * (1 + adjustment_pct / 100)
    required_per_strand = max(scaled, constants.MIN_JACK_KIPS_PER_STRAND)
    force = round_half_up(required_per_strand * Decimal(strand_count), 2)
    theoretical = round_half_up(
        (force / Decimal(strand_count)) * Decimal(bed["length_ft"]) * 12
        / (area * constants.STRAND_MODULUS_KSI), 3)
    deviation = round_half_up(
        (Decimal(measured_elongation_in) - theoretical) / theoretical * 100, 2)
    return force, theoretical, deviation


# ---------------------------------------------------------------------------
# bed_run_cost_allocation (PRD 3.6)
# ---------------------------------------------------------------------------
def run_cast_pieces(run):
    """Pieces on the run that are CAST, ordered by erection_sequence_no ASC
    then created_at ASC."""
    rows = [p for p in db.store.pieces.values()
            if p["bed_run_id"] == run["id"] and p["production_status"] == "CAST"]
    return sorted(rows, key=lambda p: (p["erection_sequence_no"],
                                       p["created_at"], p["_seq"]))


def bed_run_cost_allocation(run, bed, mix):
    """Returns (cost fields dict, [(piece, allocated_cents), ...])."""
    pieces = run_cast_pieces(run)
    volume = sum((Decimal(p["concrete_volume_cy"]) for p in pieces), Decimal(0))
    run_volume_cy = round_half_up(volume, 2)
    concrete = round_int(Decimal(mix["unit_cost_cents_per_cy"]) * run_volume_cy)
    force = run["computed_jacking_force_kips"] or Decimal(0)
    strand = round_int(Decimal(force) * constants.STRAND_COST_CENTS_PER_KIP)
    energy = 0
    for cycle in db.store.curing_cycles.values():
        if cycle["bed_run_id"] == run["id"] and cycle["status"] == "COMPLETED":
            energy += int(cycle["energy_cost_cents"] or 0)
    form_setup = constants.BED_TYPE_SETUP_CENTS[bed["bed_type"]]

    direct = concrete + strand + energy + form_setup
    if direct < constants.OVERHEAD_TIER_1_CENTS:
        rate = Decimal("22.0")
    elif direct < constants.OVERHEAD_TIER_2_CENTS:
        rate = Decimal("18.0")
    else:
        rate = Decimal("14.0")
    overhead = round_int(Decimal(direct) * rate / 100)
    total = direct + overhead

    allocations = []
    if pieces:
        base_share = total // len(pieces)
        remainder = total - base_share * len(pieces)
        for index, piece in enumerate(pieces):
            allocations.append((piece, base_share + remainder if index == 0
                                else base_share))
    fields = {
        "concrete_cost_cents": concrete,
        "strand_cost_cents": strand,
        "energy_cost_cents": energy,
        "form_setup_cents": form_setup,
        "direct_subtotal_cents": direct,
        "overhead_rate_pct": rate,
        "overhead_cents": overhead,
        "total_cost_cents": total,
    }
    return fields, allocations


# ---------------------------------------------------------------------------
# yard_slot_occupancy (PRD 3.7)
# ---------------------------------------------------------------------------
def slot_active_placements(slot_id):
    return [p for p in db.store.yard_placements.values()
            if p["yard_slot_id"] == slot_id and p["status"] == "ACTIVE"]


def slot_occupancy(slot):
    active = slot_active_placements(slot["id"])
    weight = Decimal(0)
    for placement in active:
        piece = db.store.pieces.get(placement["piece_id"])
        if piece is not None:
            weight += Decimal(piece["weight_lb"])
    return weight, len(active)


def slot_status(slot):
    if slot.get("seeded_blocked"):
        return "BLOCKED"
    weight, stacked = slot_occupancy(slot)
    if stacked == 0:
        return "EMPTY"
    if stacked == slot["max_stack_count"] or weight == Decimal(slot["capacity_weight_lb"]):
        return "FULL"
    return "PARTIAL"


# ---------------------------------------------------------------------------
# shipment_load_metrics and shipment_permit_fee (PRD 3.8)
# ---------------------------------------------------------------------------
def shipment_lines(shipment_id):
    rows = [l for l in db.store.shipment_lines.values()
            if l["shipment_id"] == shipment_id]
    return sorted(rows, key=lambda l: (l["load_position"], l["_seq"]))


def shipment_metrics(shipment):
    lines = shipment_lines(shipment["id"])
    pieces = [db.store.pieces[l["piece_id"]] for l in lines
              if l["piece_id"] in db.store.pieces]
    gross = constants.TRACTOR_TARE_LB + sum(
        (Decimal(p["weight_lb"]) for p in pieces), Decimal(0))
    if pieces:
        max_w = max(Decimal(p["width_ft"]) for p in pieces)
        max_h = max(Decimal(p["height_ft"]) for p in pieces)
        max_l = max(Decimal(p["length_ft"]) for p in pieces)
    else:
        max_w = max_h = max_l = Decimal(0)
    is_oversize = (max_w > constants.LEGAL_WIDTH_FT
                   or max_h > constants.LEGAL_HEIGHT_FT
                   or max_l > constants.LEGAL_LENGTH_FT
                   or gross > constants.LEGAL_GROSS_WEIGHT_LB)
    return {
        "line_count": len(lines),
        "gross_weight_lb": gross,
        "max_width_ft": max_w,
        "max_height_ft": max_h,
        "max_length_ft": max_l,
        "is_oversize": is_oversize,
    }


def line_surcharge_cents(shipment, line):
    """This line's rounded oversize surcharge; 0 while the load is legal."""
    metrics = shipment_metrics(shipment)
    if not metrics["is_oversize"]:
        return 0
    piece = db.store.pieces.get(line["piece_id"])
    if piece is None:
        return 0
    w_over = max(Decimal(0), Decimal(piece["width_ft"]) - constants.LEGAL_WIDTH_FT)
    h_over = max(Decimal(0), Decimal(piece["height_ft"]) - constants.LEGAL_HEIGHT_FT)
    l_over = max(Decimal(0), Decimal(piece["length_ft"]) - constants.LEGAL_LENGTH_FT)
    raw_cents = (w_over * constants.WIDTH_RATE_DOLLARS_PER_FT
                 + h_over * constants.HEIGHT_RATE_DOLLARS_PER_FT
                 + l_over * constants.LENGTH_RATE_DOLLARS_PER_FT) * 100
    return round_int(raw_cents)


def shipment_permit_fee(shipment):
    metrics = shipment_metrics(shipment)
    if not metrics["is_oversize"]:
        return 0
    total = constants.PERMIT_BASE_CENTS
    for line in shipment_lines(shipment["id"]):
        total += line_surcharge_cents(shipment, line)
    permit_id = shipment.get("haul_permit_id")
    escorts = 0
    if permit_id:
        permit = db.store.haul_permits.get(permit_id)
        if permit is not None:
            escorts = int(permit["escort_count"])
    return total + escorts * constants.ESCORT_CENTS_EACH
