"""Shared domain services: lookups, cascades, ledgers and derived counters."""

import math
from datetime import timedelta
from decimal import Decimal

import calc
from calc import rhu
from errors import ApiError
from store import db, fmt_iso, now, now_iso, parse_iso, touch


# ---------------------------------------------------------------------------
# Existence
# ---------------------------------------------------------------------------
def fetch(collection, ident, error_id):
    if not isinstance(ident, str):
        raise ApiError(error_id)
    row = collection.get(ident)
    if row is None:
        raise ApiError(error_id)
    return row


def water_body_or_404(ident):
    return fetch(db.water_bodies, ident, "ERR_WATER_BODY_NOT_FOUND")


def station_or_404(ident):
    return fetch(db.stations, ident, "ERR_STATION_NOT_FOUND")


def inspector_or_404(ident):
    return fetch(db.inspectors, ident, "ERR_INSPECTOR_NOT_FOUND")


def watercraft_or_404(ident):
    return fetch(db.watercraft, ident, "ERR_WATERCRAFT_NOT_FOUND")


def agreement_or_404(ident):
    return fetch(db.agreements, ident, "ERR_RECIPROCITY_AGREEMENT_NOT_FOUND")


def record_or_404(ident):
    return fetch(db.records, ident, "ERR_INSPECTION_RECORD_NOT_FOUND")


def decon_order_or_404(ident):
    return fetch(db.decon_orders, ident, "ERR_DECON_ORDER_NOT_FOUND")


def quarantine_order_or_404(ident):
    return fetch(db.quarantine_orders, ident, "ERR_QUARANTINE_ORDER_NOT_FOUND")


def detection_report_or_404(ident):
    return fetch(db.detection_reports, ident, "ERR_DETECTION_REPORT_NOT_FOUND")


def campaign_or_404(ident):
    return fetch(db.campaigns, ident, "ERR_CAMPAIGN_NOT_FOUND")


# ---------------------------------------------------------------------------
# Station derived counters (PRD 3.1 / 3.2)
# ---------------------------------------------------------------------------
def recompute_station_staffing(station):
    """certified_inspector_count and decon_service_available.

    The scaffold enumerates station version bumps for the seal, fee, campaign
    and detection cascades but deliberately never for this staffing recompute,
    so this cascade does not advance the station's version.
    """
    if station is None:
        return
    count = 0
    for insp in db.inspectors.values():
        if (insp["home_station_id"] == station["id"]
                and insp["status"] == "ACTIVE"
                and insp["certification_level"] in ("LEVEL_2", "DECON_CERTIFIED")):
            count += 1
    station["certified_inspector_count"] = count
    station["decon_service_available"] = bool(
        count >= calc.CERTIFIED_INSPECTOR_DECON_THRESHOLD
        and station["hot_water_capable"]
    )


def station_staffing_cascade(inspector):
    recompute_station_staffing(db.stations.get(inspector["home_station_id"]))


# ---------------------------------------------------------------------------
# Inspector standing (PRD 2.9 / 3.2) -- lazy certification expiry
# ---------------------------------------------------------------------------
def evaluate_inspector(inspector):
    """Apply the lazy ACTIVE -> EXPIRED transition if it is now due."""
    if inspector is None or inspector["status"] != "ACTIVE":
        return
    expires = parse_iso(inspector["certification_expires_at"])
    if expires is None or now() < expires:
        return
    inspector["status"] = "EXPIRED"
    touch(inspector)
    station_staffing_cascade(inspector)


def require_active(inspector):
    """Rejection step 16."""
    evaluate_inspector(inspector)
    if inspector["status"] != "ACTIVE":
        raise ApiError("ERR_INSPECTOR_NOT_ACTIVE")


def require_decon_certified(inspector):
    """Rejection step 17 for treatment."""
    if (inspector["certification_level"] != "DECON_CERTIFIED"
            or not inspector["decon_endorsement"]):
        raise ApiError("ERR_INSPECTOR_NOT_CERTIFIED")


def require_verifier_certified(inspector):
    """Rejection step 17 for dry verification and quarantine release."""
    if inspector["certification_level"] not in ("LEVEL_2", "DECON_CERTIFIED"):
        raise ApiError("ERR_INSPECTOR_NOT_CERTIFIED")


def stamp_certification_expiry(inspector):
    inspector["certification_expires_at"] = fmt_iso(
        now() + timedelta(hours=calc.CERT_VALID_HOURS)
    )


def recompute_training(inspector):
    """Recredit hours, re-derive the level, and fire any promotion edge."""
    total = Decimal("0")
    for tr in db.training_records.values():
        if tr["inspector_id"] == inspector["id"] and tr["passed"]:
            total += Decimal(str(tr["hours"]))
    total = rhu(total, 2)
    before = (inspector["training_hours_total"], inspector["certification_level"],
              inspector["status"], inspector["certification_expires_at"])
    inspector["training_hours_total"] = float(total)
    inspector["certification_level"] = calc.certification_level_for(
        total, inspector["decon_endorsement"]
    )
    level = inspector["certification_level"]
    if level != "TRAINEE" and inspector["status"] in ("PROBATIONARY", "EXPIRED"):
        inspector["status"] = "ACTIVE"
        stamp_certification_expiry(inspector)
    after = (inspector["training_hours_total"], inspector["certification_level"],
             inspector["status"], inspector["certification_expires_at"])
    if before != after:
        touch(inspector)
    station_staffing_cascade(inspector)


# ---------------------------------------------------------------------------
# Fee ledger (PRD 3.5)
# ---------------------------------------------------------------------------
def apply_fee(record, dwell_seconds=None):
    """Re-run the pinned fee order and book the delta onto the station ledger."""
    station = db.stations.get(record["station_id"])
    previous_total = record["total_fee_cents"]

    waived = False
    if record["reciprocity_seal_honored"] and record["honored_agreement_id"]:
        agreement = db.agreements.get(record["honored_agreement_id"])
        waived = bool(agreement is not None and agreement["fee_waiver"])
    record["inspection_fee_cents"] = 0 if waived else calc.BASE_INSPECTION_FEE_CENTS

    if dwell_seconds is None:
        record["decon_fee_cents"] = 0
    else:
        record["decon_fee_cents"] = calc.decon_fee_for_dwell(dwell_seconds)

    subtotal = record["inspection_fee_cents"] + record["decon_fee_cents"]
    record["surcharge_cents"] = calc.surcharge_for_subtotal(subtotal)
    record["total_fee_cents"] = subtotal + record["surcharge_cents"]

    if station is not None:
        station["collected_fees_cents"] += record["total_fee_cents"] - previous_total
        touch(station)


def refund_treatment_portion(record):
    """Abandonment reverses exactly the treatment-attributable portion."""
    amount = record["decon_fee_cents"] + record["surcharge_cents"]
    record["fee_refunded_cents"] = amount
    station = db.stations.get(record["station_id"])
    if station is not None:
        station["collected_fees_cents"] -= amount
        station["refunded_fees_cents"] += amount
        touch(station)


# ---------------------------------------------------------------------------
# Enforcement strikes (PRD 3.5 / 2.10)
# ---------------------------------------------------------------------------
def derive_watchlist(vessel):
    watchlisted = vessel["compliance_strikes"] >= calc.WATCHLIST_STRIKE_THRESHOLD
    vessel["watchlist_status"] = "WATCHLISTED" if watchlisted else "CLEAR"
    vessel["mandatory_decon_flag"] = bool(watchlisted)


def apply_referral(record, reason, agency_code=None):
    """NONE -> REFERRED plus the three-hop cascade onto the vessel."""
    record["enforcement_status"] = "REFERRED"
    record["referral_reason"] = reason
    if agency_code is not None:
        record["agency_code"] = agency_code
    vessel = db.watercraft.get(record["watercraft_id"])
    if vessel is not None:
        vessel["compliance_strikes"] += 1
        derive_watchlist(vessel)
        touch(vessel)
    touch(record)


# ---------------------------------------------------------------------------
# Screening (PRD 3.3 / 3.4)
# ---------------------------------------------------------------------------
def seal_age_hours(issued_at, arrived_at):
    if issued_at is None or arrived_at is None:
        return 0
    delta = (arrived_at - issued_at).total_seconds()
    return max(0, int(math.floor(delta / 3600.0)))


def apply_screening(record, water_body, vessel, residual, standing_ml,
                    agreement, honored):
    """Writes the seal decision, both scoring variants and the two flags."""
    if honored and agreement is not None:
        record["reciprocity_seal_honored"] = True
        record["reciprocity_credit_points"] = calc.RECIPROCITY_CREDIT_POINTS
        record["honored_agreement_id"] = agreement["id"]
    else:
        record["reciprocity_seal_honored"] = False
        record["reciprocity_credit_points"] = 0
        record["honored_agreement_id"] = None

    record["residual_water_present"] = residual
    record["standing_water_ml"] = standing_ml

    last_removed = parse_iso(vessel["last_removed_at"])
    arrived = parse_iso(record["arrived_at"])

    score, dry_credit = calc.risk_score(
        water_body, vessel, residual, standing_ml,
        record["reciprocity_seal_honored"], last_removed, arrived,
    )
    advisory, _ = calc.risk_score(
        water_body, vessel, residual, standing_ml,
        record["reciprocity_seal_honored"], last_removed, now(),
    )
    record["risk_score"] = score
    record["dry_credit_points"] = dry_credit
    record["advisory_risk_score"] = advisory
    band = calc.risk_band_for(score)
    record["risk_band"] = band

    record["decon_mandatory"] = bool(
        band in ("HIGH", "EXTREME")
        or vessel["mandatory_decon_flag"]
        or (band == "MODERATE" and residual)
    )
    record["quarantine_warranted"] = bool(
        band == "EXTREME"
        or water_body["infestation_status"] == "CONFIRMED_INFESTED"
    )

    record["inspection_status"] = "SCREENED"
    record["screening_completed_at"] = now_iso()
    vessel["last_water_body_id"] = water_body["id"]
    touch(vessel)
    touch(record)


def has_verified_decon(record_id):
    for order in db.decon_orders.values():
        if order["inspection_record_id"] == record_id and order["status"] == "VERIFIED":
            return True
    return False


# ---------------------------------------------------------------------------
# Decontamination bay capacity (PRD 3.6)
# ---------------------------------------------------------------------------
def bay_conflict_count(order, station_id, start, end):
    """Closed-interval overlap count against the other orders at the station."""
    count = 0
    for other in db.decon_orders.values():
        if other["id"] == order["id"]:
            continue
        if other["station_id"] != station_id:
            continue
        if other["treatment_started_at"] is None:
            continue
        if other["status"] not in ("TREATED", "RETREAT_REQUIRED"):
            continue
        o_start = parse_iso(other["treatment_started_at"])
        o_end = parse_iso(other["bay_released_at"]) or o_start
        if o_start is None:
            continue
        if o_start <= end and start <= o_end:
            count += 1
    return count


def apply_treatment(order, record, technician, water_temp_f, pressure_psi,
                    dwell_seconds):
    started = now()
    treated = started + timedelta(seconds=dwell_seconds)
    released = treated + timedelta(minutes=calc.BAY_BUFFER_MINUTES)

    order["water_temp_f"] = water_temp_f
    order["pressure_psi"] = pressure_psi
    order["dwell_seconds"] = dwell_seconds
    order["treatment_started_at"] = fmt_iso(started)
    order["treated_at"] = fmt_iso(treated)
    order["bay_released_at"] = fmt_iso(released)
    order["attempt_count"] = order["attempt_count"] + 1
    order["treated_by_inspector_id"] = technician["id"]
    order["status"] = "TREATED"

    band = order["band_at_order"]
    effectiveness = calc.treatment_effectiveness_pct(
        water_temp_f, pressure_psi, dwell_seconds, band
    )
    order["treatment_effectiveness_pct"] = float(effectiveness)
    base, required = calc.required_dry_hours(band, effectiveness)
    order["base_dry_hours"] = base
    order["required_dry_hours"] = required
    order["dry_until"] = fmt_iso(treated + timedelta(hours=required))

    apply_fee(record, dwell_seconds)
    touch(record)
    touch(order)


# ---------------------------------------------------------------------------
# Quarantine holds (PRD 3.7)
# ---------------------------------------------------------------------------
def apply_hold(order, vessel):
    order["hold_hours_required"] = calc.hold_hours_for(
        order["band_at_issue"], order["rejected_release_count"]
    )
    issued = parse_iso(order["issued_at"])
    order["hold_until"] = fmt_iso(
        issued + timedelta(hours=order["hold_hours_required"])
    )
    if vessel is not None:
        vessel["quarantine_hold_until"] = order["hold_until"]


def retire_seal(station):
    if station is None:
        return
    station["seals_in_circulation_count"] -= 1
    station["seals_retired_count"] += 1
    touch(station)


def station_seal_state_code(station):
    if station["station_type"] == "WATERBODY_ACCESS":
        water_body = db.water_bodies.get(station["water_body_id"])
        if water_body is not None:
            return water_body["state_code"]
    return calc.PROGRAM_STATE_CODE


# ---------------------------------------------------------------------------
# Detection acceptance cascade (PRD 3.8)
# ---------------------------------------------------------------------------
def accept_detection(report):
    water_body = db.water_bodies.get(report["water_body_id"])
    if water_body is None:
        return
    water_body["detection_count"] += 1
    if report["detection_class"] == "LIVE_ORGANISM":
        water_body["live_detection_count"] += 1

    confirmed = False
    if water_body["live_detection_count"] >= calc.INFESTATION_CONFIRM_LIVE_THRESHOLD:
        water_body["infestation_status"] = "CONFIRMED_INFESTED"
        water_body["risk_tier"] = "HIGH"
        confirmed = True
    elif (water_body["detection_count"] >= calc.INFESTATION_SUSPECT_DETECTION_THRESHOLD
            and water_body["infestation_status"] == "CLEAN"):
        water_body["infestation_status"] = "SUSPECT"
    touch(water_body)

    if not confirmed:
        return
    for station in db.stations.values():
        if (station["water_body_id"] == water_body["id"]
                and station["status"] in ("PLANNED", "OPEN", "SUSPENDED")
                and not station["mandatory_inspection"]):
            station["mandatory_inspection"] = True
            touch(station)
            for window in db.station_hours.values():
                if (window["station_id"] == station["id"]
                        and window["staffing_level"] == "SINGLE"):
                    window["staffing_level"] = "DOUBLE"
                    touch(window)


# ---------------------------------------------------------------------------
# Campaign allocation and evaluation (PRD 3.9)
# ---------------------------------------------------------------------------
COMPLIANT_STATUSES = ("PASSED", "DECON_COMPLETED")
DISPOSED_STATUSES = ("PASSED", "DECON_COMPLETED", "REFUSED", "DECON_FAILED_ABANDONED")


def campaign_candidates(campaign):
    """Candidate stations in the pinned order: created_at ASC then name bytes ASC."""
    rows = [
        s for s in db.stations.values()
        if s["water_body_id"] == campaign["target_water_body_id"]
        and s["status"] in ("PLANNED", "OPEN", "SUSPENDED")
    ]
    rows.sort(key=lambda s: (s["created_at"], s["name"].encode("utf-8")))
    return rows


def records_in_window(station_id, start, end):
    count = 0
    for record in db.records.values():
        if station_id is not None and record["station_id"] != station_id:
            continue
        arrived = parse_iso(record["arrived_at"])
        if arrived is None:
            continue
        if start <= arrived < end:
            count += 1
    return count


def allocate_campaign(campaign):
    """Floored-per-station shares plus one-cent remainder walk in pinned order."""
    candidates = campaign_candidates(campaign)
    if not candidates:
        raise ApiError("ERR_NO_STATIONS_FOR_CAMPAIGN")
    budget = campaign["budget_cents"]
    if budget < len(candidates):
        raise ApiError("ERR_CAMPAIGN_BUDGET_EXCEEDED")

    start = parse_iso(campaign["start_at"])
    end = parse_iso(campaign["end_at"])
    weights = [1 + records_in_window(s["id"], start, end) for s in candidates]
    total_weight = sum(weights)

    amounts = [int((budget * w) // total_weight) for w in weights]
    remainder = budget - sum(amounts)
    index = 0
    while remainder > 0 and amounts:
        amounts[index % len(amounts)] += 1
        remainder -= 1
        index += 1

    allocations = []
    for station, amount in zip(candidates, amounts):
        station["campaign_allocated_cents"] += amount
        touch(station)
        allocations.append({"station_id": station["id"], "allocated_cents": amount})
    campaign["station_allocations"] = allocations


def deallocate_campaign(campaign):
    for entry in campaign["station_allocations"]:
        station = db.stations.get(entry["station_id"])
        if station is not None:
            station["campaign_allocated_cents"] -= entry["allocated_cents"]
            touch(station)
    campaign["station_allocations"] = []


def compliance_rate(target_water_body_id, start, end):
    """Half-open window on arrived_at; None when the denominator is empty."""
    numerator = 0
    denominator = 0
    for record in db.records.values():
        if (target_water_body_id is not None
                and record["prior_water_body_id"] != target_water_body_id):
            continue
        arrived = parse_iso(record["arrived_at"])
        if arrived is None or not (start <= arrived < end):
            continue
        if record["inspection_status"] in DISPOSED_STATUSES:
            denominator += 1
            if record["inspection_status"] in COMPLIANT_STATUSES:
                numerator += 1
    if denominator == 0:
        return None
    return Decimal(numerator) / Decimal(denominator)
