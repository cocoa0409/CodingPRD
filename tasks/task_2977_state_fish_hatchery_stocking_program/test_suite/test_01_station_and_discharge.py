"""
Standing up a station and keeping its discharge record.

Covers registration and the ledgers it seeds, reading a station back, the
uniqueness of a station code, the self-classification of a discharge sample, the
sub-resource that lists those samples, the immediacy of the derived station
figures, and the compliance freeze a second exceedance triggers.
"""

from test_helpers import (
    ADMIN_HEADERS,
    NON_EXISTENT_UUID,
    assert_appropriation_ledger,
    assert_common_fields,
    assert_descending_by,
    assert_female_ledger,
    assert_integer_equals,
    assert_no_revision_fields,
    assert_number_equals,
    assert_water_right_ledger,
    ids_of,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as err
from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures as fx


def test_registration_seeds_every_ledger_at_rest(api):
    """
    A newly registered station reports its full derived field set.

    PRD 3.1: "Registration seeds all three ledgers at rest. `water_reserved_af`
    and `water_used_af` both start at zero, so `water_available_af` starts equal
    to `annual_water_right_af`. `biomass_on_hand_lbs` starts at zero and
    `density_index` at zero. `exceedance_count_rolling` starts at zero and
    `operating_posture` at `OPEN`. `budget_committed_cents` and
    `budget_spent_cents` both start at zero, so `budget_available_cents` starts
    equal to `annual_budget_cents`."

    Design: Corner/entities/hatchery_creation_returns_the_full_computed_field_set
    """
    payload = f.hatchery_payload(
        name="Silver Creek Hatchery",
        annual_water_right_af=120.0,
        rearing_capacity_lbs=2000.0,
        oxygen_supply_lpm=6.0,
        tss_permit_limit_mg_l=20.0,
        annual_budget_cents=50000000,
    )
    station = validate_success(api.create_hatchery(payload, ADMIN_HEADERS), 201)

    assert_common_fields(station, expected_version=1)
    assert station["name"] == "Silver Creek Hatchery"
    assert station["station_code"] == payload["station_code"]
    assert station["water_source_type"] == k.WATER_SOURCE_SPRING

    assert_number_equals(station["water_reserved_af"], 0.0, 4, "water_reserved_af")
    assert_number_equals(station["water_used_af"], 0.0, 4, "water_used_af")
    assert_number_equals(station["water_available_af"], 120.0, 4, "water_available_af")
    assert_water_right_ledger(station)

    assert_integer_equals(station["budget_committed_cents"], 0, "budget_committed_cents")
    assert_integer_equals(station["budget_spent_cents"], 0, "budget_spent_cents")
    assert_integer_equals(
        station["budget_available_cents"], 50000000, "budget_available_cents"
    )
    assert_appropriation_ledger(station)

    assert_number_equals(station["biomass_on_hand_lbs"], 0.0, 2, "biomass_on_hand_lbs")
    assert_number_equals(station["density_index"], 0.0, 4, "density_index")
    assert_integer_equals(
        station["exceedance_count_rolling"], 0, "exceedance_count_rolling"
    )
    assert station["operating_posture"] == k.POSTURE_OPEN


def test_station_reads_back_to_its_own_manager(api):
    """
    The station's own manager may read the station, addressing it with the
    station's own id.

    PRD 3.1: "the new station's `id` is the value a `HatcheryManager` must present
    as `X-User-ID` in order to act on that station's records."

    Design: Corner/entities/hatchery_retrieval_returns_the_stored_row_to_its_own_manager
    """
    ctx = fx.station_at_rest(api)
    station = ctx["hatchery"]

    fetched = validate_success(api.get_hatchery(station["id"], ctx["manager"]), 200)

    assert fetched["id"] == station["id"]
    assert fetched["station_code"] == station["station_code"]
    assert fetched["operating_posture"] == k.POSTURE_OPEN
    assert_number_equals(
        fetched["water_available_af"],
        station["annual_water_right_af"],
        4,
        "water_available_af",
    )
    assert_common_fields(fetched, expected_version=1)


def test_unknown_station_id_reports_the_stations_own_404(api):
    """
    A station id that resolves to nothing produces the stations collection's own
    404 rather than any other error.

    PRD 2.11: "An identifier in the URL path is resolved against the collection
    the path addresses, and a value that resolves to nothing produces that
    collection's own 404: `ERR_HATCHERY_NOT_FOUND`, `ERR_WATER_NOT_FOUND`,
    `ERR_BROOD_STOCK_NOT_FOUND`, `ERR_SPAWN_EVENT_NOT_FOUND`,
    `ERR_LOT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`,
    `ERR_PLAN_NOT_FOUND`, `ERR_TRANSPORT_UNIT_NOT_FOUND` or
    `ERR_EVENT_NOT_FOUND`."

    Design: Corner/entities/hatchery_id_that_does_not_exist_returns_not_found
    """
    response = api.get_hatchery(NON_EXISTENT_UUID, ADMIN_HEADERS)

    validate_error(response, err.ERR_HATCHERY_NOT_FOUND, 404)


def test_discharge_sample_carries_no_version_and_no_updated_at(api):
    """
    A discharge sample is the one record type with neither revision field.

    PRD 3.1: "A discharge sample is a permanent record. There is no operation
    that edits or deletes one, it carries no `version` and no `updated_at`, and
    its classification is final at the moment it is written."

    Design: Corner/entities/effluent_reading_is_immutable_and_carries_no_version
    """
    ctx = fx.station_at_rest(api)

    reading = validate_success(
        api.create_effluent_reading(
            f.effluent_reading_payload(
                ctx["hatchery"]["id"],
                sampled_at=f.instant(2026, 7, 31, 6),
                tss_mg_l=10.0,
                total_phosphorus_mg_l=0.05,
                flow_af=1.0,
            ),
            ctx["manager"],
        ),
        201,
    )

    assert_no_revision_fields(reading)
    assert reading["hatchery_id"] == ctx["hatchery"]["id"]
    assert reading["status"] == k.EFFLUENT_COMPLIANT


def test_second_station_reusing_a_station_code_is_refused(api):
    """
    A station code must be unique across every station on file.

    PRD 3.1: "The `station_code` is a four-character code drawn only from
    uppercase letters and digits, and it must be unique across every station on
    file — a duplicate is refused with `ERR_DUPLICATE_STATION_CODE` (HTTP 409)."

    Design: Corner/errors/duplicate_station_code_is_refused_on_the_second_hatchery
    """
    first = validate_success(
        api.create_hatchery(f.hatchery_payload(station_code="SLVC"), ADMIN_HEADERS), 201
    )
    assert first["station_code"] == "SLVC"

    response = api.create_hatchery(
        f.hatchery_payload(name="Copycat Hatchery", station_code="SLVC"), ADMIN_HEADERS
    )

    validate_error(response, err.ERR_DUPLICATE_STATION_CODE, 409)


def test_sample_exactly_on_both_limits_is_compliant_with_a_zero_margin(api):
    """
    Both discharge comparisons are strictly greater, so a sample sitting exactly
    on the permit limit and exactly on the phosphorus limit is compliant.

    PRD 3.1: "A sample landing exactly on either limit is `COMPLIANT`, because
    both comparisons are strictly greater. Alongside the classification the
    service records `exceedance_margin_mg_l`, which is the amount by which
    `tss_mg_l` overshot the station's ceiling, floored at zero so that a
    compliant sample records a margin of zero, and rounded to three decimal
    places."

    Design: Corner/calculations/effluent_sample_exactly_at_the_permit_limit_is_compliant
    """
    ctx = fx.station_at_rest(api, tss_permit_limit_mg_l=20.0)

    reading = validate_success(
        api.create_effluent_reading(
            f.effluent_reading_payload(
                ctx["hatchery"]["id"],
                sampled_at=f.instant(2026, 7, 31, 6),
                tss_mg_l=20.0,
                total_phosphorus_mg_l=0.10,
                flow_af=1.5,
            ),
            ctx["manager"],
        ),
        201,
    )

    assert reading["status"] == k.EFFLUENT_COMPLIANT
    assert_number_equals(
        reading["exceedance_margin_mg_l"], 0.0, 3, "exceedance_margin_mg_l"
    )

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_integer_equals(
        station["exceedance_count_rolling"], 0, "exceedance_count_rolling"
    )
    assert station["operating_posture"] == k.POSTURE_OPEN


def test_effluent_sub_resource_lists_newest_first_and_filters_by_status(api):
    """
    The station's discharge log is a sub-resource ordered newest sample first,
    and its optional status filter narrows `total_count` itself.

    PRD 3.1: "The station's own manager and a `ProgramAdmin` may read a station's
    samples back as a list, newest sample first, optionally filtered by
    `status`; a manager reading another station's samples is refused with
    `ERR_HATCHERY_SCOPE_VIOLATION`."

    Design: Corner/endpoints/effluent_sub_resource_lists_newest_first_and_filters_by_status
    """
    ctx = fx.station_at_rest(api, annual_water_right_af=120.0, tss_permit_limit_mg_l=20.0)
    station, manager = ctx["hatchery"], ctx["manager"]

    compliant = fx.log_effluent_reading(
        api,
        station,
        sampled_at=f.instant(2026, 7, 31, 6),
        tss_mg_l=20.0,
        total_phosphorus_mg_l=0.08,
        flow_af=1.5,
    )
    exceedance = fx.log_effluent_reading(
        api,
        station,
        sampled_at=f.instant(2026, 7, 31, 12),
        tss_mg_l=26.5,
        total_phosphorus_mg_l=0.08,
        flow_af=1.5,
    )
    assert compliant["status"] == k.EFFLUENT_COMPLIANT
    assert exceedance["status"] == k.EFFLUENT_EXCEEDANCE

    filtered, meta = validate_paginated(
        api.list_hatchery_effluent_readings(
            station["id"], manager, {"status": k.EFFLUENT_EXCEEDANCE}
        )
    )
    assert meta["total_count"] == 1, meta
    assert meta["has_more"] is False
    assert meta["limit"] == k.DEFAULT_LIMIT
    assert meta["offset"] == 0
    assert ids_of(filtered) == [exceedance["id"]]
    assert_number_equals(
        filtered[0]["exceedance_margin_mg_l"], 6.5, 3, "exceedance_margin_mg_l"
    )

    everything, meta_all = validate_paginated(
        api.list_hatchery_effluent_readings(station["id"], manager)
    )
    assert meta_all["total_count"] == 2, meta_all
    assert ids_of(everything) == [exceedance["id"], compliant["id"]]
    assert_descending_by(everything, "sampled_at")

    after = fx.read_hatchery(api, station)
    assert_number_equals(after["water_used_af"], 3.0, 4, "water_used_af")
    assert_number_equals(after["water_available_af"], 117.0, 4, "water_available_af")
    assert_integer_equals(
        after["exceedance_count_rolling"], 1, "exceedance_count_rolling"
    )
    assert after["operating_posture"] == k.POSTURE_RESTRICTED


def test_immediate_consistency_shows_the_recomputed_station_in_the_same_call(api):
    """
    A feeding's own 200 response already carries the recomputed lot figures, and
    the station read immediately afterwards already shows the derived biomass and
    density.

    PRD 3.4: "Two consequences of a feeding reach beyond the lot. First, the
    station's `biomass_on_hand_lbs`, `density_index` and `operating_posture` are
    all recomputed, which is how feeding a growing lot restricts a station and
    how the mortality in a feeding relaxes it."

    Design: Corner/consistency_model/immediate_consistency_shows_the_recomputed_station_in_the_same_call
    """
    ctx = fx.lot_at_egg(api)
    station, lot = ctx["hatchery"], ctx["lot"]
    assert_integer_equals(lot["count_on_hand"], 20000, "count_on_hand")

    feeding = validate_success(
        api.record_feeding(
            lot["id"],
            f.feeding_payload(
                fed_at=f.instant(2026, 8, 10, 12),
                feed_lbs=100.0,
                avg_weight_g_after=3.99,
                mortality_count=0,
            ),
            ctx["manager"],
        ),
        200,
    )

    assert_number_equals(feeding["biomass_lbs"], 175.93, 2, "biomass_lbs")
    assert_number_equals(feeding["cumulative_feed_lbs"], 100.0, 2, "cumulative_feed_lbs")
    assert_number_equals(feeding["fcr_biological"], 0.583, 3, "fcr_biological")

    station_now = fx.read_hatchery(api, station)
    assert_number_equals(
        station_now["biomass_on_hand_lbs"], 175.93, 2, "biomass_on_hand_lbs"
    )
    assert_number_equals(station_now["density_index"], 0.0880, 4, "density_index")

    lot_now = fx.read_lot(api, station, lot["id"])
    assert_number_equals(lot_now["biomass_lbs"], 175.93, 2, "biomass_lbs")
    assert_integer_equals(lot_now["version"], 2, "version")


def test_second_exceedance_freezes_the_station_and_cascades_to_the_planned_take(api):
    """
    A discharge sample walks four links: the reading classifies itself, the
    station freezes, its `SPAWNING` brood group suspends, and that group's
    `PLANNED` egg take cancels.

    PRD 2.6: "When a station becomes `FROZEN` — whether from `OPEN` or from
    `RESTRICTED` — every brood group of that station in `SPAWNING` status
    transitions to `SUSPENDED`, and because each of those groups is now
    suspended, each of its spawn events still in `PLANNED` status transitions to
    `CANCELLED`, returning that event's committed females to the group's
    available pool and that event's reserved acre-feet to the station's available
    water."

    Design: Difficulty/transitive_cascade/effluent_exceedance_freezes_production_and_returns_reservations
    """
    ctx = fx.spawning_group(
        api, {"annual_water_right_af": 120.0, "tss_permit_limit_mg_l": 20.0}
    )
    station, brood_stock, manager = ctx["hatchery"], ctx["brood_stock"], ctx["manager"]
    spawn_event = fx.create_spawn_event(api, station, brood_stock)
    assert spawn_event["status"] == k.SPAWN_PLANNED

    first = fx.log_exceedance(
        api, station, sampled_at=f.instant(2026, 8, 1), tss_mg_l=26.5, flow_af=0.5
    )
    assert first["status"] == k.EFFLUENT_EXCEEDANCE
    assert_number_equals(
        first["exceedance_margin_mg_l"], 6.5, 3, "exceedance_margin_mg_l"
    )
    assert (
        fx.read_hatchery(api, station)["operating_posture"] == k.POSTURE_RESTRICTED
    )

    second = validate_success(
        api.create_effluent_reading(
            f.effluent_reading_payload(
                station["id"],
                sampled_at=f.instant(2026, 8, 1),
                tss_mg_l=30.0,
                total_phosphorus_mg_l=0.05,
                flow_af=0.5,
            ),
            manager,
        ),
        201,
    )

    assert second["status"] == k.EFFLUENT_EXCEEDANCE
    assert_number_equals(
        second["exceedance_margin_mg_l"], 10.0, 3, "exceedance_margin_mg_l"
    )

    frozen = fx.read_hatchery(api, station)
    assert_integer_equals(
        frozen["exceedance_count_rolling"], 2, "exceedance_count_rolling"
    )
    assert frozen["operating_posture"] == k.POSTURE_FROZEN

    assert (
        fx.read_brood_stock(api, station, brood_stock["id"])["status"]
        == k.BROOD_SUSPENDED
    )
    cancelled = validate_success(
        api.get_spawn_event(spawn_event["id"], manager), 200
    )
    assert cancelled["status"] == k.SPAWN_CANCELLED


def test_the_freeze_cascade_returns_the_reserved_acre_feet_and_females(api):
    """
    The far end of the freeze cascade is a pair of restored ledgers: the females
    the cancelled take had committed and the acre-feet it had reserved come back.

    PRD 2.5: "Planning a take reserves acre-feet; cancelling that planned take
    returns exactly the same acre-feet; recording the take converts reserved
    acre-feet into used acre-feet. The identity — adjudicated right equals
    available plus reserved plus used — holds after the reservation, after the
    cancellation, and after the conversion."

    Design: Difficulty/transitive_cascade/effluent_exceedance_freezes_production_and_returns_reservations
    """
    ctx = fx.spawning_group(
        api, {"annual_water_right_af": 120.0, "tss_permit_limit_mg_l": 20.0}
    )
    station, brood_stock = ctx["hatchery"], ctx["brood_stock"]
    spawn_event = fx.create_spawn_event(api, station, brood_stock)
    assert_number_equals(spawn_event["water_reserved_af"], 3.0, 4, "water_reserved_af")

    reserved = fx.read_brood_stock(api, station, brood_stock["id"])
    assert_integer_equals(reserved["females_reserved"], 20, "females_reserved")
    assert_integer_equals(reserved["females_available"], 380, "females_available")

    fx.freeze_station(api, station, f.instant(2026, 8, 1), f.instant(2026, 8, 1))

    released = fx.read_brood_stock(api, station, brood_stock["id"])
    assert_integer_equals(released["females_reserved"], 0, "females_reserved")
    assert_integer_equals(released["females_spent"], 0, "females_spent")
    assert_integer_equals(released["females_available"], 400, "females_available")
    assert_female_ledger(released)

    after = fx.read_hatchery(api, station)
    assert_number_equals(after["water_reserved_af"], 0.0, 4, "water_reserved_af")
    assert_number_equals(after["water_used_af"], 1.0, 4, "water_used_af")
    assert_number_equals(after["water_available_af"], 119.0, 4, "water_available_af")
    assert_water_right_ledger(after)
