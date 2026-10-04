"""Vacant-unit setpoint automation, occupancy, intrusion and self-guided tours."""

import pytest

from test_helpers import (
    HARDWARE,
    LEASING,
    MANAGER,
    ApiErrorId,
    advance_clock,
    build_user_headers,
    get_success_data,
    list_alerts,
    list_credentials,
    pin_clock,
    provision_device,
    provision_property,
    provision_unit,
    read_tour_session,
    read_unit,
    setup_tour_session,
    setup_unit_with_online_lock,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Setpoint derivation
# ---------------------------------------------------------------------------

def test_vacant_automation_takes_the_dehumidification_override_for_hot_humid_air(api):
    """PRD §3.3: "When the relative humidity is at or above 60 percent and the
    window forecast is at or above 27 Celsius, the unit is dehumidified rather
    than merely cooled: the platform ignores the base and the hot clamp entirely
    and sets the setpoint to 24.0 Celsius."

    Design: Difficulty/dual_variant_calc/setpoint_comfort_variant_vs_dehumidification_override
    """
    pin_clock()
    prop = provision_property()
    unit = provision_unit(prop["id"])

    data = validate_success(
        api.run_vacant_automation(
            unit["id"], {"window_forecast_c": 33, "relative_humidity_pct": 70}, MANAGER
        ),
        200,
    )
    assert data["target_setpoint_c"] == pytest.approx(24.0, abs=0.01)
    assert data["hvac_mode"] == "VACANT_AUTO"


def test_humid_stress_branch_needs_both_thresholds(api):
    """PRD §3.3: "Humidity alone does not trigger this — a humid but mild window
    takes the base shape — and a hot but dry window takes the base shape as
    well."

    Design: Corner/calculations/setpoint_humidity_boundary_at_60_pct
    """
    pin_clock()
    prop = provision_property()
    unit = provision_unit(prop["id"])

    override = validate_success(
        api.run_vacant_automation(
            unit["id"], {"window_forecast_c": 30, "relative_humidity_pct": 60}, MANAGER
        ),
        200,
    )
    assert override["target_setpoint_c"] == pytest.approx(24.0, abs=0.01), (
        "humidity 60 and forecast 30 satisfies both limbs of the override"
    )

    base = validate_success(
        api.run_vacant_automation(
            unit["id"], {"window_forecast_c": 30, "relative_humidity_pct": 59}, MANAGER
        ),
        200,
    )
    assert base["target_setpoint_c"] == pytest.approx(27.0, abs=0.01), (
        "humidity 59 misses the override, so the hot base applies"
    )


def test_base_hot_branch_matches_the_comfort_variant_on_the_same_forecast(api):
    """PRD §3.3: "Ordinarily the base setpoint is 26.0 Celsius. If the window
    forecast reaches or exceeds 30 Celsius, the base rises to 27.0 Celsius."

    Design: Difficulty/dual_variant_calc/setpoint_comfort_variant_vs_dehumidification_override
    """
    pin_clock()
    prop = provision_property()
    unit = provision_unit(prop["id"])

    data = validate_success(
        api.run_vacant_automation(
            unit["id"], {"window_forecast_c": 33, "relative_humidity_pct": 45}, MANAGER
        ),
        200,
    )
    assert data["target_setpoint_c"] == pytest.approx(27.0, abs=0.01), (
        "the same 33C forecast on a dry window yields the hot base, 3.0C above the override"
    )


def test_hot_forecast_threshold_is_inclusive_at_thirty_celsius(api):
    """PRD §3.3: "If the window forecast reaches or exceeds 30 Celsius, the base
    rises to 27.0 Celsius."

    Design: Corner/calculations/setpoint_hot_threshold_boundary_at_30_c
    """
    pin_clock()
    prop = provision_property()
    unit = provision_unit(prop["id"])

    hot = validate_success(
        api.run_vacant_automation(
            unit["id"], {"window_forecast_c": 30, "relative_humidity_pct": 45}, MANAGER
        ),
        200,
    )
    assert hot["target_setpoint_c"] == pytest.approx(27.0, abs=0.01)

    mild = validate_success(
        api.run_vacant_automation(
            unit["id"], {"window_forecast_c": 29, "relative_humidity_pct": 45}, MANAGER
        ),
        200,
    )
    assert mild["target_setpoint_c"] == pytest.approx(26.0, abs=0.01)


def test_new_unit_is_born_vacant_with_the_default_vacant_setpoint(api):
    """PRD §3.1: "A newly created unit is born vacant. The server sets
    `occupancy_status` to `VACANT`, `hvac_mode` to `VACANT_AUTO`, and
    `target_setpoint_c` to 26.0 — the default vacant setpoint — and
    `unauthorized_entry_detected` to false."

    Design: Difficulty/dual_variant_calc/setpoint_comfort_variant_vs_dehumidification_override
    """
    pin_clock()
    prop = provision_property()
    unit = provision_unit(prop["id"])

    assert unit["occupancy_status"] == "VACANT"
    assert unit["hvac_mode"] == "VACANT_AUTO"
    assert unit["target_setpoint_c"] == pytest.approx(26.0, abs=0.01)
    assert unit["unauthorized_entry_detected"] is False


# ---------------------------------------------------------------------------
# Setpoint override range
# ---------------------------------------------------------------------------

def test_setpoint_override_above_the_maximum_is_rejected_and_the_maximum_accepted(api):
    """PRD §3.3: "If the caller supplies a `setpoint_override_c`, it is validated
    against the permitted range before use: a value below 15 or above 27 is
    refused with `ERR_SETPOINT_OUT_OF_RANGE` (422)."

    Design: Corner/validations/setpoint_override_out_of_range_rejected
    """
    pin_clock()
    prop = provision_property()
    unit = provision_unit(prop["id"])

    rejected = api.run_vacant_automation(
        unit["id"],
        {"window_forecast_c": 25, "relative_humidity_pct": 40, "setpoint_override_c": 40},
        MANAGER,
    )
    validate_error(rejected, ApiErrorId.ERR_SETPOINT_OUT_OF_RANGE, 422)

    accepted = validate_success(
        api.run_vacant_automation(
            unit["id"],
            {"window_forecast_c": 25, "relative_humidity_pct": 40, "setpoint_override_c": 27},
            MANAGER,
        ),
        200,
    )
    assert accepted["target_setpoint_c"] == pytest.approx(27.0, abs=0.01)


def test_setpoint_override_below_the_minimum_is_rejected(api):
    """PRD §3.3: "If the caller supplies a `setpoint_override_c`, it is validated
    against the permitted range before use: a value below 15 or above 27 is
    refused with `ERR_SETPOINT_OUT_OF_RANGE` (422)."

    Design: Corner/validations/setpoint_override_out_of_range_rejected
    """
    pin_clock()
    prop = provision_property()
    unit = provision_unit(prop["id"])
    before = read_unit(prop["id"], unit["id"])["target_setpoint_c"]

    resp = api.run_vacant_automation(
        unit["id"],
        {"window_forecast_c": 25, "relative_humidity_pct": 40, "setpoint_override_c": 14},
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_SETPOINT_OUT_OF_RANGE, 422)
    assert read_unit(prop["id"], unit["id"])["target_setpoint_c"] == before


# ---------------------------------------------------------------------------
# Occupancy cycle
# ---------------------------------------------------------------------------

def test_unit_occupancy_cycles_back_to_vacant_after_notice_expires(api):
    """PRD §3.1: "`VACANT` becomes `OCCUPIED` when a resident moves in;
    `OCCUPIED` becomes `NOTICE` when that resident gives notice; `NOTICE`
    becomes `NOTICE_ENDED` when the logical clock reaches the declared notice
    end; and `NOTICE_ENDED` becomes `VACANT` again once the unit is returned to
    the vacant program."

    Design: Difficulty/non_linear_state_machine/unit_occupancy_cycle_vacant_occupied_vacant
    """
    pin_clock()
    prop, bld, unit, device = setup_unit_with_online_lock(unit_number="U-C1")
    resident = get_success_data(
        api.create_resident(
            {
                "property_id": prop["id"],
                "unit_id": unit["id"],
                "full_name": "Rae Circle",
                "email": "rae@x.com",
            },
            MANAGER,
        )
    )
    get_success_data(api.onboard_resident(resident["id"], MANAGER))

    assert read_unit(prop["id"], unit["id"])["occupancy_status"] == "OCCUPIED"

    get_success_data(
        api.deactivate_resident(resident["id"], {"notice_end_at": "2026-09-10T00:00:00Z"}, MANAGER)
    )
    assert read_unit(prop["id"], unit["id"])["occupancy_status"] == "NOTICE"

    advance_clock("2026-09-11T00:00:00Z")
    assert read_unit(prop["id"], unit["id"])["occupancy_status"] == "NOTICE_ENDED", (
        "the clock reaching the declared notice end advances the unit"
    )

    get_success_data(
        api.run_vacant_automation(
            unit["id"], {"window_forecast_c": 25, "relative_humidity_pct": 40}, MANAGER
        )
    )
    returned = read_unit(prop["id"], unit["id"])
    assert returned["occupancy_status"] == "VACANT", "the cycle returns the unit to its start"
    assert returned["hvac_mode"] == "VACANT_AUTO"
    assert returned["target_setpoint_c"] == pytest.approx(26.0, abs=0.01)


def test_clock_advance_alone_moves_a_noticed_unit_to_notice_ended(api):
    """PRD §3.10: "When the clock moves, credentials whose `valid_until` has
    arrived are expired, guest passes whose `end_at` has arrived are expired, and
    units in `NOTICE` whose declared notice end has been reached advance to
    `NOTICE_ENDED`."

    Design: Difficulty/non_linear_state_machine/unit_occupancy_cycle_vacant_occupied_vacant
    """
    pin_clock()
    prop, bld, unit, device = setup_unit_with_online_lock(unit_number="U-C2")
    resident = get_success_data(
        api.create_resident(
            {
                "property_id": prop["id"],
                "unit_id": unit["id"],
                "full_name": "Nia Notice",
                "email": "nia@x.com",
            },
            MANAGER,
        )
    )
    get_success_data(api.onboard_resident(resident["id"], MANAGER))
    get_success_data(
        api.deactivate_resident(resident["id"], {"notice_end_at": "2026-09-10T00:00:00Z"}, MANAGER)
    )

    advance_clock("2026-09-09T23:59:59Z")
    assert read_unit(prop["id"], unit["id"])["occupancy_status"] == "NOTICE"

    advance_clock("2026-09-10T00:00:00Z")
    assert read_unit(prop["id"], unit["id"])["occupancy_status"] == "NOTICE_ENDED"


def test_vacant_automation_leaves_an_occupied_unit_occupied(api):
    """PRD §3.3: "When it is run against a unit in `NOTICE_ENDED` and no resident
    whose status is `ACTIVE` still references the unit, the unit moves to
    `VACANT`."

    Design: Difficulty/non_linear_state_machine/unit_occupancy_cycle_vacant_occupied_vacant
    """
    pin_clock()
    prop, bld, unit, device = setup_unit_with_online_lock(unit_number="U-C3")
    resident = get_success_data(
        api.create_resident(
            {
                "property_id": prop["id"],
                "unit_id": unit["id"],
                "full_name": "Ada Active",
                "email": "ada@x.com",
            },
            MANAGER,
        )
    )
    get_success_data(api.onboard_resident(resident["id"], MANAGER))

    get_success_data(
        api.run_vacant_automation(
            unit["id"], {"window_forecast_c": 25, "relative_humidity_pct": 40}, MANAGER
        )
    )
    assert read_unit(prop["id"], unit["id"])["occupancy_status"] == "OCCUPIED"


# ---------------------------------------------------------------------------
# Intrusion detection
# ---------------------------------------------------------------------------

def test_uncredentialed_unlock_on_a_vacant_unit_raises_unauthorized_entry(api):
    """PRD §3.3: "When a `HardwareTechnician` or `PropertyManager` records an
    unlock event against a smart lock on a unit whose `occupancy_status` is
    `VACANT` ... The platform then sets the unit's
    `unauthorized_entry_detected` to true and raises a `DeviceAlert` of type
    `UNAUTHORIZED_ENTRY`, severity `HIGH`, in `OPEN` status."

    Design: Corner/endpoints/vacant_unit_lock_open_without_credential_raises_unauthorized_entry
    """
    pin_clock()
    prop = provision_property(unit_capacity=2)
    bld = get_success_data(
        api.create_building(
            prop["id"],
            {"name": "VW-B1", "network_design": "FIELD_MESH", "wifi_rssi_dbm": -60},
            build_user_headers("op-admin-1", "PlatformAdmin"),
        )
    )
    vacant_unit = provision_unit(prop["id"], unit_number="U-VW1", building_id=bld["id"])
    occupied_unit = provision_unit(prop["id"], unit_number="U-VW2", building_id=bld["id"])
    vacant_lock = provision_device(
        device_type="SMART_LOCK", building_id=bld["id"], unit_id=vacant_unit["id"],
        firmware_version="LATEST", battery_pct=100,
    )
    occupied_lock = provision_device(
        device_type="SMART_LOCK", building_id=bld["id"], unit_id=occupied_unit["id"],
        firmware_version="LATEST", battery_pct=100,
    )
    get_success_data(
        api.run_device_scan(
            bld["id"],
            {"reachable_device_ids": [vacant_lock["id"], occupied_lock["id"]]},
            HARDWARE,
        )
    )
    get_success_data(
        api.create_resident(
            {
                "property_id": prop["id"],
                "unit_id": occupied_unit["id"],
                "full_name": "Vic Watch",
                "email": "vic@x.com",
            },
            MANAGER,
        )
    )

    validate_success(
        api.record_lock_event(vacant_lock["id"], {"event_type": "UNLOCK"}, MANAGER), 200
    )
    validate_success(
        api.record_lock_event(occupied_lock["id"], {"event_type": "UNLOCK"}, MANAGER), 200
    )

    assert read_unit(prop["id"], vacant_unit["id"])["unauthorized_entry_detected"] is True
    alerts = list_alerts(device_id=vacant_lock["id"])
    assert any(
        a["alert_type"] == "UNAUTHORIZED_ENTRY" and a["status"] == "OPEN"
        and a["severity"] == "HIGH"
        for a in alerts
    ), "an uncredentialed open on a vacant unit is an intrusion"
    assert read_unit(prop["id"], occupied_unit["id"])["unauthorized_entry_detected"] is False
    assert read_unit(prop["id"], occupied_unit["id"])["occupancy_status"] == "OCCUPIED"


def test_lock_event_moves_lock_state_without_moving_device_status(api):
    """PRD §3.2: "Recording a lock event against a smart lock that is currently
    `ONLINE` moves `lock_state` to `UNLOCKED` when the event type is an unlock
    and back to `LOCKED` on a close ... Recording a lock event does not move the
    device's `status`, which stays `ONLINE`."

    Design: Corner/endpoints/vacant_unit_lock_open_without_credential_raises_unauthorized_entry
    """
    pin_clock()
    prop, bld, unit, device = setup_unit_with_online_lock(unit_number="U-LS1")

    unlocked = validate_success(
        api.record_lock_event(device["id"], {"event_type": "UNLOCK"}, MANAGER), 200
    )
    assert unlocked["lock_state"] == "UNLOCKED"
    assert unlocked["status"] == "ONLINE"

    relocked = validate_success(
        api.record_lock_event(
            device["id"], {"event_type": "LOCK", "credential_code": "code-1"}, MANAGER
        ),
        200,
    )
    assert relocked["lock_state"] == "LOCKED"
    assert relocked["status"] == "ONLINE"


# ---------------------------------------------------------------------------
# Tour sessions
# ---------------------------------------------------------------------------

def test_denied_tour_retries_and_then_verifies(api):
    """PRD §3.6: "A denied session can be retried, and the retry cycle
    `REQUESTED` to `DENIED` to `REQUESTED` is the non-linear shape in this state
    machine."

    Design: Difficulty/non_linear_state_machine/tour_verification_deny_retry_cycle
    """
    pin_clock()
    prop, unit, tour = setup_tour_session(
        unit_number="U-L9", prospect_id_document="DL-77",
        requested_start_at="2026-09-02T15:00:00Z",
    )

    denied = validate_success(
        api.verify_tour_session(tour["id"], {"identity_document_number": "DL-00"}, LEASING),
        200,
    )
    assert denied["status"] == "DENIED"
    assert denied["verify_attempts"] == 1, "each deny counts an attempt"

    verified = validate_success(
        api.verify_tour_session(tour["id"], {"identity_document_number": "DL-77"}, LEASING),
        200,
    )
    assert verified["status"] == "VERIFIED"
    assert verified["verify_attempts"] == 2


def test_tour_verification_mints_exactly_one_tour_credential(api):
    """PRD §3.6: "The platform then mints a `TOUR`-type `AccessCredential` for
    the unit, `ACTIVE` on issue, valid from `requested_start_at` until
    `requested_start_at` plus the session's `duration_minutes`."

    Design: Difficulty/non_linear_state_machine/tour_verification_deny_retry_cycle
    """
    pin_clock()
    prop, unit, tour = setup_tour_session(
        unit_number="U-L10", prospect_id_document="DL-77",
        requested_start_at="2026-09-02T15:00:00Z",
    )
    validate_success(
        api.verify_tour_session(tour["id"], {"identity_document_number": "DL-00"}, LEASING), 200
    )
    validate_success(
        api.verify_tour_session(tour["id"], {"identity_document_number": "DL-77"}, LEASING), 200
    )

    creds = list_credentials(unit_id=unit["id"])
    tour_creds = [c for c in creds if c["credential_type"] == "TOUR"]
    assert len(tour_creds) == 1, "the denied attempt issued nothing"
    assert tour_creds[0]["status"] == "ACTIVE"
    assert tour_creds[0]["valid_from"].startswith("2026-09-02T15:00")


def test_verification_after_the_sixty_minute_window_is_expired(api):
    """PRD §3.6: "the verification window is short: it stays open for 60 minutes
    measured from `requested_start_at`, and a verification attempted after that
    window has elapsed is refused with `ERR_IDENTITY_VERIFICATION_EXPIRED` (409)."

    Design: Corner/errors/identity_verification_ttl_expired_rejects_tour_verify
    """
    pin_clock()
    prop, unit, tour = setup_tour_session(
        unit_number="U-LL1", prospect_id_document="DL-LL",
        requested_start_at="2026-09-02T15:00:00Z",
    )
    advance_clock("2026-09-02T17:00:00Z")

    resp = api.verify_tour_session(tour["id"], {"identity_document_number": "DL-LL"}, LEASING)
    validate_error(resp, ApiErrorId.ERR_IDENTITY_VERIFICATION_EXPIRED, 409)

    stored = read_tour_session(unit["id"], tour["id"])
    assert stored["status"] == "REQUESTED"
    assert stored["verify_attempts"] == 0
    assert not [c for c in list_credentials(unit_id=unit["id"]) if c["credential_type"] == "TOUR"]


def test_tour_session_defaults_to_requested_with_zero_attempts(api):
    """PRD §3.6: "The session is born `REQUESTED` with `verify_attempts` at 0."
    PRD §3.6: "optionally the `duration_minutes`, which defaults to 60."

    Design: Difficulty/non_linear_state_machine/tour_verification_deny_retry_cycle
    """
    pin_clock()
    prop, unit, tour = setup_tour_session(
        unit_number="U-L11", prospect_id_document="DL-88",
        requested_start_at="2026-09-02T15:00:00Z",
    )
    assert tour["status"] == "REQUESTED"
    assert tour["verify_attempts"] == 0
    assert tour["duration_minutes"] == 60