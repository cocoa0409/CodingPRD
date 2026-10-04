"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the server is restarted before every individual test.
Setup steps use get_success_data() (lenient validator) so failures surface as
clear "Setup failed" errors rather than confusing assertion failures.
"""
import itertools
from datetime import datetime, timedelta

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CENTER_DEFAULTS, CLOCK_MORNING, CLOCK_WINDOW, TEST_DEFAULTS
from .factories import (
    create_appointment_payload, create_estimate_payload, create_patient_payload,
    create_phlebotomist_payload, create_service_center_payload, create_specimen_payload,
    create_test_order_payload, create_courier_run_payload, create_tube_requirement_payload,
)
from .test_users import (
    TEST_USERS, make_patient_headers, make_phlebotomist_headers,
)

INTAKE = TEST_USERS["intake_headers"]
LIAISON = TEST_USERS["lab_liaison_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]

# PRD §2.8 requires an `expected_test_order_version` on booking, and the write
# advances the order's version. These helpers avoid concurrent bookings per
# order; a *terminal* prior visit (REJECTED / RECOLLECTED reopen the order) does
# not count, since §3.4/§3.7 put the order back on the worklist for a new visit.
_APPOINTED_ORDERS = set()
_LIVE_APPOINTMENTS: dict = {}

_mrn_counter = itertools.count(1)


def _mrn(prefix="MRN-3103"):
    return f"{prefix}-{next(_mrn_counter):04d}"


def add_minutes(iso, minutes):
    """Add a whole number of minutes to an ISO 8601 UTC instant."""
    dt = datetime.strptime(iso.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
    return (dt + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def ok(response, expected=None):
    """Lenient setup-step validator with a clear failure message."""
    return get_success_data(response, expected)


# ─── Tier 0: clock and reference seed ─────────────────────────────────────────

def set_clock(current_utc):
    """Advance the logical clock; returns the clock instant."""
    ok(api_client.set_clock(current_utc, SUPERVISOR))
    return current_utc


def seed_reference(clock=CLOCK_MORNING):
    """Set the clock and idempotently seed the reference plan and grids.

    Returns the seeded reference InsurancePlan id.
    """
    set_clock(clock)
    data = ok(api_client.seed_reference(SUPERVISOR))
    return data["insurance_plan_id"]


# ─── Tier 1: state progression / base entities ────────────────────────────────

def new_center(**overrides):
    """Create a ServiceCenter. Returns the created center row."""
    return ok(api_client.create_service_center(create_service_center_payload(**overrides),
                                               SUPERVISOR), 201)


def new_patient(full_name="Ada Nguyen", birth_date="1990-04-02T00:00:00Z", **overrides):
    """Register a Patient with a unique mrn unless one is supplied."""
    overrides.setdefault("mrn", _mrn())
    return ok(api_client.create_patient(
        create_patient_payload(full_name=full_name, birth_date=birth_date, **overrides),
        INTAKE), 201)


def new_phlebotomist(service_center_id, credential="RN", full_name="Hana Reed", **overrides):
    """Add a phlebotomist to a center roster (status starts ON_DUTY)."""
    return ok(api_client.create_phlebotomist(
        create_phlebotomist_payload(service_center_id, full_name=full_name,
                                    credential=credential, **overrides),
        SUPERVISOR), 201)


def new_order(service_center_id, patient_id, insurance_plan_id, **overrides):
    """Intake a TestOrder. Returns the raw created order row."""
    return ok(api_client.create_test_order(
        create_test_order_payload(service_center_id, patient_id, insurance_plan_id,
                                  **overrides), INTAKE), 201)


def resolve_insurance(test_order_id, headers=None):
    """Resolve eligibility; returns the updated order row."""
    return ok(api_client.insurance_resolve(test_order_id, headers or INTAKE))


def resolve_necessity(test_order_id, headers=None):
    return ok(api_client.necessity_check(test_order_id, headers or INTAKE))


def run_ops(service_center_id):
    """Run the operations checkpoint; returns the updated center row."""
    return ok(api_client.run_ops(service_center_id, SUPERVISOR))


def get_order(test_order_id, headers=None):
    return ok(api_client.get_test_order(test_order_id, headers or INTAKE))


def get_service_center(service_center_id, headers=None):
    return ok(api_client.get_service_center(service_center_id, headers or SUPERVISOR))


def get_appointment(appointment_id, headers=None):
    return ok(api_client.get_appointment(appointment_id, headers or INTAKE))


def get_specimen(specimen_id, headers=None):
    return ok(api_client.get_specimen(specimen_id, headers or LIAISON))


def get_courier_run(courier_run_id, headers=None):
    return ok(api_client.get_courier_run(courier_run_id, headers or LIAISON))


def new_tube_requirement(test_panel, tube_code, **overrides):
    return ok(api_client.create_tube_requirement(
        create_tube_requirement_payload(test_panel, tube_code, **overrides), LIAISON), 201)


def new_courier_run(service_center_id, dispatch_utc, direction="OUTBOUND", **overrides):
    return ok(api_client.create_courier_run(
        create_courier_run_payload(service_center_id, dispatch_utc, direction, **overrides),
        LIAISON), 201)


# ─── Tier 2: entity hierarchy (center + plan + patient + ELIGIBLE order) ─────

def setup_center_and_plan(clock=CLOCK_MORNING, **center_overrides):
    """Center + seeded reference plan. Returns (center, plan_id)."""
    plan_id = seed_reference(clock)
    center = new_center(**center_overrides)
    return center, plan_id


def setup_eligible_order(clock=CLOCK_MORNING, center_overrides=None,
                         order_overrides=None, patient_overrides=None):
    """Center + reference plan + patient + an ELIGIBLE order.

    Returns a dict with center, plan_id, patient, order.
    """
    center, plan_id = setup_center_and_plan(clock=clock, **(center_overrides or {}))
    patient = new_patient(**(patient_overrides or {}))
    order = new_order(center["id"], patient["id"], plan_id, **(order_overrides or {}))
    order = resolve_insurance(order["id"])
    return {"center": center, "plan_id": plan_id, "patient": patient, "order": order}


def book(center_id, order_id, scheduled_start_utc, expected_version=None, **overrides):
    """Book an appointment, defaulting expected_test_order_version to the live one.

    A second booking for an order that already carries a *live* visit would be
    that order's second concurrent visit, which several PRD rules treat
    specially (e.g. §3.6's courier-run selection reads the order's single open
    appointment). Guard against it so a stray double-booking surfaces as a setup
    error instead of a puzzling downstream failure.

    The guard deliberately does NOT fire once the order's previous visit has
    reached a terminal draw_state: PRD §3.4/§3.7 send a rejected or recollected
    order back to `SCHEDULED` on the worklist, so a test that reopens an order
    is expected to book the reopened item afresh.
    """
    order_id_seen = order_id in _APPOINTED_ORDERS
    if order_id_seen:
        live = [a for a in _LIVE_APPOINTMENTS.get(order_id, ())]
        if live:
            raise AssertionError(
                f"order {order_id} already carries a live booked appointment "
                f"in this test")
    _APPOINTED_ORDERS.add(order_id)
    if expected_version is None:
        expected_version = get_order(order_id)["version"]
    appointment = ok(api_client.create_appointment(
        create_appointment_payload(center_id, order_id, scheduled_start_utc,
                                   expected_version, **overrides), INTAKE), 201)
    _LIVE_APPOINTMENTS.setdefault(order_id, set()).add(appointment["id"])
    return appointment


def check_in(patient_id, appointment_id, headers=None):
    """Check in; defaults to the owning Patient's identity, but an
    IntakeCoordinator acting at the desk may be passed explicitly (PRD §3.3)."""
    return ok(api_client.check_in(appointment_id,
                                  headers or make_patient_headers(patient_id)))


def call_patient(appointment_id):
    return ok(api_client.call_appointment(appointment_id, INTAKE))


# ─── Tier 3: full lifecycle shortcuts ─────────────────────────────────────────

def setup_checked_in_visit(clock=CLOCK_WINDOW, scheduled_start_utc="2026-09-01T14:00:00Z",
                           left_margin_minutes=30, order_overrides=None,
                           center_overrides=None, patient_overrides=None):
    """Center + ELIGIBLE order + booked appointment + checked in.

    Returns a dict with center, plan_id, patient, order, appointment, shift.
    """
    shift_data = setup_eligible_order(clock=clock, center_overrides=center_overrides,
                                      order_overrides=order_overrides,
                                      patient_overrides=patient_overrides)
    appointment = book(shift_data["center"]["id"], shift_data["order"]["id"],
                       scheduled_start_utc)
    appointment = check_in(shift_data["patient"]["id"], appointment["id"])
    shift_data["appointment"] = appointment
    shift_data["order"] = get_order(shift_data["order"]["id"])
    return shift_data


def draw_visit_to_collected(visit, phlebotomist_id, tube_code="EDTA_LAVENDER",
                            volume_ml=4.0, order_of_draw=1, register=True):
    """call -> start-draw -> register specimen -> finish-draw.

    Returns (appointment_after_finish, specimen or None).
    """
    appt = visit["appointment"]
    call_patient(appt["id"])
    phleb_headers = make_phlebotomist_headers(phlebotomist_id)
    ok(api_client.start_draw(appt["id"], phleb_headers))
    # PRD §3.4: finishing requires at least one specimen to exist for the
    # order, so every collected visit registers a drawn tube here.
    specimen = ok(api_client.create_specimen(
        create_specimen_payload(visit["order"]["id"], tube_code=tube_code,
                                volume_ml=volume_ml, order_of_draw=order_of_draw),
        phleb_headers), 201)
    finished = ok(api_client.finish_draw(appt["id"], phleb_headers))
    return finished, specimen


def setup_collected_order_with_specimen(clock="2026-09-01T13:30:00Z",
                                        scheduled_start_utc="2026-09-01T14:00:00Z",
                                        tube_code="EDTA_LAVENDER", volume_ml=4.0,
                                        order_of_draw=1, order_overrides=None,
                                        credential="PBT", register=True):
    """A fully drawn, COLLECTED order carrying one UNASSIGNED specimen.

    The center is not pediatric-capable and the default rota credential is plain
    PBT, which PRD §2.6 says covers SELF_SERVICE and STANDARD modes; that matches
    the STANDARD orders these fixtures build. A PEDIATRIC/DIFFICULT_DRAW caller
    passes its own credential and center.

    Returns a dict with center, plan_id, patient, order, appointment, specimen,
    phlebotomist.
    """
    center, plan_id = setup_center_and_plan(clock=clock, pediatric_capable=False)
    phleb = new_phlebotomist(center["id"], credential=credential)
    patient = new_patient()
    order = new_order(center["id"], patient["id"], plan_id, **(order_overrides or {}))
    order = resolve_insurance(order["id"])
    appointment = book(center["id"], order["id"], scheduled_start_utc)
    appointment = check_in(patient["id"], appointment["id"])
    visit = {"center": center, "plan_id": plan_id, "patient": patient,
             "order": order, "appointment": appointment}
    finished, specimen = draw_visit_to_collected(
        visit, phleb["id"], tube_code=tube_code, volume_ml=volume_ml,
        order_of_draw=order_of_draw, register=register)
    return {"center": center, "plan_id": plan_id, "patient": patient,
            "order": get_order(order["id"]), "appointment": finished,
            "specimen": specimen, "phlebotomist": phleb}


def setup_windowed_visit(clock="2026-09-01T12:30:00Z",
                         scheduled_start_utc="2026-09-01T13:00:00Z",
                         tube_code="EDTA_LAVENDER", volume_ml=4.0, order_of_draw=1,
                         credential="PBT", order_overrides=None, register=True):
    """A drawn, COLLECTED order whose specimen is eligible for courier handoff.

    The clock sits inside the visit's check-in window and at least 15 minutes
    before the handoff cutoff, so an assignment against a run dispatching at
    18:00Z satisfies the operating-hours, D1, cutoff and stability rules.

    Returns a dict with center, plan_id, patient, order, appointment, specimen,
    phlebotomist.
    """
    if (order_overrides or {}).get("icd10_codes"):
        raise AssertionError(
            "CDD windowed fixtures need a necessity grid for their codes; build "
            "the rule and call necessity-check in the test instead")
    center, plan_id = setup_center_and_plan(clock=clock, pediatric_capable=False)
    phleb = new_phlebotomist(center["id"], credential=credential)
    patient = new_patient()
    order = new_order(center["id"], patient["id"], plan_id, **(order_overrides or {}))
    order = resolve_insurance(order["id"])
    appointment = book(center["id"], order["id"], scheduled_start_utc)
    appointment = check_in(patient["id"], appointment["id"])
    visit = {"center": center, "plan_id": plan_id, "patient": patient,
             "order": order, "appointment": appointment}
    finished, specimen = draw_visit_to_collected(
        visit, phleb["id"], tube_code=tube_code, volume_ml=volume_ml,
        order_of_draw=order_of_draw, register=register)
    return {"center": center, "plan_id": plan_id, "patient": patient,
            "order": get_order(order["id"]), "appointment": finished,
            "specimen": specimen, "phlebotomist": phleb}


def setup_windowed_assigned_specimen(dispatch_utc="2026-09-01T18:00:00Z", **kwargs):
    """A windowed visit whose specimen is assigned to an OUTBOUND run."""
    kwargs.setdefault("clock", "2026-09-01T12:30:00Z")
    kwargs.setdefault("scheduled_start_utc", "2026-09-01T13:00:00Z")
    data = setup_windowed_visit(**kwargs)
    run = new_courier_run(data["center"]["id"], dispatch_utc)
    specimen = ok(api_client.assign_courier(data["specimen"]["id"], run["id"], LIAISON))
    data["specimen"] = specimen
    data["courier_run"] = run
    return data


def setup_windowed_compromised_specimen(dispatch_utc="2026-09-01T18:00:00Z",
                                        compromise_reason="HEMOLYZED",
                                        compromise_clock="2026-09-01T17:50:00Z",
                                        recollection_ready=False,
                                        **kwargs):
    """A windowed assignment put back by a compromise declared strictly inside
    the run's cutoff-to-dispatch window.

    With ``recollection_ready`` the order is additionally given the
    `ATTENDED_COLLECTED` estimate that PRD §3.7 makes a precondition of the
    recollection path ("it requires that the order's estimate be on the
    `ATTENDED_COLLECTED` variant with its twenty percent discount in force").
    The plain rejection path needs no such estimate.
    """
    kwargs.setdefault("clock", "2026-09-01T13:00:00Z")
    data = setup_windowed_assigned_specimen(dispatch_utc=dispatch_utc, **kwargs)
    set_clock(compromise_clock)
    specimen = ok(api_client.compromise_specimen(data["specimen"]["id"],
                                                 compromise_reason, LIAISON))
    data["specimen"] = specimen
    if recollection_ready:
        order = get_order(data["order"]["id"])
        ok(api_client.create_estimate(
            order["id"],
            create_estimate_payload("ATTENDED_COLLECTED", order["version"]),
            INTAKE), 201)
    return data


def setup_assigned_specimen(clock="2026-09-01T13:30:00Z",
                            dispatch_utc="2026-09-01T18:00:00Z",
                            tube_code="EDTA_LAVENDER", **kwargs):
    """Order drawn and its specimen assigned to an OUTBOUND courier run.

    The clock sits inside the visit's check-in window and at least fifteen
    minutes before the run's cutoff, so the assignment is admissible.
    """
    kwargs.setdefault("scheduled_start_utc", "2026-09-01T13:00:00Z")
    data = setup_collected_order_with_specimen(clock=clock, tube_code=tube_code, **kwargs)
    run = new_courier_run(data["center"]["id"], dispatch_utc)
    specimen = ok(api_client.assign_courier(data["specimen"]["id"], run["id"], LIAISON))
    data["specimen"] = specimen
    data["courier_run"] = run
    return data


# ─── Tier 4: accumulation / threshold targeting ──────────────────────────────

def setup_three_specimens_assigned(clock="2026-09-01T14:30:00Z",
                                   dispatch_utc="2026-09-01T19:00:00Z",
                                   tube_code="EDTA_LAVENDER", count=3):
    """One order with `count` specimens all assigned to a single OUTBOUND run.

    Returns (data, [specimen_id, ...]).
    """
    data = setup_collected_order_with_specimen(
        clock=clock, tube_code=tube_code,
        scheduled_start_utc=add_minutes(clock, 15))
    run = new_courier_run(data["center"]["id"], dispatch_utc)
    ids = []
    phleb_headers = make_phlebotomist_headers(data["phlebotomist"]["id"])
    for _ in range(count):
        specimen = ok(api_client.create_specimen(
            create_specimen_payload(data["order"]["id"], tube_code=tube_code,
                                    volume_ml=4.0, order_of_draw=1), phleb_headers), 201)
        ok(api_client.assign_courier(specimen["id"], run["id"], LIAISON))
        ids.append(specimen["id"])
    data["courier_run"] = run
    data["specimen_ids"] = ids
    return data, ids


def setup_roster_with_queue(center_id, on_duty_specs, clock_positions):
    """Add phlebotomists from `on_duty_specs` = [(credential, name), ...]."""
    phlebotomists = []
    for credential, name in on_duty_specs:
        phlebotomists.append(new_phlebotomist(center_id, credential=credential,
                                              full_name=name))
    return phlebotomists


def setup_wait_scenario():
    """Seven checked-in visits built so the wait read diverges between variants.

    Six earlier WAITING rows: three carry a strictly higher complexity score than
    the reading row and three tie with it; exactly one phlebotomist is on duty, so
    the queue-depth quotient divides by one. Under the instantaneous variant the
    reading row reports 12 minutes (WITHIN_WINDOW); under the blend-rate variant
    the identical data reports 9 minutes (IMMEDIATE).

    Returns a dict with center, plan_id, order (the reading order), patient,
    appointment (the reading appointment), earlier_appointments, phlebotomist.
    """
    clock = "2026-09-01T13:00:00Z"
    plan_id = seed_reference(clock)
    # station_count 10 so the seven booked cells fit inside the day's aggregate.
    center = new_center(station_count=10, pediatric_capable=True)
    phleb = new_phlebotomist(center["id"], credential="RN", full_name="Hana Reed")
    run_ops(center["id"])
    schedule = [
        ("2026-09-01T13:00:00Z", "2026-09-01T13:15:00Z", "DIFFICULT_DRAW"),
        ("2026-09-01T13:10:00Z", "2026-09-01T13:30:00Z", "DIFFICULT_DRAW"),
        ("2026-09-01T13:20:00Z", "2026-09-01T13:45:00Z", "DIFFICULT_DRAW"),
        ("2026-09-01T13:30:00Z", "2026-09-01T14:00:00Z", "STANDARD"),
        ("2026-09-01T13:40:00Z", "2026-09-01T14:15:00Z", "STANDARD"),
        ("2026-09-01T13:50:00Z", "2026-09-01T14:30:00Z", "STANDARD"),
        ("2026-09-01T13:55:00Z", "2026-09-01T14:45:00Z", "SELF_SERVICE"),
    ]
    return _build_wait_rows(center, plan_id, phleb, schedule)


def _build_wait_rows(center, plan_id, phleb, schedule):
    """Book and check in all seven visits with the clock correctly positioned."""
    rows = []
    for created_clock, start_utc, mode in schedule:
        set_clock(created_clock)
        patient = new_patient()
        order = new_order(center["id"], patient["id"], plan_id, collection_mode=mode)
        order = resolve_insurance(order["id"])
        appointment = book(center["id"], order["id"], start_utc)
        rows.append({"patient": patient, "order": order,
                     "appointment": appointment, "start_utc": start_utc, "mode": mode})

    # Windows: [start - 30, start + 15]. Check in each visit at a clock position
    # that falls inside its own window, moving strictly forward in time.
    checkin_clocks = ["2026-09-01T13:00:00Z", "2026-09-01T13:10:00Z",
                      "2026-09-01T13:20:00Z", "2026-09-01T13:30:00Z",
                      "2026-09-01T13:45:00Z", "2026-09-01T14:00:00Z",
                      "2026-09-01T14:15:00Z"]
    for row, clock_at in zip(rows, checkin_clocks):
        set_clock(clock_at)
        row["appointment"] = check_in(row["patient"]["id"], row["appointment"]["id"])

    reading = rows[-1]
    set_clock("2026-09-01T14:15:00Z")
    return {
        "center": center, "plan_id": plan_id, "phlebotomist": phleb,
        "patient": reading["patient"], "order": reading["order"],
        "appointment": reading["appointment"],
        "earlier_appointments": [r["appointment"] for r in rows[:-1]],
        "rows": rows,
    }


def setup_staff_pending_visit():
    """A PEDIATRIC visit at a pediatric-capable center whose roster has only a
    plain PBT phlebotomist, so the call cannot resolve a credential.

    Returns a dict with center, plan_id, patient, order, appointment, phlebotomist.
    """
    clock = "2026-09-01T13:30:00Z"
    plan_id = seed_reference(clock)
    center = new_center(pediatric_capable=True, draw_hold_minutes=30)
    phleb = new_phlebotomist(center["id"], credential="PBT", full_name="Omar Vela")
    kid = new_patient(full_name="Kid Sato", birth_date="2016-03-03T00:00:00Z")
    order = new_order(center["id"], kid["id"], plan_id, collection_mode="PEDIATRIC")
    order = resolve_insurance(order["id"])
    appointment = book(center["id"], order["id"], "2026-09-01T14:00:00Z")
    appointment = check_in(kid["id"], appointment["id"])
    return {"center": center, "plan_id": plan_id, "patient": kid, "order": order,
            "appointment": appointment, "phlebotomist": phleb}


def setup_scheduled_order_for_scheduling_order_state():
    """A center, an ELIGIBLE order, its booked appointment checked in.

    Used by the cross-entity check that an order cannot be scheduled once its
    appointment is no longer in draw_state SCHEDULED.
    """
    return setup_checked_in_visit(clock="2026-09-01T13:00:00Z")


# ─── Tier 5: finalization / terminal state ───────────────────────────────────

def setup_cancelled_order(clock=CLOCK_MORNING):
    """Center + order already cancelled via the cancel endpoint."""
    data = setup_eligible_order(clock=clock)
    ok(api_client.cancel_test_order(data["order"]["id"], INTAKE))
    data["order"] = get_order(data["order"]["id"])
    return data


def setup_rejected_order(clock=CLOCK_MORNING):
    """Order drawn, specimen assigned, compromised and rejected."""
    data = setup_windowed_compromised_specimen(dispatch_utc="2026-09-01T18:00:00Z",
                                        compromise_reason="CLOTTED")
    specimen = ok(api_client.reject_specimen(data["specimen"]["id"], LIAISON))
    data["specimen"] = specimen
    data["order"] = get_order(data["order"]["id"])
    return data