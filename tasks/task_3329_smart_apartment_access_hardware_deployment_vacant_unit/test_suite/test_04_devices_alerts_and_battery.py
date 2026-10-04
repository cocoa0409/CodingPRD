"""Device provisioning, reachability scans, alerts and the repair loop."""

from test_helpers import (
    HARDWARE,
    ApiErrorId,
    get_success_data,
    list_alerts,
    list_devices,
    list_work_orders,
    open_work_order,
    pin_clock,
    provision_building,
    provision_device,
    provision_property,
    provision_unit,
    read_device,
    setup_building_with_offline_leak_sensor,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Provisioning defaults
# ---------------------------------------------------------------------------

def test_device_creation_applies_the_declared_defaults(api):
    """PRD §3.2: "The platform initializes the device to `status` `PROVISIONED`,
    `lock_state` `LOCKED`, `battery_replacements` 0, and `battery_pct` at the
    supplied value or 100 when none is supplied."

    Design: Corner/entities/device_create_applies_declared_defaults
    """
    pin_clock()
    prop = provision_property()
    bld = provision_building(prop["id"])
    unit = provision_unit(prop["id"], building_id=bld["id"])

    resp = api.create_device(
        {"device_type": "SMART_LOCK", "unit_id": unit["id"], "building_id": bld["id"],
         "firmware_version": "LATEST"},
        HARDWARE,
    )
    data = validate_success(resp, 201)
    assert data["battery_pct"] == 100
    assert data["status"] == "PROVISIONED"
    assert data["lock_state"] == "LOCKED"
    assert data["battery_replacements"] == 0


def test_hub_battery_is_pinned_at_one_hundred_regardless_of_input(api):
    """PRD §3.2: "A hub is mains-powered: its `battery_pct` is pinned at 100
    regardless of what is supplied, and it never draws down."

    Design: Corner/entities/device_create_applies_declared_defaults
    """
    pin_clock()
    prop = provision_property()
    bld = provision_building(prop["id"])

    data = validate_success(
        api.create_device(
            {"device_type": "HUB", "building_id": bld["id"],
             "firmware_version": "LATEST", "battery_pct": 12},
            HARDWARE,
        ),
        201,
    )
    assert data["battery_pct"] == 100


def test_device_list_narrows_to_a_single_building(api):
    """PRD §2.3: "Several list endpoints accept optional narrowing filters ...
    When a filter is omitted, the endpoint returns the unfiltered collection."

    Design: Corner/entities/device_list_filters_by_building
    """
    pin_clock()
    prop = provision_property(unit_capacity=2)
    bld_one = provision_building(prop["id"], name="B1")
    bld_two = provision_building(prop["id"], name="B2")
    dev_one = provision_device(device_type="SMART_LOCK", building_id=bld_one["id"])
    dev_two = provision_device(device_type="SMART_LOCK", building_id=bld_two["id"])

    rows = list_devices(building_id=bld_one["id"])
    assert [d["id"] for d in rows] == [dev_one["id"]]
    assert all(d["building_id"] == bld_one["id"] for d in rows)
    assert dev_two["id"] not in [d["id"] for d in rows]


# ---------------------------------------------------------------------------
# Reachability scans
# ---------------------------------------------------------------------------

def test_scan_drains_only_the_absent_devices(api):
    """PRD §2.10: "Every reachability scan in which a device is absent costs the
    device one percentage point of `battery_pct` ... A device that is present in
    the scan loses nothing."

    Design: Corner/endpoints/device_scan_drains_battery_of_unreachable_devices
    """
    pin_clock()
    prop = provision_property()
    bld = provision_building(prop["id"])
    reachable = provision_device(
        device_type="SMART_LOCK", building_id=bld["id"], firmware_version="LATEST",
        battery_pct=100,
    )
    absent = provision_device(
        device_type="SMART_LOCK", building_id=bld["id"], firmware_version="LATEST",
        battery_pct=100,
    )
    # PRD §3.2 declares the absent-scan transition only for a device that is
    # already `ONLINE`, so both locks are first driven `ONLINE` by a scan that
    # reports them reachable.
    get_success_data(
        api.run_device_scan(
            bld["id"],
            {"reachable_device_ids": [reachable["id"], absent["id"]]},
            HARDWARE,
        )
    )

    get_success_data(
        api.run_device_scan(bld["id"], {"reachable_device_ids": [reachable["id"]]}, HARDWARE)
    )

    assert read_device(bld["id"], reachable["id"])["battery_pct"] == 100
    absent_now = read_device(bld["id"], absent["id"])
    assert absent_now["battery_pct"] == 99
    assert absent_now["status"] == "UNREACHABLE"
    assert read_device(bld["id"], reachable["id"])["status"] == "ONLINE"


def test_scan_raises_a_high_offline_alert_and_reports_it_in_the_envelope(api):
    """PRD §3.2: "A device in `ONLINE` that does not answer becomes
    `UNREACHABLE`, draws one percentage point of battery, and raises an `OFFLINE`
    alert against it — this alert is `OPEN` from birth and carries severity
    `HIGH`."

    Design: Corner/endpoints/device_scan_response_carries_alert_envelope_fields
    """
    pin_clock()
    prop, bld, unit, device, alert, resp = setup_building_with_offline_leak_sensor(
        unit_number="U-EE1", return_scan=True
    )

    assert resp.json()["response_type"] == "array"
    data = validate_success(resp, 200)
    assert data, "the scan that drives the sensor absent reports the alert it raised"
    entry = next(a for a in data if a["device_id"] == device["id"])
    assert entry["alert_type"] == "OFFLINE"
    assert entry["status"] == "OPEN"
    assert entry["severity"] == "HIGH"
    body = resp.json()
    assert body["meta"]["api_request_id"]
    assert body["meta"]["api_request_timestamp"]


def test_scan_raises_a_medium_low_battery_alert_below_twenty_percent(api):
    """PRD §2.10: "A scan in which a device is reachable and its `battery_pct` is
    strictly below 20 percent raises a low-battery alert on that device, with
    severity `MEDIUM`."
    PRD §3.9: "`LOW_BATTERY` alerts are `MEDIUM`."

    Design: Corner/endpoints/device_scan_response_carries_alert_envelope_fields
    """
    pin_clock()
    prop = provision_property()
    bld = provision_building(prop["id"])
    weak = provision_device(
        device_type="SMART_LOCK", building_id=bld["id"], firmware_version="LATEST",
        battery_pct=19,
    )

    data = validate_success(
        api.run_device_scan(bld["id"], {"reachable_device_ids": [weak["id"]]}, HARDWARE), 200
    )
    assert any(
        a["alert_type"] == "LOW_BATTERY" and a["severity"] == "MEDIUM" for a in data
    )


def test_scan_revives_an_unreachable_device_and_resolves_its_offline_alert(api):
    """PRD §3.2: "A device in `UNREACHABLE` that answers again returns to
    `ONLINE`, and any `OPEN` `OFFLINE` alert on it is resolved."

    Design: Corner/endpoints/device_scan_drains_battery_of_unreachable_devices
    """
    pin_clock()
    prop, bld, unit, device, alert = setup_building_with_offline_leak_sensor(
        unit_number="U-RE1", battery_pct=80
    )
    assert read_device(bld["id"], device["id"])["status"] == "UNREACHABLE"

    get_success_data(
        api.run_device_scan(bld["id"], {"reachable_device_ids": [device["id"]]}, HARDWARE)
    )

    assert read_device(bld["id"], device["id"])["status"] == "ONLINE"
    alerts = list_alerts(device_id=device["id"])
    assert all(
        a["status"] != "OPEN" for a in alerts if a["alert_type"] == "OFFLINE"
    ), "the open OFFLINE alert is resolved by the answering scan"


# ---------------------------------------------------------------------------
# Battery replacement
# ---------------------------------------------------------------------------

def test_replacement_restores_charge_and_increments_the_counter(api):
    """PRD §3.9: "A successful replacement restores `battery_pct` to 100,
    increments `battery_replacements` by one, and resolves any `OPEN`
    `LOW_BATTERY` alert on the device."

    Design: Corner/endpoints/replace_battery_restores_charge_and_increments_counter
    """
    pin_clock()
    prop = provision_property()
    bld = provision_building(prop["id"])
    device = provision_device(
        device_type="SMART_LOCK", building_id=bld["id"], firmware_version="LATEST",
        battery_pct=20,
    )
    get_success_data(
        api.run_device_scan(bld["id"], {"reachable_device_ids": [device["id"]]}, HARDWARE)
    )

    data = validate_success(api.replace_battery(device["id"], HARDWARE), 200)
    assert data["battery_pct"] == 100
    assert data["battery_replacements"] == 1


def test_unreachable_device_cannot_have_its_battery_replaced(api):
    """PRD §3.9: "The replacement requires the device to be `ONLINE` — a device
    that is `UNREACHABLE` cannot be serviced and the attempt is refused with
    `ERR_DEVICE_UNREACHABLE` (409)."

    Design: Corner/errors/device_unreachable_blocks_battery_replacement
    """
    pin_clock()
    prop = provision_property()
    bld = provision_building(prop["id"])
    device = provision_device(
        device_type="SMART_LOCK", building_id=bld["id"], firmware_version="LATEST",
        battery_pct=30,
    )
    get_success_data(api.run_device_scan(bld["id"], {"reachable_device_ids": []}, HARDWARE))

    resp = api.replace_battery(device["id"], HARDWARE)
    validate_error(resp, ApiErrorId.ERR_DEVICE_UNREACHABLE, 409)
    assert read_device(bld["id"], device["id"])["battery_pct"] == 29


def test_critical_firmware_device_is_decommissioned_on_replacement(api):
    """PRD §3.9: "replacing the battery of a device whose `firmware_version` is
    `CRITICAL` does not return the device to service. A device whose firmware is
    `CRITICAL` moves from `ONLINE` to `DECOMMISSIONED`, which is terminal."

    Design: Corner/errors/device_unreachable_blocks_battery_replacement
    """
    pin_clock()
    prop = provision_property()
    bld = provision_building(prop["id"])
    device = provision_device(
        device_type="SMART_LOCK", building_id=bld["id"], firmware_version="CRITICAL",
        battery_pct=40,
    )
    get_success_data(
        api.run_device_scan(bld["id"], {"reachable_device_ids": [device["id"]]}, HARDWARE)
    )

    data = validate_success(api.replace_battery(device["id"], HARDWARE), 200)
    assert data["status"] == "DECOMMISSIONED"


# ---------------------------------------------------------------------------
# Work orders
# ---------------------------------------------------------------------------

def test_work_order_creation_records_the_alert_version_guard(api):
    """PRD §3.9: "A `PropertyManager` or `HardwareTechnician` opens one by
    supplying the `assigned_technician_id` of the technician taking the job —
    optional at creation — and the mandatory `expected_device_alert_version`."

    Design: Corner/cross_cutting_complexity_layers/stale_device_alert_version_blocks_work_order_creation
    """
    pin_clock()
    prop, bld, unit, device, alert = setup_building_with_offline_leak_sensor(
        unit_number="U-WO1"
    )
    resp = api.create_work_order(
        alert["id"],
        {"assigned_technician_id": "tech-nia", "expected_device_alert_version": alert["version"]},
        HARDWARE,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "OPEN"
    assert data["battery_replaced"] is False


def test_work_order_creation_without_the_version_guard_is_incomplete(api):
    """PRD §2.9: "Clients of these operations must supply the version they last
    observed for the parent resource they are writing against; the field is
    mandatory, not optional, and a request that omits it is incomplete."

    Design: Corner/cross_cutting_complexity_layers/stale_device_alert_version_blocks_work_order_creation
    """
    pin_clock()
    prop, bld, unit, device, alert = setup_building_with_offline_leak_sensor(
        unit_number="U-WO2"
    )
    resp = api.create_work_order(
        alert["id"], {"assigned_technician_id": "tech-nia"}, HARDWARE
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_stale_device_alert_version_blocks_work_order_creation(api):
    """PRD §2.9: "If the alert's current `version` differs from the supplied
    value ... the operation is rejected with `ERR_STALE_VERSION` and an HTTP
    status of 412."

    Design: Corner/cross_cutting_complexity_layers/stale_device_alert_version_blocks_work_order_creation
    """
    pin_clock()
    prop, bld, unit, device, alert = setup_building_with_offline_leak_sensor(
        unit_number="U-VV1"
    )
    resp = api.create_work_order(
        alert["id"],
        {"assigned_technician_id": "tech-paul",
         "expected_device_alert_version": alert["version"] - 1},
        HARDWARE,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
    assert list_work_orders(device_id=device["id"]) == []


def test_sensor_alert_work_order_replacement_chain(api):
    """PRD §3.9: "Moving an order from `OPEN` to `ASSIGNED` requires a non-null
    technician and, in the same transaction, acknowledges the parent alert — the
    alert moves from `OPEN` to `ACKNOWLEDGED`."
    PRD §3.9: "Moving an order from `ASSIGNED` to `CLOSED` requires either that
    the target device is `ONLINE` or that the battery was replaced, and it
    resolves the parent alert, moving it from `ACKNOWLEDGED` to `RESOLVED`; when
    the order records a battery replacement, the target device's
    `battery_replacements` count is incremented by one."

    Design: Difficulty/transitive_cascade/sensor_alert_wo_replacement_three_hop_chain
    """
    pin_clock()
    prop, bld, unit, device, alert = setup_building_with_offline_leak_sensor(
        unit_number="U-CH1", battery_pct=10
    )
    assert read_device(bld["id"], device["id"])["status"] == "UNREACHABLE"
    assert [a for a in list_alerts(device_id=device["id"]) if a["alert_type"] == "OFFLINE"]

    work_order = open_work_order(alert["id"], alert_version=alert["version"])
    validate_success(
        api.assign_work_order(
            work_order["id"], {"technician_id": "tech-nia", "confirm_repair": True}, HARDWARE
        ),
        200,
    )
    acknowledged = [a for a in list_alerts(device_id=device["id"]) if a["id"] == alert["id"]][0]
    assert acknowledged["status"] == "ACKNOWLEDGED"

    closed = validate_success(
        api.assign_work_order(
            work_order["id"],
            {"technician_id": "tech-nia", "replaced_battery": True, "confirm_repair": True},
            HARDWARE,
        ),
        200,
    )
    assert closed["status"] == "CLOSED"
    assert read_device(bld["id"], device["id"])["battery_replacements"] == 1
    resolved = [a for a in list_alerts(device_id=device["id"]) if a["id"] == alert["id"]][0]
    assert resolved["status"] == "RESOLVED"


def test_assigning_a_closed_work_order_is_rejected(api):
    """PRD §3.9: "Assignment of an order that is already `CLOSED` is refused
    with `ERR_ALREADY_TERMINAL` (409)."

    Design: Corner/state_machines/work_order_assign_from_closed_returns_invalid_state
    """
    pin_clock()
    prop, bld, unit, device, alert = setup_building_with_offline_leak_sensor(
        unit_number="U-TT1"
    )
    work_order = open_work_order(alert["id"], alert_version=alert["version"])
    validate_success(
        api.assign_work_order(
            work_order["id"], {"technician_id": "tech-ivy"}, HARDWARE
        ),
        200,
    )
    validate_success(
        api.assign_work_order(
            work_order["id"],
            {"technician_id": "tech-ivy", "replaced_battery": True, "confirm_repair": True},
            HARDWARE,
        ),
        200,
    )

    resp = api.assign_work_order(
        work_order["id"], {"technician_id": "tech-ivy", "confirm_repair": True}, HARDWARE
    )
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL, 409)
    stored = list_work_orders(device_id=device["id"])[0]
    assert stored["status"] == "CLOSED"


def test_assigning_a_work_order_after_resolution_is_rejected_with_a_state_error(api):
    """PRD §2.12: "Sixth, the target resource must not already be in a terminal
    state — otherwise `ERR_ALREADY_TERMINAL` (409); this guards work-order
    assignment once the order is `CLOSED`."
    PRD §3.9: "The order is a three-step ladder: `OPEN` becomes `ASSIGNED`, and
    `ASSIGNED` becomes `CLOSED`, which is terminal."

    Design: Corner/state_machines/work_order_assign_from_closed_returns_invalid_state
    """
    pin_clock()
    prop, bld, unit, device, alert = setup_building_with_offline_leak_sensor(
        unit_number="U-TT2"
    )
    work_order = open_work_order(alert["id"], alert_version=alert["version"])
    validated = validate_success(
        api.assign_work_order(
            work_order["id"], {"technician_id": "tech-ivy", "confirm_repair": True}, HARDWARE
        ),
        200,
    )
    assert validated["status"] == "ASSIGNED"
    validate_success(
        api.assign_work_order(
            work_order["id"],
            {"technician_id": "tech-ivy", "replaced_battery": True, "confirm_repair": True},
            HARDWARE,
        ),
        200,
    )

    resp = api.assign_work_order(
        work_order["id"], {"technician_id": "tech-ivy", "confirm_repair": True}, HARDWARE
    )
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL, 409)


def test_work_orders_can_be_listed_by_alert(api):
    """PRD §2.3: "The available filter parameters across the API are ...
    `device_id`, and `alert_id`; each is used only by the endpoints named in §4,
    and each is optional."

    Design: Corner/cross_cutting_complexity_layers/stale_device_alert_version_blocks_work_order_creation
    """
    pin_clock()
    prop, bld, unit, device, alert = setup_building_with_offline_leak_sensor(
        unit_number="U-WL1"
    )
    work_order = open_work_order(alert["id"], alert_version=alert["version"])

    rows = list_work_orders(alert_id=alert["id"])
    assert [w["id"] for w in rows] == [work_order["id"]]

def test_scan_creates_a_single_offline_alert_for_the_absent_sensor(api):
    """PRD §3.2: "A device in `ONLINE` that does not answer becomes
    `UNREACHABLE`, draws one percentage point of battery, and raises an `OFFLINE`
    alert against it — this alert is `OPEN` from birth and carries severity
    `HIGH`."

    Design: Difficulty/transitive_cascade/sensor_alert_wo_replacement_three_hop_chain
    """
    pin_clock()
    prop, bld, unit, device, alert = setup_building_with_offline_leak_sensor(
        unit_number="U-CH2", battery_pct=10
    )

    stored = read_device(bld["id"], device["id"])
    assert stored["status"] == "UNREACHABLE"
    assert stored["battery_pct"] == 9, "one percentage point drawn by the absent scan"

    offline = [a for a in list_alerts(device_id=device["id"]) if a["alert_type"] == "OFFLINE"]
    assert len(offline) == 1
    assert offline[0]["status"] == "OPEN"
    assert offline[0]["severity"] == "HIGH"


def test_replacement_on_the_chained_sensor_restores_its_charge(api):
    """PRD §3.9: "when the order records a battery replacement, the target
    device's `battery_replacements` count is incremented by one."

    Design: Difficulty/transitive_cascade/sensor_alert_wo_replacement_three_hop_chain
    """
    pin_clock()
    prop, bld, unit, device, alert = setup_building_with_offline_leak_sensor(
        unit_number="U-CH3", battery_pct=10
    )
    work_order = open_work_order(alert["id"], alert_version=alert["version"])
    validate_success(
        api.assign_work_order(
            work_order["id"], {"technician_id": "tech-nia", "confirm_repair": True}, HARDWARE
        ),
        200,
    )
    validate_success(
        api.assign_work_order(
            work_order["id"],
            {"technician_id": "tech-nia", "replaced_battery": True, "confirm_repair": True},
            HARDWARE,
        ),
        200,
    )

    repaired = read_device(bld["id"], device["id"])
    assert repaired["battery_replacements"] == 1
