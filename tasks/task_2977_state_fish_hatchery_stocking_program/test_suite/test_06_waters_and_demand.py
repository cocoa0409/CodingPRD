"""
Destinations, demand intake and the priority score.

Covers the waters listing and its filters, the shape gates on registering a
water, the parent lookup a request depends on, the one transition a water has,
the frozen priority score and its clamped plan-gap term, the deliberately
uncapped fill percentage beside the floored shortfall, the terminality of a
withdrawn request, and the requests listing.
"""

from test_helpers import (
    ADMIN_HEADERS,
    BIO_CARLA_HEADERS,
    NON_EXISTENT_UUID,
    PUB_DANA_HEADERS,
    assert_common_fields,
    assert_integer_equals,
    assert_number_equals,
    ids_of,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as err
from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures as fx

# A syntactically valid UUID that no stocking request ever holds.
UNKNOWN_REQUEST_ID = "33333333-3333-4333-8333-333333333333"


def test_waters_listing_paginates_with_total_count_and_has_more(api):
    """
    The waters listing pages the rows but counts the whole set, and its filters
    narrow that count rather than the page.

    PRD 2.3: "List responses carry four pagination fields inside `meta`: `limit`
    and `offset` echoing the values in force, `total_count` giving the number of
    records matching the filters before paging, and `has_more` indicating whether
    any matching record remains beyond the current page."

    Design: Corner/entities/waters_listing_paginates_with_total_count_and_has_more
    """
    blue_mesa = fx.create_water(api)
    taylor_park = fx.create_water(
        api,
        name="Taylor Park Reservoir",
        county="Gunnison",
        habitat_suitability_score=70,
        angler_demand_index=60,
        plan_target_count=4000,
        access_type=k.ACCESS_SHORE_ONLY,
    )
    spinney = fx.create_water(
        api,
        name="Spinney Mountain Reservoir",
        county="Park",
        water_class=k.WATER_CLASS_WARMWATER_LAKE,
        habitat_suitability_score=60,
        angler_demand_index=100,
        plan_species=k.SPECIES_WALLEYE,
        plan_target_count=1000,
        access_type=k.ACCESS_REMOTE,
    )

    first_page, meta = validate_paginated(
        api.list_waters(BIO_CARLA_HEADERS, {"limit": 2, "offset": 0})
    )
    assert meta["limit"] == 2, meta
    assert meta["offset"] == 0, meta
    assert meta["total_count"] == 3, meta
    assert meta["has_more"] is True
    assert len(first_page) == 2, ids_of(first_page)

    second_page, meta_two = validate_paginated(
        api.list_waters(BIO_CARLA_HEADERS, {"limit": 2, "offset": 2})
    )
    assert meta_two["total_count"] == 3, meta_two
    assert meta_two["has_more"] is False
    assert len(second_page) == 1, ids_of(second_page)
    assert ids_of(first_page + second_page) == [
        blue_mesa["id"],
        taylor_park["id"],
        spinney["id"],
    ]

    walleye, walleye_meta = validate_paginated(
        api.list_waters(ADMIN_HEADERS, {"plan_species": k.SPECIES_WALLEYE})
    )
    assert walleye_meta["total_count"] == 1, walleye_meta
    assert ids_of(walleye) == [spinney["id"]]

    _, gunnison_meta = validate_paginated(
        api.list_waters(ADMIN_HEADERS, {"county": "Gunnison"})
    )
    assert gunnison_meta["total_count"] == 2, gunnison_meta


def test_water_creation_missing_plan_target_count_is_rejected(api):
    """
    The annual plan target is required, and a body without it persists nothing.

    PRD 3.6: "A stocking destination is registered by a `ProgramAdmin` with a
    `name`, the `county` of record, a `water_class` — one of `COLDWATER_LAKE`,
    `COLDWATER_STREAM` or `WARMWATER_LAKE` — a `habitat_suitability_score` and an
    `angler_demand_index` each expressed on a 0-to-100 scale, the `plan_species`
    named in the water's management plan, the annual `plan_target_count` in fish,
    and an `access_type` of `PUBLIC_BOAT`, `SHORE_ONLY` or `REMOTE`."

    Design: Corner/entities/water_creation_missing_plan_target_count_is_rejected
    """
    payload = f.water_payload(
        name="Antero Reservoir",
        county="Park",
        habitat_suitability_score=55,
        angler_demand_index=40,
        access_type=k.ACCESS_SHORE_ONLY,
        plan_target_count=f.OMIT,
    )
    assert "plan_target_count" not in payload

    response = api.create_water(payload, ADMIN_HEADERS)

    validate_error(response, err.ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(api.list_waters(ADMIN_HEADERS))
    assert meta["total_count"] == 0, meta


def test_water_class_outside_the_declared_enum_is_rejected(api):
    """
    A plausible-sounding fourth water class is refused rather than stored as free
    text.

    PRD 3.6: "a `water_class` — one of `COLDWATER_LAKE`, `COLDWATER_STREAM` or
    `WARMWATER_LAKE`"

    Design: Corner/entities/water_class_outside_the_declared_enum_is_rejected
    """
    response = api.create_water(
        f.water_payload(
            name="Eleven Mile Canyon Reservoir",
            county="Park",
            water_class="RESERVOIR",
            habitat_suitability_score=65,
            angler_demand_index=70,
            plan_target_count=3000,
        ),
        ADMIN_HEADERS,
    )

    validate_error(response, err.ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(api.list_waters(ADMIN_HEADERS))
    assert meta["total_count"] == 0, meta


def test_habitat_suitability_score_above_one_hundred_is_rejected(api):
    """
    Both scoring inputs are bounded by an inclusive 0-to-100 range: 101 is refused,
    100 is accepted, and a negative demand index is refused too.

    PRD 3.6: "Both scores must fall between 0 and 100 inclusive, and
    `plan_target_count` must be at least 1."

    Design: Corner/entities/habitat_suitability_score_above_one_hundred_is_rejected
    """
    def trappers_lake(**overrides):
        fields = dict(
            name="Trappers Lake",
            county="Garfield",
            habitat_suitability_score=101,
            angler_demand_index=50,
            plan_species=k.SPECIES_BROWN_TROUT,
            plan_target_count=500,
            access_type=k.ACCESS_REMOTE,
        )
        fields.update(overrides)
        return f.water_payload(**fields)

    validate_error(
        api.create_water(trappers_lake(), ADMIN_HEADERS), err.ERR_INVALID_REQUEST, 400
    )
    validate_error(
        api.create_water(trappers_lake(angler_demand_index=-1), ADMIN_HEADERS),
        err.ERR_INVALID_REQUEST,
        400,
    )

    on_the_bound = validate_success(
        api.create_water(
            trappers_lake(habitat_suitability_score=100), ADMIN_HEADERS
        ),
        201,
    )
    assert_integer_equals(
        on_the_bound["habitat_suitability_score"], 100, "habitat_suitability_score"
    )
    assert on_the_bound["status"] == k.WATER_ACTIVE
    assert_common_fields(on_the_bound, expected_version=1)


def test_stocking_request_on_an_unknown_water_returns_not_found(api):
    """
    A request cannot be scored without its destination water, so an unresolvable
    `water_id` is a 404 rather than a request with no score.

    PRD 2.11: "Identifiers carried in a request body are resolved the same way,
    against the collection each one names, and they too report the referenced
    collection's own 404."

    Design: Corner/entities/stocking_request_on_an_unknown_water_returns_not_found
    """
    fx.create_water(api)

    response = api.create_stocking_request(
        f.stocking_request_payload(
            NON_EXISTENT_UUID,
            requested_count=500,
            justification="Request against a water that does not exist",
        ),
        BIO_CARLA_HEADERS,
    )

    validate_error(response, err.ERR_WATER_NOT_FOUND, 404)

    _, meta = validate_paginated(api.list_stocking_requests(ADMIN_HEADERS))
    assert meta["total_count"] == 0, meta

def test_closing_a_water_moves_active_to_closed_and_is_not_repeatable(api):
    """
    Retirement is the water's only transition: it bumps the version, leaves the
    plan counters exactly as they were, and cannot be applied twice.

    PRD 3.6: "A `ProgramAdmin` may retire a water, moving it from `ACTIVE` to
    `CLOSED`; `CLOSED` is terminal and closing an already-closed water is
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/closing_a_water_moves_active_to_closed_and_is_not_repeatable
    """
    water = fx.create_water(api)
    assert water["status"] == k.WATER_ACTIVE
    assert_common_fields(water, expected_version=1)

    closed = validate_success(api.close_water(water["id"], ADMIN_HEADERS), 200)

    assert closed["status"] == k.WATER_CLOSED
    assert_integer_equals(closed["version"], 2, "version")
    assert_integer_equals(closed["allocated_count_ytd"], 0, "allocated_count_ytd")
    assert_integer_equals(closed["released_count_ytd"], 0, "released_count_ytd")
    assert_integer_equals(closed["plan_shortfall_count"], 2000, "plan_shortfall_count")
    assert_number_equals(closed["plan_fill_pct"], 0.0, 2, "plan_fill_pct")

    validate_error(
        api.close_water(water["id"], ADMIN_HEADERS), err.ERR_INVALID_STATE, 409
    )

    again = fx.read_water(api, water["id"])
    assert again["status"] == k.WATER_CLOSED
    assert_integer_equals(again["version"], 2, "version")


def test_priority_score_is_frozen_at_creation_and_the_plan_gap_clamps_at_zero(api):
    """
    A request is scored once, from the water's counters as they stood then. After
    the water is over-allocated the plan-gap term clamps to zero for the next
    request, and the earlier request keeps the score it was given.

    PRD 3.6: "The `priority_score` is a single figure on a 0-to-100 scale, computed
    from the destination water's counters as they stand at that moment and then
    frozen on the request; a later change to the water's counters does not re-score
    an existing request."

    Design: Corner/calculations/priority_score_is_frozen_at_creation_and_the_plan_gap_clamps_at_zero
    """
    ctx = fx.granted_request(api, fx.station_at_rest(api))
    first_request, water = ctx["request"], ctx["water"]

    # 0.45*80 + 0.35*90 + 0.20*100.00 = 87.50, biologist weight 1.00, +10 species.
    assert_number_equals(first_request["priority_score"], 97.50, 2, "priority_score")
    assert_integer_equals(first_request["allocated_count"], 2400, "allocated_count")

    over_allocated = fx.read_water(api, water["id"])
    assert_integer_equals(
        over_allocated["plan_shortfall_count"], 0, "plan_shortfall_count"
    )
    assert_number_equals(over_allocated["plan_fill_pct"], 120.0, 2, "plan_fill_pct")

    second = validate_success(
        api.create_stocking_request(
            f.stocking_request_payload(
                water["id"],
                requested_count=600,
                justification="Second pass on Blue Mesa after the first grant",
            ),
            BIO_CARLA_HEADERS,
        ),
        201,
    )

    # The gap term is max(0, 2000 - 0 - 2400) / 2000 = 0.00, so 87.50 - 20.00 + 10.
    assert_number_equals(second["priority_score"], 77.50, 2, "priority_score")

    unchanged = fx.read_request(api, first_request["id"])
    assert_number_equals(unchanged["priority_score"], 97.50, 2, "priority_score")


def test_water_plan_fill_pct_can_exceed_one_hundred_while_shortfall_floors_at_zero(api):
    """
    The two outputs of the same plan-progress rule are clamped differently: the
    shortfall count floors at zero while the fill percentage runs past 100.

    PRD 3.6: "`plan_fill_pct` is the sum of `released_count_ytd` and
    `allocated_count_ytd`, divided by `plan_target_count`, expressed as a percentage
    and rounded to two decimal places — and it is deliberately not capped, so a
    water with a `plan_target_count` of 2000 carrying 2400 allocated and nothing yet
    released reports a `plan_shortfall_count` of 0 and a `plan_fill_pct` of 120.00."

    Design: Corner/calculations/water_plan_fill_pct_can_exceed_one_hundred_while_shortfall_floors_at_zero
    """
    ctx = fx.granted_request(api, fx.station_at_rest(api))

    water = fx.read_water(api, ctx["water"]["id"])

    assert_integer_equals(water["plan_target_count"], 2000, "plan_target_count")
    assert_integer_equals(water["allocated_count_ytd"], 2400, "allocated_count_ytd")
    assert_integer_equals(water["released_count_ytd"], 0, "released_count_ytd")
    assert_integer_equals(water["plan_shortfall_count"], 0, "plan_shortfall_count")
    assert_number_equals(water["plan_fill_pct"], 120.0, 2, "plan_fill_pct")


def test_attach_to_plan_after_withdraw_is_an_invalid_transition(api):
    """
    A withdrawn request is finished with: attaching it to a plan is refused as an
    invalid state rather than enlarging the candidate set, and the plan it aimed
    at is left untouched.

    PRD 3.6: "`WITHDRAWN` is terminal, as are `DENIED` and `FULFILLED`, and
    withdrawing a request in any of those, or one already `ALLOCATED`, is
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/attach_to_plan_after_withdraw_is_an_invalid_transition
    """
    ctx = fx.station_at_rest(api)
    water = fx.create_water(api)
    request = fx.create_stocking_request(api, water)
    plan = fx.create_allocation_plan(api, ctx["hatchery"])
    assert plan["status"] == k.PLAN_DRAFT
    assert_integer_equals(plan["version"], 1, "version")

    withdrawn = validate_success(
        api.withdraw_stocking_request(request["id"], BIO_CARLA_HEADERS), 200
    )
    assert withdrawn["status"] == k.REQUEST_WITHDRAWN

    response = api.attach_to_plan(
        request["id"], f.attach_to_plan_payload(plan["id"], 1), BIO_CARLA_HEADERS
    )

    validate_error(response, err.ERR_INVALID_STATE, 409)

    after = fx.read_request(api, request["id"])
    assert after["status"] == k.REQUEST_WITHDRAWN
    assert after["allocation_plan_id"] is None, after["allocation_plan_id"]

    plan_after = fx.read_plan(api, plan["id"])
    assert plan_after["status"] == k.PLAN_DRAFT
    assert_integer_equals(plan_after["version"], 1, "version")
    assert_integer_equals(plan_after["run_count"], 0, "run_count")


def test_stocking_requests_listing_filters_by_status_and_paginates(api):
    """
    The requests listing narrows `total_count` by the filter itself rather than
    only trimming the page, and pages through the narrowed set.

    PRD 3.6: "A `ProgramAdmin`, a `HatcheryManager`, a `RegionalBiologist` or a
    `PublicRequester` may read a single request with its score, grant and status, or
    list requests filtered by `water_id`, `allocation_plan_id`, `status`,
    `requester_kind` and `species`"

    Design: Corner/cross_cutting_complexity_layers/stocking_requests_listing_filters_by_status_and_paginates
    """
    blue_mesa = fx.create_water(api)
    taylor_park = fx.create_water(
        api,
        name="Taylor Park Reservoir",
        habitat_suitability_score=70,
        angler_demand_index=60,
        plan_target_count=4000,
        access_type=k.ACCESS_SHORE_ONLY,
    )
    first = fx.create_stocking_request(api, blue_mesa)
    second = fx.create_stocking_request(api, taylor_park, requested_count=1000)
    public = fx.create_stocking_request(
        api,
        blue_mesa,
        PUB_DANA_HEADERS,
        requested_count=500,
        justification="Family fishing weekend at Blue Mesa",
    )
    assert public["requester_kind"] == k.REQUESTER_KIND_PUBLIC
    validate_success(
        api.withdraw_stocking_request(public["id"], PUB_DANA_HEADERS), 200
    )

    page_one, meta_one = validate_paginated(
        api.list_stocking_requests(
            ADMIN_HEADERS, {"status": k.REQUEST_SUBMITTED, "limit": 1, "offset": 0}
        )
    )
    assert meta_one["limit"] == 1, meta_one
    assert meta_one["offset"] == 0, meta_one
    assert meta_one["total_count"] == 2, meta_one
    assert meta_one["has_more"] is True
    assert len(page_one) == 1, ids_of(page_one)

    page_two, meta_two = validate_paginated(
        api.list_stocking_requests(
            ADMIN_HEADERS, {"status": k.REQUEST_SUBMITTED, "limit": 1, "offset": 1}
        )
    )
    assert meta_two["total_count"] == 2, meta_two
    assert meta_two["has_more"] is False
    assert len(page_two) == 1, ids_of(page_two)
    assert page_two[0]["id"] != page_one[0]["id"]
    assert sorted(ids_of(page_one + page_two)) == sorted([first["id"], second["id"]])

    gone, meta_gone = validate_paginated(
        api.list_stocking_requests(ADMIN_HEADERS, {"status": k.REQUEST_WITHDRAWN})
    )
    assert meta_gone["total_count"] == 1, meta_gone
    assert ids_of(gone) == [public["id"]]

    from_the_public, meta_public = validate_paginated(
        api.list_stocking_requests(
            ADMIN_HEADERS, {"requester_kind": k.REQUESTER_KIND_PUBLIC}
        )
    )
    assert meta_public["total_count"] == 1, meta_public
    assert ids_of(from_the_public) == [public["id"]]


def test_unknown_request_id_returns_request_not_found(api):
    """
    Withdrawing a request that does not exist is the requests collection's own
    404, and the administrator's exemption from the ownership test means nothing
    can mask it.

    PRD 2.1: "A `ProgramAdmin` is exempt from that ownership test and may withdraw
    or attach any requester's request."

    Design: Corner/errors/unknown_request_id_returns_request_not_found
    """
    response = api.withdraw_stocking_request(UNKNOWN_REQUEST_ID, ADMIN_HEADERS)

    validate_error(response, err.ERR_REQUEST_NOT_FOUND, 404)
