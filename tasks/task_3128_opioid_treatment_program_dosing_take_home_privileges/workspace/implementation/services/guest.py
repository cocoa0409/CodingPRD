"""Guest dosing arrangements (PRD 3.11; SCAFFOLD guest state machine)."""
from datetime import timedelta

import db
from errors import ApiError
from services import entity, program as program_svc


def arrangement_of(arrangement_id):
    row = db.guest_dosing_arrangements.get(arrangement_id)
    if row is None:
        raise ApiError("ERR_ARRANGEMENT_NOT_FOUND", "No GuestDosingArrangement with the supplied id")
    return row


def patient_of(arrangement):
    return db.patients.get(arrangement.get("patient_id"))


def receiving_program_of(arrangement):
    return db.programs.get(arrangement.get("receiving_program_id"))


def window_overlaps_open_day(program, start_date, end_date):
    """The receiving clinic must have an open day inside the requested travel window."""
    start = db.parse_date(start_date)
    end = db.parse_date(end_date)
    if start is None or end is None or end < start:
        return False
    codes = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
    open_days = set(program.get("open_days") or [])
    if not open_days:
        return False
    cursor = start
    while cursor <= end:
        if codes[cursor.weekday()] in open_days:
            return True
        cursor += timedelta(days=1)
    return False


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------
def create_arrangement(patient, receiving_program_id, travel_start_date, travel_end_date, actor):
    receiving = db.programs.get(receiving_program_id)
    if receiving is None:
        raise ApiError("ERR_PROGRAM_NOT_FOUND", "No Program with the supplied id")
    start = db.parse_date(travel_start_date)
    end = db.parse_date(travel_end_date)
    if start is None or end is None:
        raise ApiError("ERR_INVALID_REQUEST", "travel dates must be ISO dates")
    if end < start:
        raise ApiError("ERR_INVALID_REQUEST", "travel_end_date must not precede travel_start_date")
    # Priority 11: the originating/receiving clinic constraints.
    if patient.get("program_id") == receiving_program_id:
        raise ApiError(
            "ERR_SAME_PROGRAM_GUEST_DOSING",
            "A patient cannot guest-dose at their own clinic",
        )
    if not receiving.get("guest_dosing_enabled"):
        raise ApiError("ERR_GUEST_DOSING_NOT_ENABLED", "The receiving clinic does not accept guests")
    row = entity.make_arrangement(patient, receiving_program_id, travel_start_date, travel_end_date)
    db.guest_dosing_arrangements[row["id"]] = row
    return row


# ---------------------------------------------------------------------------
# transmit
# ---------------------------------------------------------------------------
def transmit(arrangement, actor):
    if arrangement.get("status") != "DRAFT":
        raise ApiError("ERR_ARRANGEMENT_NOT_DRAFT", "GuestDosingArrangement is not DRAFT")
    patient = patient_of(arrangement)
    receiving = receiving_program_of(arrangement)
    if receiving is None:
        raise ApiError("ERR_PROGRAM_NOT_FOUND", "No Program with the supplied id")
    if patient is None:
        raise ApiError("ERR_PATIENT_NOT_FOUND", "No Patient with the supplied id")

    # Priority 11 first, per PRD 3.11: the origin-versus-receiving checks run
    # before the two safety gates.
    if arrangement.get("originating_program_id") != patient.get("program_id"):
        raise ApiError(
            "ERR_ARRANGEMENT_PROGRAM_MISMATCH",
            "originating_program_id does not equal the patient's program",
        )
    if arrangement.get("receiving_program_id") == arrangement.get("originating_program_id"):
        raise ApiError(
            "ERR_SAME_PROGRAM_GUEST_DOSING",
            "A patient cannot guest-dose at their own clinic",
        )
    if not receiving.get("guest_dosing_enabled"):
        raise ApiError("ERR_GUEST_DOSING_NOT_ENABLED", "The receiving clinic does not accept guests")
    # Priority 8 / 10: the safety gates.
    if patient.get("status") != "ACTIVE":
        raise ApiError("ERR_PATIENT_NOT_ACTIVE", "Patient is not ACTIVE")
    program_svc.ensure_normal_for_medication(receiving)
    if patient.get("diversion_standing") == "CONFIRMED_DIVERSION":
        raise ApiError(
            "ERR_DIVERSIONS_OR_FINDINGS_OPEN",
            "A patient under confirmed diversion may not receive a dose",
        )
    # Priority 12: the travel window must intersect the receiving clinic's open days.
    if not window_overlaps_open_day(
        receiving, arrangement.get("travel_start_date"), arrangement.get("travel_end_date")
    ):
        raise ApiError(
            "ERR_NO_OVERLAPPING_VISIT_WINDOW",
            "The travel window does not overlap the receiving clinic's open days",
        )

    from services import dose as dose_svc

    order = dose_svc.order_of_for_patient(patient)
    arrangement["dose_authorization_token"] = db.new_token()
    arrangement["authorized_mg"] = (order or {}).get("ordered_daily_mg")
    arrangement["status"] = "PENDING_RECEIVING_ACK"
    db.stamp(arrangement)
    # A transmission for a patient advances that patient's version (PRD 3.11).
    db.stamp(patient)
    return arrangement


# ---------------------------------------------------------------------------
# acknowledge / reject
# ---------------------------------------------------------------------------
def acknowledge(arrangement, actor):
    if arrangement.get("status") != "PENDING_RECEIVING_ACK":
        raise ApiError(
            "ERR_ARRANGEMENT_NOT_PENDING_ACK",
            "GuestDosingArrangement is not PENDING_RECEIVING_ACK",
        )
    receiving_id = arrangement.get("receiving_program_id")
    if actor.role == "Nurse" and actor.program_id and actor.program_id != receiving_id:
        raise ApiError(
            "ERR_NURSE_NOT_IN_PROGRAM",
            "The acting nurse does not belong to the receiving program",
        )
    arrangement["status"] = "ACTIVE"
    arrangement["receiving_acknowledged_at"] = db.fmt_dt(db.clock_dt())
    db.stamp(arrangement)
    patient = patient_of(arrangement)
    if patient is not None:
        db.stamp(patient)
    return arrangement


def reject(arrangement, actor):
    if arrangement.get("status") != "PENDING_RECEIVING_ACK":
        raise ApiError(
            "ERR_ARRANGEMENT_NOT_PENDING_ACK",
            "GuestDosingArrangement is not PENDING_RECEIVING_ACK",
        )
    arrangement["status"] = "REJECTED"
    arrangement["dose_authorization_token"] = None
    db.stamp(arrangement)
    return arrangement


# ---------------------------------------------------------------------------
# close / cancel
# ---------------------------------------------------------------------------
def close(arrangement, actor):
    if arrangement.get("status") != "ACTIVE":
        raise ApiError("ERR_ARRANGEMENT_NOT_ACTIVE", "GuestDosingArrangement is not ACTIVE")
    end = db.parse_date(arrangement.get("travel_end_date"))
    today = db.clock_dt().replace(hour=0, minute=0, second=0, microsecond=0)
    if end is None or today <= end:
        raise ApiError(
            "ERR_TRAVEL_WINDOW_NOT_ENDED",
            "The logical clock has not moved past travel_end_date",
        )
    arrangement["status"] = "COMPLETED"
    arrangement["token_consumed"] = True
    db.stamp(arrangement)
    return arrangement


def cancel(arrangement, actor):
    if arrangement.get("status") not in ("DRAFT", "PENDING_RECEIVING_ACK", "ACTIVE"):
        raise ApiError(
            "ERR_ARRANGEMENT_NOT_CANCELLABLE",
            "GuestDosingArrangement is already in a terminal status",
        )
    arrangement["status"] = "CANCELLED"
    db.stamp(arrangement)
    return arrangement


# ---------------------------------------------------------------------------
# token redemption on a GUEST_OBSERVED dose
# ---------------------------------------------------------------------------
def redeem_token(arrangement, token):
    """Priority 23: ACTIVE, unexpired, unconsumed and matching token."""
    if not token or not arrangement.get("dose_authorization_token"):
        raise ApiError("ERR_GUEST_TOKEN_INVALID", "The guest dosing token is absent or not minted")
    if str(token) != str(arrangement.get("dose_authorization_token")):
        raise ApiError("ERR_GUEST_TOKEN_INVALID", "The guest dosing token does not match")
    if arrangement.get("status") != "ACTIVE":
        raise ApiError("ERR_GUEST_TOKEN_INVALID", "The arrangement is not ACTIVE")
    if arrangement.get("token_consumed"):
        raise ApiError(
            "ERR_GUEST_TOKEN_ALREADY_CONSUMED",
            "The guest dosing authorization token has already been redeemed",
        )
    today = db.clock_dt().replace(hour=0, minute=0, second=0, microsecond=0)
    start = db.parse_date(arrangement.get("travel_start_date"))
    end = db.parse_date(arrangement.get("travel_end_date"))
    if start is None or end is None or today < start or today > end:
        raise ApiError(
            "ERR_GUEST_DOSING_WINDOW_CLOSED",
            "The logical clock falls outside [travel_start_date, travel_end_date]",
        )
    arrangement["token_consumed"] = True
    db.stamp(arrangement)
    return arrangement