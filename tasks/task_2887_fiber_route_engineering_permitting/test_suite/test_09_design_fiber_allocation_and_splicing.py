"""Placing and unplacing enclosures inside a design revision.

Two independent things are being tested. The spacing buffer is an inclusive
boundary: 250 feet apart is legal and 249 is not, and the difference has to be
exact. And voiding a placed enclosure is a compensating action that must return
the dropped fibres to the reserve without leaving a single fibre behind.
"""

from test_helpers import (
    USER_IDS,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import assert_fiber_invariant, assert_spare_ratio_bp
from test_helpers.factories import create_design_package_payload, create_splice_point_payload

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
_GRADE_A_POLE = {
    "pole_tag": "P-001",
    "pole_owner": "TELCO",
    "condition_grade": "A",
    "available_vertical_clearance_in": 48,
    "existing_attachment_count": 2,
}


def _draft_design_with_a_head_splice():
    """A 288/48 draft design on a locked route, holding one handhole at station 0."""

    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(**_RIDGE_RING)
    segment = fx.create_segment(route["id"], **_RIDGE_AVE_1250)
    fx.accepted_walkout(
        segment["id"],
        [_GRADE_A_POLE],
        walked_on="2026-08-11",
        obstruction_count=0,
        conduit_available_confirmed=False,
        surveyor_note="clear aerial span, no obstructions",
    )
    fx.lock_scope(route["id"])
    design = fx.create_design(route["id"], fiber_count_allocated=288, express_fiber_count=48)
    head = fx.place_splice_point(
        design["id"],
        segment["id"],
        station_feet=0,
        enclosure_type="HANDHOLE",
        fiber_count_dropped=24,
    )
    return {
        "route_id": route["id"],
        "segment_id": segment["id"],
        "design_id": design["id"],
        "design_at_create": design,
        "head_splice_id": head["id"],
    }


def test_two_enclosures_exactly_two_hundred_fifty_feet_apart_are_permitted(
    api, engineer_headers
):
    """Station 250 against a sibling at station 0 is the inclusive edge of the buffer.

    PRD: "the rejection is for an absolute station separation strictly less than
    250 feet, so two enclosures exactly 250 feet apart are permitted while 249
    feet apart is refused with `ERR_SPLICE_SPACING_VIOLATION`"

    Design: Difficulty/resource_temporal_overlap/splice_point_station_buffer_equality_allowed_and_inside_rejected
    """
    built = _draft_design_with_a_head_splice()

    placed = validate_success(
        api.create_splice_point(
            create_splice_point_payload(
                built["design_id"],
                built["segment_id"],
                station_feet=250,
                enclosure_type="HANDHOLE",
                fiber_count_dropped=24,
            ),
            headers=engineer_headers,
        ),
        201,
    )
    assert placed["station_feet"] == 250
    assert placed["status"] == "PLACED"
    assert placed["voided_at"] is None


def test_an_enclosure_two_hundred_forty_nine_feet_from_a_sibling_is_refused(
    api, engineer_headers
):
    """Station 499 sits 249 feet from station 250 and is inside the buffer.

    PRD: "The **spacing buffer** requires the new enclosure to stand at least 250
    feet from every `PLACED` splice point that shares both its `design_id` and its
    `segment_id`"

    Design: Difficulty/resource_temporal_overlap/splice_point_station_buffer_equality_allowed_and_inside_rejected
    """
    built = _draft_design_with_a_head_splice()
    validate_success(
        api.create_splice_point(
            create_splice_point_payload(
                built["design_id"],
                built["segment_id"],
                station_feet=250,
                enclosure_type="HANDHOLE",
                fiber_count_dropped=24,
            ),
            headers=engineer_headers,
        ),
        201,
    )

    response = api.create_splice_point(
        create_splice_point_payload(
            built["design_id"],
            built["segment_id"],
            station_feet=499,
            enclosure_type="HANDHOLE",
            fiber_count_dropped=24,
        ),
        headers=engineer_headers,
    )
    validate_error(response, "ERR_SPLICE_SPACING_VIOLATION", 422)

    rows = validate_success(
        api.list_design_splice_points(built["design_id"], headers=engineer_headers)
    )
    assert len(rows) == 2
    assert sorted(row["station_feet"] for row in rows) == [0, 250]

    design = fx.read_design(built["design_id"])
    assert design["splice_point_count"] == 2
    assert design["handhole_count"] == 2
    assert design["assigned_drop_fiber_count"] == 48
    assert design["reserve_fiber_count"] == 192
    assert design["spare_ratio_bp"] == 6667
    assert_fiber_invariant(design)
    assert_spare_ratio_bp(design)


# ---------------------------------------------------------------------------
# Voiding gives the fibres back exactly
# ---------------------------------------------------------------------------


def test_voiding_a_splice_point_returns_every_dropped_fibre_to_the_reserve(
    api, engineer_headers
):
    """The reserve goes 240 to 216 to 240 again, and the ratio follows it back.

    PRD: "Voiding moves the splice point `PLACED → VOIDED`, which is terminal,
    stamps `voided_at` from the logical clock, returns the point's
    `fiber_count_dropped` from `assigned_drop_fiber_count` to
    `reserve_fiber_count`, re-derives `spare_ratio_bp`, `splice_point_count` and
    `handhole_count`, and increments the versions of both the splice point and its
    design package."

    Design: Difficulty/compensating_invariant/splice_point_void_restores_reserve_fiber_exactly
    """
    built = _draft_design_with_a_head_splice()
    at_create = built["design_at_create"]
    assert at_create["assigned_drop_fiber_count"] == 0
    assert at_create["reserve_fiber_count"] == 240
    assert at_create["spare_ratio_bp"] == 8333

    with_splice = fx.read_design(built["design_id"])
    assert with_splice["assigned_drop_fiber_count"] == 24
    assert with_splice["reserve_fiber_count"] == 216
    assert with_splice["spare_ratio_bp"] == 7500

    voided = validate_success(
        api.void_splice_point(built["head_splice_id"], headers=engineer_headers)
    )
    assert voided["status"] == "VOIDED"
    assert voided["voided_at"] == "2026-08-10T00:00:00Z"

    design = fx.read_design(built["design_id"])
    assert design["assigned_drop_fiber_count"] == 0
    assert design["reserve_fiber_count"] == 240
    assert design["spare_ratio_bp"] == 8333
    assert design["splice_point_count"] == 0
    assert design["handhole_count"] == 0
    assert_fiber_invariant(design)
    assert_spare_ratio_bp(design)


def test_a_voided_splice_point_is_a_state_change_and_stays_in_the_listing(
    api, engineer_headers
):
    """The row survives the void; only the placed population feeds the rollups.

    PRD: "Every placement and every voiding re-derives the design package's five
    fibre rollups from the current population of `PLACED` splice points on that
    design."

    Design: Difficulty/compensating_invariant/splice_point_void_restores_reserve_fiber_exactly
    """
    built = _draft_design_with_a_head_splice()
    validate_success(api.void_splice_point(built["head_splice_id"], headers=engineer_headers))

    rows = validate_success(
        api.list_design_splice_points(built["design_id"], headers=engineer_headers)
    )
    assert len(rows) == 1, "voiding is a state change, not a delete"
    assert rows[0]["id"] == built["head_splice_id"]
    assert rows[0]["status"] == "VOIDED"
    assert rows[0]["fiber_count_dropped"] == 24

    design = fx.read_design(built["design_id"])
    assert design["fiber_count_allocated"] == 288
    assert (
        design["fiber_count_allocated"]
        == design["express_fiber_count"]
        + design["assigned_drop_fiber_count"]
        + design["reserve_fiber_count"]
    )
    assert design["express_fiber_count"] == 48
    assert design["assigned_drop_fiber_count"] == 0
    assert design["reserve_fiber_count"] == 240


# ---------------------------------------------------------------------------
# The fibre ceiling, the terminal void, and the empty placed population
# ---------------------------------------------------------------------------

_RAIL_YARD_600 = {
    "sequence_index": 1,
    "street_name": "Rail Yard Cut",
    "municipality_code": "MUN-014",
    "length_feet": 600,
    "terrain_class": "URBAN_PAVED",
    "planned_work_start_on": "2026-09-15",
    "planned_work_end_on": "2026-09-20",
    "existing_conduit_available": False,
}


def _locked_route_with_a_draft_design(segment_spec):
    """A SCOPE_LOCKED route carrying an empty 288/48 draft design revision."""

    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(**_RIDGE_RING)
    segment = fx.create_segment(route["id"], **segment_spec)
    fx.accepted_walkout(
        segment["id"],
        [_GRADE_A_POLE],
        walked_on="2026-08-11",
        obstruction_count=0,
        conduit_available_confirmed=False,
        surveyor_note="clear aerial span, no obstructions",
    )
    fx.lock_scope(route["id"])
    design = fx.create_design(route["id"], fiber_count_allocated=288, express_fiber_count=48)
    return {
        "route_id": route["id"],
        "segment_id": segment["id"],
        "design_id": design["id"],
        "design_at_create": design,
    }


def test_the_spare_ratio_rounds_a_repeating_third_half_up(api, engineer_headers):
    """192 reserve over 288 allocated is 6666.66 basis points and reports as 6667.

    PRD: "`spare_ratio_bp` is `reserve_fiber_count` multiplied by 10,000, divided by
    `fiber_count_allocated`, rounded half up to whole basis points."

    Design: Corner/calculations/spare_ratio_bp_rounds_half_up_to_6667
    """
    built = _draft_design_with_a_head_splice()

    placed = validate_success(
        api.create_splice_point(
            create_splice_point_payload(
                built["design_id"],
                built["segment_id"],
                station_feet=250,
                enclosure_type="CABINET",
                fiber_count_dropped=24,
            ),
            headers=engineer_headers,
        ),
        201,
    )
    assert placed["status"] == "PLACED"

    design = fx.read_design(built["design_id"])
    assert design["assigned_drop_fiber_count"] == 48
    assert design["reserve_fiber_count"] == 192
    assert design["spare_ratio_bp"] == 6667, "truncation would have reported 6666"
    assert design["splice_point_count"] == 2
    assert design["handhole_count"] == 1, "only the station-zero enclosure is a handhole"
    assert_fiber_invariant(design)
    assert_spare_ratio_bp(design)


def test_a_drop_that_would_push_the_reserve_below_zero_is_refused(api, engineer_headers):
    """With the reserve already exhausted, a further legal placement still fails.

    PRD: "The **fibre conservation** constraint requires that the drop not push the
    design's `reserve_fiber_count` below zero; a placement that would over-allocate
    the cable is refused with `ERR_FIBER_ALLOCATION_EXCEEDED` and writes nothing."

    Design: Corner/validations/splice_point_drop_beyond_the_reserve_returns_fiber_allocation_exceeded
    """
    built = _locked_route_with_a_draft_design(_RAIL_YARD_600)
    head = fx.place_splice_point(
        built["design_id"],
        built["segment_id"],
        station_feet=0,
        enclosure_type="CABINET",
        fiber_count_dropped=240,
    )
    exhausted = fx.read_design(built["design_id"])
    assert exhausted["reserve_fiber_count"] == 0
    assert exhausted["spare_ratio_bp"] == 0
    version_before = exhausted["version"]

    refused = api.create_splice_point(
        create_splice_point_payload(
            built["design_id"],
            built["segment_id"],
            station_feet=500,
            enclosure_type="HANDHOLE",
            fiber_count_dropped=24,
        ),
        headers=engineer_headers,
    )
    validate_error(refused, "ERR_FIBER_ALLOCATION_EXCEEDED", 422)

    design = fx.read_design(built["design_id"])
    assert design["splice_point_count"] == 1
    assert design["assigned_drop_fiber_count"] == 240
    assert design["version"] == version_before, "the refused placement left no trace"

    rows = validate_success(
        api.list_design_splice_points(built["design_id"], headers=engineer_headers)
    )
    assert len(rows) == 1
    assert rows[0]["id"] == head["id"]


def test_a_voided_enclosure_cannot_be_voided_a_second_time(api, engineer_headers):
    """The second void is refused, so the reserve is never credited twice.

    PRD: "It requires the splice point at `PLACED` — a second voiding is
    `ERR_INVALID_SPLICE_POINT_STATE` — and requires its owning design package to be
    at `DRAFT` or `IN_REVIEW`, since voiding work inside a stamped or superseded
    package would falsify a sealed drawing; from any other design status it is
    `ERR_INVALID_DESIGN_STATE`."

    Design: Corner/state_machines/splice_point_void_from_voided_returns_invalid_splice_point_state
    """
    built = _draft_design_with_a_head_splice()
    first = validate_success(
        api.void_splice_point(built["head_splice_id"], headers=engineer_headers)
    )
    assert first["status"] == "VOIDED"

    replay = api.void_splice_point(built["head_splice_id"], headers=engineer_headers)
    validate_error(replay, "ERR_INVALID_SPLICE_POINT_STATE", 409)

    splice = validate_success(
        api.list_design_splice_points(built["design_id"], headers=engineer_headers)
    )[0]
    assert splice["status"] == "VOIDED"
    assert splice["voided_at"] == first["voided_at"]

    design = fx.read_design(built["design_id"])
    assert design["reserve_fiber_count"] == 240, "credited exactly once"
    assert design["assigned_drop_fiber_count"] == 0
    assert design["splice_point_count"] == 0
    assert design["handhole_count"] == 0
    assert_fiber_invariant(design)


def test_a_package_whose_only_enclosure_was_voided_cannot_go_to_peer_review(
    api, engineer_headers
):
    """The gate counts placed enclosures, not the placement history.

    PRD: "Submitting a draft for peer review requires the package at `DRAFT` and
    requires it to hold at least one `PLACED` splice point; a package with none —
    whether because none was ever placed or because every one was voided — is refused
    with `ERR_DESIGN_HAS_NO_SPLICE_POINTS`."

    Design: Corner/errors/design_submit_for_review_with_no_placed_splice_points_returns_the_empty_collection_error
    """
    built = _draft_design_with_a_head_splice()
    voided = validate_success(
        api.void_splice_point(built["head_splice_id"], headers=engineer_headers)
    )
    assert voided["status"] == "VOIDED"
    assert voided["voided_at"] is not None
    assert fx.read_design(built["design_id"])["splice_point_count"] == 0

    refused = api.submit_design_for_review(built["design_id"], headers=engineer_headers)
    validate_error(refused, "ERR_DESIGN_HAS_NO_SPLICE_POINTS", 422)
    assert fx.read_design(built["design_id"])["status"] == "DRAFT"

    replacement = validate_success(
        api.create_splice_point(
            create_splice_point_payload(
                built["design_id"],
                built["segment_id"],
                station_feet=0,
                enclosure_type="CABINET",
                fiber_count_dropped=12,
            ),
            headers=engineer_headers,
        ),
        201,
    )
    assert replacement["station_feet"] == 0, (
        "the voided sibling no longer constrains the station-zero slot"
    )

    submitted = validate_success(
        api.submit_design_for_review(built["design_id"], headers=engineer_headers)
    )
    assert submitted["status"] == "IN_REVIEW"
    assert submitted["submitted_by_user_id"] == USER_IDS["route_engineer"]

    design = fx.read_design(built["design_id"])
    assert design["splice_point_count"] == 1
    assert design["handhole_count"] == 0
    assert design["assigned_drop_fiber_count"] == 12
    assert design["reserve_fiber_count"] == 228
    assert_fiber_invariant(design)


def test_a_design_created_from_a_stale_view_of_the_route_is_refused(
    api, engineer_headers, admin_headers
):
    """The refused create mints nothing, so the retry is still revision 1.

    PRD: "**`POST /design-packages`** — creating the next design revision on a route
    requires `expected_route_version` to equal that route's current `version`. A
    mismatch is `ERR_STALE_ROUTE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_route_version_on_design_create_returns_stale_route_version
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(**_RIDGE_RING)
    segment = fx.create_segment(route["id"], **_RIDGE_AVE_1250)
    fx.accepted_walkout(
        segment["id"],
        [_GRADE_A_POLE],
        walked_on="2026-08-11",
        obstruction_count=0,
        conduit_available_confirmed=False,
        surveyor_note="clear aerial span, no obstructions",
    )
    fx.lock_scope(route["id"])
    stale_version = fx.route_version(route["id"])

    fx.adjust_budget(route["id"], 500000, reason="supplemental authorization")
    fresh_version = fx.route_version(route["id"])
    assert fresh_version == stale_version + 1

    refused = api.create_design_package(
        create_design_package_payload(
            route["id"], stale_version, fiber_count_allocated=288, express_fiber_count=48
        ),
        headers=engineer_headers,
    )
    validate_error(refused, "ERR_STALE_ROUTE_VERSION", 412)

    rows, meta = validate_paginated(
        api.list_route_design_packages(route["id"], headers=engineer_headers)
    )
    assert rows == []
    assert meta["total_count"] == 0

    created = validate_success(
        api.create_design_package(
            create_design_package_payload(
                route["id"], fresh_version, fiber_count_allocated=288, express_fiber_count=48
            ),
            headers=engineer_headers,
        ),
        201,
    )
    assert created["revision"] == 1, (
        "the refused create never counted toward the revision sequence"
    )
    assert created["status"] == "DRAFT"
    assert created["assigned_drop_fiber_count"] == 0
    assert created["reserve_fiber_count"] == 240
    assert created["spare_ratio_bp"] == 8333
    assert fx.route_version(route["id"]) == fresh_version + 1
