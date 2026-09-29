"""Queue B - corner section ``endpoints``.

Six instances covering the shapes the endpoint table promises rather than the
business rules behind them: create/read/list agreement on a placement cycle, the
pagination defaults of §2.3, an action endpoint that returns 200 with the
mutated resource, a path-scoped subresource list, a read-only computed
projection, and the money-free branch of the void action.

Two rendering conventions apply to the PRD quotations in the docstrings below:
the PRD's em dashes are written as ASCII hyphens and its transition arrows as
``->``.  Nothing else is altered, so every quoted sentence is greppable in
``workspace/PRD.md`` once those two substitutions are made.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_common_fields,
    assert_fields_present,
    assert_light_fields,
    assert_pagination_meta,
    assert_server_minted_id,
    assert_subset_equal,
    ids_of,
)
from test_helpers.constants import (
    ACCESS_MODE_EMBARGOED,
    ACCESS_MODE_GATE_CONTROLLED,
    ACCESS_MODE_OPEN,
    BASIS_ACTUAL,
    BILLING_UNBILLED,
    CHANNEL_EDI,
    CHANNEL_FAX,
    CHARGE_FINAL,
    CHARGE_KIND_DEMURRAGE,
    CHARGE_PROVISIONAL,
    CLOCK_BASIS_NONE,
    COLD_START_CLOCK,
    CYCLE_A_CHARGEABLE_DAYS,
    CYCLE_A_GROSS_CENTS,
    CYCLE_A_NOTICE_SENT_AT,
    CYCLE_A_RELEASE_AT,
    DEFAULT_CAR_SPOT_CAPACITY,
    DEFAULT_GATE_CLOSE_HOUR,
    DELIVERY_DELIVERED,
    DELIVERY_FAILED,
    FACILITY_KIND_INDUSTRY_TRACK,
    MOVEMENT_ORDERED,
    MOVEMENT_RELEASED,
    MOVEMENT_VOIDED,
    OWNERSHIP_PRIVATE,
    OWNERSHIP_RAILROAD_OWNED,
)
from test_helpers.test_users import ADMIN, AGENT

# --- the pagination defaults the service must supply for itself -------------
DEFAULT_LIMIT = 10
DEFAULT_OFFSET = 0

# --- the two access-mode reasons -------------------------------------------
NIGHT_GATE_REASON = "Night gate staffing only."
DERAILMENT_REASON = "Derailment on the lead."

FACILITY_FIELDS = (
    "id",
    "facility_code",
    "kind",
    "storage_clock_mode",
    "gate_open_hour",
    "gate_close_hour",
    "car_spot_capacity",
    "switch_buffer_minutes",
    "storage_free_hours",
    "storage_daily_rate_cents",
    "operates_weekends",
    "access_mode",
    "access_mode_reason",
    "occupied_spot_count",
    "last_switch_at",
    "created_at",
    "updated_at",
    "version",
)

# --- the second notice on the first cycle ----------------------------------
SECOND_NOTICE_SENT_AT = "2026-08-03T11:00:00.000Z"
VOID_REASON = "Waybill cancelled before the car moved."


# ===========================================================================
# instance: placement_cycle_create_read_and_filtered_list_agree
# ===========================================================================
def test_the_create_the_read_and_the_filtered_list_show_one_row(api):
    """201 then 200 then 200, and the filter keeps the other car's cycle out.

    PRD 3.2: "Cycles themselves can likewise be fetched individually or listed
    with optional filters on `customer_id`, `rail_car_id`, `facility_id`,
    `tariff_rule_set_id`, `movement_status` and `billing_status`, ordered the same
    way so that offset paging is stable."

    Design: Corner/endpoints/placement_cycle_create_read_and_filtered_list_agree
    """
    world = fx.reference_world(api)
    first_car = fx.make_rail_car(api, ownership=OWNERSHIP_RAILROAD_OWNED)
    second_car = fx.make_rail_car(api, ownership=OWNERSHIP_PRIVATE)

    created = api.create_placement_cycle(
        f.placement_cycle_payload(
            world["customer_id"],
            first_car["id"],
            world["facility_id"],
            world["tariff_id"],
            first_car["version"],
        ),
        AGENT,
    )
    assert created.status_code == 201
    cycle = get_success_data(created, 201)
    assert_common_fields(cycle, expected_version=1)
    assert_subset_equal(
        cycle,
        {
            "movement_status": MOVEMENT_ORDERED,
            "billing_status": BILLING_UNBILLED,
            "clock_basis": CLOCK_BASIS_NONE,
            "customer_id": world["customer_id"],
            "rail_car_id": first_car["id"],
            "facility_id": world["facility_id"],
            "tariff_rule_set_id": world["tariff_id"],
        },
    )

    # PRD 4: "Creation endpoints return HTTP 201 and every other successful call
    # returns HTTP 200".
    read = api.get_placement_cycle(cycle["id"], AGENT)
    assert read.status_code == 200
    assert get_success_data(read) == cycle

    other = get_success_data(
        api.create_placement_cycle(
            f.placement_cycle_payload(
                world["customer_id"],
                second_car["id"],
                world["facility_id"],
                world["tariff_id"],
                second_car["version"],
            ),
            AGENT,
        ),
        201,
    )
    assert other["id"] != cycle["id"]

    listed = api.list_placement_cycles(
        AGENT,
        {"rail_car_id": first_car["id"], "limit": DEFAULT_LIMIT, "offset": DEFAULT_OFFSET},
    )
    assert listed.status_code == 200
    rows = get_success_data(listed)
    assert ids_of(rows) == [cycle["id"]]
    assert_subset_equal(
        rows[0],
        {
            "rail_car_id": first_car["id"],
            "movement_status": MOVEMENT_ORDERED,
            "billing_status": BILLING_UNBILLED,
        },
    )
    assert_pagination_meta(
        listed.json()["meta"],
        limit=DEFAULT_LIMIT,
        offset=DEFAULT_OFFSET,
        total_count=1,
        has_more=False,
    )


# ===========================================================================
# instance: list_pagination_defaults_apply_when_limit_and_offset_are_omitted
# ===========================================================================
def test_omitting_both_pagination_parameters_echoes_the_defaults(api):
    """total_count counts the filtered set, and the page counts only the page.

    PRD 2.3: "`limit` controls page size: it must be an integer no smaller than 1
    and no larger than 100, and when it is omitted the service applies 10.
    `offset` controls the starting position: it must be an integer no smaller
    than 0, and when it is omitted the service applies 0."

    Design: Corner/endpoints/list_pagination_defaults_apply_when_limit_and_offset_are_omitted
    """
    world = fx.reference_world(api)
    first = fx.make_cycle(api, world)
    second = fx.make_cycle(api, world)
    both = sorted([first["id"], second["id"]])

    bare = api.list_placement_cycles(ADMIN, {"customer_id": world["customer_id"]})
    assert bare.status_code == 200
    rows = get_success_data(bare)
    assert len(rows) == 2
    assert sorted(ids_of(rows)) == both
    assert_pagination_meta(
        bare.json()["meta"],
        limit=DEFAULT_LIMIT,
        offset=DEFAULT_OFFSET,
        total_count=2,
        has_more=False,
    )

    # PRD 2.3: "`total_count` reports the size of the full filtered result set,
    # not the size of the returned page, and `has_more` is true exactly when rows
    # remain beyond the current page."
    page_one = api.list_placement_cycles(
        ADMIN, {"customer_id": world["customer_id"], "limit": 1, "offset": 0}
    )
    first_page_rows = get_success_data(page_one)
    assert len(first_page_rows) == 1
    assert_pagination_meta(
        page_one.json()["meta"], limit=1, offset=0, total_count=2, has_more=True
    )

    page_two = api.list_placement_cycles(
        ADMIN, {"customer_id": world["customer_id"], "limit": 1, "offset": 1}
    )
    second_page_rows = get_success_data(page_two)
    assert len(second_page_rows) == 1
    assert_pagination_meta(
        page_two.json()["meta"], limit=1, offset=1, total_count=2, has_more=False
    )

    # The two single-row pages partition the same filtered set.
    assert sorted(ids_of(first_page_rows) + ids_of(second_page_rows)) == both
    assert first_page_rows[0]["id"] != second_page_rows[0]["id"]


# ===========================================================================
# instance: facility_access_mode_action_returns_the_facility_and_bumps_version
# ===========================================================================
def test_the_access_mode_action_returns_the_whole_facility_each_time(api):
    """There is no PATCH on a facility, so this action is the only way through.

    PRD 3.1: "A `RailroadAgent` changes a facility's posture by supplying a new
    `access_mode` - `OPEN`, `GATE_CONTROLLED` or `EMBARGOED` - together with a
    `reason` that is recorded in `access_mode_reason`, and the facility's
    `version` increments by 1."

    Design: Corner/endpoints/facility_access_mode_action_returns_the_facility_and_bumps_version
    """
    fx.set_clock(api, COLD_START_CLOCK)
    facility = fx.make_industry_track(api)
    assert_common_fields(facility, expected_version=1)
    assert_subset_equal(
        facility,
        {
            "kind": FACILITY_KIND_INDUSTRY_TRACK,
            "access_mode": ACCESS_MODE_OPEN,
            "access_mode_reason": None,
            "occupied_spot_count": 0,
            "last_switch_at": None,
            "gate_close_hour": DEFAULT_GATE_CLOSE_HOUR,
            "car_spot_capacity": DEFAULT_CAR_SPOT_CAPACITY,
        },
    )

    gated_response = api.set_facility_access_mode(
        facility["id"],
        f.access_mode_payload(ACCESS_MODE_GATE_CONTROLLED, reason=NIGHT_GATE_REASON),
        AGENT,
    )
    # PRD 4: "there is no 204 anywhere, because every mutation returns the
    # resource it changed."
    assert gated_response.status_code == 200
    assert gated_response.status_code != 201
    gated = get_success_data(gated_response, 200)
    assert_fields_present(gated, FACILITY_FIELDS)
    assert_subset_equal(
        gated,
        {
            "id": facility["id"],
            "access_mode": ACCESS_MODE_GATE_CONTROLLED,
            "access_mode_reason": NIGHT_GATE_REASON,
            "version": facility["version"] + 1,
            "gate_close_hour": DEFAULT_GATE_CLOSE_HOUR,
            "car_spot_capacity": DEFAULT_CAR_SPOT_CAPACITY,
            "occupied_spot_count": 0,
        },
    )

    embargo_response = api.set_facility_access_mode(
        facility["id"],
        f.access_mode_payload(ACCESS_MODE_EMBARGOED, reason=DERAILMENT_REASON),
        AGENT,
    )
    assert embargo_response.status_code == 200
    embargoed = get_success_data(embargo_response, 200)
    assert_fields_present(embargoed, FACILITY_FIELDS)
    assert_subset_equal(
        embargoed,
        {
            "id": facility["id"],
            "access_mode": ACCESS_MODE_EMBARGOED,
            "access_mode_reason": DERAILMENT_REASON,
            "version": gated["version"] + 1,
            "gate_close_hour": DEFAULT_GATE_CLOSE_HOUR,
            "car_spot_capacity": DEFAULT_CAR_SPOT_CAPACITY,
        },
    )
    # The two calls walked the posture without ever touching the track's shape.
    assert embargoed["facility_code"] == facility["facility_code"]
    assert embargoed["switch_buffer_minutes"] == facility["switch_buffer_minutes"]
    assert embargoed["storage_daily_rate_cents"] == facility["storage_daily_rate_cents"]
    assert embargoed["version"] == facility["version"] + 2


# ===========================================================================
# instance: cycle_notifications_subresource_lists_only_that_cycles_notices
# ===========================================================================
def test_the_notifications_subresource_is_scoped_to_its_path_id(api):
    """sequence_number restarts at 1 under the second cycle, not at 3.

    PRD 3.3: "The `sequence_number` is this notice's 1-based position among the
    cycle's notifications ordered by `created_at` ascending."

    Design: Corner/endpoints/cycle_notifications_subresource_lists_only_that_cycles_notices
    """
    world = fx.reference_world(api)
    first_cycle = fx.constructively_placed_cycle(api, world)
    second_cycle = fx.constructively_placed_cycle(api, world)
    assert first_cycle["id"] != second_cycle["id"]

    delivered = fx.send_notice(api, first_cycle["id"], CYCLE_A_NOTICE_SENT_AT, CHANNEL_EDI)
    failed = fx.send_notice(api, first_cycle["id"], SECOND_NOTICE_SENT_AT, CHANNEL_FAX)
    other = fx.send_notice(api, second_cycle["id"], CYCLE_A_NOTICE_SENT_AT, CHANNEL_EDI)
    assert_light_fields(delivered)

    listed = api.list_notifications(
        first_cycle["id"], AGENT, {"limit": DEFAULT_LIMIT, "offset": DEFAULT_OFFSET}
    )
    assert listed.status_code == 200
    rows = get_success_data(listed)
    assert_pagination_meta(
        listed.json()["meta"],
        limit=DEFAULT_LIMIT,
        offset=DEFAULT_OFFSET,
        total_count=2,
        has_more=False,
    )
    assert ids_of(rows) == [delivered["id"], failed["id"]]
    assert_subset_equal(
        rows[0],
        {
            "placement_cycle_id": first_cycle["id"],
            "channel": CHANNEL_EDI,
            "delivery_status": DELIVERY_DELIVERED,
            "sequence_number": 1,
        },
    )
    assert_subset_equal(
        rows[1],
        {
            "placement_cycle_id": first_cycle["id"],
            "channel": CHANNEL_FAX,
            "delivery_status": DELIVERY_FAILED,
            "sequence_number": 2,
        },
    )
    assert other["id"] not in ids_of(rows)

    # PRD 3.3: "A cycle's notifications can be listed with an optional
    # `delivery_status` filter."
    filtered = api.list_notifications(
        first_cycle["id"],
        AGENT,
        {
            "delivery_status": DELIVERY_FAILED,
            "limit": DEFAULT_LIMIT,
            "offset": DEFAULT_OFFSET,
        },
    )
    failed_rows = get_success_data(filtered)
    assert ids_of(failed_rows) == [failed["id"]]
    assert_pagination_meta(filtered.json()["meta"], total_count=1, has_more=False)

    second_listed = api.list_notifications(
        second_cycle["id"], AGENT, {"limit": DEFAULT_LIMIT, "offset": DEFAULT_OFFSET}
    )
    second_rows = get_success_data(second_listed)
    assert_pagination_meta(second_listed.json()["meta"], total_count=1, has_more=False)
    assert ids_of(second_rows) == [other["id"]]
    # Numbering is per cycle: this is 1, not 3.
    assert second_rows[0]["sequence_number"] == 1
    assert second_rows[0]["placement_cycle_id"] == second_cycle["id"]
    assert delivered["id"] not in ids_of(second_rows)
    assert failed["id"] not in ids_of(second_rows)


# ===========================================================================
# instance: charges_are_read_only_computed_projections
# ===========================================================================
def test_a_charge_is_only_ever_written_by_the_cycle_cascade(api):
    """One row, two statuses, and no endpoint that could have written either.

    PRD 3.2: "Charges are read through their own retrieval capabilities and are
    never created or edited directly; a charge can be fetched individually, or
    listed with optional filters on `placement_cycle_id`, `invoice_id`,
    `charge_kind` and `status`, ordered by `created_at` ascending then `id`
    ascending, with a `Customer`-role caller silently narrowed to charges whose
    cycle belongs to it."

    Design: Corner/endpoints/charges_are_read_only_computed_projections
    """
    world = fx.reference_world(api)
    cycle = fx.actually_placed_cycle(api, world)

    def charges(status=None):
        params = {
            "placement_cycle_id": cycle["id"],
            "limit": DEFAULT_LIMIT,
            "offset": DEFAULT_OFFSET,
        }
        if status is not None:
            params["status"] = status
        return api.list_charges(ADMIN, params)

    provisional_listed = charges(CHARGE_PROVISIONAL)
    assert provisional_listed.status_code == 200
    provisional_rows = get_success_data(provisional_listed)
    assert_pagination_meta(
        provisional_listed.json()["meta"], total_count=1, has_more=False
    )
    charge_id = provisional_rows[0]["id"]
    assert_server_minted_id(charge_id)
    assert_subset_equal(
        provisional_rows[0],
        {"status": CHARGE_PROVISIONAL, "placement_cycle_id": cycle["id"]},
    )

    fx.release_cycle(api, cycle["id"], CYCLE_A_RELEASE_AT, world["customer_id"])
    assert fx.get_cycle(api, cycle["id"])["movement_status"] == MOVEMENT_RELEASED

    # The same row now answers to the other filter and to no other id.
    assert get_success_data(charges(CHARGE_PROVISIONAL)) == []
    assert_pagination_meta(charges(CHARGE_PROVISIONAL).json()["meta"], total_count=0)
    final_listed = charges(CHARGE_FINAL)
    final_rows = get_success_data(final_listed)
    assert_pagination_meta(final_listed.json()["meta"], total_count=1, has_more=False)
    assert ids_of(final_rows) == [charge_id]

    single = api.get_charge(charge_id, ADMIN)
    assert single.status_code == 200
    charge = get_success_data(single)
    assert_common_fields(charge)
    assert_subset_equal(
        charge,
        {
            "id": charge_id,
            "placement_cycle_id": cycle["id"],
            "charge_kind": CHARGE_KIND_DEMURRAGE,
            "computation_basis": BASIS_ACTUAL,
            "status": CHARGE_FINAL,
            "chargeable_days": CYCLE_A_CHARGEABLE_DAYS,
            "billable_days": CYCLE_A_CHARGEABLE_DAYS,
            "bunching_exempt_days": 0,
            "gross_amount_cents": CYCLE_A_GROSS_CENTS,
            "credit_applied_cents": 0,
            "net_amount_cents": CYCLE_A_GROSS_CENTS,
            "invoice_id": None,
        },
    )
    # Every one of those numbers arrived by cascade: the row was never posted.
    assert get_success_data(charges()) == [charge]


# ===========================================================================
# instance: void_on_an_ordered_cycle_has_no_charge_to_reverse
# ===========================================================================
def test_voiding_an_ordered_cycle_reverses_nothing_because_nothing_exists(api):
    """The widest cascade in the system, run on the one branch with no money in it.

    PRD 3.7: "Only a cycle whose `movement_status` is `ORDERED` or `RELEASED` may
    be voided - anything in flight between those two is refused with
    `ERR_INVALID_MOVEMENT_STATE` - and a cycle whose charge line sits on an invoice
    that is already `CLOSED` may not be voided at all, which is
    `ERR_INVOICE_INVALID_STATE`."

    Design: Corner/endpoints/void_on_an_ordered_cycle_has_no_charge_to_reverse
    """
    world = fx.reference_world(api)
    car = fx.make_rail_car(api, ownership=OWNERSHIP_RAILROAD_OWNED)
    cycle = fx.make_cycle(api, world, rail_car=car)
    assert cycle["movement_status"] == MOVEMENT_ORDERED
    # PRD 3.2: "No charge line exists yet: a charge is born at constructive
    # placement, not at ordering."
    assert fx.charges_of_cycle(api, cycle["id"]) == []

    voided_response = api.void_cycle(
        cycle["id"], f.void_payload(void_reason=VOID_REASON), ADMIN
    )
    assert voided_response.status_code == 200
    voided = get_success_data(voided_response)
    # PRD 3.7 takes a `void_reason` on the request but, unlike
    # `constructive_reason_code` / `access_mode_reason` / `credit_hold_reason`,
    # never declares it as a field recorded on the cycle, so it is not asserted.
    assert_subset_equal(
        voided,
        {
            "id": cycle["id"],
            "movement_status": MOVEMENT_VOIDED,
            "billing_status": BILLING_UNBILLED,
            "version": cycle["version"] + 1,
        },
    )
    assert voided["released_at"] is None

    listed = api.list_charges(
        ADMIN,
        {
            "placement_cycle_id": cycle["id"],
            "limit": DEFAULT_LIMIT,
            "offset": DEFAULT_OFFSET,
        },
    )
    assert get_success_data(listed) == []
    assert_pagination_meta(listed.json()["meta"], total_count=0, has_more=False)

    assert fx.probe_facility(api, world["facility_id"])["occupied_spot_count"] == 0

    # PRD 3.2: "a voided cycle occupies no interval at all", so the car is free.
    freed = fx.get_car(api, car["id"])
    assert freed["active_cycle_count"] == 0
    replacement = get_success_data(
        api.create_placement_cycle(
            f.placement_cycle_payload(
                world["customer_id"],
                car["id"],
                world["facility_id"],
                world["tariff_id"],
                freed["version"],
            ),
            AGENT,
        ),
        201,
    )
    assert replacement["id"] != cycle["id"]
    assert replacement["movement_status"] == MOVEMENT_ORDERED
    assert fx.get_car(api, car["id"])["active_cycle_count"] == 1
