"""Conserved quantities, version evidence and the logical clock's driven expiries."""

from test_helpers import (
    ADMIN,
    HARDWARE,
    MANAGER,
    ApiErrorId,
    advance_clock,
    assert_credential_conservation,
    create_installation_job,
    get_success_data,
    list_alerts,
    list_credentials,
    pin_clock,
    provision_property,
    provision_unit,
    read_building_version,
    read_guest_pass,
    read_property,
    request_visit,
    setup_active_resident_with_guest_pass,
    setup_building_with_offline_leak_sensor,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Budget boundary
# ---------------------------------------------------------------------------

def test_certification_is_allowed_exactly_at_the_cap_and_refused_one_cent_under(api):
    """PRD §2.8: "The platform refuses any operation that would push
    `budget_committed_cents` above `temp_budget_cents_per_day` ... the refusal
    carries `ERR_BUDGET_EXCEEDED` with an HTTP status of 409."

    Design: Corner/validations/budget_committed_boundary_rejects_visit_that_exceeds_cap
    """
    pin_clock()
    at_cap = provision_property(temp_budget_cents_per_day=4100, name="At Cap",
                                address_line="1 Cap St")
    under = provision_property(temp_budget_cents_per_day=4099, name="Under Cap",
                               address_line="2 Cap St")

    ok_unit = provision_unit(at_cap["id"], unit_number="U-CAP1")
    ok_visit = request_visit(
        ok_unit["id"], start_at="2026-09-03T10:00:00Z", end_at="2026-09-03T13:00:00Z"
    )
    problem_unit = provision_unit(under["id"], unit_number="U-CAP2")
    problem_visit = request_visit(
        problem_unit["id"], start_at="2026-09-03T10:00:00Z", end_at="2026-09-03T13:00:00Z"
    )

    certified = validate_success(
        api.certify_notice(
            ok_visit["id"], {"notice_mailed_at": "2026-09-01T09:00:00Z"}, MANAGER
        ),
        200,
    )
    assert certified["accrued_cost_cents"] == 4100
    assert read_property(at_cap["id"])["budget_committed_cents"] == 4100

    resp = api.certify_notice(
        problem_visit["id"], {"notice_mailed_at": "2026-09-01T09:00:00Z"}, MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED, 409)
    assert read_property(under["id"])["budget_committed_cents"] == 0


# ---------------------------------------------------------------------------
# Accrual evidence
# ---------------------------------------------------------------------------

def test_provisional_accrual_is_readable_from_the_property_roll_up(api):
    """PRD §2.8: "`budget_committed_cents` is the sum of `accrued_cost_cents`
    across the property's `MaintenanceVisit` rows whose status is
    `NOTICE_CERTIFIED` or `COMPLETED`."

    Design: Difficulty/dual_variant_calc/maintenance_accrual_provisional_vs_final
    """
    pin_clock()
    prop = provision_property()
    unit = provision_unit(prop["id"])
    visit = request_visit(
        unit["id"], start_at="2026-09-03T10:00:00Z", end_at="2026-09-03T12:30:00Z"
    )
    certified = validate_success(
        api.certify_notice(
            visit["id"], {"notice_mailed_at": "2026-09-01T09:00:00Z"}, MANAGER
        ),
        200,
    )
    assert certified["status"] == "NOTICE_CERTIFIED"
    assert certified["accrued_cost_cents"] == 4100
    assert read_property(prop["id"])["budget_committed_cents"] == 4100


# ---------------------------------------------------------------------------
# Version evidence
# ---------------------------------------------------------------------------

def test_installation_job_creation_advances_the_building_version_by_one(api):
    """PRD §3.8: "Creation also advances the building: the building's `version`
    is incremented by exactly one, which is precisely the mutation that any other
    client's later job creation will be measured against under §2.9."

    Design: Corner/cross_cutting_complexity_layers/stale_building_version_blocks_second_installation_job
    """
    pin_clock()
    prop = provision_property()
    bld = get_success_data(
        api.create_building(
            prop["id"],
            {"name": "VB-B1", "network_design": "FIELD_MESH", "wifi_rssi_dbm": -60},
            ADMIN,
        )
    )
    unit = provision_unit(prop["id"], unit_number="U-VB1", building_id=bld["id"])
    version_before = bld["version"]

    create_installation_job(
        bld["id"], prop["id"], unit_id=unit["id"], device_type="SMART_LOCK",
        expected_building_version=version_before,
    )

    assert read_building_version(prop["id"], bld["id"]) == version_before + 1


def test_installation_job_creation_reserves_two_thousand_cents(api):
    """PRD §2.8: "each installation job placed against a building of the property
    holds a reservation of 2000 cents, and that reservation is carried inside
    `budget_committed_cents`."

    Design: Corner/cross_cutting_complexity_layers/stale_building_version_blocks_second_installation_job
    """
    pin_clock()
    prop = provision_property()
    bld = get_success_data(
        api.create_building(
            prop["id"],
            {"name": "RS-B1", "network_design": "FIELD_MESH", "wifi_rssi_dbm": -60},
            ADMIN,
        )
    )
    unit = provision_unit(prop["id"], unit_number="U-RS1", building_id=bld["id"])
    create_installation_job(
        bld["id"], prop["id"], unit_id=unit["id"], device_type="SMART_LOCK",
        expected_building_version=bld["version"],
    )

    assert read_property(prop["id"])["budget_committed_cents"] == 2000


def test_work_order_creation_with_the_observed_alert_version_succeeds(api):
    """PRD §2.9: "The first guard applies when a work order is opened against a
    device alert. That request must carry `expected_device_alert_version`, the
    client's last observed `version` of the target `DeviceAlert`."

    Design: Corner/cross_cutting_complexity_layers/stale_device_alert_version_blocks_work_order_creation
    """
    pin_clock()
    prop, bld, unit, device, alert = setup_building_with_offline_leak_sensor(
        unit_number="U-WV1"
    )

    data = validate_success(
        api.create_work_order(
            alert["id"],
            {"assigned_technician_id": "tech-paul",
             "expected_device_alert_version": alert["version"]},
            HARDWARE,
        ),
        201,
    )
    assert data["status"] == "OPEN"
    assert data["alert_id"] == alert["id"]


def test_work_order_creation_advances_the_alert_version_by_one(api):
    """PRD §3.9: "The work order is born `OPEN` and its `battery_replaced` flag is
    false; opening it also advances the alert's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/stale_device_alert_version_blocks_work_order_creation
    """
    pin_clock()
    prop, bld, unit, device, alert = setup_building_with_offline_leak_sensor(
        unit_number="U-WV2"
    )
    validate_success(
        api.create_work_order(
            alert["id"],
            {"assigned_technician_id": "tech-paul",
             "expected_device_alert_version": alert["version"]},
            HARDWARE,
        ),
        201,
    )

    current = [a for a in list_alerts(device_id=device["id"]) if a["id"] == alert["id"]][0]
    assert current["version"] == alert["version"] + 1


# ---------------------------------------------------------------------------
# Credential conservation
# ---------------------------------------------------------------------------

def test_credential_rows_are_conserved_when_revoked(api):
    """PRD §2.7: "The four live states partition the population, so counting
    every credential a resident has ever held gives the same number whether the
    count is taken as the sum of the `active`, `expired` and `revoked` groups or
    as the size of the full set."

    Design: Difficulty/compensating_invariant/credential_status_partition_conservation
    """
    pin_clock()
    prop, bld, unit, device, resident, gpass = setup_active_resident_with_guest_pass(
        unit_number="U-CN1"
    )
    assert_credential_conservation(list_credentials(unit_id=unit["id"]), 2)

    get_success_data(
        api.deactivate_resident(
            resident["id"], {"notice_end_at": "2026-09-20T00:00:00Z"}, MANAGER
        )
    )

    after = list_credentials(unit_id=unit["id"])
    assert_credential_conservation(after, 2)
    assert {c["status"] for c in after} == {"REVOKED"}


def test_resident_scope_and_unit_scope_count_different_populations(api):
    """PRD §2.7: "Scoped to a resident — that is, restricted to rows whose
    `subject_resident_id` equals the resident's `id` — the count covers only that
    resident's own credentials and excludes guest and tour credentials. Scoped to
    a unit — restricted to rows whose `unit_id` equals the unit's `id` — the
    count covers every credential on the unit, including those of type `GUEST`
    and `TOUR`."

    Design: Difficulty/compensating_invariant/credential_status_partition_conservation
    """
    pin_clock()
    prop, bld, unit, device, resident, gpass = setup_active_resident_with_guest_pass(
        unit_number="U-CN2"
    )

    unit_rows = list_credentials(unit_id=unit["id"])
    resident_rows = list_credentials(subject_resident_id=resident["id"])

    assert len(unit_rows) == 2
    assert len(resident_rows) == 1
    assert {c["credential_type"] for c in unit_rows} == {"RESIDENT", "GUEST"}
    assert resident_rows[0]["credential_type"] == "RESIDENT"


# ---------------------------------------------------------------------------
# Logical clock driven expiries
# ---------------------------------------------------------------------------

def test_clock_advance_expires_the_guest_pass_and_its_credential(api):
    """PRD §3.10: "When the clock moves, credentials whose `valid_until` has
    arrived are expired, guest passes whose `end_at` has arrived are expired."

    Design: Corner/endpoints/clock_advance_expires_guest_pass_and_credential
    """
    pin_clock()
    prop, bld, unit, device, resident, gpass = setup_active_resident_with_guest_pass(
        start_at="2026-09-05T09:00:00Z", end_at="2026-09-06T09:00:00Z",
        unit_number="U-TK1",
    )

    advance_clock("2026-09-07T00:00:00Z")

    assert read_guest_pass(unit["id"], gpass["id"])["status"] == "EXPIRED"
    guest_creds = [
        c for c in list_credentials(unit_id=unit["id"]) if c["credential_type"] == "GUEST"
    ]
    assert guest_creds and all(c["status"] == "EXPIRED" for c in guest_creds)


def test_clock_advance_leaves_the_resident_credential_live(api):
    """PRD §3.10: "When the clock moves, credentials whose `valid_until` has
    arrived are expired, guest passes whose `end_at` has arrived are expired."

    Design: Corner/endpoints/clock_advance_expires_guest_pass_and_credential
    """
    pin_clock()
    prop, bld, unit, device, resident, gpass = setup_active_resident_with_guest_pass(
        start_at="2026-09-05T09:00:00Z", end_at="2026-09-06T09:00:00Z",
        unit_number="U-TK2",
    )

    advance_clock("2026-09-07T00:00:00Z")

    resident_creds = [
        c for c in list_credentials(unit_id=unit["id"]) if c["credential_type"] == "RESIDENT"
    ]
    assert resident_creds
    assert all(c["status"] == "ACTIVE" for c in resident_creds), (
        "the guest window closing does not touch the resident credential"
    )