"""Calculation rules (PRD sections 3.4, 3.6, 3.7, 3.8, 3.9).

Every monetary amount is an integer count of cents; each rate-driven component
is rounded half up to whole cents BEFORE the components are combined.
"""
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

import clock
import constants
import db
from services import lookup

ONE = Decimal("1")
INFUSION_MIN_VOLUME = Decimal("7.6")
LANCETS_MAX_VOLUME = Decimal("11.4")


def round_half_up(value):
    """Round a Decimal half up to a whole integer."""
    return int(Decimal(value).quantize(ONE, rounding=ROUND_HALF_UP))


def as_decimal(value):
    """Exact decimal view of a stored numeric literal."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# container_size_selection
# ---------------------------------------------------------------------------

def required_units(patient, enrollment):
    upi = constants.UNITS_PER_ITEM[patient["therapy_type"]]
    numerator = (
        patient["weekly_sharps_count"]
        * upi
        * enrollment["cadence_days"]
        * constants.SAFETY_MARGIN_NUMERATOR
    )
    denominator = constants.SAFETY_MARGIN_DENOMINATOR * constants.DAYS_PER_WEEK
    # exactly one ceiling, applied to the final quotient
    return -((-numerator) // denominator)


def candidate_sizes(patient, state_rule, demand):
    cap = as_decimal(state_rule["max_container_volume_liters"])
    therapy = patient["therapy_type"]
    rows = []
    for code, row in constants.SIZE_CATALOG.items():
        volume = row["volume_liters"]
        if volume > cap:
            continue
        if row["capacity_units"] < demand:
            continue
        if therapy == "INFUSION_SETS" and volume < INFUSION_MIN_VOLUME:
            continue
        if therapy == "LANCETS_ONLY" and volume > LANCETS_MAX_VOLUME:
            continue
        rows.append(code)
    rows.sort(
        key=lambda c: (
            constants.SIZE_CATALOG[c]["capacity_units"],
            constants.SIZE_CATALOG[c]["volume_liters"],
            c,
        )
    )
    return rows


def seal_deadline_date(issued_at, cadence_days):
    return clock.fmt_date(
        issued_at.date() + timedelta(days=cadence_days + constants.SEAL_GRACE_DAYS)
    )


# ---------------------------------------------------------------------------
# kit_cost_provisional
# ---------------------------------------------------------------------------

def provisional_cost_cents(container_size):
    row = constants.SIZE_CATALOG[container_size]
    estimated_grams = row["capacity_units"] * constants.ESTIMATED_GRAMS_PER_UNIT
    transport = round_half_up(
        Decimal(estimated_grams) * constants.TRANSPORT_RATE_CENTS_PER_KG / Decimal(1000)
    )
    return row["unit_cost_cents"] + transport


# ---------------------------------------------------------------------------
# kit_cost_final_settlement
# ---------------------------------------------------------------------------

def resolved_remediation_action(shipment_id):
    for event in lookup.shipment_events(shipment_id):
        if event["status"] == "RESOLVED" and event["remediation_action"] is not None:
            return event["remediation_action"]
    return None


def rebate_pct_for_basis(basis_cents):
    for low, high, pct in constants.REBATE_TIERS:
        if low <= basis_cents <= high:
            return pct
    return Decimal("0.00")


def final_settlement(kit, shipment, sponsor, program, destroyed_units, committed_before):
    base = constants.SIZE_CATALOG[kit["container_size"]]["unit_cost_cents"]
    transport = round_half_up(
        Decimal(shipment["observed_gross_weight_grams"])
        * constants.TRANSPORT_RATE_CENTS_PER_KG
        / Decimal(1000)
    )
    destruction = round_half_up(
        Decimal(destroyed_units)
        * constants.DESTRUCTION_RATE_CENTS_PER_UNIT[sponsor["sponsor_type"]]
    )
    action = resolved_remediation_action(shipment["id"])
    surcharge = constants.REMEDIATION_SURCHARGE_CENTS[action if action else "NONE"]

    pre_rebate = base + transport + destruction + surcharge
    capped = min(program["per_kit_allowance_cents"], pre_rebate)

    if sponsor["sponsor_type"] == "HEALTH_PLAN":
        rebate_pct = Decimal("0.00")
    else:
        rebate_pct = rebate_pct_for_basis(committed_before + capped)
    rebate = round_half_up(Decimal(capped) * rebate_pct)
    return capped - rebate, rebate_pct


# ---------------------------------------------------------------------------
# patient_risk_score
# ---------------------------------------------------------------------------

def patient_events(patient_id):
    events = []
    for event in db.ordered("nonconformance_events"):
        shipment = db.get("shipments", event["shipment_id"])
        if shipment is None:
            continue
        kit = lookup.shipment_kit(shipment)
        if kit is None:
            continue
        enrollment = lookup.kit_enrollment(kit)
        if enrollment is None or enrollment["patient_id"] != patient_id:
            continue
        events.append(event)
    return events


def _age_days(created_at_iso):
    created = clock.parse_instant(created_at_iso)
    delta = clock.now() - created
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return 0
    return seconds // 86400


def screening_risk_score(patient):
    total = Decimal(0)
    for event in patient_events(patient["id"]):
        weight = constants.REASON_WEIGHTS[event["reason_code"]]
        age = _age_days(event["created_at"])
        if age <= constants.DECAY_FRESH_MAX_AGE_DAYS:
            factor = Decimal("1")
        elif age <= constants.DECAY_HALF_MAX_AGE_DAYS:
            factor = Decimal("0.5")
        else:
            factor = Decimal("0")
        total += Decimal(weight) * factor
    return min(constants.SCORE_CEILING, round_half_up(total))


def late_kit_count(patient_id):
    today = clock.now_date_iso()
    count = 0
    for kit in lookup.patient_kits(patient_id):
        if kit["status"] not in ("ISSUED", "ACTIVE_FILLING"):
            continue
        if kit["seal_deadline_date"] is not None and kit["seal_deadline_date"] < today:
            count += 1
    return count


def audit_risk_score(patient):
    total = 0
    for event in patient_events(patient["id"]):
        total += constants.REASON_WEIGHTS[event["reason_code"]]
    total += constants.LATE_KIT_PENALTY * late_kit_count(patient["id"])
    return min(constants.SCORE_CEILING, total)


def refresh_screening_score(patient):
    """Computed field refresh: no version bump, no updated_at change."""
    patient["screening_risk_score"] = screening_risk_score(patient)
    return patient["screening_risk_score"]


def refresh_audit_score(patient):
    patient["audit_risk_score"] = audit_risk_score(patient)
    return patient["audit_risk_score"]


# ---------------------------------------------------------------------------
# label_validity_window
# ---------------------------------------------------------------------------

def label_window(valid_from):
    return valid_from + timedelta(days=constants.LABEL_VALIDITY_DAYS)


def label_window_conflict(kit_id, new_from, new_until):
    for label in lookup.kit_labels(kit_id):
        if label["status"] in ("PRINTED", "ACTIVATED"):
            existing_from = clock.parse_instant(label["valid_from"])
            existing_until = clock.parse_instant(label["valid_until"])
            if new_from <= existing_until and existing_from <= new_until:
                return True
    return False


def label_quarantine_active(kit_id):
    now = clock.now()
    for label in lookup.kit_labels(kit_id):
        if label["status"] != "VOIDED" or label["voided_at"] is None:
            continue
        voided_at = clock.parse_instant(label["voided_at"])
        boundary = voided_at + timedelta(hours=constants.LABEL_VOID_QUARANTINE_HOURS)
        if now < boundary:
            return True
    return False


# ---------------------------------------------------------------------------
# facility_intake_occupancy
# ---------------------------------------------------------------------------

def shipment_is_open(shipment):
    if shipment["transport_status"] == "LOST":
        return False
    for certificate in lookup.shipment_certificates(shipment["id"]):
        if certificate["status"] == "ISSUED":
            return False
    for event in lookup.shipment_events(shipment["id"]):
        if event["status"] == "RESOLVED" and event["remediation_action"] == "RETURN_TO_PATIENT":
            return False
    return True


def booked_units(facility_id, intake_date):
    total = 0
    for shipment in db.ordered("shipments"):
        if shipment["treatment_facility_id"] != facility_id:
            continue
        if shipment["scheduled_intake_date"] != intake_date:
            continue
        if not shipment_is_open(shipment):
            continue
        total += shipment["custody_units"]
    return total


# ---------------------------------------------------------------------------
# certificate_retention_deadline
# ---------------------------------------------------------------------------

def retention_until_date(destruction_date, patient_rule, facility_rule):
    years = constants.FEDERAL_MIN_RETENTION_YEARS
    for rule in (patient_rule, facility_rule):
        if rule is not None and rule["certificate_retention_years"] > years:
            years = rule["certificate_retention_years"]
    return clock.fmt_date(clock.add_calendar_years(destruction_date, years))


# ---------------------------------------------------------------------------
# tracking_number_minting
# ---------------------------------------------------------------------------

def next_tracking_number(postal_service):
    sequence = len(db.coll("return_labels")) + 1
    return "%s-%s" % (
        constants.POSTAL_PREFIX[postal_service],
        str(sequence).zfill(constants.TRACKING_SEQUENCE_WIDTH),
    )


def next_certificate_number(facility):
    sequence = facility["certificates_issued_count"] + 1
    return "CERT-%s-%s" % (
        facility["permit_number"],
        str(sequence).zfill(constants.CERTIFICATE_SEQUENCE_WIDTH),
    )
