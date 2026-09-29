"""Choosing how a segment will be built.

Method selection is the moment the money first appears on a segment, and three
separate rules meet inside that one call: the paving moratorium is resolved before
anything is costed, the open-cut prohibition can veto the choice outright, and the
restoration obligation is looked up on the pair of method and moratorium class. The
call is also one of only two version-guarded writes in the whole system.
"""

from test_helpers import (
    fixtures as fx,
    ids_of,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    budget_adjustment_payload,
    construction_method_payload,
    create_moratorium_window_payload,
    create_pole_observation_payload,
    create_segment_payload,
    create_walkout_payload,
    walkout_review_payload,
)

_HARBOR_LOOP = {
    "name": "Harbor Loop",
    "topology_objective": "RING_CLOSURE",
    "target_in_service_date": "2027-03-01",
    "budget_authorized_cents": 250000000,
}
_CLEAN_POLE = {
    "pole_tag": "P-001",
    "pole_owner": "TELCO",
    "condition_grade": "B",
    "available_vertical_clearance_in": 45,
    "existing_attachment_count": 2,
}


def _walked_segment_on(street_name, **segment_overrides):
    """A PLANNING route with one walked 400-foot urban paved leg down ``street_name``."""

    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(**_HARBOR_LOOP)
    segment = fx.create_segment(
        route["id"],
        sequence_index=1,
        street_name=street_name,
        municipality_code="MUN-014",
        length_feet=400,
        terrain_class="URBAN_PAVED",
        planned_work_start_on="2026-09-15",
        planned_work_end_on="2026-09-20",
        **segment_overrides,
    )
    fx.accepted_walkout(
        segment["id"],
        [_CLEAN_POLE],
        walked_on="2026-08-11",
        obstruction_count=0,
        conduit_available_confirmed=False,
        surveyor_note="leg walked, no obstructions found",
    )
    return {"route_id": route["id"], "segment_id": segment["id"]}


def test_the_preliminary_cost_of_an_aerial_urban_paved_leg_is_a_single_product(
    api, engineer_headers
):
    """400 feet at 1,237 cents a foot times 12,750 basis points is 630,870 cents.

    PRD: "It is a single product with a single rounding: the segment's `length_feet`
    multiplied by the base rate, multiplied by the terrain multiplier in basis
    points, divided by 10,000, and the quotient rounded half up to whole cents."

    Design: Corner/calculations/preliminary_cost_correct_for_an_aerial_urban_paved_400_foot_segment
    """
    built = _walked_segment_on("Dock Street")
    version = fx.route_version(built["route_id"])

    segment = validate_success(
        api.select_construction_method(
            built["segment_id"],
            construction_method_payload("AERIAL", version),
            headers=engineer_headers,
        )
    )
    assert segment["engineering_status"] == "METHOD_SELECTED"
    assert segment["construction_method"] == "AERIAL"
    assert segment["preliminary_cost_cents"] == 630870
    assert segment["bid_ready_cost_cents"] is None
    assert segment["moratorium_class"] == "NONE"
    assert segment["restoration_cost_cents"] == 0

    route = fx.read_route(built["route_id"])
    assert route["total_preliminary_cost_cents"] == 630870
    assert route["total_bid_ready_cost_cents"] == 0


def test_two_identical_bores_diverge_only_through_the_restoration_rate(
    api, engineer_headers, admin_headers
):
    """A full-restoration street costs 288,000 to restore where a clear street costs 104,000.

    PRD: "A directional bore carries 260 cents per foot with no moratorium in force,
    480 cents per foot under a no-open-cut moratorium, and 720 cents per foot under a
    full-restoration moratorium."

    Design: Corner/calculations/restoration_rate_is_keyed_on_method_and_resolved_moratorium_class
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    fx.create_moratorium_window(
        municipality_code="MUN-014",
        street_name="Slate Road",
        resurfaced_on="2026-06-01",
        starts_on="2026-09-01",
        ends_on="2026-10-31",
        moratorium_class="FULL_RESTORATION",
        ordinance_reference="ORD-2026-114",
    )
    route = fx.create_route(
        name="Twin Bore",
        topology_objective="SPUR",
        target_in_service_date="2027-06-01",
        budget_authorized_cents=250000000,
    )
    restricted = fx.create_segment(
        route["id"],
        sequence_index=1,
        street_name="Slate Road",
        municipality_code="MUN-014",
        length_feet=400,
        terrain_class="URBAN_PAVED",
        planned_work_start_on="2026-09-15",
        planned_work_end_on="2026-09-20",
    )
    clear = fx.create_segment(
        route["id"],
        sequence_index=2,
        street_name="Chalk Lane",
        municipality_code="MUN-014",
        length_feet=400,
        terrain_class="URBAN_PAVED",
        planned_work_start_on="2026-09-15",
        planned_work_end_on="2026-09-20",
    )
    for segment_id in (restricted["id"], clear["id"]):
        fx.accepted_walkout(
            segment_id,
            [_CLEAN_POLE],
            walked_on="2026-08-11",
            obstruction_count=0,
            conduit_available_confirmed=False,
            surveyor_note="bore path walked",
        )

    first = validate_success(
        api.select_construction_method(
            restricted["id"],
            construction_method_payload("DIRECTIONAL_BORE", fx.route_version(route["id"])),
            headers=engineer_headers,
        )
    )
    assert first["moratorium_class"] == "FULL_RESTORATION"
    assert first["restoration_cost_cents"] == 288000

    second = validate_success(
        api.select_construction_method(
            clear["id"],
            construction_method_payload("DIRECTIONAL_BORE", fx.route_version(route["id"])),
            headers=engineer_headers,
        )
    )
    assert second["moratorium_class"] == "NONE"
    assert second["restoration_cost_cents"] == 104000

    assert first["preliminary_cost_cents"] == 2353650
    assert second["preliminary_cost_cents"] == 2353650, (
        "the preliminary variant excludes the restoration obligation entirely"
    )
    assert fx.read_route(route["id"])["total_preliminary_cost_cents"] == 4707300


def test_trenching_a_no_open_cut_street_is_vetoed_and_writes_nothing(
    api, engineer_headers
):
    """The refusal leaves the segment untouched, so the same token still works for a bore.

    PRD: "With the moratorium resolved, the **open-cut prohibition** applies: a
    `method` of `TRENCH` on a segment whose resolved `moratorium_class` is
    `NO_OPEN_CUT` is refused with `ERR_OPEN_CUT_PROHIBITED`, and the request writes
    nothing at all — not the method, not the moratorium class, not the restoration
    figure."

    Design: Corner/validations/trench_under_a_no_open_cut_moratorium_returns_open_cut_prohibited
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    fx.create_moratorium_window(
        municipality_code="MUN-014",
        street_name="Slate Road",
        resurfaced_on="2026-06-01",
        starts_on="2026-09-01",
        ends_on="2026-10-31",
        moratorium_class="NO_OPEN_CUT",
        ordinance_reference="ORD-2026-114",
    )
    built = _walked_segment_on("Slate Road")
    version = fx.route_version(built["route_id"])

    vetoed = api.select_construction_method(
        built["segment_id"],
        construction_method_payload("TRENCH", version),
        headers=engineer_headers,
    )
    validate_error(vetoed, "ERR_OPEN_CUT_PROHIBITED", 422)

    untouched = fx.read_segment(built["segment_id"])
    assert untouched["engineering_status"] == "WALKED"
    assert untouched["construction_method"] is None
    assert untouched["moratorium_class"] == "NONE"
    assert untouched["restoration_cost_cents"] == 0
    assert fx.route_version(built["route_id"]) == version

    bored = validate_success(
        api.select_construction_method(
            built["segment_id"],
            construction_method_payload("DIRECTIONAL_BORE", version),
            headers=engineer_headers,
        )
    )
    assert bored["moratorium_class"] == "NO_OPEN_CUT"
    assert bored["restoration_cost_cents"] == 192000
    assert bored["preliminary_cost_cents"] == 2353650


def test_moratorium_windows_that_touch_at_an_endpoint_collide(api, admin_headers):
    """Closed intervals mean the incumbent's last day is still taken.

    PRD: "Registration is refused with `ERR_MORATORIUM_WINDOW_OVERLAP` when the new
    window's closed date interval intersects an existing window on the same
    `municipality_code` and `street_name`; because both intervals are closed,
    windows that merely touch at an endpoint do collide."

    Design: Corner/validations/overlapping_moratorium_window_on_the_same_street_returns_overlap
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    incumbent = fx.create_moratorium_window(
        municipality_code="MUN-014",
        street_name="Slate Road",
        resurfaced_on="2026-06-01",
        starts_on="2026-09-01",
        ends_on="2026-10-31",
        moratorium_class="FULL_RESTORATION",
        ordinance_reference="ORD-2026-114",
    )

    touching = api.create_moratorium_window(
        create_moratorium_window_payload(
            municipality_code="MUN-014",
            street_name="Slate Road",
            resurfaced_on="2026-10-29",
            starts_on="2026-10-31",
            ends_on="2026-11-15",
            moratorium_class="NO_OPEN_CUT",
            ordinance_reference="ORD-2026-402",
        ),
        headers=admin_headers,
    )
    validate_error(touching, "ERR_MORATORIUM_WINDOW_OVERLAP", 409)

    next_day = validate_success(
        api.create_moratorium_window(
            create_moratorium_window_payload(
                municipality_code="MUN-014",
                street_name="Slate Road",
                resurfaced_on="2026-10-29",
                starts_on="2026-11-01",
                ends_on="2026-11-15",
                moratorium_class="NO_OPEN_CUT",
                ordinance_reference="ORD-2026-403",
            ),
            headers=admin_headers,
        ),
        201,
    )
    assert next_day["starts_on"] == "2026-11-01"

    other_street = validate_success(
        api.create_moratorium_window(
            create_moratorium_window_payload(
                municipality_code="MUN-014",
                street_name="Chalk Lane",
                resurfaced_on="2026-08-30",
                starts_on="2026-09-01",
                ends_on="2026-10-31",
                moratorium_class="FULL_RESTORATION",
                ordinance_reference="ORD-2026-404",
            ),
            headers=admin_headers,
        ),
        201,
    )
    assert other_street["street_name"] == "Chalk Lane"

    rows, meta = validate_paginated(
        api.list_moratorium_windows(
            headers=admin_headers,
            params={"municipality_code": "MUN-014", "street_name": "Slate Road"},
        )
    )
    assert meta["total_count"] == 2
    assert ids_of(rows) == [incumbent["id"], next_day["id"]]


def test_a_bid_ready_estimate_before_a_method_is_chosen_is_a_state_fault(
    api, engineer_headers
):
    """A WALKED segment has no method to price, so the request is refused with 409.

    PRD: "Requesting it from any other engineering status is
    `ERR_INVALID_SEGMENT_ENGINEERING_STATE`."

    Design: Corner/state_machines/bid_ready_estimate_before_method_selection_returns_invalid_segment_engineering_state
    """
    built = _walked_segment_on("Dock Street")

    premature = api.request_bid_ready_estimate(built["segment_id"], headers=engineer_headers)
    validate_error(premature, "ERR_INVALID_SEGMENT_ENGINEERING_STATE", 409)

    segment = fx.read_segment(built["segment_id"])
    assert segment["engineering_status"] == "WALKED"
    assert segment["construction_method"] is None
    assert segment["bid_ready_cost_cents"] is None
    assert segment["preliminary_cost_cents"] is None
    assert fx.read_route(built["route_id"])["total_bid_ready_cost_cents"] == 0


def test_a_budget_adjustment_between_read_and_write_makes_the_method_token_stale(
    api, engineer_headers, admin_headers
):
    """The route version the client held is one behind, so the selection is a 412.

    PRD: "If the supplied value does not equal the route's current `version`, the
    request is rejected with `ERR_STALE_ROUTE_VERSION` and HTTP 412, and no field
    anywhere is written."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_route_version_on_construction_method_returns_stale_route_version
    """
    built = _walked_segment_on("Dock Street")
    stale = fx.route_version(built["route_id"])

    validate_success(
        api.adjust_route_budget(
            built["route_id"],
            budget_adjustment_payload(500000, reason="supplemental construction allowance"),
            headers=admin_headers,
        )
    )
    fresh = fx.route_version(built["route_id"])
    assert fresh == stale + 1

    refused = api.select_construction_method(
        built["segment_id"],
        construction_method_payload("AERIAL", stale),
        headers=engineer_headers,
    )
    validate_error(refused, "ERR_STALE_ROUTE_VERSION", 412)

    segment = fx.read_segment(built["segment_id"])
    assert segment["engineering_status"] == "WALKED"
    assert segment["construction_method"] is None
    assert fx.route_version(built["route_id"]) == fresh
    assert fx.read_route(built["route_id"])["total_preliminary_cost_cents"] == 0

    accepted = validate_success(
        api.select_construction_method(
            built["segment_id"],
            construction_method_payload("AERIAL", fresh),
            headers=engineer_headers,
        )
    )
    assert accepted["preliminary_cost_cents"] == 630870
    route = fx.read_route(built["route_id"])
    assert route["version"] == fresh + 1
    assert route["total_preliminary_cost_cents"] == 630870


def test_the_route_version_advances_by_exactly_one_per_accepted_write(
    api, engineer_headers, surveyor_headers, admin_headers
):
    """Segment add, budget adjustment, lock and method selection each move it once.

    PRD: "`version` is an integer that begins at 1 on creation and increments by
    exactly 1 on every mutation of that record — again including mutations confined
    to computed rollups, and including mutations applied by a cascade rather than by
    a direct request against that record."

    Design: Corner/cross_cutting_complexity_layers/route_version_increments_once_per_accepted_write
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(headers=engineer_headers, **_HARBOR_LOOP)
    at_create = route["version"]
    assert at_create == 1

    segment = validate_success(
        api.create_segment(
            create_segment_payload(
                route["id"],
                sequence_index=1,
                street_name="Dock Street",
                municipality_code="MUN-014",
                length_feet=400,
                terrain_class="URBAN_PAVED",
                planned_work_start_on="2026-09-15",
                planned_work_end_on="2026-09-20",
            ),
            headers=engineer_headers,
        ),
        201,
    )
    after_segment = fx.route_version(route["id"])
    assert after_segment == at_create + 1

    validate_success(
        api.adjust_route_budget(
            route["id"],
            budget_adjustment_payload(1000, reason="rounding reserve"),
            headers=admin_headers,
        )
    )
    after_budget = fx.route_version(route["id"])
    assert after_budget == after_segment + 1

    walkout = validate_success(
        api.create_walkout(
            create_walkout_payload(
                segment["id"],
                walked_on="2026-08-11",
                obstruction_count=0,
                conduit_available_confirmed=False,
            ),
            headers=surveyor_headers,
        ),
        201,
    )
    validate_success(
        api.create_pole_observation(
            create_pole_observation_payload(walkout["id"], **_CLEAN_POLE),
            headers=surveyor_headers,
        ),
        201,
    )
    validate_success(api.submit_walkout(walkout["id"], headers=surveyor_headers))
    validate_success(
        api.review_walkout(
            walkout["id"], walkout_review_payload("ACCEPTED"), headers=engineer_headers
        )
    )

    locked = validate_success(api.lock_route_scope(route["id"], headers=engineer_headers))
    after_lock = locked["version"]
    assert after_lock == after_budget + 1

    selected = validate_success(
        api.select_construction_method(
            segment["id"],
            construction_method_payload("AERIAL", after_lock),
            headers=engineer_headers,
        )
    )
    assert selected["preliminary_cost_cents"] == 630870

    final = fx.read_route(route["id"])
    assert final["version"] == after_lock + 1
    assert final["total_preliminary_cost_cents"] == 630870
    assert selected["version"] >= 1, "the segment carries a counter of its own"
