"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because the harness restarts the API server (and therefore empties
the database) before each individual test. Setup calls use the framework's
lenient ``get_success_data()`` so a broken precondition surfaces as a clear
"Setup step failed" error rather than a confusing assertion failure.

Identity threading: whenever a call is ownership-gated, the helper passes the
acting entity's own ``id`` through ``make_<role>_headers(...)`` rather than the
shared role constant.
"""

import pytest

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_arrangement_payload,
    create_carry_quota_payload,
    create_corrective_action_payload,
    create_counseling_session_payload,
    create_diversion_case_payload,
    create_dose_dispense_payload,
    create_dose_order_payload,
    create_exception_payload,
    create_finding_payload,
    create_inspection_payload,
    create_lot_payload,
    create_patient_payload,
    create_plan_review_payload,
    create_privilege_payload,
    create_program_payload,
    create_transaction_payload,
    create_user_payload,
)
from .test_users import (
    TEST_USERS,
    make_counselor_headers,
    make_medical_director_headers,
    make_nurse_headers,
    make_physician_headers,
    make_program_admin_headers,
    make_regulatory_auditor_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]


def _clean(payload: dict) -> dict:
    """Drop keys whose value is None so optional fields are genuinely omitted."""
    return {k: v for k, v in payload.items() if v is not None}


# ─── Clock ───────────────────────────────────────────────────────────────────

def set_clock(to_iso8601, headers=None):
    """Move the logical clock (PRD 3.14). The server never tracks real time."""
    res = api_client.set_clock(to_iso8601, headers or ADMIN)
    return get_success_data(res)


def advance_to_maintenance(patient_id, physician_headers, reconciled_days=1):
    """PATCH the treatment phase to MAINTENANCE, advancing the phase journal."""
    res = api_client.patch_treatment_phase(
        patient_id, {"treatment_phase": "MAINTENANCE", "reconciled_days": reconciled_days},
        physician_headers)
    return get_success_data(res)


# ─── Tier 1: Clinic bundle (program + quota + lot + staff) ───────────────────

def setup_clinic(allotted_carries=TEST_DEFAULTS["ALLOTTED_CARRIES"],
                 create_quota=True,
                 create_lot=True,
                 lot_overrides=None,
                 program_overrides=None,
                 with_counselor=True,
                 with_auditor=True,
                 open_days=None):
    """Create one clinic program with its carry quota, a METHADONE lot and the
    clinical staff needed by the observed-dose, carry and counseling workflows.

    Every clinic hosts a `Counselor`: §2.1 makes the acting roles the mandatory
    six-member set, counseling sessions are scheduled by a `Counselor`, and a
    session's `counselor_staff_id` is an opaque staff identifier. Registering one
    here means ``bundle["counselor_headers"]`` — and therefore a real acting
    Counselor identity, and a resolvable ``counselor_staff_id`` — is always
    available rather than depending on a per-call flag.

    Returns a bundle dict whose values are the created resources and whose
    ``*_headers`` entries are per-instance headers built from the real user ids.
    """
    prog_payload = create_program_payload(**(program_overrides or {}))
    if open_days is not None:
        prog_payload["open_days"] = open_days
    program = get_success_data(api_client.create_program(prog_payload, ADMIN))

    bundle = {
        "program": program,
        "admin_headers": ADMIN,
        "physician": None,
        "nurse": None,
        "director": None,
        "counselor": None,
        "auditor": None,
        "lot": None,
        "quota": None,
    }

    if create_quota:
        bundle["quota"] = get_success_data(api_client.open_carry_quota(
            program["id"], create_carry_quota_payload(allotted_carries), ADMIN))

    if create_lot:
        lot_defaults = {"lot_number": "LOT-A1"}
        lot_defaults.update(lot_overrides or {})
        bundle["lot"] = get_success_data(api_client.create_lot(
            create_lot_payload(program["id"], **lot_defaults), ADMIN))

    bundle["physician"] = get_success_data(api_client.create_user(
        create_user_payload(program["id"], "Paul Physician", "PHYSICIAN", "MD-3001"), ADMIN))
    bundle["nurse"] = get_success_data(api_client.create_user(
        create_user_payload(program["id"], "Nora Nurse", "NURSE", "RN-1001"), ADMIN))
    bundle["director"] = get_success_data(api_client.create_user(
        create_user_payload(program["id"], "Miles Director", "MEDICAL_DIRECTOR", "MD-2001"), ADMIN))

    if with_counselor:
        bundle["counselor"] = get_success_data(api_client.create_user(
            create_user_payload(program["id"], "Cleo Counselor", "COUNSELOR", None), ADMIN))
    if with_auditor:
        bundle["auditor"] = get_success_data(api_client.create_user(
            create_user_payload(None, "Rita Auditor", "REGULATOR", None), ADMIN))

    bundle["physician_headers"] = make_physician_headers(bundle["physician"]["id"])
    bundle["nurse_headers"] = make_nurse_headers(bundle["nurse"]["id"])
    bundle["director_headers"] = make_medical_director_headers(bundle["director"]["id"])
    if bundle["counselor"]:
        bundle["counselor_headers"] = make_counselor_headers(bundle["counselor"]["id"])
    if bundle["auditor"]:
        bundle["auditor_headers"] = make_regulatory_auditor_headers(bundle["auditor"]["id"])
    return bundle


# ─── Tier 2: Patient hierarchy ───────────────────────────────────────────────

def register_patient(clinic, **overrides):
    """Register a patient into the clinic. Lands in PENDING_ADMISSION."""
    payload = create_patient_payload(clinic["program"]["id"], **overrides)
    return get_success_data(api_client.create_patient(payload, clinic["physician_headers"]))


def admit_patient(clinic, patient_id):
    """Physician confirms the diagnosis: PENDING_ADMISSION -> ADMITTED."""
    return get_success_data(
        api_client.confirm_diagnosis(patient_id, clinic["physician_headers"]))


def create_active_order(clinic, patient_id, ordered_daily_mg=90.0,
                        medication="METHADONE", split_dose_authorized=False):
    """Create a DRAFT order and activate it. Returns (patient, order) with the
    patient advanced to ACTIVE."""
    order = get_success_data(api_client.create_dose_order(
        create_dose_order_payload(patient_id, medication, ordered_daily_mg,
                                  split_dose_authorized),
        clinic["physician_headers"]))
    api_client.activate_dose_order(order["id"], clinic["physician_headers"])
    order = get_success_data(api_client.get_dose_order(order["id"], clinic["physician_headers"]))
    patient = get_success_data(api_client.get_patient(patient_id, clinic["physician_headers"]))
    return patient, order


def setup_active_patient(clinic, ordered_daily_mg=90.0, medication="METHADONE",
                         split_dose_authorized=False, **patient_overrides):
    """Register -> confirm-diagnosis -> dose order -> activate.

    Returns (patient, order) with the patient ACTIVE.
    """
    patient = register_patient(clinic, **patient_overrides)
    admit_patient(clinic, patient["id"])
    patient, order = create_active_order(clinic, patient["id"], ordered_daily_mg,
                                         medication, split_dose_authorized)
    return patient, order


def setup_active_patient_and_maintenance(clinic, clock="2026-12-15T00:00:00Z",
                                         ordered_daily_mg=90.0, reconciled_days=1,
                                         **patient_overrides):
    """Active patient advanced to the MAINTENANCE phase with a reconciled journal.

    Returns (patient, order) refreshed after the phase change.
    """
    patient, order = setup_active_patient(clinic, ordered_daily_mg=ordered_daily_mg,
                                          **patient_overrides)
    set_clock(clock)
    patient = advance_to_maintenance(patient["id"], clinic["physician_headers"], reconciled_days)
    return patient, order


# ─── Tier 3: Dose pipeline lifecycle shortcuts ───────────────────────────────

def schedule_dose(clinic, order_id, dose_date, scheduled_datetime,
                  source_type="OBSERVED_CLINIC", inventory_lot_id=None, **extra):
    """Schedule one dose. Omitted inventory_lot_id lets the selector resolve a lot."""
    payload = _clean(create_dose_dispense_payload(
        order_id, dose_date, scheduled_datetime, source_type, inventory_lot_id, **extra))
    return get_success_data(api_client.create_dose_dispense(payload, clinic["nurse_headers"]))


def check_in_dose(clinic, dose_id):
    return get_success_data(api_client.check_in(dose_id, clinic["nurse_headers"]))


def verify_dose(clinic, dose_id, identity_matched=True):
    return get_success_data(api_client.verify_dose(
        dose_id, {"identity_matched": identity_matched}, clinic["nurse_headers"]))


def dispense_dose(clinic, dose_id, dispensed_mg, wasted_mg=0.0, returned_mg=0.0,
                  inventory_lot_id=None, witness_staff_id=None):
    payload = _clean({
        "dispensed_mg": dispensed_mg,
        "wasted_mg": wasted_mg,
        "returned_mg": returned_mg,
        "inventory_lot_id": inventory_lot_id,
        "witness_staff_id": witness_staff_id,
    })
    return get_success_data(api_client.dispense_dose(dose_id, payload, clinic["nurse_headers"]))


def complete_dose(clinic, dose_id, dispensed_mg=None, wasted_mg=0.0, returned_mg=0.0):
    payload = _clean({
        "dispensed_mg": dispensed_mg,
        "wasted_mg": wasted_mg,
        "returned_mg": returned_mg,
    })
    return get_success_data(api_client.complete_dose(dose_id, payload, clinic["nurse_headers"]))


def mark_missed(clinic, dose_id):
    return get_success_data(api_client.mark_missed(dose_id, clinic["nurse_headers"]))


def create_and_verify_dose(clinic, order_id, dose_date, scheduled_datetime,
                           inventory_lot_id=None, identity_matched=True, **extra):
    """Schedule -> check-in -> verify. Returns the NURSE_VERIFIED dose row."""
    dose = schedule_dose(clinic, order_id, dose_date, scheduled_datetime,
                         inventory_lot_id=inventory_lot_id, **extra)
    check_in_dose(clinic, dose["id"])
    return verify_dose(clinic, dose["id"], identity_matched)


def run_observed_dose(clinic, order_id, dose_date, scheduled_datetime, dispensed_mg,
                      inventory_lot_id=None, wasted_mg=0.0, returned_mg=0.0,
                      witness_staff_id=None, complete=True):
    """Full observed pipeline: schedule -> check-in -> verify -> dispense [-> complete]."""
    dose = create_and_verify_dose(clinic, order_id, dose_date, scheduled_datetime,
                                  inventory_lot_id=inventory_lot_id)
    dose = dispense_dose(clinic, dose["id"], dispensed_mg, wasted_mg, returned_mg,
                         inventory_lot_id, witness_staff_id)
    if complete:
        dose = complete_dose(clinic, dose["id"], dispensed_mg, wasted_mg, returned_mg)
    return dose


def schedule_and_miss(clinic, order_id, dose_date, scheduled_datetime, inventory_lot_id=None):
    """Schedule a dose and record it as missed. Returns the MISSED dose row."""
    dose = schedule_dose(clinic, order_id, dose_date, scheduled_datetime,
                         inventory_lot_id=inventory_lot_id)
    return mark_missed(clinic, dose["id"])


def schedule_consecutive_misses(clinic, order_id, dates, datetimes, count=3,
                                inventory_lot_id=None):
    """Schedule `count` doses and mark all but optionally the last as missed.

    Returns the list of dose rows in schedule order.
    """
    doses = []
    for i in range(count):
        doses.append(schedule_dose(clinic, order_id, dates[i], datetimes[i],
                                   inventory_lot_id=inventory_lot_id))
    for dose in doses[:-1]:
        mark_missed(clinic, dose["id"])
    return doses


# ─── Tier 4: Carry privileges, exceptions and ledgers ────────────────────────

def hold_privilege(clinic, patient_id, expected_patient_version, requested_carries=1,
                   carry_interval_days=7, **extra):
    """Open a privilege request; the row begins PENDING_REVIEW on hold."""
    payload = create_privilege_payload(patient_id, requested_carries,
                                       expected_patient_version, carry_interval_days, **extra)
    return get_success_data(api_client.create_privilege(payload, clinic["director_headers"]))


def evaluate_privilege(clinic, privilege_id):
    res = api_client.evaluate_privilege(privilege_id, clinic["director_headers"])
    return res


def create_and_evaluate_privilege(clinic, patient_id, requested_carries=1,
                                  carry_interval_days=7):
    """Hold a privilege against the patient's current version, then evaluate it."""
    patient = get_success_data(api_client.get_patient(patient_id, clinic["director_headers"]))
    priv = hold_privilege(clinic, patient_id, patient["version"], requested_carries,
                          carry_interval_days)
    evaluate_privilege(clinic, priv["id"])
    return get_success_data(api_client.get_privilege(priv["id"], clinic["director_headers"]))


def get_carry_ledger_for(clinic, patient_id):
    """Read the patient's TakeHomeCarryLedger (list endpoint, filtered by patient)."""
    data, _meta = _paginated(
        api_client.list_carry_ledgers(clinic["director_headers"], {"patient_id": patient_id}))
    return data[0]


def _paginated(response):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(response)


def list_doses(clinic, params=None, headers=None):
    data, _meta = _paginated(api_client.list_dose_dispenses(
        headers or clinic["nurse_headers"], params))
    return data


def list_transactions(clinic, params=None, headers=None):
    data, _meta = _paginated(api_client.list_transactions(headers or ADMIN, params))
    return data


def list_privileges(clinic, params=None, headers=None):
    data, _meta = _paginated(api_client.list_privileges(
        headers or clinic["director_headers"], params))
    return data


# ─── Tier 5: Finalization / cascade-ready states ─────────────────────────────

def setup_approved_privilege_with_take_home_dose(clinic, patient_id,
                                                 requested_carries=1,
                                                 clock="2026-12-15T00:00:00Z"):
    """Full carry setup: active patient -> MAINTENANCE reconciled -> approved
    privilege -> the synthesized take-home dose rows.

    Returns (patient, privilege, take_home_doses).
    """
    patient = get_success_data(api_client.get_patient(patient_id, clinic["director_headers"]))
    priv = hold_privilege(clinic, patient_id, patient["version"], requested_carries)
    get_success_data(api_client.evaluate_privilege(priv["id"], clinic["director_headers"]))
    priv = get_success_data(api_client.get_privilege(priv["id"], clinic["director_headers"]))
    doses = list_doses(clinic, {"privilege_id": priv["id"]})
    return patient, priv, doses


def setup_denied_privilege_and_routed_exception(clinic, patient_id, requested_carries=4,
                                                exception_carries=4, expected_phase="STABILIZATION"):
    """A privilege that evaluates to DENIED plus an exception routed to
    SUPERVISOR_REVIEW against it.

    Returns (privilege, exception).
    """
    patient = get_success_data(api_client.get_patient(patient_id, clinic["physician_headers"]))
    priv = hold_privilege(clinic, patient_id, patient["version"], requested_carries)
    res = api_client.evaluate_privilege(priv["id"], clinic["director_headers"])
    assert not (200 <= res.status_code < 300), (
        "Setup expected the ordinary evaluation path to deny this privilege")
    priv = get_success_data(api_client.get_privilege(priv["id"], clinic["director_headers"]))

    exc = get_success_data(api_client.create_exception(
        create_exception_payload(patient_id, exception_carries, clinic["director"]["id"],
                                 priv["version"]),
        clinic["physician_headers"]))
    exc = get_success_data(api_client.route_exception(exc["id"], clinic["physician_headers"]))
    return priv, exc


def setup_diversion_ready(clinic, patient_id, related_dose_dispense_id=None,
                          station="UNDER_REVIEW"):
    """Open a diversion case against a patient and optionally begin review."""
    case = get_success_data(api_client.create_diversion_case(
        create_diversion_case_payload(clinic["program"]["id"], patient_id,
                                      related_dose_dispense_id=related_dose_dispense_id),
        clinic["auditor_headers"]))
    if station == "UNDER_REVIEW":
        case = get_success_data(api_client.begin_review(case["id"], clinic["auditor_headers"]))
    return case


# ─── Specialised clinic bundles for threshold targeting ──────────────────────

def setup_two_slot_clinic(max_daily_dose_slots=2, lot_quantity_mg=100.0,
                          lot_number="LOT-SMALL", reusable_for_take_home=False):
    """A clinic whose open day holds only `max_daily_dose_slots` doses and whose
    single lot cannot cover two full 90 mg draws."""
    return setup_clinic(
        allotted_carries=10,
        program_overrides={"name": "BayMark Foothill", "max_daily_dose_slots": max_daily_dose_slots,
                           "open_days": ["MO", "TU", "WE", "TH", "FR"]},
        lot_overrides={"lot_number": lot_number, "quantity_received_mg": lot_quantity_mg,
                       "reusable_for_take_home": reusable_for_take_home},
    )


def setup_three_slot_clinic(max_daily_dose_slots=3, lot_quantity_mg=900.0,
                            lot_number="LOT-MESA"):
    """A clinic whose open day accepts exactly `max_daily_dose_slots` occupants."""
    return setup_clinic(
        allotted_carries=10,
        program_overrides={"name": "BayMark Mesa",
                           "max_daily_dose_slots": max_daily_dose_slots},
        lot_overrides={"lot_number": lot_number, "quantity_received_mg": lot_quantity_mg},
    )


def setup_permit_clinic(max_daily_dose_slots=20, lot_quantity_mg=900.0,
                        lot_number="LOT-DELTA"):
    """A clinic with ample day capacity, so only the per-patient daily permit binds."""
    return setup_clinic(
        allotted_carries=10,
        program_overrides={"name": "BayMark Delta",
                           "max_daily_dose_slots": max_daily_dose_slots},
        lot_overrides={"lot_number": lot_number, "quantity_received_mg": lot_quantity_mg},
    )


def setup_origin_and_receiving_clinic(receiving_open_days=("SA",),
                                      receiving_hours=("08:00", "10:00")):
    """Two CA clinics: an originating clinic open Monday to Friday and a receiving
    clinic whose only open day is Saturday morning."""
    origin = setup_clinic(
        allotted_carries=10,
        program_overrides={"name": "BayMark Origin", "open_days": ["MO", "TU", "WE", "TH", "FR"]},
    )
    receiving = setup_clinic(
        allotted_carries=10,
        program_overrides={"name": "BayMark Coast",
                           "clinic_hours_start": receiving_hours[0],
                           "clinic_hours_end": receiving_hours[1],
                           "open_days": list(receiving_open_days),
                           "max_daily_dose_slots": 10},
    )
    return origin, receiving


def setup_variance_clinic(lot_quantity_mg=10150.0, lot_number="LOT-155"):
    """A clinic whose lot holds 10150.0 mg so a 10000.0 mg dispense leaves a
    150.0 mg delivered deficit against a 10000.0 mg period total."""
    return setup_clinic(
        lot_overrides={"lot_number": lot_number, "quantity_received_mg": lot_quantity_mg},
    )


# ─── Raw transaction helper ──────────────────────────────────────────────────

def record_transaction(clinic, lot_id, transaction_type, quantity_mg, **extra):
    payload = create_transaction_payload(lot_id, transaction_type, quantity_mg, **extra)
    return get_success_data(api_client.create_transaction(_clean(payload), ADMIN))


# ─── Inspection / compliance helpers ─────────────────────────────────────────

def setup_inspection_with_findings(clinic, findings=None, diversion=True):
    """Announce an inspection, record findings and optionally open a diversion case.

    `findings` is a list of (requirement_code, severity) tuples.
    Returns the inspection row.
    """
    inspection = get_success_data(api_client.create_inspection(
        create_inspection_payload(clinic["program"]["id"]), clinic["auditor_headers"]))
    for code, severity in (findings or []):
        get_success_data(api_client.create_finding(
            create_finding_payload(inspection["id"], code, severity), clinic["auditor_headers"]))
    return inspection


def open_and_review_diversion(clinic, patient_id, detection_source="URINE_SCREEN",
                              severity="MAJOR"):
    case = get_success_data(api_client.create_diversion_case(
        create_diversion_case_payload(clinic["program"]["id"], patient_id,
                                      detection_source=detection_source, severity=severity),
        clinic["auditor_headers"]))
    return get_success_data(api_client.begin_review(case["id"], clinic["auditor_headers"]))


# ─── Counseling helpers ──────────────────────────────────────────────────────

def attend_counseling(clinic, patient_id, attended_minutes, scheduled_datetime,
                      session_type="INDIVIDUAL", duration_minutes=60,
                      counselor_staff_id=None):
    """Schedule and complete a counseling session with the minutes actually attended.

    The acting Counselor and the recorded ``counselor_staff_id`` are the same
    entity-backed user, taken from the clinic bundle. §2.1 resolves an acting
    Counselor to a persisted `User` row, and §3.15 keeps ``counselor_staff_id``
    as a resolvable staff identifier, so neither may be a made-up constant.
    """
    if counselor_staff_id is None:
        counselor_staff_id = clinic["counselor"]["id"]
    session = get_success_data(api_client.create_counseling_session(
        create_counseling_session_payload(patient_id, scheduled_datetime, session_type,
                                          duration_minutes, counselor_staff_id),
        clinic["counselor_headers"]))
    return get_success_data(api_client.complete_counseling_session(
        session["id"], {"attended_minutes": attended_minutes}, clinic["counselor_headers"]))


def record_plan_review(clinic, patient_id, reviewed_at):
    return get_success_data(api_client.create_plan_review(
        create_plan_review_payload(patient_id, clinic["physician"]["id"], reviewed_at),
        clinic["physician_headers"]))


# ─── Counseling currency helper ──────────────────────────────────────────────

def ensure_counseling_current(clinic, patient_id, clock_iso="2026-12-15T00:00:00Z",
                              session_datetime=None,
                              attended_minutes=60):
    """Bring both halves of the counseling standing to CURRENT.

    PRD 3.8: a patient with no completed plan review more than three days past
    admission reads COUNSELING_DEFICIENT, and fewer than 60 credited minutes in
    the phase cadence window reads COUNSELING_DEFICIENT as well. A carry
    evaluation on such a patient carries a six-point readiness penalty (PRD
    2.5), so fixtures that need an approvable applicant must first make the
    standing genuinely current.

    The session is *completed* 29 days before the evaluation clock — the fixture
    drives the logical clock back to that instant, records the session and
    restores the clock. The 29-day offset is chosen for phase-independence:
    PRD 3.8's cadence window is 7 days in `INDUCTION`, 14 in `STABILIZATION`, 30
    in `MAINTENANCE` and 7 in `MEDICAL_WITHDRAWAL`, so only a MAINTENANCE
    patient can have its standing credited from a session that old. For any
    shorter cadence the offset is pulled inside that window (and, where the
    window permits, kept outside the trailing 28-day window PRD 2.5 reads for
    Direction A's one-point-per-session term, so a caller's pinned published
    figure is not perturbed). The standing therefore becomes CURRENT without the
    published stability reading picking up a credit the scenario did not budget
    for.
    """
    days_back = _counseling_offset_days(clinic, patient_id, clock_iso)
    if session_datetime is None:
        session_datetime = _days_before(clock_iso, days_back)
    set_clock(session_datetime)
    attend_counseling(clinic, patient_id, attended_minutes, session_datetime)
    set_clock(clock_iso)
    record_plan_review(clinic, patient_id, clock_iso)
    return get_success_data(api_client.get_patient(patient_id, clinic["director_headers"]))


# PRD 3.8's cadence length per phase.
_PHASE_CADENCE_DAYS = {
    "INDUCTION": 7,
    "STABILIZATION": 14,
    "MAINTENANCE": 30,
    "MEDICAL_WITHDRAWAL": 7,
}

# PRD 2.5's trailing window for the one-point-per-session Direction A credit.
_DIRECTION_A_COUNSELING_WINDOW_DAYS = 28


def _counseling_offset_days(clinic, patient_id, clock_iso):
    """How far back to complete a session so the standing reads CURRENT.

    The offset must fall inside the phase's cadence window, and is kept outside
    Direction A's 28-day window whenever that window is wider than the cadence —
    which is only true in MAINTENANCE, where 29 sits between the two.
    """
    phase = "INDUCTION"
    row = db_patient_phase(clinic, patient_id)
    if row is not None:
        phase = row.get("treatment_phase") or phase
    cadence = _PHASE_CADENCE_DAYS.get(phase, 7)
    if cadence <= _DIRECTION_A_COUNSELING_WINDOW_DAYS:
        # The cadence window is narrower than Direction A's, so the session must
        # sit inside it and will also be seen by Direction A; take the boundary.
        return cadence
    return _DIRECTION_A_COUNSELING_WINDOW_DAYS + 1


def db_patient_phase(clinic, patient_id):
    """Read the patient's current phase through the declared endpoint."""
    res = api_client.get_patient(patient_id, clinic["director_headers"])
    if not (200 <= res.status_code < 300):
        return None
    try:
        return res.json().get("data")
    except ValueError:
        return None


def _days_before(iso_instant, days):
    from datetime import datetime, timedelta
    dt = datetime.strptime(iso_instant, "%Y-%m-%dT%H:%M:%SZ")
    return (dt - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def setup_approvable_carry_patient(clinic, clock="2026-12-15T00:00:00Z",
                                   admission_clock=TEST_DEFAULTS["CLOCK_START"],
                                   time_in_treatment_days=None,
                                   ordered_daily_mg=90.0, reconciled_days=1,
                                   session_datetime=None, **patient_overrides):
    """A patient on the MAINTENANCE phase with a reconciled journal and a
    genuinely CURRENT counseling standing, ready for a carry evaluation to be
    decided on its stability reading alone.

    ``admission_clock`` sets when the patient is admitted, so callers can place
    the patient at any tenure by choosing how far ``clock`` sits beyond it.
    ``time_in_treatment_days`` is a convenience alternative that derives the
    admission instant from the requested tenure, which is the term PRD 3.7's
    time-in-treatment carry table is read against; a scenario that wants the
    pool or phase term to bind rather than the table term must place its patient
    at a tenure whose table allowance exceeds the cap it is probing.

    Returns (patient, order).
    """
    if time_in_treatment_days is not None:
        admission_clock = _days_before(clock, time_in_treatment_days)
    set_clock(admission_clock)
    patient, order = setup_active_patient(clinic, ordered_daily_mg=ordered_daily_mg,
                                          **patient_overrides)
    set_clock(clock)
    advance_to_maintenance(patient["id"], clinic["physician_headers"], reconciled_days)
    patient = ensure_counseling_current(clinic, patient["id"], clock_iso=clock,
                                        session_datetime=session_datetime)
    return patient, order


# ─── Corrective action helper ────────────────────────────────────────────────

def open_critical_corrective_action(clinic, finding_id=None):
    return get_success_data(api_client.create_corrective_action(
        create_corrective_action_payload(clinic["program"]["id"], "CRITICAL",
                                         finding_id=finding_id),
        ADMIN))