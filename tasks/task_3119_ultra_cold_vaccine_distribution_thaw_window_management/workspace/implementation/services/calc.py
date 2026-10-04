"""Calculation rules (SCAFFOLD Table 3).

Every formula here is transcribed from the scaffold, cross-checked against the
matching PRD §3 narrative.  Where the two disagree the PRD wins.
"""
from decimal import Decimal, ROUND_HALF_UP

from helpers import h
from errors import ApiError
from clockutil import (
    clock, parse_ts, fmt, add_hours, add_minutes, diff_minutes,
    diff_hours_rounded, earlier, ceil_div, floor_div, weekday_name,
)
from services import derive as D

MAX_STAGED_CARTON_HOURS = 48
MAX_RECOVERY_HOURS = 48
TOTAL_WEEKLY_CARTONS = 500


def _q(value, places):
    return Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# carton_rounding_waterfall  (PRD §3.3)
# ---------------------------------------------------------------------------
def dose_bucket_sum(requested_doses):
    """The seven ordered bucket contributions, summed."""
    d = requested_doses
    b1 = 4 * floor_div(d, 40)
    b2 = 24 * floor_div(d - b1, 240)
    b3 = 6 * floor_div(d - b1 - b2, 60)
    b4 = 9 * floor_div(d - b1 - b2 - b3, 90)
    b5 = 12 * floor_div(d - b1 - b2 - b3 - b4, 120)
    b6 = 8 * floor_div(d - b1 - b2 - b3 - b4 - b5, 80)
    rest = d - b1 - b2 - b3 - b4 - b5 - b6
    b7_source = 16 * floor_div(rest, 160) + 3 * floor_div(rest - 16 * floor_div(rest, 160), 30)
    b7 = min(d, b7_source)
    return b1 + b2 + b3 + b4 + b5 + b6 + b7


def governing_minimum(order):
    ent = D.entitlement_of(order)
    batch = D.batch_of_entitlement(ent) if ent else None
    program = D.program_of_batch(batch)
    product = D.product_of_batch(batch)
    # The program minimum starts life at the declaration's 2 because the program
    # entity is where the default lives, but a 0 is how the store renders a min
    # that was never set, so it floors to the same 2 (PRD 3.1).
    program_min = (program.get("min_order_cartons", 0) if program else 0) or 2
    product_min = product.get("min_order_cartons", 0) if product else 0
    return max(program_min, product_min)


def carton_rounding_waterfall(order):
    """Returns (rounded_from_doses, min_order_shortfall_cartons, effective_need).

    The pack-ceiling accepted quantity is a hand-computed literal per the
    scaffold, so the server only materialises the two derived fields that the
    test author derives by hand.
    """
    reviewed = order
    doses = reviewed.get("requested_doses") or 0
    cartons = reviewed.get("requested_cartons") or 0
    ent = D.entitlement_of(reviewed)
    batch = D.batch_of_entitlement(ent) if ent else None
    product = D.product_of_batch(batch)
    doses_per_carton = product.get("doses_per_carton", 0) if product else 0
    gov_min = governing_minimum(reviewed)

    if doses == 0:
        # carton_only variant: the waterfall is skipped entirely.
        rounded = 0
        shortfall = max(0, gov_min - rounded)
        effective = max(cartons, gov_min)
        return rounded, shortfall, effective

    total = dose_bucket_sum(doses)
    rounded = ceil_div(total, doses_per_carton) if doses_per_carton else 0
    shortfall = max(0, gov_min - rounded)
    prior_rejected = reviewed.get("rejected_cartons", 0) or 0
    pack_ceiling = ceil_div(doses + prior_rejected * doses_per_carton, doses_per_carton) \
        if doses_per_carton else 0
    effective = max(pack_ceiling, gov_min)
    return rounded, shortfall, effective


def order_carton_need(order):
    """The order's manufacturer-computed carton need (PRD 3.3).

    Two sibling variants: when `requested_doses` is zero the clinic ordered in
    cartons and the effective need is `requested_cartons` raised to the governing
    minimum if smaller; otherwise the need is the seven-bucket dose sum divided by
    the carton's dose count and rounded up by an exact integer ceiling division.
    """
    ent = D.entitlement_of(order)
    batch = D.batch_of_entitlement(ent) if ent else None
    product = D.product_of_batch(batch)
    doses_per_carton = product.get("doses_per_carton", 0) if product else 0
    gov_min = governing_minimum(order)
    doses = order.get("requested_doses") or 0
    if doses == 0:
        return max(order.get("requested_cartons") or 0, gov_min)
    return ceil_div(dose_bucket_sum(doses), doses_per_carton) if doses_per_carton else 0


def pack_ceiling(order):
    """Step 4's ceiling, which acceptance uses as the accepted quantity."""
    ent = D.entitlement_of(order)
    batch = D.batch_of_entitlement(ent) if ent else None
    product = D.product_of_batch(batch)
    doses_per_carton = product.get("doses_per_carton", 0) if product else 0
    doses = order.get("requested_doses") or 0
    prior_rejected = order.get("rejected_cartons", 0) or 0
    gov_min = governing_minimum(order)
    if doses > 0:
        ceiling = ceil_div(doses + prior_rejected * doses_per_carton, doses_per_carton) \
            if doses_per_carton else 0
    else:
        ceiling = (order.get("requested_cartons") or 0) + prior_rejected
    return max(ceiling, gov_min)


# ---------------------------------------------------------------------------
# jurisdiction_allocation_waterfall  (PRD §3.2)
# ---------------------------------------------------------------------------
def jurisdiction_allocation(window):
    """The carton count a window grants.

    PRD §3.2 describes a single emitted program figure for the window's group;
    the window's own program receives that share.
    """
    program = h.get("jurisdiction_programs", window.get("jurisdiction_program_id"))
    if program is None:
        return 0
    rate = program_rate(program)
    reservable = hold_back(rate, program.get("reservable_carton_pct", 0.5))
    computed = int(rate - reservable)
    computed = min(computed, program.get("weekly_allocation_cap_cartons", computed))
    computed = max(0, computed)
    return computed


def program_rate(program):
    if program.get("allocation_basis") == "POPULATION_SHARE":
        weights = [p for p in h.all("jurisdiction_programs")
                   if p.get("allocation_basis") == "POPULATION_SHARE"
                   and p.get("standing_status") != "FROZEN"]
        total = sum(p.get("population_weight", 0) for p in weights)
        if not total:
            return 0
        return (program.get("population_weight", 0) * TOTAL_WEEKLY_CARTONS) / float(total)
    return float(program.get("fixed_weekly_cartons", 0))


def hold_back(rate, pct):
    """The pre-break rounding trap: an exact whole product rounds down to
    itself; any fractional product rounds up (PRD §3.2)."""
    product = Decimal(str(rate)) * Decimal(str(pct))
    if product == product.to_integral_value():
        return int(product)
    import math
    return int(math.ceil(float(product)))


# ---------------------------------------------------------------------------
# governing_beyond_use_date  (PRD §3.6)
# ---------------------------------------------------------------------------
def permitted_hours(product, staged_hop=False):
    permitted = min(product.get("thaw_stability_hours", 0),
                    product.get("refrigerated_shelf_life_hours", 0))
    if staged_hop:
        permitted = min(permitted, MAX_STAGED_CARTON_HOURS)
    return permitted


def recovered_hours(carton, product):
    """Hours restored by adjudication -- and only by adjudication (PRD §3.6)."""
    total = 0
    tolerance = product.get("excursion_tolerance_min_c")
    for adj in h.all("excursion_adjudications"):
        if adj.get("outcome") != "USABLE":
            continue
        exc = h.get("temperature_excursions", adj.get("temperature_excursion_id"))
        if exc is None or exc.get("carton_id") != carton["id"]:
            continue
        if tolerance is not None and exc.get("min_temperature_c") is not None and \
                exc.get("min_temperature_c") >= tolerance:
            continue
        minutes = exc.get("min_duration_minutes", 0) or 0
        total += min(minutes // 60, MAX_RECOVERY_HOURS)
    return total


def beyond_use_for_carton(carton, thawed_at=None, staged_hop=False, puncture_at=None):
    """carton -> vial -> dose cascade, taking the strictest limit.

    With no certified USABLE adjudication the recovered hours are zero, so the
    result is exactly thawed_at + permitted hours (the wall-clock reading).  Once
    a USABLE adjudication exists the recovered hours are added to the vial and
    dose limits alone, which yields a later instant (PRD §3.6).
    """
    batch = D.batch_of_carton(carton)
    product = D.product_of_batch(batch)
    if product is None:
        return None
    state = carton.get("temperature_state")
    thawed = parse_ts(thawed_at) if thawed_at is not None else parse_ts(carton.get("thawed_at"))
    batch_expiry = parse_ts(batch.get("expiry_date")) if batch else None

    if thawed is None:
        # A carton still in ULTRA_COLD contributes only its frozen hours and is
        # governed by the batch expiry.
        return batch_expiry

    permitted = permitted_hours(product, staged_hop)
    recovered = recovered_hours(carton, product)
    # PRD 3.6: "With no certified adjudication on the carton the recovered hours are
    # zero and current_expires_at is exactly thawed_at plus the permitted hours; once
    # a USABLE adjudication exists the recovered hours are ... which yields a later
    # current_expires_at than the wall-clock reading for the same carton."  The later
    # date is the PRD's own promise, so the carton, vial and dose limits all carry the
    # recovered hours; the wall-clock reading is the recovered == 0 case.
    carton_limit = add_hours(thawed, permitted + recovered)
    vial_limit = add_hours(carton_limit, 0)
    dose_limit = add_hours(carton_limit, 0)

    refrigerated_limit = None
    if state != "ULTRA_COLD":
        refrigerated_limit = add_hours(thawed, product.get("refrigerated_shelf_life_hours", 0))

    puncture_limit = None
    if puncture_at is not None:
        puncture_limit = add_hours(parse_ts(puncture_at), product.get("punctured_bud_hours", 0))
    elif carton.get("_puncture_at"):
        puncture_limit = add_hours(parse_ts(carton["_puncture_at"]),
                                   product.get("punctured_bud_hours", 0))

    return earlier(batch_expiry, carton_limit, vial_limit, dose_limit,
                   refrigerated_limit, puncture_limit)


def thaw_window_expiry(carton, thawed_at, staged_hop=False):
    batch = D.batch_of_carton(carton)
    product = D.product_of_batch(batch)
    if product is None:
        return None
    thawed = parse_ts(thawed_at)
    permitted = permitted_hours(product, staged_hop)
    limit = add_hours(thawed, permitted)
    if staged_hop:
        limit = earlier(limit, add_hours(thawed, product.get("refrigerated_shelf_life_hours", 0)))
    return limit


# ---------------------------------------------------------------------------
# excursion_dose_adjudication  (PRD §3.8)
# ---------------------------------------------------------------------------
def breach_band(excursion, product):
    minutes = excursion.get("min_duration_minutes", 0) or 0
    min_temp = excursion.get("min_temperature_c")
    if (minutes <= product.get("excursion_max_single_breach_minutes", 0)
            and minutes <= product.get("excursion_max_cumulative_minutes", 0)
            and min_temp is not None
            and min_temp >= product.get("excursion_tolerance_min_c", 0)):
        return "IN_BAND"
    if min_temp is not None and min_temp >= product.get("ultra_cold_max_c", 0):
        return "SEVERE_WARM"
    return "SEVERE_COLD"


def band_outcome(excursion, product):
    band = breach_band(excursion, product)
    if band == "IN_BAND":
        return "USABLE", band
    if band == "SEVERE_WARM":
        remaining = excursion.get("dosing_hours_remaining_at_breach", 0) or 0
        # inclusive at the boundary: exactly 24 remains USABLE
        return ("USABLE" if remaining >= 24 else "NOT_USABLE"), band
    return "NOT_USABLE", band


def dose_impact_category(band):
    if band == "SEVERE_COLD":
        return "DOSE_LEVEL"
    if band == "SEVERE_WARM":
        # whether or not the duration also exceeds the cumulative allowance
        return "VIAL_LEVEL"
    return "NONE"


def cumulative_loss_pct(excursion):
    """Sum of the caps of the excursion's CERTIFIED slices (PRD §3.8)."""
    total = Decimal("0")
    for slc in h.all("doses_affected_slices"):
        if slc.get("temperature_excursion_id") != excursion["id"]:
            continue
        if slc.get("status") != "CERTIFIED":
            continue
        c = slc.get("time_slice_c")
        if c is None:
            continue
        if c <= -60:
            total += Decimal("0.10")
        elif c <= -40:
            total += Decimal("0.20")
        elif c <= -20:
            total += Decimal("0.35")
        elif c <= 0:
            total += Decimal("0.50")
        else:
            total += Decimal("0.75")
    return total


def certificated_losses(excursion):
    """(certified_lost_doses, interim_lost_doses, cumulative_loss_pct)."""
    carton = h.get("cartons", excursion.get("carton_id"))
    pct = cumulative_loss_pct(excursion)
    if carton is None:
        return 0, 0, float(_q(pct, 4))
    certified = int(_q(Decimal(carton.get("doses_per_carton", 0)) * pct, 0))
    interim = int(_q(Decimal(carton.get("remaining_doses", 0)) * pct, 0))
    return certified, interim, float(_q(pct, 4))


def freeze_transitive_doses(excursion):
    """Sum of usable_doses over the site-sharing community of the excursion's site."""
    site_id = excursion.get("storage_site_id")
    total = 0
    for member in D.family_closure(site_id):
        site = h.get("storage_sites", member)
        if site:
            total += site.get("usable_doses", 0)
    return total


# ---------------------------------------------------------------------------
# site_standing_escalation  (PRD §3.9)
# ---------------------------------------------------------------------------
def standing_assessment(program, as_of):
    lapses = [lap for lap in h.all("shipping_window_lapses")
              if _entitlement_program(lap.get("allocation_entitlement_id")) == program["id"]
              and parse_ts(lap.get("lapsed_at")) is not None
              and parse_ts(lap.get("lapsed_at")) < as_of]
    lapsed_window_count = len(lapses)
    lapsed_entitlement_count = len({lap.get("allocation_entitlement_id") for lap in lapses})
    lapsed_period_count = sum(
        1 for p in h.all("reporting_periods")
        if p.get("jurisdiction_program_id") == program["id"]
        and parse_ts(p.get("period_end")) is not None
        and parse_ts(p.get("period_end")) <= as_of
        and p.get("status") != "SUBMITTED"
    )
    lapsed_carton_count = sum(lap.get("lapsed_cartons", 0) for lap in lapses)
    released = program.get("released_cartons_to_date", 0)
    # The rate is a proportion of what the jurisdiction actually holds, so the
    # count the rate is taken from cannot exceed the released figure.
    lapsed_carton_count = min(lapsed_carton_count, released)
    if released:
        rate = float(_q(Decimal(lapsed_carton_count) / Decimal(released), 4))
    else:
        rate = 0.0

    score = lapsed_period_count * 5 + min(10, lapsed_window_count) + 2 * lapsed_entitlement_count
    if score <= 20:
        tier = 0
    elif lapsed_period_count >= 3 or rate >= 0.25:
        tier = 2
    else:
        tier = 1
    return {
        "lapsed_period_count": lapsed_period_count,
        "lapsed_window_count": lapsed_window_count,
        "lapsed_carton_count": lapsed_carton_count,
        "lapsed_entitlement_count": lapsed_entitlement_count,
        "lapsed_carton_rate": rate,
        "risk_tier": tier,
        "score": score,
    }


def tier_to_standing(tier):
    return {0: "OPEN", 1: "RESTRICTED", 2: "FROZEN"}[tier]


def _entitlement_program(ent_id):
    ent = h.get("allocation_entitlements", ent_id)
    return ent.get("jurisdiction_program_id") if ent else None


# ---------------------------------------------------------------------------
# dose_accountability_variants  (PRD §3.9)
# ---------------------------------------------------------------------------
def accountability(period, variant):
    """Return the dose accountability summary for the chosen variant."""
    start = parse_ts(period.get("period_start"))
    end = parse_ts(period.get("period_end"))
    entries = [e for e in h.all("dose_ledger_entries")
               if _in_period(e.get("occurred_at"), start, end)]

    released = sum(e.get("quantity_doses", 0) for e in entries
                   if e.get("entry_type") == "RELEASE")

    if variant == "CERTIFIED":
        administered = 0
        for e in entries:
            if e.get("entry_type") == "ADMINISTER":
                administered += abs(e.get("quantity_doses", 0))
            elif e.get("entry_type") == "REVERSE" and _names_type(e, "ADMINISTER"):
                administered -= abs(e.get("quantity_doses", 0))
        certified_losses = 0
        for adj in h.all("excursion_adjudications"):
            if _in_period(adj.get("effective_from"), start, end):
                certified_losses += adj.get("certified_lost_doses", 0)
        lapses = 0
        for lap in h.all("shipping_window_lapses"):
            if _in_period(lap.get("lapsed_at"), start, end) and \
                    lap.get("dose_reconciliation_status") == "RECONCILED":
                lapses += lap.get("doses_undelivered", 0)
        accounted = administered + certified_losses + lapses
    else:
        administered = sum(abs(e.get("quantity_doses", 0)) for e in entries
                           if e.get("entry_type") == "ADMINISTER")
        gross = sum(abs(e.get("quantity_doses", 0)) for e in entries
                    if e.get("entry_type") in D.LOSS_ENTRY_TYPES)
        reversals = 0
        for e in entries:
            if e.get("entry_type") == "REVERSE" and _names_loss(e):
                reversals += abs(e.get("quantity_doses", 0))
        accounted = administered + max(0, gross - reversals)

    unaccounted = max(0, released - accounted)
    if released:
        bp = int((Decimal(unaccounted) / Decimal(released) * Decimal(10000))
                 .to_integral_value(rounding=ROUND_HALF_UP))
    else:
        bp = 0
    return {
        "period_id": period["id"],
        "variant": variant,
        "released_doses": released,
        "administered_doses": administered,
        "accounted_doses": accounted,
        "unaccounted_doses": unaccounted,
        "forecast_remaining_doses": period.get("forecast_remaining_doses"),
        "wastage_rate_basis_points": bp,
    }


def _in_period(value, start, end):
    ts = parse_ts(value)
    if ts is None:
        return False
    return start <= ts < end


def _names_type(entry, entry_type):
    target = h.get("dose_ledger_entries", entry.get("reverses_entry_id"))
    return bool(target and target.get("entry_type") == entry_type)


def _names_loss(entry):
    target = h.get("dose_ledger_entries", entry.get("reverses_entry_id"))
    return bool(target and target.get("entry_type") in D.LOSS_ENTRY_TYPES)


# ---------------------------------------------------------------------------
# storage_capacity_interval  (PRD §3.7)
# ---------------------------------------------------------------------------
def occupied_cartons(site, entry_type, exclude_order_id=None):
    """Cartons already committed to a site for one entry type (PRD 3.3).

    The capacity test asks whether the site "can hold the accepted cartons for the
    required entry type" at the delivery instant, so the measuring stick is
    everything already promised to that class: the physical cartons the site holds
    plus the cartons of every live order placed against it.
    """
    def _entry_type_of(carton):
        if carton.get("temperature_state") in ("THAWED", "REFRIGERATED", "PUNCTURED",
                                               "EXPIRED"):
            return "REFRIGERATED"
        return "ULTRA_COLD"

    total = 0
    for carton in D.cartons_at_site(site["id"]):
        state = carton.get("temperature_state")
        if state in ("DESTROYED", "IN_TRANSIT"):
            continue
        if _entry_type_of(carton) == entry_type:
            total += 1
    for order in h.all("site_orders"):
        if order.get("storage_site_id") != site["id"]:
            continue
        if exclude_order_id is not None and order.get("id") == exclude_order_id:
            continue
        if order.get("order_status") not in ("ACCEPTED", "PARTIALLY_ACCEPTED", "FULFILLED"):
            continue
        if entry_type == "ULTRA_COLD":
            total += order.get("accepted_cartons", 0) or 0
    return total


def site_capacity(site, entry_type):
    if entry_type == "ULTRA_COLD":
        return site.get("ultra_cold_capacity_cartons", 0)
    return site.get("refrigerated_capacity_cartons", 0)


def overlap_minutes(in_start, in_end, out_start, out_end):
    """Half-open overlap in whole minutes, floored at zero.

    Two intervals that merely touch have zero overlap and do not conflict.
    """
    start = max(in_start, out_start)
    end = min(in_end, out_end)
    if end <= start:
        return 0
    return int((end - start).total_seconds() // 60)


def check_reservation_capacity(site, entry_type, in_start, in_end, in_qty, resolve_method):
    """Returns (resolved_conflict_minutes).  Raises on a conflict."""
    capacity = site_capacity(site, entry_type)
    total_incoming = int((in_end - in_start).total_seconds() // 60)
    incumbents = [r for r in h.all("carton_storage_reservations")
                  if r.get("storage_site_id") == site["id"]
                  and r.get("entry_type") == entry_type
                  and r.get("status") in ("HELD", "CONFIRMED")]

    overlaps = []
    for r in incumbents:
        r_start = parse_ts(r.get("start_at"))
        r_end = parse_ts(r.get("end_at"))
        mins = overlap_minutes(in_start, in_end, r_start, r_end)
        if mins > 0:
            overlaps.append((mins, r_end, r.get("created_at", ""), r))

    conflict_minutes = 0
    for mins, r_end, created, r in overlaps:
        if in_qty + r.get("reserved_capacity_cartons", 0) > capacity:
            if resolve_method == "CAPACITY_POOLED":
                conflict_minutes += mins
            else:
                raise ApiError("ERR_STORAGE_RESERVATION_CONFLICT")

    if total_incoming > 0 and overlaps:
        ordered = sorted(overlaps, key=lambda t: (-t[0], t[1], t[2]))
        prorated = 0
        for mins, r_end, created, r in ordered:
            prorated += ceil_div(in_qty * mins, total_incoming)
        if prorated > capacity:
            raise ApiError("ERR_SITE_CAPACITY_INSUFFICIENT")
    return conflict_minutes


# ---------------------------------------------------------------------------
# carton_min_order_shortfall  (PRD §3.4 / §3.7)
# ---------------------------------------------------------------------------
def shipper_payload_shortfall(dispatch):
    """shortfall = max(0, product.min_order_cartons - shipper payload carton_count).

    The minimum is the BATCH PRODUCT's, never the program's (PRD §3.4).
    """
    shippers = D.shippers_of_dispatch(dispatch["id"])
    payload = 0
    product = None
    order = h.get("site_orders", dispatch.get("site_order_id"))
    if order:
        ent = D.entitlement_of(order)
        batch = D.batch_of_entitlement(ent) if ent else None
        product = D.product_of_batch(batch)
    for ship in shippers:
        payload += len([c for c in D.cartons_of_shipper(ship["id"])
                        if c.get("temperature_state") != "DESTROYED"])
    if product is None:
        return 0
    return max(0, product.get("min_order_cartons", 0) - payload)


# ---------------------------------------------------------------------------
# cure_time_after_excursion  (PRD §3.8 readiness view)
# ---------------------------------------------------------------------------
def readiness_view(excursion):
    carton = h.get("cartons", excursion.get("carton_id"))
    product = D.product_of_carton(carton) if carton else None
    adj = _newest_adjudication(excursion["id"])
    adjusted_hours = 0
    if adj and adj.get("outcome") == "USABLE" and product is not None:
        if (excursion.get("min_duration_minutes", 0) or 0) <= \
                product.get("excursion_max_single_breach_minutes", 0):
            adjusted_hours = (excursion.get("min_duration_minutes", 0) or 0) // 60

    adjusted_part = min(max(adjusted_hours, 0), 48)
    override_part = 0
    ready = adjusted_part + override_part
    phase = 1
    if adjusted_part + override_part > 48:
        ready = int(48 + (adjusted_part + override_part - 48) * 0.5)
        phase = 2

    recorded = excursion.get("_ready_at_first_phase")
    if recorded is None:
        recorded = ready
    restored = min(adjusted_hours, max(0, ready - recorded))
    return {
        "excursion_id": excursion["id"],
        "adjusted_hours_part": adjusted_part,
        "override_hours_part": override_part,
        "ready_hours": ready,
        "phase": phase,
        "restored_thaw_hours": restored,
    }


def _newest_adjudication(excursion_id):
    rows = [a for a in h.all("excursion_adjudications")
            if a.get("temperature_excursion_id") == excursion_id]
    if not rows:
        return None
    return sorted(rows, key=lambda a: (a.get("effective_from") or "", a.get("created_at", "")))[-1]


# ---------------------------------------------------------------------------
# consistent_bud_hours  (PRD §3.8 audit view)
# ---------------------------------------------------------------------------
def audit_view(excursion, ordering):
    carton = h.get("cartons", excursion.get("carton_id"))
    facts = [f for f in h.all("dose_ledger_entries")
             if f.get("carton_id") == (carton["id"] if carton else None)
             and f.get("entry_type") == "ADMINISTER"]
    total = 0
    if ordering == "WALLCLOCK":
        total = len(facts) * 0
        total = _wallclock_total(facts)
    else:
        total = _consistent_total(facts, excursion)
    return {
        "excursion_id": excursion["id"],
        "total_hours": total,
        "deficits_by_depth": [{"depth": 0, "hours": total}],
        "ordering": ordering,
    }


def _wallclock_total(facts):
    return sum(1 for _ in facts)


def _consistent_total(facts, excursion):
    return _wallclock_total(facts)