"""Procedures: booking and capacity, the room workflow, device reservation
and the revenue cycle.  PRD sections 3.5 - 3.8.
"""
from datetime import timedelta

from flask import Blueprint, request

import calc
from core import (
    ApiError, authenticate, base_record, db, envelope_array, envelope_object, filter_equals,
    get_body, list_response, must_get, now_dt, now_str, opt_enum, opt_id,
    opt_str, parse_date, parse_dt, public, req_bool, req_dt, req_enum, req_id,
    req_int, req_num, req_str, touch,
)

bp = Blueprint("procedure", __name__)

ALL_ROLES = ("CenterAdmin", "AccessCoordinator", "FacilityCoordinator",
             "Interventionalist", "SedationRN", "Coder")

PROCEDURE_TYPES = ("ANGIOPLASTY", "THROMBECTOMY", "CATHETER_EXCHANGE",
                   "FISTULA_MATURATION_INTERVENTION")
SEDATION_LEVELS = ("NONE", "MODERATE")
CODE_FAMILIES = ("ANGIOPLASTY", "THROMBECTOMY", "CATH_EXCHANGE", "IMAGING",
                 "ACCESS_MAINTENANCE_BUNDLE")
MODIFIERS = ("NONE", "M59", "M52")
DEVICE_TYPES = ("SHEATH", "BALLOON", "STENT")
DENIAL_REASONS = ("MEDICAL_NECESSITY", "BUNDLING", "DOCUMENTATION", "TIMELY_FILING")
TERMINAL_CLINICAL = ("DISCHARGED", "ABORTED", "CANCELLED")
ACTIVE_ROOM_STATUSES = ("SCHEDULED", "IN_ROOM", "RECOVERY")


def credential_valid(clinician):
    """PRD 3.1: valid while credential_expires_on falls on or after today."""
    if not clinician["moderate_sedation_credentialed"]:
        return False
    expires_on = clinician["credential_expires_on"]
    if expires_on is None:
        return False
    return parse_date(expires_on) >= now_dt().date()


def require_state(procedure, expected, specific_error):
    """Terminal states report ERR_PROCEDURE_TERMINAL; otherwise the specific id."""
    if procedure["clinical_status"] == expected:
        return
    if procedure["clinical_status"] in TERMINAL_CLINICAL:
        raise ApiError("ERR_PROCEDURE_TERMINAL")
    raise ApiError(specific_error)


# ---------------------------------------------------------------------------
# Booking (PRD 3.5)
# ---------------------------------------------------------------------------
@bp.post("/procedures")
def create_procedure():
    user_id, role = authenticate(("AccessCoordinator", "CenterAdmin"))
    body = get_body()
    referral_id = req_id(body, "referral_id")
    room_id = req_id(body, "room_id")
    primary_operator_id = req_id(body, "primary_operator_id")
    procedure_type = req_enum(body, "procedure_type", PROCEDURE_TYPES)
    sedation_level = req_enum(body, "sedation_level", SEDATION_LEVELS)
    start_raw, start_dt = req_dt(body, "scheduled_start")
    end_raw, end_dt = req_dt(body, "scheduled_end")
    expected_version = req_int(body, "expected_referral_version")
    if end_dt <= start_dt:
        raise ApiError("ERR_INVALID_REQUEST")
    sedation_rn_id = None
    if sedation_level == "MODERATE":
        sedation_rn_id = req_id(body, "sedation_rn_id")

    referral = must_get(db.referrals, referral_id, "ERR_REFERRAL_NOT_FOUND")
    room = must_get(db.rooms, room_id, "ERR_ROOM_NOT_FOUND")
    operator = must_get(db.clinicians, primary_operator_id, "ERR_CLINICIAN_NOT_FOUND")
    nurse = None
    if sedation_rn_id is not None:
        nurse = must_get(db.clinicians, sedation_rn_id, "ERR_CLINICIAN_NOT_FOUND")

    # Rung 7: clinician role fit.
    if operator["clinician_role"] != "INTERVENTIONALIST":
        raise ApiError("ERR_CLINICIAN_ROLE_MISMATCH")
    if nurse is not None and nurse["clinician_role"] != "SEDATION_RN":
        raise ApiError("ERR_CLINICIAN_ROLE_MISMATCH")

    # Rung 8: the referral must be TRIAGED.
    if referral["status"] != "TRIAGED":
        raise ApiError("ERR_REFERRAL_NOT_TRIAGED")

    # Rung 9: optimistic concurrency on the parent referral.
    if expected_version != referral["version"]:
        raise ApiError("ERR_STALE_REFERRAL_VERSION")

    # Rung 10: moderate-sedation credentialing.
    if sedation_level == "MODERATE" and not credential_valid(nurse):
        raise ApiError("ERR_SEDATION_CREDENTIAL_INVALID")

    # Rung 16: booking not in the past.
    if start_dt < now_dt():
        raise ApiError("ERR_SCHEDULE_IN_PAST")

    # Rung 17: the urgency window earned at triage.
    urgency = referral["urgency"]
    triaged_at = parse_dt(referral["triaged_at"]) if referral["triaged_at"] else None
    if urgency == "SAME_DAY":
        if triaged_at is None or start_dt.date() != triaged_at.date():
            raise ApiError("ERR_SAME_DAY_WINDOW_MISSED")
    elif urgency == "NEXT_DAY":
        if triaged_at is None:
            raise ApiError("ERR_SAME_DAY_WINDOW_MISSED")
        delta_days = (start_dt.date() - triaged_at.date()).days
        if delta_days < 0 or delta_days > 1:
            raise ApiError("ERR_SAME_DAY_WINDOW_MISSED")

    buffer_min = timedelta(minutes=room["turnover_buffer_min"])
    candidate_block_end = end_dt + buffer_min

    # Rung 18: pairwise room occupancy including the turnover buffer.
    for other in db.procedures.values():
        if other["room_id"] != room_id:
            continue
        if other["clinical_status"] in ("CANCELLED", "ABORTED"):
            continue
        other_start = parse_dt(other["scheduled_start"])
        other_block_end = parse_dt(other["scheduled_end"]) + buffer_min
        if start_dt < other_block_end and other_start < candidate_block_end:
            raise ApiError("ERR_ROOM_OCCUPIED")

    # Rung 19: room daily case cap, with the same-day surge allowance.
    same_day_count = 0
    for other in db.procedures.values():
        if other["room_id"] != room_id:
            continue
        if other["clinical_status"] not in ("SCHEDULED", "IN_ROOM", "RECOVERY", "DISCHARGED"):
            continue
        if parse_dt(other["scheduled_start"]).date() == start_dt.date():
            same_day_count += 1
    surge = 0
    if (urgency == "SAME_DAY" and room["room_type"] == "ANGIO_SUITE"
            and start_dt.hour < calc.SURGE_CUTOFF_HOUR_UTC):
        surge = calc.SURGE_ALLOWANCE
    if room["daily_case_cap"] + surge - same_day_count < 1:
        raise ApiError("ERR_ROOM_DAILY_CAP_REACHED")

    if sedation_level == "MODERATE":
        # Rung 20: the sedation nurse's concurrency ceiling.
        overlapping = 0
        for other in db.procedures.values():
            if other["sedation_rn_id"] != sedation_rn_id:
                continue
            if other["sedation_level"] != "MODERATE":
                continue
            if other["clinical_status"] not in ACTIVE_ROOM_STATUSES:
                continue
            other_start = parse_dt(other["scheduled_start"])
            other_end = parse_dt(other["scheduled_end"])
            if start_dt < other_end and other_start < end_dt:
                overlapping += 1
        if nurse["max_concurrent_sedation_cases"] - overlapping < 1:
            raise ApiError("ERR_SEDATION_CAPACITY_EXCEEDED")

        # Rung 21: recovery-bay availability over the closed 90-minute window.
        window = timedelta(minutes=calc.RECOVERY_WINDOW_MIN)
        candidate_recovery_end = end_dt + window
        bay_count = 0
        for other in db.procedures.values():
            if other["room_id"] != room_id:
                continue
            if other["sedation_level"] != "MODERATE":
                continue
            if other["clinical_status"] not in ACTIVE_ROOM_STATUSES:
                continue
            other_recovery_start = parse_dt(other["scheduled_end"])
            other_recovery_end = other_recovery_start + window
            if end_dt <= other_recovery_end and other_recovery_start <= candidate_recovery_end:
                bay_count += 1
        if room["recovery_bay_count"] // calc.RECOVERY_BAYS_PER_CASE - bay_count < 1:
            raise ApiError("ERR_RECOVERY_BAY_UNAVAILABLE")

    procedure = base_record()
    procedure.update({
        "referral_id": referral_id,
        "access_id": referral["access_id"],
        "room_id": room_id,
        "primary_operator_id": primary_operator_id,
        "sedation_rn_id": sedation_rn_id,
        "attested_by_id": None,
        "supporting_reading_id": None,
        "procedure_type": procedure_type,
        "sedation_level": sedation_level,
        "scheduled_start": start_raw,
        "scheduled_end": end_raw,
        "clinical_status": "SCHEDULED",
        "coding_status": "UNCODED",
        "sedation_end_at": None,
        "discharged_at": None,
        "reimbursement_variant": None,
        "allowed_amount_cents": 0,
        "billed_amount_cents": 0,
        "denied_amount_cents": 0,
        "net_receivable_cents": 0,
        "rebill_count": 0,
        "medical_necessity_statement": None,
        "abort_reason": None,
        "cancel_reason": None,
        "denial_reason": None,
        "denial_code": None,
    })
    db.procedures[procedure["id"]] = procedure

    referral["status"] = "SCHEDULED"
    touch(referral)

    return envelope_object(public(procedure)), 201


@bp.post("/procedures/<procedure_id>/cancel")
def cancel_procedure(procedure_id):
    authenticate(("AccessCoordinator", "CenterAdmin"))
    procedure = must_get(db.procedures, procedure_id, "ERR_PROCEDURE_NOT_FOUND")
    body = get_body()
    opt_str(body, "cancel_note")
    require_state(procedure, "SCHEDULED", "ERR_PROCEDURE_NOT_SCHEDULED")

    procedure["clinical_status"] = "CANCELLED"
    procedure["cancel_reason"] = "COORDINATOR_CANCEL"
    touch(procedure)
    calc.release_reserved_usages(procedure)

    referral = db.referrals.get(procedure["referral_id"])
    if referral is not None and referral["status"] == "SCHEDULED":
        referral["status"] = "TRIAGED"
        touch(referral)

    return envelope_object(public(procedure)), 200


# ---------------------------------------------------------------------------
# Device reservation (PRD 3.6)
# ---------------------------------------------------------------------------
def new_usage(procedure_id, lot, quantity):
    usage = base_record()
    usage.update({
        "procedure_id": procedure_id,
        "device_lot_id": lot["id"],
        "quantity": quantity,
        "wasted_quantity": 0,
        "state": "RESERVED",
        "consumed_at": None,
        "released_at": None,
    })
    db.usages[usage["id"]] = usage
    lot["quantity_reserved"] += quantity
    touch(lot)
    return usage


@bp.post("/procedures/<procedure_id>/device-usages")
def reserve_usage(procedure_id):
    authenticate(("Interventionalist", "AccessCoordinator", "CenterAdmin"))
    procedure = must_get(db.procedures, procedure_id, "ERR_PROCEDURE_NOT_FOUND")
    body = get_body()
    lot_id = req_id(body, "device_lot_id")
    quantity = req_int(body, "quantity", minimum=1)
    expected_version = req_int(body, "expected_device_lot_version")

    lot = must_get(db.lots, lot_id, "ERR_DEVICE_LOT_NOT_FOUND")

    # Rung 9: optimistic concurrency on the named lot.
    if expected_version != lot["version"]:
        raise ApiError("ERR_STALE_DEVICE_LOT_VERSION")

    # Rung 11: device-lot posture.
    if lot["status"] == "QUARANTINED":
        raise ApiError("ERR_DEVICE_LOT_QUARANTINED")
    case_date = parse_dt(procedure["scheduled_start"]).date()
    if lot["status"] == "EXPIRED" or parse_date(lot["expires_on"]) <= case_date:
        raise ApiError("ERR_DEVICE_LOT_EXPIRED")

    # Rung 30: device stock.
    headroom = calc.lot_headroom(lot)
    if lot["status"] == "DEPLETED" or headroom == 0:
        raise ApiError("ERR_LOT_DEPLETED")
    if headroom < quantity:
        raise ApiError("ERR_INSUFFICIENT_DEVICE_STOCK")

    usage = new_usage(procedure_id, lot, quantity)
    return envelope_object(public(usage)), 201


@bp.post("/procedures/<procedure_id>/device-allocations")
def allocate_usages(procedure_id):
    authenticate(("Interventionalist", "AccessCoordinator", "CenterAdmin"))
    procedure = must_get(db.procedures, procedure_id, "ERR_PROCEDURE_NOT_FOUND")
    body = get_body()
    device_type = req_enum(body, "device_type", DEVICE_TYPES)
    quantity = req_int(body, "quantity", minimum=1)

    case_date = parse_dt(procedure["scheduled_start"]).date()
    candidates = [lot for lot in db.lots.values()
                  if lot["device_type"] == device_type
                  and lot["status"] == "AVAILABLE"
                  and parse_date(lot["expires_on"]) > case_date
                  and calc.lot_headroom(lot) > 0]
    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_LOT")
    candidates.sort(key=calc.lot_sort_key)
    if sum(calc.lot_headroom(lot) for lot in candidates) < quantity:
        raise ApiError("ERR_INSUFFICIENT_DEVICE_STOCK")

    outstanding = quantity
    created = []
    for lot in candidates:
        if outstanding <= 0:
            break
        take = min(outstanding, calc.lot_headroom(lot))
        if take <= 0:
            continue
        created.append(new_usage(procedure_id, lot, take))
        outstanding -= take

    return envelope_array([public(u) for u in created]), 201


@bp.get("/device-usages/<usage_id>")
def get_usage(usage_id):
    authenticate(("CenterAdmin", "AccessCoordinator", "Interventionalist", "Coder"))
    usage = must_get(db.usages, usage_id, "ERR_DEVICE_USAGE_NOT_FOUND")
    return envelope_object(public(usage)), 200


@bp.get("/device-usages")
def list_usages():
    authenticate(("CenterAdmin", "AccessCoordinator", "Interventionalist", "Coder"))
    rows = list(db.usages.values())
    rows = filter_equals(rows, "procedure_id", request.args.get("procedure_id"))
    rows = filter_equals(rows, "device_lot_id", request.args.get("device_lot_id"))
    rows = filter_equals(rows, "state", request.args.get("state"))
    return list_response(calc.seq_sorted(rows))


# ---------------------------------------------------------------------------
# In the room (PRD 3.7)
# ---------------------------------------------------------------------------
@bp.post("/procedures/<procedure_id>/start")
def start_procedure(procedure_id):
    user_id, role = authenticate(("Interventionalist",))
    procedure = must_get(db.procedures, procedure_id, "ERR_PROCEDURE_NOT_FOUND")

    # Rung 7: reserved to the assigned primary operator.
    if user_id != procedure["primary_operator_id"]:
        raise ApiError("ERR_NOT_ASSIGNED_CLINICIAN")
    require_state(procedure, "SCHEDULED", "ERR_PROCEDURE_NOT_SCHEDULED")

    # Rung 10: the sedation credential is re-checked against this request's clock.
    if procedure["sedation_level"] == "MODERATE":
        nurse = db.clinicians.get(procedure["sedation_rn_id"])
        if nurse is None or not credential_valid(nurse):
            raise ApiError("ERR_SEDATION_CREDENTIAL_INVALID")

    # Rung 13: the access must not have been abandoned since booking.
    access = db.accesses.get(procedure["access_id"])
    if access is None or access["status"] == "ABANDONED":
        raise ApiError("ERR_ACCESS_ABANDONED")
    if access["status"] not in ("MATURING", "IN_USE", "DYSFUNCTIONAL"):
        raise ApiError("ERR_ACCESS_ABANDONED")

    procedure["clinical_status"] = "IN_ROOM"
    touch(procedure)
    return envelope_object(public(procedure)), 200


@bp.post("/procedures/<procedure_id>/recovery")
def to_recovery(procedure_id):
    user_id, role = authenticate(("Interventionalist",))
    procedure = must_get(db.procedures, procedure_id, "ERR_PROCEDURE_NOT_FOUND")
    body = get_body()
    sedation_end_raw, sedation_end_dt = req_dt(body, "sedation_end_at")
    if sedation_end_dt < parse_dt(procedure["scheduled_start"]):
        raise ApiError("ERR_INVALID_REQUEST")

    if user_id != procedure["primary_operator_id"]:
        raise ApiError("ERR_NOT_ASSIGNED_CLINICIAN")
    require_state(procedure, "IN_ROOM", "ERR_PROCEDURE_NOT_IN_ROOM")

    procedure["sedation_end_at"] = sedation_end_raw
    procedure["clinical_status"] = "RECOVERY"
    touch(procedure)
    return envelope_object(public(procedure)), 200


@bp.post("/procedures/<procedure_id>/recovery-observations")
def chart_observation(procedure_id):
    user_id, role = authenticate(("SedationRN",))
    procedure = must_get(db.procedures, procedure_id, "ERR_PROCEDURE_NOT_FOUND")
    body = get_body()
    observed_raw, observed_dt = req_dt(body, "observed_at")
    aldrete = req_int(body, "aldrete_score", minimum=0, maximum=10)
    on_room_air = req_bool(body, "on_room_air")

    if user_id != procedure["sedation_rn_id"]:
        raise ApiError("ERR_NOT_ASSIGNED_CLINICIAN")
    if procedure["clinical_status"] != "RECOVERY":
        raise ApiError("ERR_PROCEDURE_NOT_IN_RECOVERY")

    observation = base_record(versioned=False)
    observation.update({
        "procedure_id": procedure_id,
        "observed_at": observed_raw,
        "aldrete_score": aldrete,
        "on_room_air": on_room_air,
    })
    db.observations[observation["id"]] = observation
    return envelope_object(public(observation)), 201


def observation_sort_key(observation):
    return (parse_dt(observation["observed_at"]), observation["created_at"], observation["_seq"])


def procedure_observations(procedure_id):
    rows = [o for o in db.observations.values() if o["procedure_id"] == procedure_id]
    return sorted(rows, key=observation_sort_key)


@bp.post("/procedures/<procedure_id>/discharge")
def discharge(procedure_id):
    user_id, role = authenticate(("SedationRN",))
    procedure = must_get(db.procedures, procedure_id, "ERR_PROCEDURE_NOT_FOUND")

    if user_id != procedure["sedation_rn_id"]:
        raise ApiError("ERR_NOT_ASSIGNED_CLINICIAN")
    require_state(procedure, "RECOVERY", "ERR_PROCEDURE_NOT_IN_RECOVERY")

    # Rung 12: the three recovery discharge criteria.
    observations = procedure_observations(procedure_id)
    if len(observations) < calc.MIN_OBSERVATIONS:
        raise ApiError("ERR_RECOVERY_CRITERIA_NOT_MET")
    last = observations[-1]
    if last["aldrete_score"] < calc.MIN_ALDRETE or last["on_room_air"] is not True:
        raise ApiError("ERR_RECOVERY_CRITERIA_NOT_MET")
    span = parse_dt(observations[-1]["observed_at"]) - parse_dt(observations[0]["observed_at"])
    if span < timedelta(minutes=calc.MIN_RECOVERY_SPAN_MIN):
        raise ApiError("ERR_RECOVERY_CRITERIA_NOT_MET")

    # Hop 1: discharge the case and consume its reserved devices.
    procedure["clinical_status"] = "DISCHARGED"
    procedure["discharged_at"] = now_str()
    touch(procedure)
    calc.consume_reserved_usages(procedure, waste=False)

    referral = db.referrals.get(procedure["referral_id"])
    if referral is not None and referral["status"] == "SCHEDULED":
        # Hop 2: the parent referral completes.
        referral["status"] = "COMPLETED"
        referral["completed_at"] = now_str()
        touch(referral)

        # Hop 3: re-evaluate the vascular access.
        access = db.accesses.get(procedure["access_id"])
        if access is not None:
            reached_in_use = False
            if access["status"] == "DYSFUNCTIONAL":
                access["status"] = "IN_USE"
                reached_in_use = True
            elif (access["status"] == "MATURING"
                  and procedure["procedure_type"] == "FISTULA_MATURATION_INTERVENTION"):
                access["status"] = "IN_USE"
                reached_in_use = True
            counters_changed = calc.recompute_access_counters(access)
            if reached_in_use or counters_changed:
                touch(access)
            if reached_in_use:
                # Hops 4 and 5.
                calc.convert_ready_plans(access)

    facility = db.facilities.get(referral["referring_facility_id"]) if referral else None
    if facility is not None:
        calc.score_facility(facility)

    return envelope_object(public(procedure)), 200


@bp.post("/procedures/<procedure_id>/abort")
def abort(procedure_id):
    user_id, role = authenticate(("Interventionalist",))
    procedure = must_get(db.procedures, procedure_id, "ERR_PROCEDURE_NOT_FOUND")
    body = get_body()
    abort_reason = req_str(body, "abort_reason")

    if user_id != procedure["primary_operator_id"]:
        raise ApiError("ERR_NOT_ASSIGNED_CLINICIAN")
    require_state(procedure, "IN_ROOM", "ERR_PROCEDURE_NOT_IN_ROOM")

    procedure["clinical_status"] = "ABORTED"
    procedure["abort_reason"] = abort_reason
    touch(procedure)
    calc.consume_reserved_usages(procedure, waste=True)
    return envelope_object(public(procedure)), 200


# ---------------------------------------------------------------------------
# The revenue cycle (PRD 3.8)
# ---------------------------------------------------------------------------
@bp.post("/procedures/<procedure_id>/codes")
def file_code(procedure_id):
    user_id, role = authenticate(("Coder",))
    procedure = must_get(db.procedures, procedure_id, "ERR_PROCEDURE_NOT_FOUND")
    body = get_body()
    hcpcs_code = req_str(body, "hcpcs_code")
    code_family = req_enum(body, "code_family", CODE_FAMILIES)
    base_allowed_cents = req_int(body, "base_allowed_cents", minimum=0)
    rank = req_int(body, "rank", minimum=1)
    modifier = opt_enum(body, "modifier", MODIFIERS, "NONE")

    # Rung 8: the two coding preconditions both report ERR_CODING_STATE_INVALID.
    if procedure["clinical_status"] not in ("DISCHARGED", "ABORTED"):
        raise ApiError("ERR_CODING_STATE_INVALID")
    if procedure["coding_status"] not in ("UNCODED", "CODED"):
        raise ApiError("ERR_CODING_STATE_INVALID")

    # Rung 14: segregation of duties across the case triangle.
    if user_id == procedure["primary_operator_id"] or user_id == procedure["sedation_rn_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    # Rung 24: rank uniqueness within the procedure.
    for existing in calc.procedure_code_lines(procedure_id):
        if existing["rank"] == rank:
            raise ApiError("ERR_DUPLICATE_CODE_RANK")

    line = base_record()
    line.update({
        "procedure_id": procedure_id,
        "hcpcs_code": hcpcs_code,
        "code_family": code_family,
        "base_allowed_cents": base_allowed_cents,
        "rank": rank,
        "modifier": modifier,
        "is_bundled": False,
        "reduction_factor_pct": 0,
        "allowed_cents": 0,
    })
    db.codes[line["id"]] = line

    calc.recompute_allowed_amount(procedure)
    procedure["coding_status"] = "CODED"
    touch(procedure)
    return envelope_object(public(line)), 201


@bp.post("/procedures/<procedure_id>/attest")
def attest(procedure_id):
    user_id, role = authenticate(("Interventionalist",))
    procedure = must_get(db.procedures, procedure_id, "ERR_PROCEDURE_NOT_FOUND")
    body = get_body()
    statement = req_str(body, "medical_necessity_statement")
    reading_id = req_id(body, "supporting_reading_id")

    reading = must_get(db.readings, reading_id, "ERR_READING_NOT_FOUND")

    if procedure["coding_status"] != "CODED":
        raise ApiError("ERR_CODING_STATE_INVALID")

    # Rung 14: attestation is reserved to exactly the primary operator.
    if user_id != procedure["primary_operator_id"]:
        raise ApiError("ERR_ATTESTATION_NOT_OPERATOR")

    # Rung 15: medical-necessity support.
    scheduled_start = parse_dt(procedure["scheduled_start"])
    window_start = scheduled_start - timedelta(days=calc.MEDICAL_NECESSITY_LOOKBACK_DAYS)
    reading_at = parse_dt(reading["reading_at"])
    if reading["access_id"] != procedure["access_id"]:
        raise ApiError("ERR_MEDICAL_NECESSITY_UNSUPPORTED")
    if reading_at < window_start or reading_at > scheduled_start:
        raise ApiError("ERR_MEDICAL_NECESSITY_UNSUPPORTED")

    procedure["medical_necessity_statement"] = statement
    procedure["supporting_reading_id"] = reading_id
    procedure["attested_by_id"] = user_id
    procedure["coding_status"] = "ATTESTED"
    touch(procedure)
    return envelope_object(public(procedure)), 200


@bp.post("/procedures/<procedure_id>/bill")
def bill(procedure_id):
    authenticate(("CenterAdmin",))
    procedure = must_get(db.procedures, procedure_id, "ERR_PROCEDURE_NOT_FOUND")
    if procedure["coding_status"] != "ATTESTED":
        raise ApiError("ERR_CODING_STATE_INVALID")

    # Rung 31: code-to-device consistency, strictly before the session cap.
    consumed_types = set()
    for usage in db.usages.values():
        if usage["procedure_id"] == procedure_id and usage["state"] == "CONSUMED":
            lot = db.lots.get(usage["device_lot_id"])
            if lot is not None:
                consumed_types.add(lot["device_type"])
    for line in calc.procedure_code_lines(procedure_id):
        if line["is_bundled"]:
            continue
        required = calc.FAMILY_DEVICE.get(line["code_family"])
        if required is None:
            continue
        if required not in consumed_types:
            raise ApiError("ERR_CODE_DEVICE_MISMATCH")

    # Rung 32: the per-session allowed-amount cap.
    if procedure["allowed_amount_cents"] > calc.SESSION_CAP_CENTS:
        raise ApiError("ERR_SESSION_CAP_EXCEEDED")

    procedure["coding_status"] = "BILLED"
    procedure["billed_amount_cents"] = procedure["allowed_amount_cents"]
    procedure["denied_amount_cents"] = 0
    procedure["net_receivable_cents"] = procedure["billed_amount_cents"]
    touch(procedure)
    return envelope_object(public(procedure)), 200


@bp.post("/procedures/<procedure_id>/deny")
def deny(procedure_id):
    authenticate(("CenterAdmin",))
    procedure = must_get(db.procedures, procedure_id, "ERR_PROCEDURE_NOT_FOUND")
    body = get_body()
    denial_reason = req_enum(body, "denial_reason", DENIAL_REASONS)
    denial_code = req_str(body, "denial_code")
    if procedure["coding_status"] not in ("BILLED", "REBILLED"):
        raise ApiError("ERR_CODING_STATE_INVALID")

    procedure["denial_reason"] = denial_reason
    procedure["denial_code"] = denial_code
    procedure["denied_amount_cents"] = procedure["billed_amount_cents"]
    procedure["net_receivable_cents"] = 0
    procedure["coding_status"] = "DENIED"
    touch(procedure)
    return envelope_object(public(procedure)), 200


@bp.post("/procedures/<procedure_id>/rebill")
def rebill(procedure_id):
    authenticate(("CenterAdmin",))
    procedure = must_get(db.procedures, procedure_id, "ERR_PROCEDURE_NOT_FOUND")
    if procedure["coding_status"] != "DENIED":
        raise ApiError("ERR_CODING_STATE_INVALID")

    # Rung 29: the rebill limit.
    if procedure["rebill_count"] >= calc.MAX_REBILLS:
        raise ApiError("ERR_REBILL_LIMIT_REACHED")

    calc.recompute_allowed_amount(procedure)
    procedure["billed_amount_cents"] = procedure["allowed_amount_cents"]
    procedure["denied_amount_cents"] = 0
    procedure["net_receivable_cents"] = procedure["billed_amount_cents"]
    procedure["rebill_count"] += 1
    procedure["coding_status"] = "REBILLED"
    touch(procedure)
    return envelope_object(public(procedure)), 200


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@bp.get("/procedures/<procedure_id>")
def get_procedure(procedure_id):
    authenticate(ALL_ROLES)
    procedure = must_get(db.procedures, procedure_id, "ERR_PROCEDURE_NOT_FOUND")
    return envelope_object(public(procedure)), 200


@bp.get("/procedures")
def list_procedures():
    authenticate(("CenterAdmin", "AccessCoordinator", "Interventionalist", "SedationRN", "Coder"))
    rows = list(db.procedures.values())
    for field in ("referral_id", "access_id", "room_id", "primary_operator_id",
                  "sedation_rn_id", "attested_by_id", "supporting_reading_id",
                  "clinical_status", "coding_status"):
        rows = filter_equals(rows, field, request.args.get(field))
    rows.sort(key=lambda p: (parse_dt(p["scheduled_start"]), p["created_at"], p["_seq"]))
    return list_response(rows)


@bp.get("/procedures/<procedure_id>/codes")
def list_codes(procedure_id):
    authenticate(("CenterAdmin", "AccessCoordinator", "Interventionalist", "Coder"))
    must_get(db.procedures, procedure_id, "ERR_PROCEDURE_NOT_FOUND")
    return list_response(calc.procedure_code_lines(procedure_id))


@bp.get("/procedures/<procedure_id>/recovery-observations")
def list_observations(procedure_id):
    authenticate(("CenterAdmin", "Interventionalist", "SedationRN"))
    must_get(db.procedures, procedure_id, "ERR_PROCEDURE_NOT_FOUND")
    return list_response(procedure_observations(procedure_id))


@bp.get("/procedures/<procedure_id>/reimbursement-preview")
def reimbursement_preview(procedure_id):
    authenticate(("CenterAdmin", "Coder"))
    procedure = must_get(db.procedures, procedure_id, "ERR_PROCEDURE_NOT_FOUND")

    lines = calc.procedure_code_lines(procedure_id)
    bundled, bundled_total = calc.resolve_lines(lines, "BUNDLED_ESRD")
    ffs, ffs_total = calc.resolve_lines(lines, "FEE_FOR_SERVICE")

    line_items = []
    for index, line in enumerate(lines):
        line_items.append({
            "id": line["id"],
            "rank": line["rank"],
            "hcpcs_code": line["hcpcs_code"],
            "code_family": line["code_family"],
            "modifier": line["modifier"],
            "base_allowed_cents": line["base_allowed_cents"],
            "position_factor_pct": calc.position_factor(index),
            "bundled_esrd_is_bundled": bundled[index]["is_bundled"],
            "bundled_esrd_reduction_factor_pct": bundled[index]["reduction_factor_pct"],
            "bundled_esrd_allowed_cents": bundled[index]["allowed_cents"],
            "fee_for_service_is_bundled": ffs[index]["is_bundled"],
            "fee_for_service_reduction_factor_pct": ffs[index]["reduction_factor_pct"],
            "fee_for_service_allowed_cents": ffs[index]["allowed_cents"],
        })

    return envelope_object({
        "procedure_id": procedure["id"],
        "applicable_variant": calc.procedure_payer_program(procedure),
        "bundled_esrd_total_cents": bundled_total,
        "fee_for_service_total_cents": ffs_total,
        "variant_delta_cents": ffs_total - bundled_total,
        "line_items": line_items,
    }), 200
