"""The shape of the fulfillment centre's endpoint surface and who may drive it.

The site is described once and then only read: routes, dock bays, grid zones,
pick stations, the catalogue and the maintenance calendar are brought into
existence and read back, and nothing in the building can be edited in place or
deleted — every later change to a zone or a wave arrives through a named
operational action rather than through an update to the row itself, so a
freshly opened wave reads all of its derived figures at their documented zeros
and a freshly registered zone reads as OPERATIONAL with no accuracy score yet.
The audit lever is the one bulk payload the service accepts, and it counts a
whole zone in a single all-or-nothing call. Whatever refuses a request — a
grid zone identifier that names nothing, a page size beyond the hundredth
record, a maintenance window whose end precedes its start, a retrieval task
being bound to a tote from somebody else's wave — the refusal comes back in the
same envelope, carrying an error identifier and a human-readable message and
nothing whatsoever from the entity that was asked about. And the operator
population stays segregated: the site administrator owns the plant and the
capacity levers, the shopper owns their own basket, the planner forms and
dispatches waves, the pick operator drives totes and retrievals, the grid
engineer owns maintenance and audits, the catalogue is readable by all five,
and the planner who closed the picking floor on a wave is barred from being the
one who releases its van.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiError
from test_helpers.assertions import (
    assert_common_fields,
    assert_delivery_wave_shape,
    assert_dock_bay_shape,
    assert_field_absent_or_null,
    assert_grid_zone_shape,
    assert_instant_equals,
    assert_int_field,
    assert_inventory_sku_shape,
    assert_load_sequence,
    assert_maintenance_window_shape,
    assert_money,
    assert_order_statuses,
    assert_ratio,
    assert_sku_ledger,
    assert_station_status_matches_count,
    assert_status,
    assert_tote_shape,
    assert_version_is,
    assert_wave_posture,
    list_items_and_meta,
    read_object,
)
from test_helpers.constants import DEFAULT_CLOCK_UTC
from test_helpers.test_users import (
    EMPTY_ROLE_HEADERS,
    EMPTY_USER_ID_HEADERS,
    MISSING_ROLE_HEADERS,
    MISSING_USER_ID_HEADERS,
    NO_HEADERS,
    UNKNOWN_ROLE_HEADERS,
)
from test_helpers.types import (
    BillingStatus,
    FulfillmentStatus,
    GridZoneStatus,
    MaintenanceWindowStatus,
    PickStationStatus,
    PickTaskStatus,
    TemperatureZone,
    ToteStatus,
    WavePosture,
    WaveStatus,
)

#: The audit and maintenance calendar used by the infrastructure reads.
FIRST_WINDOW_START = "2026-08-10T01:00:00.000Z"
FIRST_WINDOW_END = "2026-08-10T03:00:00.000Z"
SECOND_WINDOW_START = "2026-08-10T04:00:00.000Z"
SECOND_WINDOW_END = "2026-08-10T06:00:00.000Z"

#: A second delivery window, far enough out that lead-time surge stays at zero.
LATER_SLOT_START = "2026-08-05T14:00:00.000Z"
LATER_SLOT_END = "2026-08-05T16:00:00.000Z"

#: The dock occupation the van is given while the wave is still forming.
LOAD_START = "2026-08-05T09:00:00.000Z"
LOAD_END = "2026-08-05T10:00:00.000Z"


def _refusal_body(response):
    """Read a refusal's raw envelope so its uniform shape can be inspected."""
    return response.json()


def _assert_uniform_refusal_envelope(response):
    """Every refusal answers in one envelope and leaks no entity fields."""
    body = _refusal_body(response)
    assert body["response_type"] == "error", (
        f"a refusal must carry response_type 'error', got {body['response_type']!r}"
    )
    payload = body["data"]
    assert set(payload) == {"error_id", "message"}, (
        f"a refusal payload carries exactly error_id and message, got {sorted(payload)}"
    )
    assert payload["message"].strip(), "a refusal must explain itself"
    meta = body["meta"]
    assert set(meta) == {"api_request_id", "api_request_timestamp"}, (
        "a refusal's meta carries only api_request_id and api_request_timestamp, "
        f"got {sorted(meta)}"
    )
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    for leaked in ("id", "created_at", "updated_at", "version"):
        assert leaked not in payload, f"a refusal must not leak {leaked}"


def test_grid_infrastructure_is_registered_once_and_only_ever_read_back(
    api, admin_headers, wave_planner_headers, grid_engineer_headers
):
    """A zone, a bay and its maintenance calendar are readable exactly as registered.

    Cites the requirement it rests on: "A newly registered zone is `OPERATIONAL`;
    both of its accuracy figures, `accuracy_score_unit_weighted` and
    `accuracy_score_sku_weighted`, are null until the zone has been audited at
    least once, as is `last_audited_at`."

    Design: Corner/endpoints/crud_surface_is_create_and_read_only_for_grid_infrastructure
    """
    zone = read_object(
        api.create_grid_zone(
            factories.grid_zone_payload(
                temperature_zone=TemperatureZone.AMBIENT.value, bot_count=4
            ),
            admin_headers,
        ),
        201,
    )
    bay = read_object(
        api.create_dock_bay(
            factories.dock_bay_payload(parallel_van_capacity=2), admin_headers
        ),
        201,
    )
    first_window = read_object(
        api.create_maintenance_window(
            factories.maintenance_window_payload(
                zone["id"],
                window_start=FIRST_WINDOW_START,
                window_end=FIRST_WINDOW_END,
            ),
            grid_engineer_headers,
        ),
        201,
    )
    second_window = read_object(
        api.create_maintenance_window(
            factories.maintenance_window_payload(
                zone["id"],
                window_start=SECOND_WINDOW_START,
                window_end=SECOND_WINDOW_END,
            ),
            grid_engineer_headers,
        ),
        201,
    )
    for created in (zone, bay, first_window, second_window):
        assert_common_fields(created)
        assert_version_is(created, 1)
        assert_instant_equals(
            created["updated_at"], created["created_at"], label="updated_at at birth"
        )

    read_zone = read_object(api.get_grid_zone(zone["id"], grid_engineer_headers), 200)
    assert_grid_zone_shape(read_zone)
    assert read_zone["id"] == zone["id"]
    assert read_zone["zone_code"] == zone["zone_code"]
    assert read_zone["temperature_zone"] == TemperatureZone.AMBIENT.value
    assert_int_field(read_zone, "bot_count", 4)
    assert_status(read_zone, GridZoneStatus.OPERATIONAL.value)
    assert_field_absent_or_null(read_zone, "accuracy_score_unit_weighted")
    assert_field_absent_or_null(read_zone, "accuracy_score_sku_weighted")
    assert_field_absent_or_null(read_zone, "last_audited_at")

    read_bay = read_object(api.get_dock_bay(bay["id"], wave_planner_headers), 200)
    assert_dock_bay_shape(read_bay)
    assert read_bay["id"] == bay["id"]
    assert read_bay["bay_code"] == bay["bay_code"]
    assert_int_field(read_bay, "parallel_van_capacity", 2)

    read_window = read_object(
        api.get_maintenance_window(second_window["id"], grid_engineer_headers), 200
    )
    assert_maintenance_window_shape(read_window)
    assert read_window["grid_zone_id"] == zone["id"]
    assert_instant_equals(read_window["window_start"], SECOND_WINDOW_START)
    assert_instant_equals(read_window["window_end"], SECOND_WINDOW_END)
    assert_status(read_window, MaintenanceWindowStatus.SCHEDULED.value)

    scheduled, meta = list_items_and_meta(
        api.list_maintenance_windows(
            grid_engineer_headers,
            params={
                "grid_zone_id": zone["id"],
                "status": MaintenanceWindowStatus.SCHEDULED.value,
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 2, "both windows on the zone are still scheduled"
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert {window["id"] for window in scheduled} == {
        first_window["id"],
        second_window["id"],
    }


def test_a_zone_count_is_written_whole_or_not_at_all(
    api, admin_headers, grid_engineer_headers
):
    """One unknown identifier in the counts array leaves every SKU uncounted.

    Cites the requirement it rests on: "Every named SKU must belong to the
    audited zone; an unknown SKU identifier is refused with
    `ERR_SKU_NOT_FOUND`."

    It also rests on: "For each SKU named in the payload, the SKU's
    `last_count_system_units` is set to that SKU's `physical_units` **as it
    stood immediately before this call**, `last_count_counted_units` is set to
    the submitted `counted_units`, and `last_count_variance_units` is set to the
    counted figure minus the system figure — so a physical surplus is positive
    and a shrink is negative."

    Design: Corner/endpoints/bulk_audit_counts_are_applied_all_or_nothing
    """
    ambient_zone = fixtures.create_grid_zone(
        api, temperature_zone=TemperatureZone.AMBIENT.value
    )
    chilled_zone = fixtures.create_grid_zone(
        api, temperature_zone=TemperatureZone.CHILLED.value
    )
    pasta = fixtures.create_inventory_sku(api, ambient_zone["id"], physical_units=10)
    penne = fixtures.create_inventory_sku(api, ambient_zone["id"], physical_units=10)
    cream = fixtures.create_inventory_sku(
        api,
        chilled_zone["id"],
        temperature_zone=TemperatureZone.CHILLED.value,
        physical_units=10,
    )

    rejected = api.record_audit_counts(
        ambient_zone["id"],
        factories.audit_counts_payload(
            [
                factories.audit_count_entry(pasta["id"], 9),
                factories.audit_count_entry(NON_EXISTENT_UUID, 5),
            ]
        ),
        grid_engineer_headers,
    )
    validate_error(rejected, ApiError.SKU_NOT_FOUND.value)

    untouched = fixtures.read_inventory_sku(api, pasta["id"])
    assert_inventory_sku_shape(untouched)
    assert_sku_ledger(untouched, physical_units=10, allocated_units=0, on_hand_units=10)
    assert_field_absent_or_null(untouched, "last_count_system_units")
    assert_field_absent_or_null(untouched, "last_count_counted_units")
    assert_field_absent_or_null(untouched, "last_count_variance_units")
    zone_before = fixtures.read_grid_zone(api, ambient_zone["id"])
    assert_status(zone_before, GridZoneStatus.OPERATIONAL.value)
    assert_field_absent_or_null(zone_before, "accuracy_score_unit_weighted")
    assert_field_absent_or_null(zone_before, "last_audited_at")

    fixtures.record_audit_counts(
        api, ambient_zone["id"], [(pasta["id"], 9), (penne["id"], 10)]
    )

    counted_pasta = fixtures.read_inventory_sku(api, pasta["id"])
    assert_int_field(counted_pasta, "last_count_system_units", 10)
    assert_int_field(counted_pasta, "last_count_counted_units", 9)
    assert_int_field(counted_pasta, "last_count_variance_units", -1)
    assert_sku_ledger(
        counted_pasta, physical_units=9, allocated_units=0, on_hand_units=9
    )
    counted_penne = fixtures.read_inventory_sku(api, penne["id"])
    assert_int_field(counted_penne, "last_count_system_units", 10)
    assert_int_field(counted_penne, "last_count_counted_units", 10)
    assert_int_field(counted_penne, "last_count_variance_units", 0)
    assert_sku_ledger(
        counted_penne, physical_units=10, allocated_units=0, on_hand_units=10
    )

    audited_zone = fixtures.read_grid_zone(api, ambient_zone["id"])
    assert_ratio(audited_zone, "accuracy_score_unit_weighted", 0.9500)
    assert_ratio(audited_zone, "accuracy_score_sku_weighted", 0.9500)
    assert_status(audited_zone, GridZoneStatus.AUDIT_HOLD.value)
    assert_instant_equals(audited_zone["last_audited_at"], DEFAULT_CLOCK_UTC)

    other_zone = fixtures.read_grid_zone(api, chilled_zone["id"])
    assert_status(other_zone, GridZoneStatus.OPERATIONAL.value)
    assert_field_absent_or_null(other_zone, "accuracy_score_unit_weighted")
    spared = fixtures.read_inventory_sku(api, cream["id"])
    assert_sku_ledger(spared, physical_units=10, allocated_units=0, on_hand_units=10)
    assert_field_absent_or_null(spared, "last_count_system_units")


def test_a_retrieval_task_binds_only_to_a_tote_of_its_own_wave(
    api, pick_operator_headers
):
    """A tote from another van's wave cannot receive this wave's retrieval.

    Cites the requirement it rests on: "The named tote must be `OPEN` and must
    belong to the same wave as the task."

    It also rests on: "Violation: `ERR_INVALID_STATE` (409). Applies to every
    action-style `POST` endpoint."

    Design: Corner/endpoints/assign_tote_links_a_task_only_to_a_tote_of_its_own_wave
    """
    plant = fixtures.build_plant(
        api,
        temperature_zone=TemperatureZone.AMBIENT.value,
        station={
            "temperature_zone_capability": [TemperatureZone.AMBIENT.value],
            "max_concurrent_totes": 3,
        },
    )
    route_id = plant["route"]["id"]
    station_id = plant["station"]["id"]
    pasta = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    early_slot = fixtures.create_delivery_slot(api, route_id, total_capacity_units=10)
    later_slot = fixtures.create_delivery_slot(
        api,
        route_id,
        window_start=LATER_SLOT_START,
        window_end=LATER_SLOT_END,
        total_capacity_units=10,
    )
    picking_here = fixtures.build_picking_wave(
        api, route_id, early_slot["id"], [pasta["id"]], ordered_qty=2, units=2
    )
    picking_elsewhere = fixtures.build_picking_wave(
        api, route_id, later_slot["id"], [pasta["id"]], ordered_qty=2, units=2
    )
    own_task = picking_here["tasks"][0]
    foreign_task = picking_elsewhere["tasks"][0]
    own_tote = fixtures.create_tote(
        api,
        picking_here["wave"]["id"],
        station_id,
        temperature_zone=TemperatureZone.AMBIENT.value,
    )
    foreign_tote = fixtures.create_tote(
        api,
        picking_elsewhere["wave"]["id"],
        station_id,
        temperature_zone=TemperatureZone.AMBIENT.value,
    )

    wrong_wave = api.assign_tote(
        own_task["id"],
        factories.assign_tote_payload(foreign_tote["id"]),
        pick_operator_headers,
    )
    validate_error(wrong_wave, ApiError.INVALID_STATE.value)

    no_such_tote = api.assign_tote(
        own_task["id"],
        factories.assign_tote_payload(NON_EXISTENT_UUID),
        pick_operator_headers,
    )
    validate_error(no_such_tote, ApiError.TOTE_NOT_FOUND.value)

    still_unbound = fixtures.read_pick_task(api, own_task["id"])
    assert_field_absent_or_null(still_unbound, "tote_id")
    assert_status(still_unbound, PickTaskStatus.QUEUED.value)
    assert_int_field(
        fixtures.read_tote(api, foreign_tote["id"]), "assigned_line_count", 0
    )

    bound = read_object(
        api.assign_tote(
            own_task["id"],
            factories.assign_tote_payload(own_tote["id"]),
            pick_operator_headers,
        ),
        200,
    )
    assert bound["tote_id"] == own_tote["id"]
    assert_status(bound, PickTaskStatus.QUEUED.value)

    filled_tote = fixtures.read_tote(api, own_tote["id"])
    assert_tote_shape(filled_tote)
    assert_int_field(filled_tote, "assigned_line_count", 1)
    assert_status(filled_tote, ToteStatus.OPEN.value)
    assert_int_field(
        fixtures.read_tote(api, foreign_tote["id"]), "assigned_line_count", 0
    )
    assert_field_absent_or_null(
        fixtures.read_pick_task(api, foreign_task["id"]), "tote_id"
    )

    bound_tasks, meta = list_items_and_meta(
        api.list_pick_tasks(
            pick_operator_headers,
            params={"tote_id": own_tote["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1, "only this wave's retrieval sits in the tote"
    assert [task["id"] for task in bound_tasks] == [own_task["id"]]

    station = fixtures.read_pick_station(api, station_id)
    assert_int_field(station, "current_tote_count", 2)
    assert_status(station, PickStationStatus.ACTIVE.value)
    assert_station_status_matches_count(station)


def test_a_freshly_opened_wave_reads_every_derived_figure_at_its_zero(
    api, wave_planner_headers
):
    """A wave that has just been opened carries an empty load list and no cost yet.

    Cites the requirement it rests on: "A newly opened wave has `status`
    `FORMING` and `posture` `OPEN`, an `order_count` and a `tote_count` of 0, an
    empty `load_sequence` array, a null `transport_cost_cents`, a null
    `consolidated_by_user_id`, and a null `dock_bay_id` with null `load_start`
    and `load_end`."

    Design: Corner/endpoints/computed_read_of_a_fresh_wave_returns_the_zeroed_derived_fields
    """
    plant = fixtures.build_plant(
        api,
        temperature_zone=TemperatureZone.AMBIENT.value,
        route={"per_km_cost_cents": 150},
    )
    route_id = plant["route"]["id"]
    pasta = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(api, route_id, total_capacity_units=10)
    confirmed = fixtures.build_confirmed_order(
        api, route_id, slot["id"], [pasta["id"]], ordered_qty=2, units=2
    )
    wave = fixtures.create_delivery_wave(api, route_id, slot["id"])

    fresh = read_object(api.get_delivery_wave(wave["id"], wave_planner_headers), 200)
    assert_delivery_wave_shape(fresh)
    assert_status(fresh, WaveStatus.FORMING.value)
    assert_wave_posture(fresh, WavePosture.OPEN.value)
    assert_int_field(fresh, "order_count", 0)
    assert_int_field(fresh, "tote_count", 0)
    assert fresh["load_sequence"] == [], "an unloaded wave carries the empty array"
    assert_field_absent_or_null(fresh, "transport_cost_cents")
    assert_field_absent_or_null(fresh, "dock_bay_id")
    assert_field_absent_or_null(fresh, "load_start")
    assert_field_absent_or_null(fresh, "load_end")
    assert_field_absent_or_null(fresh, "consolidated_by_user_id")

    fixtures.slot_order_into_wave(api, wave["id"], confirmed["order"]["id"])
    waved_order = fixtures.read_order(
        api, confirmed["account"]["id"], confirmed["order"]["id"]
    )
    assert_order_statuses(waved_order, fulfillment_status=FulfillmentStatus.WAVED.value)
    assert waved_order["wave_id"] == wave["id"]

    with_one_stop = read_object(
        api.get_delivery_wave(wave["id"], wave_planner_headers), 200
    )
    assert_int_field(with_one_stop, "order_count", 1)
    assert_status(with_one_stop, WaveStatus.FORMING.value)
    assert_wave_posture(with_one_stop, WavePosture.OPEN.value)
    assert_int_field(with_one_stop, "tote_count", 0)
    assert with_one_stop["load_sequence"] == []
    assert_field_absent_or_null(with_one_stop, "transport_cost_cents")

    forming, meta = list_items_and_meta(
        api.list_delivery_waves(
            wave_planner_headers,
            params={
                "route_id": route_id,
                "status": WaveStatus.FORMING.value,
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert [row["id"] for row in forming] == [wave["id"]]

    members, member_meta = list_items_and_meta(
        api.list_customer_orders(
            wave_planner_headers,
            params={"wave_id": wave["id"], "limit": 10, "offset": 0},
        )
    )
    assert member_meta["total_count"] == 1
    assert [order["id"] for order in members] == [confirmed["order"]["id"]]


def test_every_refusal_family_answers_in_the_same_envelope(
    api, admin_headers, grid_engineer_headers
):
    """A missing zone, an oversized page, a malformed body and an unresolved path all refuse alike.

    Cites the requirement it rests on: "The `meta` object for error responses
    contains only `api_request_id` and `api_request_timestamp`."

    It also rests on: "A `limit` outside the range 1 through 100 inclusive, or a
    negative `offset`, or either parameter supplied as something other than an
    integer, is rejected with `ERR_INVALID_PAGINATION` (HTTP 422)."

    Design: Corner/errors/error_envelope_is_uniform_across_the_status_families
    """
    zone = fixtures.create_grid_zone(
        api, temperature_zone=TemperatureZone.AMBIENT.value, bot_count=4
    )

    no_such_zone = api.get_grid_zone(NON_EXISTENT_UUID, grid_engineer_headers)
    validate_error(no_such_zone, ApiError.ZONE_NOT_FOUND.value)

    oversized_page = api.list_inventory_skus(
        grid_engineer_headers,
        params={"grid_zone_id": zone["id"], "limit": 101, "offset": 0},
    )
    validate_error(oversized_page, ApiError.INVALID_PAGINATION.value)

    inverted_window = api.create_maintenance_window(
        factories.maintenance_window_payload(
            zone["id"],
            window_start=FIRST_WINDOW_END,
            window_end=FIRST_WINDOW_START,
        ),
        grid_engineer_headers,
    )
    validate_error(inverted_window, ApiError.INVALID_REQUEST.value)

    stray_field = api.create_maintenance_window(
        factories.maintenance_window_payload(
            zone["id"],
            window_start=FIRST_WINDOW_START,
            window_end=FIRST_WINDOW_END,
            bot_count=4,
        ),
        grid_engineer_headers,
    )
    validate_error(stray_field, ApiError.INVALID_REQUEST.value)

    no_such_window = api.activate_maintenance_window(
        NON_EXISTENT_UUID, grid_engineer_headers
    )
    validate_error(no_such_window, ApiError.MAINTENANCE_WINDOW_NOT_FOUND.value)

    for refusal in (
        no_such_zone,
        oversized_page,
        inverted_window,
        stray_field,
        no_such_window,
    ):
        _assert_uniform_refusal_envelope(refusal)

    untouched = fixtures.read_grid_zone(api, zone["id"])
    assert_grid_zone_shape(untouched)
    assert_status(untouched, GridZoneStatus.OPERATIONAL.value)
    assert_field_absent_or_null(untouched, "last_audited_at")
    assert_version_is(untouched, 1)

    windows, meta = list_items_and_meta(
        api.list_maintenance_windows(
            grid_engineer_headers,
            params={"grid_zone_id": zone["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 0, "no refused window may have been written"
    assert windows == []


def test_each_role_drives_its_own_exclusive_lever_while_the_catalogue_reads_to_all(
    api,
    admin_headers,
    wave_planner_headers,
    pick_operator_headers,
    grid_engineer_headers,
    make_customer_headers,
):
    """Every operator group holds one write of its own while the catalogue stays open to all.

    Cites the requirement it rests on: "The Authorized Role(s) column lists the
    values of `X-User-Role` that clear the role gate for that endpoint; clearing
    the role gate is necessary but not sufficient, because the ownership and
    state rules described in §2.1, §2.7, §2.8 and §3 still apply."

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations
    """
    plant = fixtures.build_plant(
        api,
        temperature_zone=TemperatureZone.AMBIENT.value,
        route={"base_delivery_fee_cents": 599, "per_km_cost_cents": 150},
        station={
            "temperature_zone_capability": [TemperatureZone.AMBIENT.value],
            "max_concurrent_totes": 3,
        },
    )
    route_id = plant["route"]["id"]
    station_id = plant["station"]["id"]
    second_zone = fixtures.create_grid_zone(
        api, temperature_zone=TemperatureZone.AMBIENT.value, bot_count=4
    )
    pasta = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    first_slot = fixtures.create_delivery_slot(api, route_id, total_capacity_units=10)
    second_slot = fixtures.create_delivery_slot(
        api,
        route_id,
        window_start=LATER_SLOT_START,
        window_end=LATER_SLOT_END,
        total_capacity_units=10,
    )
    picking = fixtures.build_picking_wave(
        api, route_id, first_slot["id"], [pasta["id"]], ordered_qty=2, units=2
    )
    shopper_headers = make_customer_headers(picking["account"]["id"])

    bay = read_object(
        api.create_dock_bay(
            factories.dock_bay_payload(parallel_van_capacity=1), admin_headers
        ),
        201,
    )
    assert_dock_bay_shape(bay)
    assert_int_field(bay, "parallel_van_capacity", 1)

    second_basket = read_object(
        api.create_customer_order(
            factories.customer_order_payload(stop_distance_km=9.00), shopper_headers
        ),
        201,
    )
    assert_order_statuses(
        second_basket, fulfillment_status=FulfillmentStatus.DRAFT.value
    )

    second_wave = read_object(
        api.create_delivery_wave(
            factories.delivery_wave_payload(route_id, second_slot["id"]),
            wave_planner_headers,
        ),
        201,
    )
    assert_delivery_wave_shape(second_wave)
    assert_status(second_wave, WaveStatus.FORMING.value)
    assert_wave_posture(second_wave, WavePosture.OPEN.value)

    window = read_object(
        api.create_maintenance_window(
            factories.maintenance_window_payload(
                second_zone["id"],
                window_start=FIRST_WINDOW_START,
                window_end=FIRST_WINDOW_END,
            ),
            grid_engineer_headers,
        ),
        201,
    )
    assert_maintenance_window_shape(window)
    assert_status(window, MaintenanceWindowStatus.SCHEDULED.value)

    tote = read_object(
        api.create_tote(
            factories.tote_payload(
                picking["wave"]["id"],
                station_id,
                temperature_zone=TemperatureZone.AMBIENT.value,
            ),
            pick_operator_headers,
        ),
        201,
    )
    assert_tote_shape(tote)
    assert_status(tote, ToteStatus.OPEN.value)
    assert_int_field(tote, "assigned_line_count", 0)

    for reader in (
        admin_headers,
        wave_planner_headers,
        pick_operator_headers,
        grid_engineer_headers,
        shopper_headers,
    ):
        catalogue, meta = list_items_and_meta(
            api.list_inventory_skus(
                reader,
                params={
                    "grid_zone_id": plant["zone"]["id"],
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 1, (
            f"the catalogue is readable by {reader['X-User-Role']}"
        )
        assert [row["id"] for row in catalogue] == [pasta["id"]]
        assert_inventory_sku_shape(catalogue[0])

    station = fixtures.read_pick_station(api, station_id)
    assert_int_field(station, "current_tote_count", 1)
    assert_status(station, PickStationStatus.ACTIVE.value)
    assert_station_status_matches_count(station)


def test_absent_empty_or_unheard_of_credentials_are_refused_first(
    api, make_customer_headers
):
    """A basket write with no usable credentials is turned away before its body is read.

    Cites the requirement it rests on: "If either header is absent or present but
    empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before
    anything else is examined."

    It also rests on: "If `X-User-Role` carries a string that is not one of the
    five role names defined below, the request is rejected with
    `ERR_UNKNOWN_ROLE` (HTTP 401)."

    Design: Corner/rbac/auth_ladder_walks_unauthenticated_then_unknown_role_then_forbidden_then_identity
    """
    plant = fixtures.build_plant(
        api,
        temperature_zone=TemperatureZone.AMBIENT.value,
        route={"base_delivery_fee_cents": 599, "per_km_cost_cents": 150},
    )
    pasta = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    ada = fixtures.build_shopper_with_basket(
        api, plant["route"]["id"], [pasta["id"]], ordered_qty=2
    )
    line_payload = factories.order_line_payload(pasta["id"], ordered_qty=2)

    for label, headers in (
        ("neither header", NO_HEADERS),
        ("no acting principal", MISSING_USER_ID_HEADERS),
        ("no acting role", MISSING_ROLE_HEADERS),
        ("an empty principal", EMPTY_USER_ID_HEADERS),
        ("an empty role", EMPTY_ROLE_HEADERS),
    ):
        refused = api.add_order_line(ada["order"]["id"], line_payload, headers)
        validate_error(refused, ApiError.UNAUTHENTICATED.value)
        _assert_uniform_refusal_envelope(refused)
        assert refused.json()["data"]["error_id"] == ApiError.UNAUTHENTICATED.value, (
            f"a request carrying {label} is unauthenticated before anything else"
        )

    unheard_of = api.add_order_line(
        ada["order"]["id"], line_payload, UNKNOWN_ROLE_HEADERS
    )
    validate_error(unheard_of, ApiError.UNKNOWN_ROLE.value)
    _assert_uniform_refusal_envelope(unheard_of)

    intact = fixtures.read_order(api, ada["account"]["id"], ada["order"]["id"])
    assert_money(intact, "merchandise_subtotal_cents", 1400)
    lines, meta = list_items_and_meta(
        api.list_order_lines(
            make_customer_headers(ada["account"]["id"]),
            params={"order_id": ada["order"]["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1, "no refused write may have added a line"
    assert [line["id"] for line in lines] == [ada["lines"][0]["id"]]


def test_the_role_identity_and_ownership_gates_refuse_in_that_order(
    api, wave_planner_headers, unknown_customer_headers, make_customer_headers
):
    """An unlisted role, an unresolvable shopper and a stranger are each refused on their own ground.

    Cites the requirement it rests on: "Concretely, a `Customer` whose
    `X-User-ID` does not resolve to any existing `CustomerAccount` is rejected
    with `ERR_CUSTOMER_IDENTITY_UNKNOWN` (HTTP 403), and a `Customer` acting on a
    `CustomerOrder` — directly, or indirectly through one of its `OrderLine` rows
    or `SlotBooking` rows — whose `customer_id` differs from `X-User-ID` is
    rejected with `ERR_ORDER_NOT_OWNED` (HTTP 403)."

    It also rests on: "If the role is recognised but is not among the roles
    authorised for the target endpoint in §4, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/auth_ladder_walks_unauthenticated_then_unknown_role_then_forbidden_then_identity
    """
    plant = fixtures.build_plant(
        api,
        temperature_zone=TemperatureZone.AMBIENT.value,
        route={"base_delivery_fee_cents": 599, "per_km_cost_cents": 150},
    )
    route_id = plant["route"]["id"]
    pasta = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    ada = fixtures.build_shopper_with_basket(
        api, route_id, [pasta["id"]], ordered_qty=2
    )
    bo = fixtures.create_customer_account(api, route_id)
    line_payload = factories.order_line_payload(pasta["id"], ordered_qty=2)

    wrong_role = api.add_order_line(
        ada["order"]["id"], line_payload, wave_planner_headers
    )
    validate_error(wrong_role, ApiError.FORBIDDEN_ROLE.value)
    _assert_uniform_refusal_envelope(wrong_role)

    no_such_shopper = api.add_order_line(
        ada["order"]["id"], line_payload, unknown_customer_headers
    )
    validate_error(no_such_shopper, ApiError.CUSTOMER_IDENTITY_UNKNOWN.value)
    _assert_uniform_refusal_envelope(no_such_shopper)

    stranger = api.add_order_line(
        ada["order"]["id"], line_payload, make_customer_headers(bo["id"])
    )
    validate_error(stranger, ApiError.ORDER_NOT_OWNED.value)
    _assert_uniform_refusal_envelope(stranger)

    owner_headers = make_customer_headers(ada["account"]["id"])
    intact = fixtures.read_order(api, ada["account"]["id"], ada["order"]["id"])
    assert_money(intact, "merchandise_subtotal_cents", 1400)
    assert_order_statuses(intact, fulfillment_status=FulfillmentStatus.DRAFT.value)
    lines, meta = list_items_and_meta(
        api.list_order_lines(
            owner_headers,
            params={"order_id": ada["order"]["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1, "three refusals left the basket as it was"
    assert [line["id"] for line in lines] == [ada["lines"][0]["id"]]


def test_the_planner_who_closed_the_picking_floor_may_not_release_the_van(
    api, wave_planner_headers, second_wave_planner_headers
):
    """Releasing the van demands a second pair of hands from the one that consolidated it.

    Cites the requirement it rests on: "Dispatching that same wave requires the
    acting `X-User-ID` to be a *different* string; if the two match, the dispatch
    is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/the_planner_who_consolidated_a_wave_cannot_also_dispatch_it
    """
    plant = fixtures.build_plant(
        api,
        temperature_zone=TemperatureZone.AMBIENT.value,
        route={"base_delivery_fee_cents": 599, "per_km_cost_cents": 150},
        bay={"parallel_van_capacity": 1},
        station={
            "temperature_zone_capability": [TemperatureZone.AMBIENT.value],
            "max_concurrent_totes": 3,
        },
    )
    route_id = plant["route"]["id"]
    pasta = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(api, route_id, total_capacity_units=10)
    waved = fixtures.build_waved_order(
        api,
        route_id,
        slot["id"],
        [pasta["id"]],
        ordered_qty=2,
        units=2,
        stop_distance_km=5.00,
    )
    wave_id = waved["wave"]["id"]
    order_id = waved["order"]["id"]
    account_id = waved["account"]["id"]

    fixtures.assign_dock(api, wave_id, plant["bay"]["id"], LOAD_START, LOAD_END)
    fixtures.start_picking(api, wave_id)
    task = fixtures.pick_tasks_for_wave(api, wave_id)[0]
    tote = fixtures.create_tote(
        api,
        wave_id,
        plant["station"]["id"],
        temperature_zone=TemperatureZone.AMBIENT.value,
    )
    fixtures.assign_tote(api, task["id"], tote["id"])
    fixtures.start_retrieval(api, task["id"])
    fixtures.complete_pick_task(api, task["id"], 2)
    fixtures.seal_tote(api, tote["id"])
    fixtures.consolidate_wave(api, wave_id, headers=wave_planner_headers)
    fixtures.compute_loading_sequence(api, wave_id, headers=wave_planner_headers)

    loading = fixtures.read_wave(api, wave_id)
    assert loading["consolidated_by_user_id"] == wave_planner_headers["X-User-ID"], (
        "consolidating stamps the acting planner onto the wave"
    )
    assert_status(loading, WaveStatus.LOADING.value)
    assert_load_sequence(loading, [tote["id"]])
    assert_money(loading, "transport_cost_cents", 750)

    same_hands = api.dispatch_wave(wave_id, wave_planner_headers)
    validate_error(same_hands, ApiError.SEGREGATION_OF_DUTIES.value)
    _assert_uniform_refusal_envelope(same_hands)

    still_loading = fixtures.read_wave(api, wave_id)
    assert_status(still_loading, WaveStatus.LOADING.value)
    assert_load_sequence(still_loading, [tote["id"]])
    held_order = fixtures.read_order(api, account_id, order_id)
    assert_order_statuses(
        held_order,
        fulfillment_status=FulfillmentStatus.LOADED.value,
        billing_status=BillingStatus.AUTHORIZED.value,
    )
    assert_field_absent_or_null(held_order, "captured_amount_cents")

    released = read_object(
        api.dispatch_wave(wave_id, second_wave_planner_headers), 200
    )
    assert_delivery_wave_shape(released)
    assert_status(released, WaveStatus.DISPATCHED.value)
    assert released["consolidated_by_user_id"] == wave_planner_headers["X-User-ID"]

    dispatched_order = fixtures.read_order(api, account_id, order_id)
    assert_order_statuses(
        dispatched_order,
        fulfillment_status=FulfillmentStatus.DISPATCHED.value,
        billing_status=BillingStatus.CAPTURED.value,
    )
    assert_money(dispatched_order, "captured_amount_cents", 1999)
    assert_money(dispatched_order, "order_total_cents", 1999)
    assert_status(fixtures.read_tote(api, tote["id"]), ToteStatus.LOADED.value)
