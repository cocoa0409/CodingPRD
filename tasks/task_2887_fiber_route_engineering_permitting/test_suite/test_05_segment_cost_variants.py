"""The two construction-cost variants that deliberately disagree.

A segment is priced twice over its life. The preliminary figure rounds the whole
length once; the bid-ready figure prices the segment in 100-foot station blocks
and rounds every block before summing them, then adds the obstruction surcharge,
the restoration obligation and the granted make-ready contribution. The gap
between the two numbers is the specification working, not a defect.
"""

from test_helpers import fixtures as fx, validate_success
from test_helpers.factories import (
    construction_method_payload,
    create_pole_observation_payload,
    create_route_payload,
    create_segment_payload,
    create_walkout_payload,
    walkout_review_payload,
)


def _walked_segment(
    api,
    engineer,
    surveyor,
    route_overrides,
    segment_overrides,
    walkout_overrides,
    observation_overrides,
):
    """One route, one segment, one ACCEPTED walkout: the segment is at WALKED."""

    fx.set_clock("2026-08-10T00:00:00Z")
    route = validate_success(
        api.create_route(create_route_payload(**route_overrides), headers=engineer), 201
    )
    segment = validate_success(
        api.create_segment(
            create_segment_payload(route["id"], **segment_overrides), headers=engineer
        ),
        201,
    )
    walkout = validate_success(
        api.create_walkout(
            create_walkout_payload(segment["id"], **walkout_overrides), headers=surveyor
        ),
        201,
    )
    validate_success(
        api.create_pole_observation(
            create_pole_observation_payload(walkout["id"], **observation_overrides),
            headers=surveyor,
        ),
        201,
    )
    validate_success(api.submit_walkout(walkout["id"], headers=surveyor))
    validate_success(
        api.review_walkout(walkout["id"], walkout_review_payload("ACCEPTED"), headers=engineer)
    )
    return {"route_id": route["id"], "segment_id": segment["id"]}


_RIDGE_RING = {
    "name": "Ridge Ring",
    "topology_objective": "RING_CLOSURE",
    "target_in_service_date": "2027-03-01",
    "budget_authorized_cents": 250000000,
}
_RIDGE_AVE_1250 = {
    "sequence_index": 1,
    "street_name": "Ridge Ave",
    "municipality_code": "MUN-014",
    "length_feet": 1250,
    "terrain_class": "URBAN_PAVED",
    "planned_work_start_on": "2026-09-15",
    "planned_work_end_on": "2026-09-25",
    "existing_conduit_available": False,
}
_CLEAR_WALK = {
    "walked_on": "2026-08-11",
    "obstruction_count": 0,
    "conduit_available_confirmed": False,
    "surveyor_note": "clear aerial span, no obstructions",
}
_GRADE_A_POLE = {
    "pole_tag": "P-001",
    "pole_owner": "TELCO",
    "condition_grade": "A",
    "available_vertical_clearance_in": 48,
    "existing_attachment_count": 2,
}


def _aerial_ridge_segment(api, engineer, surveyor):
    return _walked_segment(
        api, engineer, surveyor, _RIDGE_RING, _RIDGE_AVE_1250, _CLEAR_WALK, _GRADE_A_POLE
    )


def _bored_rural_segment(api, engineer, surveyor):
    built = _walked_segment(
        api,
        engineer,
        surveyor,
        {
            "name": "Rural Spur South",
            "topology_objective": "SPUR",
            "target_in_service_date": "2027-04-15",
            "budget_authorized_cents": 100000000,
        },
        {
            "sequence_index": 1,
            "street_name": "County Road 12",
            "municipality_code": "MUN-031",
            "length_feet": 1150,
            "terrain_class": "RURAL_SHOULDER",
            "planned_work_start_on": "2026-09-15",
            "planned_work_end_on": "2026-09-30",
            "existing_conduit_available": False,
        },
        {
            "walked_on": "2026-08-11",
            "obstruction_count": 1,
            "conduit_available_confirmed": False,
            "surveyor_note": "one culvert obstruction at station 400",
        },
        {
            "pole_tag": "P-401",
            "pole_owner": "MUNICIPAL_LIGHT",
            "condition_grade": "B",
            "available_vertical_clearance_in": 46,
            "existing_attachment_count": 1,
        },
    )
    version = validate_success(api.get_route(built["route_id"], headers=engineer))["version"]
    validate_success(
        api.select_construction_method(
            built["segment_id"],
            construction_method_payload("DIRECTIONAL_BORE", version),
            headers=engineer,
        )
    )
    return built


def test_one_segment_carries_two_cost_figures_six_cents_apart(
    api, engineer_headers, surveyor_headers
):
    """1250 aerial feet of urban paved street price at 1971469 and 1971475.

    PRD: "**Summing unrounded block values and rounding once at the end is
    forbidden and yields a different number.**"

    Design: Difficulty/dual_variant_calc/segment_cost_preliminary_versus_bid_ready_rounding_divergence
    """
    built = _aerial_ridge_segment(api, engineer_headers, surveyor_headers)
    version = validate_success(
        api.get_route(built["route_id"], headers=engineer_headers)
    )["version"]

    selected = validate_success(
        api.select_construction_method(
            built["segment_id"],
            construction_method_payload("AERIAL", version),
            headers=engineer_headers,
        )
    )
    assert selected["preliminary_cost_cents"] == 1971469
    assert selected["bid_ready_cost_cents"] is None

    locked = validate_success(
        api.request_bid_ready_estimate(built["segment_id"], headers=engineer_headers)
    )
    assert locked["bid_ready_cost_cents"] == 1971475
    assert locked["preliminary_cost_cents"] == 1971469
    assert locked["bid_ready_cost_cents"] - locked["preliminary_cost_cents"] == 6


def test_both_cost_variants_roll_up_separately_onto_the_route(
    api, engineer_headers, surveyor_headers
):
    """The route reports both totals, and neither overwrites the other.

    PRD: "The route's `total_preliminary_cost_cents` is the sum of
    `preliminary_cost_cents` across its segments and its
    `total_bid_ready_cost_cents` is the sum of `bid_ready_cost_cents` across its
    segments, in both cases counting a null child value as zero."

    Design: Difficulty/dual_variant_calc/segment_cost_preliminary_versus_bid_ready_rounding_divergence
    """
    built = _aerial_ridge_segment(api, engineer_headers, surveyor_headers)
    version = validate_success(
        api.get_route(built["route_id"], headers=engineer_headers)
    )["version"]
    validate_success(
        api.select_construction_method(
            built["segment_id"],
            construction_method_payload("AERIAL", version),
            headers=engineer_headers,
        )
    )
    validate_success(api.request_bid_ready_estimate(built["segment_id"], headers=engineer_headers))

    segment = validate_success(api.get_segment(built["segment_id"], headers=engineer_headers))
    assert segment["moratorium_class"] == "NONE"
    assert segment["restoration_cost_cents"] == 0
    assert segment["accepted_obstruction_count"] == 0
    assert segment["engineering_status"] == "DESIGN_LOCKED"

    route = validate_success(api.get_route(built["route_id"], headers=engineer_headers))
    assert route["total_preliminary_cost_cents"] == 1971469
    assert route["total_bid_ready_cost_cents"] == 1971475


def test_bid_ready_rounds_each_station_block_before_summing_them(
    api, engineer_headers, surveyor_headers
):
    """1150 bored feet give a block-wise subtotal of 4909212, not 4909206.

    PRD: "The construction subtotal is then the number of full blocks multiplied
    by one block's rounded cost, plus the leftover cost."

    Design: Difficulty/combinatorial_formula/bid_ready_station_block_rounding_order_pinned
    """
    built = _bored_rural_segment(api, engineer_headers, surveyor_headers)

    locked = validate_success(
        api.request_bid_ready_estimate(built["segment_id"], headers=engineer_headers)
    )
    assert locked["bid_ready_cost_cents"] == 5283212, (
        "The block-rounded construction subtotal is 11 * 426888 + 213444 == 4909212; "
        "rounding once over the whole 1150 feet gives 4909206 and a wrong total of 5283206"
    )
    block_subtotal = (
        locked["bid_ready_cost_cents"]
        - 75000 * locked["accepted_obstruction_count"]
        - locked["restoration_cost_cents"]
    )
    assert block_subtotal == 4909212
    assert block_subtotal == 11 * 426888 + 213444


def test_bid_ready_adds_the_surcharge_and_restoration_on_top_of_the_blocks(
    api, engineer_headers, surveyor_headers
):
    """The obstruction surcharge and the restoration obligation are extra terms.

    PRD: "The bid-ready figure is the construction subtotal plus the obstruction
    surcharge plus the restoration obligation plus the granted make-ready sum."

    Design: Difficulty/combinatorial_formula/bid_ready_station_block_rounding_order_pinned
    """
    built = _bored_rural_segment(api, engineer_headers, surveyor_headers)
    validate_success(api.request_bid_ready_estimate(built["segment_id"], headers=engineer_headers))

    segment = validate_success(api.get_segment(built["segment_id"], headers=engineer_headers))
    assert segment["moratorium_class"] == "NONE"
    assert segment["restoration_cost_cents"] == 299000
    assert segment["preliminary_cost_cents"] == 4909206
    assert segment["accepted_obstruction_count"] == 1
    assert segment["bid_ready_cost_cents"] == 5283212
    assert segment["engineering_status"] == "DESIGN_LOCKED"

    route = validate_success(api.get_route(built["route_id"], headers=engineer_headers))
    assert route["total_bid_ready_cost_cents"] == 5283212


_SLATE_ROAD_400 = {
    "sequence_index": 1,
    "street_name": "Slate Road",
    "municipality_code": "MUN-014",
    "length_feet": 400,
    "terrain_class": "URBAN_PAVED",
    "planned_work_start_on": "2026-09-15",
    "planned_work_end_on": "2026-09-20",
    "existing_conduit_available": False,
}


def test_an_aerial_build_owes_nothing_under_a_full_restoration_moratorium(
    api, engineer_headers, surveyor_headers
):
    """The window resolves onto the segment, yet the restoration obligation is zero.

    PRD: "An aerial build disturbs no pavement and therefore carries a restoration
    rate of 0 cents per foot under all three moratorium classes."

    Design: Corner/calculations/restoration_cost_is_zero_for_aerial_even_under_a_full_restoration_moratorium
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    fx.create_moratorium_window(
        municipality_code="MUN-014",
        street_name="Slate Road",
        resurfaced_on="2026-08-30",
        starts_on="2026-09-01",
        ends_on="2026-10-31",
        moratorium_class="FULL_RESTORATION",
        ordinance_reference="ORD-2026-114",
    )
    built = _walked_segment(
        api,
        engineer_headers,
        surveyor_headers,
        _RIDGE_RING,
        _SLATE_ROAD_400,
        _CLEAR_WALK,
        _GRADE_A_POLE,
    )
    version = validate_success(
        api.get_route(built["route_id"], headers=engineer_headers)
    )["version"]

    selected = validate_success(
        api.select_construction_method(
            built["segment_id"],
            construction_method_payload("AERIAL", version),
            headers=engineer_headers,
        )
    )
    assert selected["moratorium_class"] == "FULL_RESTORATION", (
        "the window covers this street and overlaps the planned work dates"
    )
    assert selected["restoration_cost_cents"] == 0
    assert selected["preliminary_cost_cents"] == 630870

    locked = validate_success(
        api.request_bid_ready_estimate(built["segment_id"], headers=engineer_headers)
    )
    assert locked["engineering_status"] == "DESIGN_LOCKED"
    assert locked["accepted_obstruction_count"] == 0
    assert locked["restoration_cost_cents"] == 0
    assert locked["bid_ready_cost_cents"] == 630872
    assert locked["preliminary_cost_cents"] == 630870

    route = validate_success(api.get_route(built["route_id"], headers=engineer_headers))
    assert route["total_bid_ready_cost_cents"] == 630872
    assert route["total_preliminary_cost_cents"] == 630870
