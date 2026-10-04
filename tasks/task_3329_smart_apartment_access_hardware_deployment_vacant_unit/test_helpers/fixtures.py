"""Composite setup helpers.

Each helper builds a precondition from scratch using only PRD-declared
endpoints. The server is restarted before every test, so nothing here may
assume pre-existing state; every helper begins by pinning the logical clock.

All setup calls use the lenient `get_success_data` validator so a broken
precondition reports a clear "Setup step failed" instead of a confusing
assertion failure downstream.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START
from .factories import (
    create_building_payload,
    create_deactivate_payload,
    create_device_payload,
    create_guest_pass_payload,
    create_installation_job_payload,
    create_maintenance_visit_payload,
    create_property_payload,
    create_resident_payload,
    create_tour_session_payload,
    create_unit_payload,
    create_work_order_payload,
)
from .test_users import (
    ADMIN,
    HARDWARE,
    LEASING,
    MAINTENANCE,
    MANAGER,
    TEST_USERS,
    make_resident_headers,
)

api = api_client


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def pin_clock(current_utc: str = CLOCK_START):
    """Pin the logical clock. Every fixture chain starts here."""
    return get_success_data(api.set_clock(current_utc, ADMIN))


def advance_clock(current_utc: str):
    return get_success_data(api.set_clock(current_utc, ADMIN))


# ---------------------------------------------------------------------------
# Primitive provisioning steps
# ---------------------------------------------------------------------------

def provision_property(temp_budget_cents_per_day=500_000, unit_capacity=1, **overrides):
    payload = create_property_payload(
        temp_budget_cents_per_day=temp_budget_cents_per_day,
        unit_capacity=unit_capacity,
        **overrides,
    )
    return get_success_data(api.create_property(payload, ADMIN))


def provision_building(property_id, wifi_rssi_dbm=-60, network_design="FIELD_MESH",
                       **overrides):
    payload = create_building_payload(
        network_design=network_design, wifi_rssi_dbm=wifi_rssi_dbm, **overrides
    )
    return get_success_data(api.create_building(property_id, payload, ADMIN))


def provision_unit(property_id, unit_number="U-101", building_id=None, **overrides):
    payload = create_unit_payload(unit_number=unit_number)
    if building_id is not None:
        payload["building_id"] = building_id
    payload.update(overrides)
    return get_success_data(api.create_unit(property_id, payload, MANAGER))


def provision_device(device_type="SMART_LOCK", building_id=None, unit_id=None,
                     firmware_version="LATEST", **overrides):
    payload = create_device_payload(
        device_type=device_type, firmware_version=firmware_version, **overrides
    )
    if unit_id is not None:
        payload["unit_id"] = unit_id
    if building_id is not None:
        payload["building_id"] = building_id
    return get_success_data(api.create_device(payload, HARDWARE))


def onboard_online_lock(building_id, unit_id, firmware_version="LATEST",
                        battery_pct=100):
    """Provision a smart lock on the unit and drive it ONLINE with a scan."""
    device = provision_device(
        device_type="SMART_LOCK", building_id=building_id, unit_id=unit_id,
        firmware_version=firmware_version, battery_pct=battery_pct,
    )
    get_success_data(
        api.run_device_scan(building_id, {"reachable_device_ids": [device["id"]]}, HARDWARE)
    )
    return device


def create_resident(property_id, unit_id, full_name="Test Resident",
                    email="resident@example.com", **overrides):
    payload = create_resident_payload(full_name=full_name, email=email, **overrides)
    payload["property_id"] = property_id
    payload["unit_id"] = unit_id
    return get_success_data(api.create_resident(payload, MANAGER))


# ---------------------------------------------------------------------------
# Read-back helpers (list endpoints, then locate the row)
# ---------------------------------------------------------------------------

def read_property(property_id):
    return get_success_data(api.get_property(property_id, ADMIN))


def read_unit(property_id, unit_id):
    rows = get_success_data(api.list_units(MANAGER, {"property_id": property_id}))
    return _find(rows, unit_id, "unit")


def read_building(property_id, building_id):
    rows = get_success_data(api.list_buildings(MANAGER, {"property_id": property_id}))
    return _find(rows, building_id, "building")


def read_building_version(property_id, building_id):
    return read_building(property_id, building_id)["version"]


def read_device(building_id, device_id):
    rows = get_success_data(api.list_devices(HARDWARE, {"building_id": building_id}))
    return _find(rows, device_id, "device")


def read_resident(property_id, resident_id):
    rows = get_success_data(api.list_residents(MANAGER, {"property_id": property_id}))
    return _find(rows, resident_id, "resident")


def read_maintenance_visit(unit_id, visit_id):
    rows = get_success_data(api.list_maintenance_visits(MANAGER, {"unit_id": unit_id}))
    return _find(rows, visit_id, "maintenance visit")


def read_installation_job(building_id, job_id):
    rows = get_success_data(
        api.list_installation_jobs(HARDWARE, {"building_id": building_id})
    )
    return _find(rows, job_id, "installation job")


def read_guest_pass(unit_id, guest_pass_id):
    rows = get_success_data(api.list_guest_passes(MANAGER, {"unit_id": unit_id}))
    return _find(rows, guest_pass_id, "guest pass")


def read_tour_session(unit_id, tour_session_id):
    rows = get_success_data(api.list_tour_sessions(LEASING, {"unit_id": unit_id}))
    return _find(rows, tour_session_id, "tour session")


def list_units(property_id=None, building_id=None, occupancy_status=None):
    params = {}
    if property_id is not None:
        params["property_id"] = property_id
    if building_id is not None:
        params["building_id"] = building_id
    if occupancy_status is not None:
        params["occupancy_status"] = occupancy_status
    return get_success_data(api.list_units(MANAGER, params))


def list_buildings(property_id=None):
    params = {}
    if property_id is not None:
        params["property_id"] = property_id
    return get_success_data(api.list_buildings(MANAGER, params))


def list_devices(building_id=None, unit_id=None):
    params = {}
    if building_id is not None:
        params["building_id"] = building_id
    if unit_id is not None:
        params["unit_id"] = unit_id
    return get_success_data(api.list_devices(HARDWARE, params))


def list_credentials(unit_id=None, subject_resident_id=None):
    params = {}
    if unit_id is not None:
        params["unit_id"] = unit_id
    if subject_resident_id is not None:
        params["subject_resident_id"] = subject_resident_id
    return get_success_data(api.list_access_credentials(MANAGER, params))


def list_status_events(resident_id):
    return get_success_data(
        api.list_resident_status_events(MANAGER, {"resident_id": resident_id})
    )


def list_alerts(building_id=None, device_id=None):
    params = {}
    if building_id is not None:
        params["building_id"] = building_id
    if device_id is not None:
        params["device_id"] = device_id
    return get_success_data(api.list_device_alerts(MANAGER, params))


def list_work_orders(alert_id=None, device_id=None):
    params = {}
    if alert_id is not None:
        params["alert_id"] = alert_id
    if device_id is not None:
        params["device_id"] = device_id
    return get_success_data(api.list_work_orders(MANAGER, params))


def _find(rows, entity_id, label):
    for row in rows:
        if row["id"] == entity_id:
            return row
    raise AssertionError(f"Setup failed: {label} {entity_id} not present in listing")


# ---------------------------------------------------------------------------
# Tier 1/2 — common hierarchies
# ---------------------------------------------------------------------------

def setup_property_and_unit(temp_budget_cents_per_day=500_000, unit_capacity=1,
                            unit_number="U-101", with_building=False):
    """Clock pinned + property + one unit. Returns (property, unit) or
    (property, building, unit) when `with_building` is set."""
    pin_clock()
    prop = provision_property(
        temp_budget_cents_per_day=temp_budget_cents_per_day, unit_capacity=unit_capacity
    )
    if with_building:
        bld = provision_building(prop["id"])
        unit = provision_unit(prop["id"], unit_number=unit_number, building_id=bld["id"])
        return prop, bld, unit
    unit = provision_unit(prop["id"], unit_number=unit_number)
    return prop, unit


def setup_property_building_unit(temp_budget_cents_per_day=500_000, unit_capacity=1,
                                 unit_number="U-101", wifi_rssi_dbm=-60,
                                 network_design="FIELD_MESH"):
    """Clock pinned + property + connectivity-passing building + unit.
    Returns (property, building, unit)."""
    pin_clock()
    prop = provision_property(
        temp_budget_cents_per_day=temp_budget_cents_per_day, unit_capacity=unit_capacity
    )
    bld = provision_building(
        prop["id"], wifi_rssi_dbm=wifi_rssi_dbm, network_design=network_design
    )
    unit = provision_unit(prop["id"], unit_number=unit_number, building_id=bld["id"])
    return prop, bld, unit


def setup_unit_with_online_lock(temp_budget_cents_per_day=500_000, unit_number="U-L1"):
    """Property + building + unit + an ONLINE smart lock on the unit.
    Returns (property, building, unit, device)."""
    prop, bld, unit = setup_property_building_unit(
        temp_budget_cents_per_day=temp_budget_cents_per_day, unit_number=unit_number
    )
    device = onboard_online_lock(bld["id"], unit["id"])
    return prop, bld, unit, device


def setup_occupied_unit_with_online_lock(unit_number="U-O1", onboard=False):
    """Unit with an ONLINE smart lock and one resident.

    Onboarding is skipped when `onboard` is False so callers that need
    PENDING_CREDENTIAL keep that state. Returns
    (property, building, unit, device, resident).
    """
    prop, bld, unit, device = setup_unit_with_online_lock(unit_number=unit_number)
    resident = create_resident(prop["id"], unit["id"])
    if onboard:
        get_success_data(api.onboard_resident(resident["id"], MANAGER))
        resident = read_resident(prop["id"], resident["id"])
    return prop, bld, unit, device, resident


def setup_active_resident_with_guest_pass(start_at="2026-09-05T09:00:00Z",
                                          end_at="2026-09-06T09:00:00Z",
                                          guest_label="Guest", unit_number="U-G1"):
    """Onboarded resident with one ACTIVE guest pass on their unit.
    Returns (property, building, unit, device, resident, guest_pass)."""
    prop, bld, unit, device, resident = setup_occupied_unit_with_online_lock(
        unit_number=unit_number, onboard=True
    )
    gpass = get_success_data(
        api.issue_guest_pass(
            unit["id"],
            create_guest_pass_payload(
                host_resident_id=resident["id"], guest_label=guest_label,
                start_at=start_at, end_at=end_at,
            ),
            MANAGER,
        )
    )
    return prop, bld, unit, device, resident, gpass


# ---------------------------------------------------------------------------
# Tier 3 — maintenance visit lifecycles
# ---------------------------------------------------------------------------

def request_visit(unit_id, start_at="2026-09-03T10:00:00Z",
                  end_at="2026-09-03T12:00:00Z", is_emergency=False,
                  technician_id="tech-field-1"):
    payload = create_maintenance_visit_payload(
        technician_id=technician_id, start_at=start_at, end_at=end_at,
        is_emergency=is_emergency,
    )
    return get_success_data(api.request_maintenance_visit(unit_id, payload, MANAGER))


def certify_visit(visit_id, notice_mailed_at="2026-09-01T09:00:00Z"):
    return get_success_data(
        api.certify_notice(visit_id, {"notice_mailed_at": notice_mailed_at}, MANAGER)
    )


def setup_visit(notice_certified=False, start_at="2026-09-03T10:00:00Z",
                end_at="2026-09-03T12:30:00Z", is_emergency=False,
                notice_mailed_at="2026-09-01T09:00:00Z",
                temp_budget_cents_per_day=500_000, unit_number="U-V1"):
    """Property + unit + one maintenance visit in REQUESTED (or NOTICE_CERTIFIED).
    Returns (property, unit, visit)."""
    prop, unit = setup_property_and_unit(
        temp_budget_cents_per_day=temp_budget_cents_per_day, unit_number=unit_number
    )
    visit = request_visit(
        unit["id"], start_at=start_at, end_at=end_at, is_emergency=is_emergency
    )
    if notice_certified:
        visit = certify_visit(visit["id"], notice_mailed_at=notice_mailed_at)
    return prop, unit, visit


def setup_completed_visit(actual_hours=2.0, start_at="2026-09-03T10:00:00Z",
                          end_at="2026-09-03T12:00:00Z", unit_number="U-VC1"):
    """Visit walked to COMPLETED. Returns (property, unit, visit)."""
    prop, unit, visit = setup_visit(
        notice_certified=True, start_at=start_at, end_at=end_at,
        unit_number=unit_number,
    )
    visit = get_success_data(
        api.complete_maintenance_visit(visit["id"], {"actual_hours": actual_hours}, MAINTENANCE)
    )
    return prop, unit, visit


# ---------------------------------------------------------------------------
# Tier 3 — device / alert / work-order lifecycles
# ---------------------------------------------------------------------------

def setup_building_with_offline_leak_sensor(battery_pct=50, unit_number="U-AL1",
                                            leave_alert_open=True,
                                            return_scan=False):
    """Building with a LEAK_SENSOR driven UNREACHABLE by a scan, producing an
    OFFLINE alert. Returns (property, building, unit, device, alert).

    Normally the alert is read back through `GET /device-alerts`. When
    `return_scan` is true the fixture instead returns the raw response of the
    scan that raised the alert, so a caller can assert on that scan's own
    response envelope without replaying the scan."""
    prop, bld, unit = setup_property_building_unit(unit_number=unit_number)
    device = provision_device(
        device_type="LEAK_SENSOR", building_id=bld["id"], unit_id=unit["id"],
        firmware_version="OLD", battery_pct=battery_pct,
    )
    # PRD 3.2 states the absent-scan transition only for a device that is
    # already ONLINE: "A device in `ONLINE` that does not answer becomes
    # `UNREACHABLE`". A freshly provisioned sensor is `PROVISIONED`, and the
    # PRD's only declared transition out of `PROVISIONED` is the one taken when
    # it answers a scan. So the sensor is first driven ONLINE by a scan that
    # reports it reachable; the following scan then omits it.
    get_success_data(
        api.run_device_scan(bld["id"], {"reachable_device_ids": [device["id"]]}, HARDWARE)
    )
    scan_resp = api.run_device_scan(
        bld["id"], {"reachable_device_ids": []}, HARDWARE
    )
    alerts = get_success_data(scan_resp)
    alert = next(a for a in alerts if a["device_id"] == device["id"])
    if return_scan:
        return prop, bld, unit, device, alert, scan_resp
    return prop, bld, unit, device, alert


def setup_building_with_two_locks(battery_pct=100, unit_number="U-2L1"):
    """Building with two smart locks, neither scanned yet.
    Returns (property, building, unit_one, unit_two, device_one, device_two)."""
    pin_clock()
    prop = provision_property(unit_capacity=2)
    bld = provision_building(prop["id"])
    unit_one = provision_unit(prop["id"], unit_number=f"{unit_number}-A", building_id=bld["id"])
    unit_two = provision_unit(prop["id"], unit_number=f"{unit_number}-B", building_id=bld["id"])
    dev_one = provision_device(
        device_type="SMART_LOCK", building_id=bld["id"], unit_id=unit_one["id"],
        firmware_version="LATEST", battery_pct=battery_pct,
    )
    dev_two = provision_device(
        device_type="SMART_LOCK", building_id=bld["id"], unit_id=unit_two["id"],
        firmware_version="LATEST", battery_pct=battery_pct,
    )
    return prop, bld, unit_one, unit_two, dev_one, dev_two


def open_work_order(alert_id, alert_version=None, assigned_technician_id="tech-field-1"):
    if alert_version is None:
        alert_version = 1
    payload = create_work_order_payload(assigned_technician_id=assigned_technician_id)
    payload["expected_device_alert_version"] = alert_version
    return get_success_data(api.create_work_order(alert_id, payload, HARDWARE))


# ---------------------------------------------------------------------------
# Tier 3/4 — installation jobs and their overlap windows
# ---------------------------------------------------------------------------

def create_installation_job(building_id, property_id, unit_id=None,
                            device_type="SMART_LOCK",
                            requires_resident_coordination=False,
                            access_window_start="2026-09-03T09:00:00Z",
                            access_window_end="2026-09-03T12:00:00Z",
                            expected_building_version=None):
    """Create a job using the building's *current* version unless one is given.
    Returns (job, version_used)."""
    if expected_building_version is None:
        expected_building_version = read_building_version(property_id, building_id)
    payload = create_installation_job_payload(
        device_type=device_type,
        requires_resident_coordination=requires_resident_coordination,
        access_window_start=access_window_start,
        access_window_end=access_window_end,
    )
    if unit_id is not None:
        payload["unit_id"] = unit_id
    payload["expected_building_version"] = expected_building_version
    job = get_success_data(
        api.create_installation_job(building_id, payload, MANAGER)
    )
    return job, expected_building_version


def setup_scheduled_installation_job(device_type="SMART_LOCK", unit_id=None,
                                     access_window_start="2026-09-03T09:00:00Z",
                                     access_window_end="2026-09-03T12:00:00Z",
                                     requires_resident_coordination=False,
                                     unit_number="U-IJ1", temp_budget_cents_per_day=500_000):
    """Property + passing building (+ unit when targeted) + one SCHEDULED job.
    Returns (property, building, unit, job, version_used_before_creation)."""
    prop, bld, unit = setup_property_building_unit(
        temp_budget_cents_per_day=temp_budget_cents_per_day, unit_number=unit_number
    )
    target_unit_id = unit["id"] if unit_id is None else unit_id
    job, version_used = create_installation_job(
        bld["id"], prop["id"], unit_id=target_unit_id, device_type=device_type,
        requires_resident_coordination=requires_resident_coordination,
        access_window_start=access_window_start, access_window_end=access_window_end,
    )
    return prop, bld, unit, job, version_used


def setup_in_progress_installation_job(device_type="SMART_LOCK", unit_id=None,
                                       scheduled_start_at="2026-09-03T09:30:00Z",
                                       unit_number="U-IP1",
                                       temp_budget_cents_per_day=500_000):
    """Job walked to IN_PROGRESS. Returns (property, building, unit, job)."""
    prop, bld, unit, job, _ = setup_scheduled_installation_job(
        device_type=device_type, unit_id=unit_id, unit_number=unit_number,
        temp_budget_cents_per_day=temp_budget_cents_per_day,
    )
    job = get_success_data(
        api.schedule_installation_job(
            job["id"], {"scheduled_start_at": scheduled_start_at}, HARDWARE
        )
    )
    return prop, bld, unit, job


# ---------------------------------------------------------------------------
# Misc composites
# ---------------------------------------------------------------------------

def setup_tour_session(unit_number="U-T1", prospect_id_document="DL-77",
                       requested_start_at="2026-09-02T15:00:00Z", unit_with_lock=False):
    """Vacant unit with one REQUESTED tour session. Returns (property, unit, tour)."""
    if unit_with_lock:
        prop, bld, unit, _ = setup_unit_with_online_lock(unit_number=unit_number)
    else:
        prop, unit = setup_property_and_unit(unit_number=unit_number)
    tour = get_success_data(
        api.request_tour_session(
            unit["id"],
            create_tour_session_payload(
                prospect_id_document=prospect_id_document,
                requested_start_at=requested_start_at,
            ),
            LEASING,
        )
    )
    return prop, unit, tour


def revoked_resident_setup(notice_end_at="2026-09-05T00:00:00Z",
                           clock_after="2026-09-06T00:00:00Z",
                           unit_number="U-RV1"):
    """Unit whose sole resident has been onboarded, deactivated and bubbled to
    REVOKED. Returns (property, building, unit, device, resident)."""
    prop, bld, unit, device, resident = setup_occupied_unit_with_online_lock(
        unit_number=unit_number, onboard=True
    )
    get_success_data(
        api.deactivate_resident(
            resident["id"], create_deactivate_payload(notice_end_at=notice_end_at), MANAGER
        )
    )
    advance_clock(clock_after)
    resident = read_resident(prop["id"], resident["id"])
    return prop, bld, unit, device, resident


def make_resident_headers_for(resident):
    """Convenience: ownership-gated resident headers for a resident dict."""
    return make_resident_headers(resident["id"])