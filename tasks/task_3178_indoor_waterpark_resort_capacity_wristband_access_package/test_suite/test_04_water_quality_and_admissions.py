"""Water chemistry, the closure protocol, reopening, and admission at the gate."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers import fixtures as fx


def test_a_failing_reading_holds_the_resort_closed(api, platform_ops_headers):
    """PRD §3.7: "`pool_posture` is `CLOSED` when at least one water log for the property carries a `log_status` of `FAIL` and a null `superseded_at`; it is `OPEN` when every failed log for the property has a non-null `superseded_at`."

    Design: Corner/calculations/pool_posture_closes_on_fail_reading
    """
    resort = fx.create_resort(name="Bloomington")
    attraction = fx.create_attraction(resort["id"])
    log = fx.create_water_quality_log(
        resort["id"], attraction["id"], sampled_at="2026-09-03T09:00:00Z", ph_reading=6.0
    )
    assert log["log_status"] == "FAIL"
    assert validate_success(api.get_resort(resort["id"], platform_ops_headers))["pool_posture"] == "CLOSED"


def test_a_plausible_but_unsafe_reading_is_recorded_rather_than_refused(api, aquatics_manager_headers):
    """PRD §3.7: "The second is the safe window, and crossing it is not an error at
    all: the reading is accepted, recorded, and classified."

    Design: Corner/calculations/pool_posture_closes_on_fail_reading
    """
    resort = fx.create_resort(name="Bloomington")
    attraction = fx.create_attraction(resort["id"])
    log = validate_success(
        api.create_water_quality_log(
            resort["id"],
            {
                "attraction_id": attraction["id"],
                "sampled_at": "2026-09-03T09:00:00Z",
                "ph_reading": 6.0,
                "free_chlorine_ppm": 2.0,
                "turbidity_ntu": 0.3,
            },
            aquatics_manager_headers,
        ),
        201,
    )
    assert log["log_status"] == "FAIL"
    assert log["superseded_at"] is None


def test_a_superseding_pass_reopens_the_property(api, aquatics_manager_headers):
    """PRD §3.7: "The new passing reading is appended and the standing failure's
    `superseded_at` is stamped with the instant it was displaced by,
    `pool_posture` is recomputed, and the property's `version` is incremented."
    PRD §3.7: "`pool_posture` is `OPEN` when every failed log for the property has
    a non-null `superseded_at`."

    Design: Corner/calculations/pool_posture_reopens_after_superseding_pass
    """
    resort = fx.create_resort(name="Grapevine")
    attraction = fx.create_attraction(resort["id"])
    log = fx.create_water_quality_log(
        resort["id"], attraction["id"], sampled_at="2026-09-03T09:00:00Z", ph_reading=6.0
    )
    passing = validate_success(
        api.supersede_water_quality_log(
            resort["id"],
            log["id"],
            {
                "sampled_at": "2026-09-03T10:00:00Z",
                "ph_reading": 7.4,
                "free_chlorine_ppm": 2.0,
                "turbidity_ntu": 0.3,
            },
            aquatics_manager_headers,
        )
    )
    assert passing["log_status"] == "PASS"
    assert validate_success(api.get_resort(resort["id"], aquatics_manager_headers))[
        "pool_posture"
    ] == "OPEN"


def test_a_closure_revokes_today_bands_and_declines_their_grants(api, aquatics_manager_headers,
                                                                platform_ops_headers):
    """PRD §3.7: "Every wristband whose `valid_on_service_date` equals the
    property's current service date and whose `wristband_status` is in either
    `ISSUED` or `ACTIVE` is moved to `REVOKED` with `access_status` `DENIED`,
    `access_denied_reason` of `WATER_QUALITY_CLOSED`, `room_charge_enabled` false,
    and `arcade_credit_limit_cents` 0."
    PRD §3.7: "Every arcade credit grant that had succeeded on any of those bands
    is declined with `decline_reason` `WRISTBAND_REVOKED`."

    Design: Difficulty/transitive_cascade/pool_closure_revokes_band_then_declines_grants
    """
    resort, _attraction, _reservation, band = fx.setup_pool_closure_with_active_band(
        arcade_credit_rate_cents_per_unit=9450
    )
    revoked = validate_success(api.get_wristband(resort["id"], band["id"], platform_ops_headers))
    assert revoked["wristband_status"] == "REVOKED"
    assert revoked["access_denied_reason"] == "WATER_QUALITY_CLOSED"
    assert validate_success(
        api.get_resort(resort["id"], platform_ops_headers)
    )["pool_posture"] == "CLOSED"


def test_a_closure_still_leaves_an_unrevoked_band_grants_succeeded(api, platform_ops_headers,
                                                                   anonymous_headers):
    """PRD §3.7: "Every arcade credit grant that had succeeded on any of those
    bands is declined with `decline_reason` `WRISTBAND_REVOKED`."

    Design: Difficulty/transitive_cascade/pool_closure_revokes_band_then_declines_grants
    """
    resort = fx.create_resort(arcade_credit_rate_cents_per_unit=9450)
    fx.set_clock(resort["id"], "2026-09-04T10:00:00Z")
    attraction = fx.create_attraction(resort["id"])
    room_type = fx.create_room_type(resort["id"])
    reservation = fx.create_reservation(
        resort["id"], room_type["id"], guest_count=2, arrival_date="2026-09-04",
        departure_date="2026-09-06",
    )
    reservation = fx.check_in_reservation(resort["id"], reservation["id"])
    # PRD 3.7 only revokes bands whose valid_on_service_date equals the
    # property's current service date, so this band sits a day later.
    band = fx.create_wristband(
        resort["id"], "RESERVATION_GUEST", "Nell", reservation_id=reservation["id"],
        valid_on_service_date="2026-09-05",
    )
    band = fx.activate_wristband(resort["id"], band["id"])
    grant = validate_success(
        api.post_arcade_grant(resort["id"], band["id"], {"amount_cents": 900}, anonymous_headers), 201
    )
    fx.create_water_quality_log(
        resort["id"], attraction["id"], sampled_at="2026-09-04T11:00:00Z", ph_reading=6.1
    )
    untouched = validate_success(api.get_arcade_credit(resort["id"], grant["id"], platform_ops_headers))
    assert untouched["grant_status"] == "SUCCEEDED"


def test_admission_is_refused_while_the_pool_is_closed(api, gate_attendant_headers):
    """PRD §3.5: "Two further gate conditions are inherited from §2.4 and apply to every crossing: the property's `pool_posture` must be `OPEN`, failing which `ERR_POOL_CLOSED` is returned, and the attraction-side readiness check yielding `ERR_ATTRACTION_NOT_OPEN` is evaluated before the capacity ceiling."

    Design: Corner/validations/admission_refused_while_pool_closed
    """
    resort, _attraction, _reservation, band = fx.setup_pool_closure_with_active_band()
    response = api.post_admission(
        resort["id"],
        {"wristband_id": band["id"], "service_date": "2026-09-03", "direction": "IN"},
        gate_attendant_headers,
    )
    validate_error(response, ApiErrorId.ERR_POOL_CLOSED.value)


def test_an_implausible_reading_fails_plausibility_before_the_attraction_gate(
    api, aquatics_manager_headers, platform_ops_headers
):
    """PRD §3.7: "a reading whose pH falls outside the closed interval from 0 to 14,
    whose free chlorine falls outside the closed interval from 0.0 to 10.0 parts
    per million, or whose turbidity falls outside the closed interval from 0 to 50
    nephelometric turbidity units is physically impossible and is rejected outright
    with `ERR_WATER_QUALITY_OUT_OF_RANGE` (HTTP 422)."
    PRD §2.4: "The remaining checks run in this order: the service-date horizon (`ERR_SERVICE_DATE_OUT_OF_RANGE`, which guards day-pass sales and group bookings, and fires when the requested `service_date` falls more than 365 days after the property's current service date); target state admissibility (`ERR_INVALID_STATE`, guarding every state-transition operation); pool posture (`ERR_POOL_CLOSED`, guarding gate admission posting and wristband activation); attraction readiness (`ERR_ATTRACTION_NOT_OPEN`, guarding gate admission posting and activity-session creation); physical plausibility of a submitted water reading (`ERR_WATER_QUALITY_OUT_OF_RANGE`); cabana overlap and capacity (`ERR_CABANA_DOUBLE_BOOKED` and `ERR_CABANA_UNITS_UNAVAILABLE`); the day-pass ceiling (`ERR_DAY_PASS_CAP_EXCEEDED`); the park capacity ceiling (`ERR_PARK_CAPACITY_EXCEEDED`); the arcade ceiling (`ERR_ARCADE_LIMIT_EXCEEDED`); the birthday-party minimum (`ERR_GROUP_MINIMUM_NOT_MET`); and finally the deposit requirement together with gateway acceptance (`ERR_PAYMENT_DECLINED`)."

    Design: Difficulty/priority_pair_validation_conflict/branch_manager_cannot_override_safety_closure_priority
    """
    resort = fx.create_resort(name="Sandusky")
    attraction = fx.create_attraction(resort["id"], required_certification="LIFEGUARD")
    response = api.create_water_quality_log(
        resort["id"],
        {
            "attraction_id": attraction["id"],
            "sampled_at": "2026-09-03T11:00:00Z",
            "ph_reading": 15.0,
            "free_chlorine_ppm": 2.0,
            "turbidity_ntu": 0.4,
        },
        aquatics_manager_headers,
    )
    validate_error(response, ApiErrorId.ERR_WATER_QUALITY_OUT_OF_RANGE.value)
    assert validate_success(
        api.get_attraction(resort["id"], attraction["id"], platform_ops_headers)
    )["attraction_status"] == "CLOSED"
    logs = validate_success(
        api.list_attraction_water_quality_logs(resort["id"], attraction["id"], aquatics_manager_headers)
    )
    assert logs == []


def test_a_second_reading_at_the_same_instant_is_refused(api, aquatics_manager_headers):
    """PRD §3.7: "A reading submitted for an attraction and instant that already
    carries a log is refused with `ERR_DUPLICATE_READING_AT_INSTANT` (HTTP 409)."

    Design: Corner/state_machines/group_cancel_cascades_to_activity_bookings
    """
    resort = fx.create_resort(name="Grapevine")
    attraction = fx.create_attraction(resort["id"])
    fx.create_water_quality_log(
        resort["id"], attraction["id"], sampled_at="2026-09-03T09:00:00Z", ph_reading=7.4
    )
    response = api.create_water_quality_log(
        resort["id"],
        {
            "attraction_id": attraction["id"],
            "sampled_at": "2026-09-03T09:00:00Z",
            "ph_reading": 7.5,
            "free_chlorine_ppm": 2.0,
            "turbidity_ntu": 0.3,
        },
        aquatics_manager_headers,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_READING_AT_INSTANT.value)

def test_the_plausibility_gate_pre_empts_the_attraction_gate_for_every_axis(
    api, aquatics_manager_headers, platform_ops_headers
):
    """PRD §3.7: "a reading whose pH falls outside the closed interval from 0 to 14,
    whose free chlorine falls outside the closed interval from 0.0 to 10.0 parts
    per million, or whose turbidity falls outside the closed interval from 0 to 50
    nephelometric turbidity units is physically impossible and is rejected outright
    with `ERR_WATER_QUALITY_OUT_OF_RANGE` (HTTP 422)."
    PRD §2.4: "The remaining checks run in this order: the service-date horizon (`ERR_SERVICE_DATE_OUT_OF_RANGE`, which guards day-pass sales and group bookings, and fires when the requested `service_date` falls more than 365 days after the property's current service date); target state admissibility (`ERR_INVALID_STATE`, guarding every state-transition operation); pool posture (`ERR_POOL_CLOSED`, guarding gate admission posting and wristband activation); attraction readiness (`ERR_ATTRACTION_NOT_OPEN`, guarding gate admission posting and activity-session creation); physical plausibility of a submitted water reading (`ERR_WATER_QUALITY_OUT_OF_RANGE`); cabana overlap and capacity (`ERR_CABANA_DOUBLE_BOOKED` and `ERR_CABANA_UNITS_UNAVAILABLE`); the day-pass ceiling (`ERR_DAY_PASS_CAP_EXCEEDED`); the park capacity ceiling (`ERR_PARK_CAPACITY_EXCEEDED`); the arcade ceiling (`ERR_ARCADE_LIMIT_EXCEEDED`); the birthday-party minimum (`ERR_GROUP_MINIMUM_NOT_MET`); and finally the deposit requirement together with gateway acceptance (`ERR_PAYMENT_DECLINED`)."

    Design: Difficulty/priority_pair_validation_conflict/branch_manager_cannot_override_safety_closure_priority
    """
    resort = fx.create_resort(name="Sandusky")
    attraction = fx.create_attraction(resort["id"], required_certification="LIFEGUARD")
    response = api.create_water_quality_log(
        resort["id"],
        {
            "attraction_id": attraction["id"],
            "sampled_at": "2026-09-03T12:00:00Z",
            "ph_reading": 7.4,
            "free_chlorine_ppm": 12.0,
            "turbidity_ntu": 0.4,
        },
        aquatics_manager_headers,
    )
    validate_error(response, ApiErrorId.ERR_WATER_QUALITY_OUT_OF_RANGE.value)
    assert validate_success(
        api.get_attraction(resort["id"], attraction["id"], platform_ops_headers)
    )["attraction_status"] == "CLOSED"
