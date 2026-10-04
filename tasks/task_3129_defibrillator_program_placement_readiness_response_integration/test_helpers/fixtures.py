"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures
produce clear "Setup failed" errors instead of confusing assertion failures.

Each helper builds its preconditions from scratch using only PRD-declared
endpoints; every test starts against an empty database.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_cabinet_payload,
    create_campus_payload,
    create_case_review_payload,
    create_consumable_lot_payload,
    create_device_model_payload,
    create_device_payload,
    create_inspection_payload,
    create_inspection_submit_payload,
    create_responder_payload,
    create_self_test_report_payload,
    create_training_session_payload,
    create_zone_payload,
)
from .test_users import (
    TEST_USERS,
    make_inspector_headers,
    make_medical_director_headers,
    make_responder_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["program_manager_headers"]
SYSTEM = TEST_USERS["system_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock + catalog + campus primitives
# ---------------------------------------------------------------------------

def set_clock(current_utc: str = "2026-09-01T00:00:00Z"):
    """Set the server logical clock."""
    res = api_client.set_clock({"current_utc": current_utc}, ADMIN)
    return get_success_data(res)


def create_device_model(pad_months=24, battery_months=48,
                        prescription_required=False, **overrides):
    payload = create_device_model_payload(
        pad_shelf_life_months=pad_months,
        battery_shelf_life_months=battery_months,
        prescription_required=prescription_required,
        **overrides,
    )
    return get_success_data(api_client.create_device_model(payload, ADMIN))


def create_campus(**overrides):
    return get_success_data(
        api_client.create_campus(create_campus_payload(**overrides), ADMIN)
    )


def create_zone(campus_id, **overrides):
    return get_success_data(
        api_client.create_zone(create_zone_payload(campus_id, **overrides), PM)
    )


def create_cabinet(zone_id, **overrides):
    return get_success_data(
        api_client.create_cabinet(create_cabinet_payload(zone_id, **overrides), PM)
    )


def create_device(campus_id, device_model_id, **overrides):
    return get_success_data(
        api_client.create_device(
            create_device_payload(campus_id, device_model_id, **overrides), PM
        )
    )


def create_lot(campus_id, device_model_id, kind="PAD", **overrides):
    return get_success_data(
        api_client.create_consumable_lot(
            create_consumable_lot_payload(
                campus_id, device_model_id, kind=kind, **overrides
            ),
            PM,
        )
    )


def create_responder(campus_id, responder_role="LAY_RESPONDER", **overrides):
    return get_success_data(
        api_client.create_responder(
            create_responder_payload(campus_id, responder_role=responder_role, **overrides),
            PM,
        )
    )


def get_device(device_id):
    return get_success_data(api_client.get_device(device_id, PM))


# ---------------------------------------------------------------------------
# Tier 1: state progression — device install / consumable install / commission
# ---------------------------------------------------------------------------

def install_device_into_cabinet(device_id, cabinet_id, expected_device_version):
    """REGISTERED -> INSTALLED. Returns the updated Device."""
    res = api_client.install_device(
        device_id,
        {"cabinet_id": cabinet_id,
         "expected_device_version": expected_device_version},
        PM,
    )
    return get_success_data(res)


def install_consumable(device_id, lot_id):
    """Install a consumable lot into a device, refreshing expected_device_version
    from the live device first. Returns the new Install record."""
    current = get_device(device_id)
    res = api_client.create_install(
        {
            "device_id": device_id,
            "consumable_lot_id": lot_id,
            "expected_device_version": current["version"],
        },
        PM,
    )
    return get_success_data(res)


def schedule_and_pass_inspection(device_id, inspector_id,
                                 scheduled_for="2026-09-01T00:00:00Z",
                                 checklist_items=None):
    """Schedule an inspection and submit it as PASS. Returns the Inspection."""
    headers = make_inspector_headers(inspector_id)
    insp = get_success_data(
        api_client.create_inspection(
            create_inspection_payload(device_id, inspector_id,
                                      scheduled_for=scheduled_for),
            headers,
        )
    )
    submit = create_inspection_submit_payload()
    if checklist_items is not None:
        submit["checklist_items"] = checklist_items
    return get_success_data(
        api_client.submit_inspection(insp["id"], submit, headers)
    )


def certify_responder(campus_id, responder_id, instructor_id,
                      session_ends_at="2026-08-01T04:00:00Z",
                      certification_months_granted=24):
    """Create a completed training session (ended in the past relative to the
    default logical clock) so `responder_id` becomes certified.

    Requires the session window to be valid at creation: starts_at must be
    later than the current time, so this helper walks the clock back to
    2026-07-01, creates the session, enrolls, advances the clock past
    ends_at, completes, then restores the clock to 2026-09-01.
    """
    set_clock("2026-07-01T00:00:00Z")
    session = get_success_data(
        api_client.create_training_session(
            create_training_session_payload(
                campus_id,
                instructor_id,
                starts_at="2026-08-01T00:00:00Z",
                ends_at=session_ends_at,
                certification_months_granted=certification_months_granted,
            ),
            PM,
        )
    )
    get_success_data(
        api_client.enroll_training_session(
            session["id"], {"responder_id": responder_id}, PM
        )
    )
    set_clock("2026-08-02T00:00:00Z")
    get_success_data(
        api_client.complete_training_session(
            session["id"], {"attendee_ids": [responder_id]}, PM
        )
    )
    set_clock("2026-09-01T00:00:00Z")
    return session


# ---------------------------------------------------------------------------
# Tier 2: hierarchy — campus/zone/cabinet/device with optional consumables
# ---------------------------------------------------------------------------

def setup_campus_zone_cabinet_device(prescription_required=False,
                                     pad_months=24, battery_months=48,
                                     serial_number="SN-1",
                                     response_time_target_seconds=240,
                                     **campus_overrides):
    """Campus + zone + cabinet (EMPTY) + REGISTERED device.

    Returns (campus, zone, cabinet, device, device_model).
    """
    set_clock("2026-09-01T00:00:00Z")
    model = create_device_model(
        pad_months=pad_months, battery_months=battery_months,
        prescription_required=prescription_required,
    )
    campus = create_campus(
        response_time_target_seconds=response_time_target_seconds,
        **campus_overrides,
    )
    zone = create_zone(campus["id"])
    cabinet = create_cabinet(zone["id"])
    device = create_device(campus["id"], model["id"], serial_number=serial_number)
    return campus, zone, cabinet, device, model


def setup_installed_device_with_consumables(serial_number="SN-2"):
    """Campus + zone + cabinet + device INSTALLED with ACTIVE pad and battery
    installs. Posture will be DEGRADED (no passing inspection yet).

    Returns dict with campus, zone, cabinet, device, model, pad_lot,
    battery_lot, pad_install, battery_install.
    """
    campus, zone, cabinet, device, model = setup_campus_zone_cabinet_device(
        serial_number=serial_number
    )
    pad_lot = create_lot(campus["id"], model["id"], kind="PAD")
    battery_lot = create_lot(campus["id"], model["id"], kind="BATTERY")
    device = install_device_into_cabinet(device["id"], cabinet["id"], device["version"])
    pad_install = install_consumable(device["id"], pad_lot["id"])
    battery_install = install_consumable(device["id"], battery_lot["id"])
    return {
        "campus": campus,
        "zone": zone,
        "cabinet": cabinet,
        "device": get_device(device["id"]),
        "model": model,
        "pad_lot": pad_lot,
        "battery_lot": battery_lot,
        "pad_install": pad_install,
        "battery_install": battery_install,
    }


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_commissioned_device(serial_number="SN-3", with_certified_responder=True):
    """Device driven all the way to IN_SERVICE with posture READY:
    install + consumables + PASS inspection + PASS self-test + commission.

    Also creates (when with_certified_responder):
      - an INSPECTOR responder (inspections),
      - a MEDICAL_DIRECTOR responder (instructor / case review),
      - a certified LAY_RESPONDER (emergency acknowledge/resolve).

    Returns dict with all artifacts and ids.
    """
    ctx = setup_installed_device_with_consumables(serial_number=serial_number)
    campus = ctx["campus"]
    device_id = ctx["device"]["id"]

    inspector = create_responder(
        campus["id"], responder_role="INSPECTOR",
        full_name="Inspector I", badge_number="IN-1",
    )
    md = create_responder(
        campus["id"], responder_role="MEDICAL_DIRECTOR",
        full_name="MD One", badge_number="MD-1",
    )
    schedule_and_pass_inspection(device_id, inspector["id"])
    get_success_data(
        api_client.create_self_test_report(
            create_self_test_report_payload(device_id, result="PASS"), SYSTEM
        )
    )
    get_success_data(api_client.commission_device(device_id, PM))

    responder = None
    if with_certified_responder:
        responder = create_responder(
            campus["id"], responder_role="LAY_RESPONDER",
            full_name="Responder R", badge_number="R-1",
        )
        certify_responder(campus["id"], responder["id"], md["id"])

    ctx.update({
        "device": get_device(device_id),
        "inspector": inspector,
        "medical_director": md,
        "responder": responder,
    })
    return ctx


def open_cabinet_event(ctx):
    """Open the cabinet of a commissioned device, creating an EmergencyEvent
    (status OPEN). Returns the EmergencyEvent."""
    res = api_client.open_cabinet(ctx["cabinet"]["id"], ANON)
    return get_success_data(res)


def acknowledge_event(event_id, responder_id):
    return get_success_data(
        api_client.acknowledge_emergency_event(
            event_id, make_responder_headers(responder_id)
        )
    )


def resolve_event(event_id, responder_id, hospital_code="H-1",
                  patient_transported=True, pads_consumed=False):
    return get_success_data(
        api_client.resolve_emergency_event(
            event_id,
            {
                "hospital_code": hospital_code,
                "patient_transported": patient_transported,
                "pads_consumed": pads_consumed,
            },
            make_responder_headers(responder_id),
        )
    )


def setup_resolved_event(serial_number="SN-4", pads_consumed=False):
    """Commissioned device whose cabinet was opened and the resulting event
    acknowledged and resolved. Returns ctx dict extended with `event`."""
    ctx = setup_commissioned_device(serial_number=serial_number)
    event = open_cabinet_event(ctx)
    acknowledge_event(event["id"], ctx["responder"]["id"])
    event = resolve_event(
        event["id"], ctx["responder"]["id"], pads_consumed=pads_consumed
    )
    ctx["event"] = event
    return ctx


def setup_case_review_in_state(target_state="DRAFT", serial_number="SN-5",
                               pads_consumed=False):
    """Resolved event with a second MedicalDirector (not the campus
    medical_director_id) as reviewer. Returns ctx extended with `event`,
    `review`, `reviewer`, `acceptor`.

    target_state: DRAFT or SUBMITTED.
    """
    ctx = setup_resolved_event(serial_number=serial_number,
                               pads_consumed=pads_consumed)
    campus = ctx["campus"]
    reviewer = create_responder(
        campus["id"], responder_role="MEDICAL_DIRECTOR",
        full_name="MD Reviewer", badge_number="MD-R",
    )
    acceptor = create_responder(
        campus["id"], responder_role="MEDICAL_DIRECTOR",
        full_name="MD Acceptor", badge_number="MD-A",
    )
    review = get_success_data(
        api_client.create_case_review(
            create_case_review_payload(ctx["event"]["id"], reviewer["id"]),
            make_medical_director_headers(reviewer["id"]),
        )
    )
    if target_state == "SUBMITTED":
        review = get_success_data(
            api_client.submit_case_review(
                review["id"], make_medical_director_headers(reviewer["id"])
            )
        )
    ctx.update({"event": get_success_data(
        api_client.get_emergency_event(ctx["event"]["id"], PM)
    ), "review": review, "reviewer": reviewer, "acceptor": acceptor})
    return ctx
