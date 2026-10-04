"""Day-pass pricing, the day-pass ceiling, the service-date horizon, and its OCC gate."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers import fixtures as fx


def test_ten_day_pass_units_attract_no_volume_addition(api):
    """PRD §3.5: "The per-unit component is `units_requested` multiplied by the
    day-pass base charge of 4200 cents."
    PRD §3.5: "Read as a formula, the surcharge applies to every complete ten-unit block above the first ten units, so ten units attract no addition at all, eleven through twenty units attract exactly 1000 cents, and twenty-one through thirty units attract 2000 cents; a partial block adds nothing."

    Design: Corner/calculations/day_pass_price_at_exactly_ten_units_stays_flat
    """
    resort = fx.create_resort(park_capacity_occupancy_units=40, day_pass_cap_units=20)
    day_pass = fx.create_day_pass(resort["id"], service_date="2026-09-03", units_requested=10)
    assert day_pass["price_total_cents"] == 42000


def test_nineteen_day_pass_units_attract_exactly_one_block(api):
    """PRD §3.5: "eleven through twenty units attract exactly 1000 cents, and
    twenty-one through thirty units attract 2000 cents; a partial block adds
    nothing."

    Design: Corner/cross_cutting_complexity_layers/arcade_rate_threshold_holds_the_result_staircase
    """
    resort = fx.create_resort(park_capacity_occupancy_units=40, day_pass_cap_units=30)
    day_pass = fx.create_day_pass(resort["id"], service_date="2026-09-03", units_requested=19)
    assert day_pass["price_total_cents"] == 79800


def test_twenty_day_pass_units_attract_one_block_not_a_replacement_rate(api):
    """PRD §3.5: "Importantly, the ten-unit allowance is a *floor on the surcharge*,
    not an alternative rate: the base charge of 4200 cents applies to every unit
    including the first ten. Twelve units therefore cost twelve times 4200 cents
    plus a single block of 1000 cents, and not ten units at the base rate plus two
    units at the block rate."

    Design: Corner/calculations/day_pass_price_above_threshold_adds_one_block
    """
    resort = fx.create_resort(park_capacity_occupancy_units=40, day_pass_cap_units=20)
    day_pass = fx.create_day_pass(resort["id"], service_date="2026-09-03", units_requested=20)
    assert day_pass["price_total_cents"] == 85000
    assert day_pass["price_total_cents"] != 84000


def test_a_voided_day_pass_stops_counting_toward_the_date(api, front_desk_headers):
    """PRD §3.5: "The walk-in allocation is enforced per service date through
    `day_pass_reserved_units`, defined as the sum of `units_requested` across every
    day pass whose `service_date` is that date and whose `day_pass_status` is
    either `RESERVED` or `ADMITTED`. Passes that have been voided or expired
    contribute nothing to the sum."

    Design: Corner/calculations/day_pass_reserved_units_excludes_voided_passes
    """
    resort = fx.create_resort(park_capacity_occupancy_units=40, day_pass_cap_units=20)
    first = fx.create_day_pass(resort["id"], service_date="2026-09-03", units_requested=4)
    second = fx.create_day_pass(resort["id"], service_date="2026-09-03", units_requested=6)
    validate_success(api.void_day_pass(resort["id"], first["id"], front_desk_headers))
    ledger = fx.get_capacity(resort["id"], "2026-09-03")
    assert ledger["day_pass_reserved_units"] == 6
    assert validate_success(
        api.get_day_pass(resort["id"], first["id"], front_desk_headers)
    )["day_pass_status"] == "VOID"
    assert validate_success(
        api.get_day_pass(resort["id"], second["id"], front_desk_headers)
    )["day_pass_status"] == "RESERVED"


def test_a_sale_that_fits_both_ceilings_passes_and_commits_units(api):
    """PRD §3.5: "A sale or an admission that would push the day-passed total above
    the property's `day_pass_cap_units` is refused with `ERR_DAY_PASS_CAP_EXCEEDED`
    (HTTP 409), and the boundary is inclusive — a request that lands exactly on the
    cap is accepted."

    Design: Corner/validations/fully_satisfied_day_pass_sale_succeeds
    """
    resort = fx.create_resort(park_capacity_occupancy_units=30, day_pass_cap_units=20)
    day_pass = fx.create_day_pass(resort["id"], service_date="2026-09-03", units_requested=6)
    assert day_pass["day_pass_status"] == "RESERVED"
    assert fx.get_capacity(resort["id"], "2026-09-03")["day_pass_reserved_units"] == 6
    assert day_pass["price_total_cents"] == 25200


def test_a_sale_past_the_day_pass_ceiling_is_refused(api):
    """PRD §3.5: "A sale or an admission that would push the day-passed total above
    the property's `day_pass_cap_units` is refused with `ERR_DAY_PASS_CAP_EXCEEDED`
    (HTTP 409), and the boundary is inclusive — a request that lands exactly on the
    cap is accepted."

    Design: Corner/validations/day_pass_ceiling_breach_rejected
    """
    resort = fx.create_resort(park_capacity_occupancy_units=30, day_pass_cap_units=4)
    fx.create_day_pass(resort["id"], service_date="2026-09-03", units_requested=4)
    version = fx.refresh_resort(resort["id"])["version"]
    response = api.create_day_pass(
        resort["id"],
        {"service_date": "2026-09-03", "units_requested": 4, "expected_resort_version": version},
        fx.FRONT_DESK,
    )
    validate_error(response, ApiErrorId.ERR_DAY_PASS_CAP_EXCEEDED.value)


def test_a_sale_past_the_service_date_horizon_is_refused(api):
    """PRD §3.5: "The property's separate chronological horizon applies here and to
    group bookings alone: a `service_date` set more than 365 days after the
    property's current service date is refused with `ERR_SERVICE_DATE_OUT_OF_RANGE`
    (HTTP 409)."

    Design: Corner/validations/service_date_beyond_horizon_rejected
    """
    resort = fx.create_resort(name="Mason")
    version = resort["version"]
    response = api.create_day_pass(
        resort["id"],
        {
            "service_date": "2028-09-01",
            "units_requested": 1,
            "expected_resort_version": version,
        },
        fx.FRONT_DESK,
    )
    validate_error(response, ApiErrorId.ERR_SERVICE_DATE_OUT_OF_RANGE.value)


def test_the_horizon_gate_pre_empts_the_day_pass_ceiling(api):
    """PRD §2.4: "The remaining checks run in this order: the service-date horizon (`ERR_SERVICE_DATE_OUT_OF_RANGE`, which guards day-pass sales and group bookings, and fires when the requested `service_date` falls more than 365 days after the property's current service date); target state admissibility (`ERR_INVALID_STATE`, guarding every state-transition operation); pool posture (`ERR_POOL_CLOSED`, guarding gate admission posting and wristband activation); attraction readiness (`ERR_ATTRACTION_NOT_OPEN`, guarding gate admission posting and activity-session creation); physical plausibility of a submitted water reading (`ERR_WATER_QUALITY_OUT_OF_RANGE`); cabana overlap and capacity (`ERR_CABANA_DOUBLE_BOOKED` and `ERR_CABANA_UNITS_UNAVAILABLE`); the day-pass ceiling (`ERR_DAY_PASS_CAP_EXCEEDED`); the park capacity ceiling (`ERR_PARK_CAPACITY_EXCEEDED`); the arcade ceiling (`ERR_ARCADE_LIMIT_EXCEEDED`); the birthday-party minimum (`ERR_GROUP_MINIMUM_NOT_MET`); and finally the deposit requirement together with gateway acceptance (`ERR_PAYMENT_DECLINED`)."

    Design: Difficulty/priority_pair_validation_conflict/out_of_range_service_date_outranks_day_pass_cap
    """
    resort = fx.create_resort(name="Sandusky", park_capacity_occupancy_units=30, day_pass_cap_units=0)
    version = resort["version"]
    response = api.create_day_pass(
        resort["id"],
        {
            "service_date": "2027-10-01",
            "units_requested": 1,
            "expected_resort_version": version,
        },
        fx.FRONT_DESK,
    )
    validate_error(response, ApiErrorId.ERR_SERVICE_DATE_OUT_OF_RANGE.value)
    assert fx.get_capacity(resort["id"], "2027-10-01")["day_pass_reserved_units"] == 0
    assert validate_success(
        api.get_resort(resort["id"], fx.PLATFORM_OPS)
    )["day_pass_cap_units"] == 0


def test_a_stale_property_version_refuses_the_sale_and_commits_nothing(api):
    """PRD §2.9: "In each case, if the supplied value does not match the parent entity's current `version`, the request is refused before any resource is created: the mismatched day-pass sale is refused with `ERR_STALE_RESORT_VERSION` (HTTP 412) and the mismatched cabana hold with `ERR_STALE_CABANA_VERSION` (HTTP 412)."

    Design: Corner/errors/stale_resort_version_returns_412
    """
    resort = fx.create_resort(park_capacity_occupancy_units=20, day_pass_cap_units=10)
    stale_version = resort["version"]
    fx.create_day_pass(
        resort["id"],
        service_date="2026-09-03",
        units_requested=2,
        expected_resort_version=stale_version,
    )
    response = api.create_day_pass(
        resort["id"],
        {
            "service_date": "2026-09-03",
            "units_requested": 2,
            "expected_resort_version": stale_version,
        },
        fx.FRONT_DESK,
    )
    validate_error(response, ApiErrorId.ERR_STALE_RESORT_VERSION.value)
    assert fx.get_capacity(resort["id"], "2026-09-03")["day_pass_reserved_units"] == 2

def test_a_day_pass_with_no_reserved_units_left_cannot_be_admitted(api, gate_attendant_headers):
    """PRD §3.5: "A day pass presented when fewer reserved units remain than the
    presenting band consumes is refused with `ERR_DAY_PASS_UNITS_EXHAUSTED` (HTTP
    409)."

    Design: Difficulty/boundary_precision_check/day_pass_zero_units_remaining_rejects_admission
    """
    resort = fx.create_resort(name="Gurnee", park_capacity_occupancy_units=40,
                              day_pass_cap_units=20)
    fx.set_clock(resort["id"], "2026-09-03T08:00:00Z")
    room_type = fx.create_room_type(resort["id"])
    day_pass = fx.create_day_pass(resort["id"], service_date="2026-09-03", units_requested=6)
    band = fx.create_wristband(
        resort["id"], "DAY_PASS_GUEST", "Hana", day_pass_id=day_pass["id"],
        valid_on_service_date="2026-09-03",
    )
    reservation = fx.create_reservation(resort["id"], room_type["id"], guest_count=2)
    fx.check_in_reservation(resort["id"], reservation["id"])
    response = api.post_admission(
        resort["id"],
        {"wristband_id": band["id"], "service_date": "2026-09-03", "direction": "IN"},
        gate_attendant_headers,
    )
    assert response.status_code >= 400, "there are no reserved units left for this band"
    assert validate_success(
        api.get_wristband(resort["id"], band["id"], gate_attendant_headers)
    )["wristband_status"] == "REVOKED"


def test_an_abutting_cabana_window_carrying_a_stale_version_is_refused(api):
    """PRD §2.9: "In each case, if the supplied value does not match the parent entity's current `version`, the request is refused before any resource is created: the mismatched day-pass sale is refused with `ERR_STALE_RESORT_VERSION` (HTTP 412) and the mismatched cabana hold with `ERR_STALE_CABANA_VERSION` (HTTP 412)."

    Design: Difficulty/boundary_precision_check/cabana_second_hold_requires_fresh_version
    """
    resort = fx.create_resort(name="Concord", park_capacity_occupancy_units=30,
                              day_pass_cap_units=30)
    group_booking = fx.create_group_booking(
        resort["id"], group_kind="SCHOOL", member_count=2, deposit_paid_cents=1000
    )
    group_booking = fx.confirm_group_booking(resort["id"], group_booking["id"])
    cabana = fx.create_cabana(resort["id"], cabana_label="CAB-3", capacity_units=6)
    standing_version = cabana["version"]
    fx.hold_cabana(
        resort["id"], cabana["id"], group_booking["id"], member_units=2,
        start_minute=600, end_minute=660, expected_cabana_version=standing_version,
    )
    response = api.create_cabana_booking(
        resort["id"],
        {
            "cabana_id": cabana["id"],
            "group_booking_id": group_booking["id"],
            "service_date": "2026-09-03",
            "start_minute": 660,
            "end_minute": 720,
            "member_units": 1,
            "expected_cabana_version": standing_version - 1,
        },
        fx.group_headers_for(group_booking["id"]),
    )
    assert response.status_code >= 400, "an abutting hold still needs a fresh version"
    assert validate_success(
        api.get_cabana(resort["id"], cabana["id"], fx.PLATFORM_OPS)
    )["cabana_status"] == "HELD"


def test_the_horizon_gate_fires_without_committing_any_day_pass_units(api):
    """PRD §2.4: "Because compliance and safety checks sit above capacity checks in
    this list, a booking that would both breach a ceiling and clash with a standing
    closure reports the closure, not the ceiling."

    Design: Difficulty/priority_pair_validation_conflict/out_of_range_service_date_outranks_day_pass_cap
    """
    resort = fx.create_resort(name="Sandusky", park_capacity_occupancy_units=30,
                              day_pass_cap_units=0)
    response = api.create_day_pass(
        resort["id"],
        {
            "service_date": "2027-10-01",
            "units_requested": 1,
            "expected_resort_version": resort["version"],
        },
        fx.FRONT_DESK,
    )
    assert response.status_code == 409, "the daily horizon breach is a conflict"
    body = response.json()["data"]["error_id"]
    assert body == ApiErrorId.ERR_SERVICE_DATE_OUT_OF_RANGE.value
    assert body != ApiErrorId.ERR_DAY_PASS_CAP_EXCEEDED.value
    assert fx.get_capacity(resort["id"], "2027-10-01")["day_pass_reserved_units"] == 0
