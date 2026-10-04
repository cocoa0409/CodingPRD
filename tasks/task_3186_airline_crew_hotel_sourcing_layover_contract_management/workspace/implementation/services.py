"""Business logic: calculations, cascades, and shared rule helpers (PRD 3.x)."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import err

BUFFER_MINUTES = 90
TIER1_MAX = 5
TIER2_MAX = 10
LATE_CANCEL_FRACTION = Decimal("0.50")

QUIET_LADDER = {
    "STANDARD": {"BASIC", "ENHANCED", "PREMIUM"},
    "PREMIUM": {"ENHANCED", "PREMIUM"},
    "SUITE": {"PREMIUM"},
}


def round_half_up(value):
    """Round a Decimal to whole cents (or to the quantum implied) half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def get_or_404(store, rid, label):
    rec = store.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "%s not found: %s" % (label, rid))
    return rec


def union_for_crew(crew_type):
    """The UnionAgreement whose crew_type equals the given crew type."""
    for ua in db.union_agreements.values():
        if ua["crew_type"] == crew_type:
            return ua
    return None


# ---------------------------------------------------------------------------
# rest_compliance (PRD 3.5 / scaffold calculations)
# ---------------------------------------------------------------------------

def compute_rest_compliant(layover):
    """rest_compliant = effective_rest_hours >= max(station.min, union.min).

    effective_rest = floor-hours between arrival and departure minus two
    transport legs. IROPS variant: an arrival_time in the past is replaced by
    the current logical clock time (wheels-down).
    """
    station = db.stations.get(layover["station_id"])
    if station is None:
        return False
    arrival = layover["_arrival_time"]
    if layover.get("is_irregular_ops") and arrival < db.CLOCK:
        arrival = db.CLOCK
    layover_hours = db.whole_hours(arrival, layover["_departure_time"])
    transport_hours = 2 * station["transport_time_minutes"] / 60.0
    effective_rest = layover_hours - transport_hours
    min_rest = station["min_rest_hours"]
    ua = union_for_crew(layover["crew_type"])
    if ua is not None:
        min_rest = max(min_rest, ua["min_rest_hours"])
    return effective_rest >= min_rest


# ---------------------------------------------------------------------------
# pickup_timing (PRD 3.9)
# ---------------------------------------------------------------------------

def compute_pickup_time(layover, direction):
    station = db.stations[layover["station_id"]]
    minutes = station["transport_time_minutes"]
    if direction == "AIRPORT_TO_HOTEL":
        pickup = layover["_arrival_time"] + timedelta(minutes=minutes)
    else:  # HOTEL_TO_AIRPORT
        pickup = layover["_departure_time"] - timedelta(minutes=minutes + BUFFER_MINUTES)
    if layover.get("is_irregular_ops"):
        floor = db.CLOCK + timedelta(minutes=30)
        if pickup < floor:
            pickup = floor
    return pickup


# ---------------------------------------------------------------------------
# contract_value (PRD 3.2): rate * block * whole nights, round half-up once
# ---------------------------------------------------------------------------

def contract_value_cents(rate_cents, room_block_size, start_dt, end_dt):
    nights = db.whole_nights(start_dt, end_dt)
    return round_half_up(Decimal(rate_cents) * Decimal(room_block_size) * Decimal(nights))


# ---------------------------------------------------------------------------
# Union compliance gate (PRD 3.2 / 3.4) -- checked at award and activate
# ---------------------------------------------------------------------------

def check_union_compliance(quiet_room_standard, blackout_protection):
    for ua in db.union_agreements.values():
        if ua["quiet_room_required"] and quiet_room_standard == "BASIC":
            raise err(
                "ERR_UNION_STANDARD_VIOLATION",
                "union agreement %s requires non-BASIC quiet room standard" % ua["name"],
            )
        if ua["blackout_protection_required"] and blackout_protection is not True:
            raise err(
                "ERR_UNION_STANDARD_VIOLATION",
                "union agreement %s requires blackout protection" % ua["name"],
            )
        allowed = QUIET_LADDER[ua["min_room_standard"]]
        if quiet_room_standard not in allowed:
            raise err(
                "ERR_UNION_STANDARD_VIOLATION",
                "union agreement %s room standard %s not satisfied by %s"
                % (ua["name"], ua["min_room_standard"], quiet_room_standard),
            )


# ---------------------------------------------------------------------------
# Contract cascades (PRD 3.4 / 3.8)
# ---------------------------------------------------------------------------

def suspend_contract(contract):
    """ACTIVE -> SUSPENDED with the full suspension cascade."""
    contract["status"] = "SUSPENDED"
    contract["remediation_deadline"] = db.iso(db.CLOCK + timedelta(hours=168))
    db.touch(contract)
    for alloc in db.allocations.values():
        if alloc["contract_id"] == contract["id"] and alloc["status"] == "HELD":
            alloc["status"] = "RELEASED"
            db.touch(alloc)
            lay = db.layovers.get(alloc["layover_requirement_id"])
            if lay is not None and lay["status"] == "CONFIRMED":
                lay["status"] = "SURGED"
                db.touch(lay)
    for trip in db.transport_trips.values():
        if trip.get("contract_id") == contract["id"] and trip["status"] == "SCHEDULED":
            trip["status"] = "CANCELLED"
            db.touch(trip)


def terminate_contract(contract):
    """-> TERMINATED with the full termination cascade."""
    contract["status"] = "TERMINATED"
    db.touch(contract)
    for alloc in db.allocations.values():
        if alloc["contract_id"] == contract["id"] and alloc["status"] in ("HELD", "CONFIRMED"):
            alloc["status"] = "CANCELLED"
            mark_cancellation_chargeability(alloc)
            db.touch(alloc)
            lay = db.layovers.get(alloc["layover_requirement_id"])
            if lay is not None and lay["status"] == "CONFIRMED":
                lay["status"] = "SURGED"
                db.touch(lay)
    vendor = db.vendors.get(contract["vendor_id"])
    if vendor is not None:
        vendor["status"] = "SUSPENDED"
        db.touch(vendor)


# ---------------------------------------------------------------------------
# Late-cancel chargeability (PRD 3.7 / 3.10)
# ---------------------------------------------------------------------------

def mark_cancellation_chargeability(alloc):
    """Record whether a cancellation is late/chargeable at cancel time.

    CONTRACTED: late iff stay_date minus contract.late_cancel_hours still lies
    in the future relative to the logical clock.
    DISTRESSED: always chargeable on cancellation.
    """
    if alloc["kind"] == "DISTRESSED":
        alloc["_late_cancel"] = True
        return
    contract = db.contracts.get(alloc.get("contract_id"))
    if contract is None:
        alloc["_late_cancel"] = False
        return
    cutoff = alloc["_stay_date"] - timedelta(hours=contract["late_cancel_hours"])
    # PRD 3.7: the cancellation is late/chargeable exactly when the clock has
    # reached the window opening (stay_date - late_cancel_hours); cancelling
    # earlier than that window is free.
    alloc["_late_cancel"] = db.CLOCK >= cutoff


# ---------------------------------------------------------------------------
# distressed_cost (PRD 3.7): surge tier multiplier on confirm
# ---------------------------------------------------------------------------

def compute_distressed_cost(alloc):
    surge_n = 0
    for other in db.allocations.values():
        if (
            other["id"] != alloc["id"]
            and other["kind"] == "DISTRESSED"
            and other["stay_date"] == alloc["stay_date"]
            and other["status"] in ("HELD", "CONFIRMED", "CHECKED_IN")
        ):
            surge_n += 1
    if surge_n <= TIER1_MAX:
        multiplier = Decimal("1.25")
    elif surge_n <= TIER2_MAX:
        multiplier = Decimal("1.50")
    else:
        multiplier = Decimal("2.00")
    return round_half_up(Decimal(alloc["nightly_rate_cents"]) * Decimal(alloc["rooms_held"]) * multiplier)


# ---------------------------------------------------------------------------
# invoice_reconciliation + invoice_variance (PRD 3.10)
# ---------------------------------------------------------------------------

def reconcile_invoice(invoice):
    contract = db.contracts.get(invoice["contract_id"])
    start = invoice["_billing_period_start"]
    end = invoice["_billing_period_end"]

    eligible = []
    late_cancels = []
    if contract is not None:
        for alloc in db.allocations.values():
            if alloc["contract_id"] != contract["id"]:
                continue
            stay = alloc["_stay_date"]
            if not (start <= stay <= end):
                continue
            if alloc["status"] == "CHECKED_IN":
                eligible.append(alloc)
            elif alloc["status"] == "CANCELLED" and alloc.get("_late_cancel"):
                late_cancels.append(alloc)

    reconciled_room_nights = sum(a["rooms_held"] for a in eligible)
    # per-line round half-up, then sum, then round the sum (rounding mode b)
    line_sum = sum(
        round_half_up(Decimal(a["nightly_rate_cents"]) * Decimal(a["rooms_held"]))
        for a in eligible
    )
    late_line_sum = sum(
        round_half_up(Decimal(a["nightly_rate_cents"]) * Decimal(a["rooms_held"]))
        for a in late_cancels
    )
    late_cancel_charge = (LATE_CANCEL_FRACTION * Decimal(late_line_sum)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    reconciled_amount = round_half_up(Decimal(line_sum)) + int(late_cancel_charge)

    invoice["reconciled_room_nights"] = reconciled_room_nights
    invoice["reconciled_amount_cents"] = reconciled_amount

    billed = invoice["billed_amount_cents"]
    if reconciled_amount == 0:
        variance = 0.0 if billed == 0 else 100.0
    else:
        variance = float(
            (Decimal(abs(billed - reconciled_amount)) / Decimal(reconciled_amount) * Decimal(100)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        )
    invoice["variance_pct"] = variance
