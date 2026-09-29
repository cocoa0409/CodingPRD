"""Freezing a route's segment set.

Scope locking is the hinge of the whole workflow: it closes the segment set,
stamps the lock instant and computes the planned permitting-complexity index. The
tests here concentrate on the gates that guard that hinge and on the state a
refused lock must leave completely untouched.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    fixtures as fx,
    ids_of,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    create_design_package_payload,
    create_permit_application_payload,
    create_pole_attachment_application_payload,
    create_route_payload,
    create_segment_payload,
    create_splice_point_payload,
    create_walkout_payload,
)


def test_lock_scope_on_a_route_with_no_segments_is_refused(api, engineer_headers):
    """A route whose segment_count is exactly 0 cannot lock its scope.

    PRD: "Scope locking demands that the route be in `PLANNING`, that its
    `segment_count` be at least 1 — a route with no segments is
    `ERR_ROUTE_HAS_NO_SEGMENTS`"

    Design: Difficulty/boundary_precision_check/lock_scope_with_zero_segments_hits_empty_collection_boundary
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    route = validate_success(
        api.create_route(
            create_route_payload(
                name="Greenfield Ring",
                topology_objective="RING_CLOSURE",
                target_in_service_date="2027-09-01",
                budget_authorized_cents=50000000,
            ),
            headers=engineer_headers,
        ),
        201,
    )
    assert route["segment_count"] == 0

    response = api.lock_route_scope(route["id"], headers=engineer_headers)
    validate_error(response, "ERR_ROUTE_HAS_NO_SEGMENTS", 422)


def test_refused_empty_lock_leaves_both_complexity_indices_null(api, engineer_headers):
    """The empty-collection refusal writes nothing, so no division by zero happens.

    PRD: "The route is born in `PLANNING` with `segment_count` and
    `design_total_length_feet` at zero, `total_preliminary_cost_cents` and
    `total_bid_ready_cost_cents` at zero, `budget_committed_cents` at zero and
    `budget_available_cents` equal to the authorized figure, `scope_locked_at`
    null, and both complexity indices — `planned_complexity_index` and
    `live_complexity_index` — null."

    Design: Difficulty/boundary_precision_check/lock_scope_with_zero_segments_hits_empty_collection_boundary
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    route = validate_success(
        api.create_route(
            create_route_payload(
                name="Greenfield Ring",
                topology_objective="RING_CLOSURE",
                target_in_service_date="2027-09-01",
                budget_authorized_cents=50000000,
            ),
            headers=engineer_headers,
        ),
        201,
    )

    refusal = api.lock_route_scope(route["id"], headers=engineer_headers)
    assert refusal.status_code == 422, (
        f"An empty route must be refused rather than crash, got {refusal.status_code}"
    )

    after = validate_success(api.get_route(route["id"], headers=engineer_headers))
    assert after["status"] == "PLANNING"
    assert after["segment_count"] == 0
    assert after["scope_locked_at"] is None
    assert after["planned_complexity_index"] is None
    assert after["live_complexity_index"] is None


# ---------------------------------------------------------------------------
# Building the chain: derived fields, predecessors and sequence indexes
# ---------------------------------------------------------------------------

_HARBOR_LOOP = {
    "name": "Harbor Loop",
    "topology_objective": "RING_CLOSURE",
    "target_in_service_date": "2027-03-01",
    "budget_authorized_cents": 250000000,
}
_RAIL_YARD_CUT = {
    "sequence_index": 1,
    "street_name": "Rail Yard Cut",
    "municipality_code": "MUN-014",
    "length_feet": 600,
    "terrain_class": "RAIL_CROSSING",
    "planned_work_start_on": "2026-09-15",
    "planned_work_end_on": "2026-09-20",
}


def test_the_authority_class_is_derived_from_terrain_and_may_not_be_dictated(
    api, engineer_headers
):
    """A rail crossing implies RAILROAD, and naming the field in the body is a 400.

    PRD: "From it the system immediately derives `required_authority_type`, the
    permitting authority class that will have to be dealt with: paved urban,
    unpaved urban and rural shoulder terrain all fall to `MUNICIPAL_ROW`, a highway
    crossing falls to `STATE_HIGHWAY`, a rail crossing falls to `RAILROAD`, and a
    water crossing falls to `WATERWAY`."

    Design: Corner/entities/segment_computed_fields_are_derived_and_a_client_supplied_value_is_rejected
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(headers=engineer_headers, **_HARBOR_LOOP)

    dictated = api.create_segment(
        create_segment_payload(
            route["id"], required_authority_type="MUNICIPAL_ROW", **_RAIL_YARD_CUT
        ),
        headers=engineer_headers,
    )
    validate_error(dictated, "ERR_INVALID_REQUEST", 400)

    segment = validate_success(
        api.create_segment(
            create_segment_payload(route["id"], **_RAIL_YARD_CUT), headers=engineer_headers
        ),
        201,
    )
    assert segment["required_authority_type"] == "RAILROAD"
    assert segment["moratorium_class"] == "NONE"
    assert segment["restoration_cost_cents"] == 0
    assert segment["accepted_obstruction_count"] == 0
    assert segment["preliminary_cost_cents"] is None
    assert segment["bid_ready_cost_cents"] is None


def test_a_predecessor_belonging_to_another_route_is_a_mismatch_not_a_missing_row(
    api, engineer_headers
):
    """The self-reference is checked for ownership, so a valid foreign id is a 422.

    PRD: "When `predecessor_segment_id` is supplied non-null, the named segment must
    belong to the *same* route and must carry a `sequence_index` strictly lower than
    the new segment's; a predecessor on a different route, or one whose index is
    equal to or higher than the new segment's, is
    `ERR_PREDECESSOR_SEGMENT_MISMATCH`."

    Design: Corner/entities/segment_predecessor_on_another_route_returns_predecessor_segment_mismatch
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    route_a = fx.create_route(headers=engineer_headers, **_HARBOR_LOOP)
    route_b = fx.create_route(
        headers=engineer_headers,
        name="Inland Spur",
        topology_objective="SPUR",
        target_in_service_date="2027-06-01",
        budget_authorized_cents=90000000,
    )
    segment_a1 = fx.create_segment(route_a["id"], headers=engineer_headers)

    _MILL_STREET = {
        "sequence_index": 2,
        "street_name": "Mill Street",
        "municipality_code": "MUN-022",
        "length_feet": 300,
        "terrain_class": "URBAN_PAVED",
        "planned_work_start_on": "2026-10-05",
        "planned_work_end_on": "2026-10-09",
    }

    foreign = api.create_segment(
        create_segment_payload(
            route_b["id"], predecessor_segment_id=segment_a1["id"], **_MILL_STREET
        ),
        headers=engineer_headers,
    )
    validate_error(foreign, "ERR_PREDECESSOR_SEGMENT_MISMATCH", 422)

    rows, _meta = validate_paginated(
        api.list_route_segments(route_b["id"], headers=engineer_headers)
    )
    assert rows == []
    assert fx.read_route(route_b["id"])["segment_count"] == 0

    missing = api.create_segment(
        create_segment_payload(
            route_b["id"], predecessor_segment_id=NON_EXISTENT_UUID, **_MILL_STREET
        ),
        headers=engineer_headers,
    )
    validate_error(missing, "ERR_SEGMENT_NOT_FOUND", 404)


def test_a_predecessor_with_an_equal_or_higher_index_is_also_a_mismatch(
    api, engineer_headers
):
    """Order matters: the upstream segment must sit strictly lower on the chain.

    PRD: "When `predecessor_segment_id` is supplied non-null, the named segment must
    belong to the *same* route and must carry a `sequence_index` strictly lower than
    the new segment's; a predecessor on a different route, or one whose index is
    equal to or higher than the new segment's, is
    `ERR_PREDECESSOR_SEGMENT_MISMATCH`."

    Design: Corner/entities/segment_predecessor_on_another_route_returns_predecessor_segment_mismatch
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(headers=engineer_headers, **_HARBOR_LOOP)
    head = fx.create_segment(route["id"], headers=engineer_headers, sequence_index=5)

    backwards = api.create_segment(
        create_segment_payload(
            route["id"],
            sequence_index=3,
            street_name="Mill Street",
            municipality_code="MUN-014",
            length_feet=300,
            terrain_class="URBAN_PAVED",
            planned_work_start_on="2026-10-05",
            planned_work_end_on="2026-10-09",
            predecessor_segment_id=head["id"],
        ),
        headers=engineer_headers,
    )
    validate_error(backwards, "ERR_PREDECESSOR_SEGMENT_MISMATCH", 422)

    route_after = fx.read_route(route["id"])
    assert route_after["segment_count"] == 1
    assert route_after["design_total_length_feet"] == 400


def test_the_downstream_listing_walks_exactly_one_hop_along_the_chain(
    api, engineer_headers, admin_headers, surveyor_headers
):
    """On a three-link chain the head lists its successor only, and the tail nothing.

    PRD: "Two further inputs are optional: `predecessor_segment_id`, which names the
    immediately upstream segment on the same route and is null for the head segment,
    and `existing_conduit_available`, a boolean that defaults to false and records
    whether spare conduit is believed to run along the segment."

    Design: Corner/endpoints/downstream_segments_lists_only_the_direct_successor
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(headers=engineer_headers, **_HARBOR_LOOP)
    first = fx.create_segment(route["id"], headers=engineer_headers)
    second = fx.create_segment(
        route["id"],
        headers=engineer_headers,
        sequence_index=2,
        street_name="Orchard Road",
        municipality_code="MUN-014",
        length_feet=300,
        terrain_class="RURAL_SHOULDER",
        planned_work_start_on="2026-09-21",
        planned_work_end_on="2026-09-25",
        predecessor_segment_id=first["id"],
    )
    third = fx.create_segment(
        route["id"],
        headers=engineer_headers,
        sequence_index=3,
        street_name="Quarry Lane",
        municipality_code="MUN-014",
        length_feet=250,
        terrain_class="URBAN_UNPAVED",
        planned_work_start_on="2026-09-26",
        planned_work_end_on="2026-09-30",
        predecessor_segment_id=second["id"],
    )

    rows, meta = validate_paginated(
        api.list_downstream_segments(first["id"], headers=engineer_headers)
    )
    assert meta["total_count"] == 1
    assert ids_of(rows) == [second["id"]], "the transitively reachable third leg must not appear"

    rows, meta = validate_paginated(
        api.list_downstream_segments(second["id"], headers=admin_headers)
    )
    assert meta["total_count"] == 1
    assert ids_of(rows) == [third["id"]]

    rows, meta = validate_paginated(
        api.list_downstream_segments(third["id"], headers=surveyor_headers)
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False

    assert fx.read_segment(first["id"])["predecessor_segment_id"] is None
    route_after = fx.read_route(route["id"])
    assert route_after["segment_count"] == 3
    assert route_after["design_total_length_feet"] == 950


def test_a_sequence_index_is_unique_per_route_and_free_on_the_next_route(
    api, engineer_headers
):
    """Index 1 twice on one route is a 409; index 1 on a sibling route is a 201.

    PRD: "The `sequence_index` must be unused by any other segment on the same
    route; a collision is `ERR_SEQUENCE_INDEX_TAKEN`."

    Design: Corner/validations/sequence_index_reused_on_the_same_route_returns_sequence_index_taken
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    route_a = fx.create_route(headers=engineer_headers, **_HARBOR_LOOP)
    route_b = fx.create_route(
        headers=engineer_headers,
        name="Inland Spur",
        topology_objective="SPUR",
        target_in_service_date="2027-06-01",
        budget_authorized_cents=90000000,
    )
    first = fx.create_segment(route_a["id"], headers=engineer_headers)
    before = fx.read_route(route_a["id"])

    _ORCHARD_ROAD = {
        "sequence_index": 1,
        "street_name": "Orchard Road",
        "municipality_code": "MUN-014",
        "length_feet": 300,
        "terrain_class": "RURAL_SHOULDER",
        "planned_work_start_on": "2026-09-21",
        "planned_work_end_on": "2026-09-25",
    }

    collision = api.create_segment(
        create_segment_payload(route_a["id"], **_ORCHARD_ROAD), headers=engineer_headers
    )
    validate_error(collision, "ERR_SEQUENCE_INDEX_TAKEN", 409)

    unchanged = fx.read_route(route_a["id"])
    assert unchanged["segment_count"] == 1
    assert unchanged["design_total_length_feet"] == 400
    assert unchanged["version"] == before["version"]
    rows, _meta = validate_paginated(
        api.list_route_segments(route_a["id"], headers=engineer_headers)
    )
    assert ids_of(rows) == [first["id"]]

    accepted = validate_success(
        api.create_segment(
            create_segment_payload(route_b["id"], **_ORCHARD_ROAD), headers=engineer_headers
        ),
        201,
    )
    assert accepted["sequence_index"] == 1
    assert accepted["route_id"] == route_b["id"]
    route_b_after = fx.read_route(route_b["id"])
    assert route_b_after["segment_count"] == 1
    assert route_b_after["design_total_length_feet"] == 300


def test_one_still_draft_segment_refuses_the_lock_for_the_whole_route(
    api, engineer_headers, surveyor_headers
):
    """A walked first leg does not carry an unwalked second leg over the line.

    PRD: "A single still-`DRAFT` segment refuses the whole lock with
    `ERR_WALKOUT_NOT_ACCEPTED`."

    Design: Corner/validations/lock_scope_with_an_unwalked_segment_returns_walkout_not_accepted
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(headers=engineer_headers, **_HARBOR_LOOP)
    walked = fx.create_segment(route["id"], headers=engineer_headers)
    unwalked = fx.create_segment(
        route["id"],
        headers=engineer_headers,
        sequence_index=2,
        street_name="Orchard Road",
        municipality_code="MUN-014",
        length_feet=300,
        terrain_class="RURAL_SHOULDER",
        planned_work_start_on="2026-09-21",
        planned_work_end_on="2026-09-25",
    )
    fx.accepted_walkout(
        walked["id"],
        [fx.CLEAN_POLE],
        walked_on="2026-08-11",
        obstruction_count=0,
        conduit_available_confirmed=False,
        surveyor_note="first leg walked end to end",
    )

    refusal = api.lock_route_scope(route["id"], headers=engineer_headers)
    validate_error(refusal, "ERR_WALKOUT_NOT_ACCEPTED", 422)

    after = fx.read_route(route["id"])
    assert after["status"] == "PLANNING"
    assert after["scope_locked_at"] is None
    assert after["planned_complexity_index"] is None
    assert after["live_complexity_index"] is None
    assert fx.read_segment(walked["id"])["engineering_status"] == "WALKED"
    assert fx.read_segment(unwalked["id"])["engineering_status"] == "DRAFT"


def test_a_segment_added_after_the_lock_is_refused_and_the_lock_is_not_idempotent(
    api, engineer_headers
):
    """The closed segment set answers ERR_SCOPE_LOCKED, and a second lock is a state fault.

    PRD: "From that moment the segment set is closed: an attempt to add another
    segment to the route is refused with `ERR_SCOPE_LOCKED`."

    Design: Corner/errors/segment_create_after_lock_scope_returns_scope_locked
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(headers=engineer_headers, **_HARBOR_LOOP)
    first = fx.create_segment(route["id"], headers=engineer_headers)
    fx.accepted_walkout(
        first["id"],
        [fx.CLEAN_POLE],
        walked_on="2026-08-11",
        obstruction_count=0,
        conduit_available_confirmed=False,
        surveyor_note="single leg walked",
    )
    locked = fx.lock_scope(route["id"], headers=engineer_headers)
    assert locked["status"] == "SCOPE_LOCKED"
    assert locked["segment_count"] == 1
    assert locked["design_total_length_feet"] == 400

    late = api.create_segment(
        create_segment_payload(
            route["id"],
            sequence_index=2,
            street_name="Orchard Road",
            municipality_code="MUN-014",
            length_feet=300,
            terrain_class="RURAL_SHOULDER",
            planned_work_start_on="2026-09-21",
            planned_work_end_on="2026-09-25",
        ),
        headers=engineer_headers,
    )
    validate_error(late, "ERR_SCOPE_LOCKED", 409)

    frozen = fx.read_route(route["id"])
    assert frozen["segment_count"] == 1
    assert frozen["design_total_length_feet"] == 400
    assert frozen["version"] == locked["version"]
    rows, _meta = validate_paginated(
        api.list_route_segments(route["id"], headers=engineer_headers)
    )
    assert ids_of(rows) == [first["id"]]

    again = api.lock_route_scope(route["id"], headers=engineer_headers)
    validate_error(again, "ERR_INVALID_ROUTE_STATE", 409)
    assert fx.read_route(route["id"])["status"] == "SCOPE_LOCKED"


def test_every_new_row_lands_in_the_initial_state_its_narrative_declares(
    api, engineer_headers, surveyor_headers, coordinator_headers
):
    """Segment, walkout, attachment application, permit, design and splice at birth.

    PRD: "A new segment is born with `engineering_status` at `DRAFT`,
    `permit_status` at `NOT_REQUIRED`, `construction_method` null,
    `moratorium_class` at `NONE`, `restoration_cost_cents` at zero,
    `accepted_obstruction_count` at zero, and both `preliminary_cost_cents` and
    `bid_ready_cost_cents` null."

    PRD: "The application starts at `DRAFT` with `revision_round` at 0, `committed`
    false, `submitted_at` and `owner_note` null, and all five make-ready figures —
    `make_ready_items_subtotal_cents`, `make_ready_admin_fee_bp`,
    `make_ready_admin_fee_cents`, `make_ready_cost_cents` and `make_ready_days` —
    null."

    Design: Corner/state_machines/every_entity_is_created_in_its_declared_initial_state
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(headers=engineer_headers, **_HARBOR_LOOP)
    segment = validate_success(
        api.create_segment(create_segment_payload(route["id"]), headers=engineer_headers), 201
    )
    assert segment["engineering_status"] == "DRAFT"
    assert segment["permit_status"] == "NOT_REQUIRED"
    assert segment["construction_method"] is None

    walkout = validate_success(
        api.create_walkout(create_walkout_payload(segment["id"]), headers=surveyor_headers), 201
    )
    assert walkout["status"] == "OPEN"
    assert walkout["review_round"] == 0
    assert walkout["worst_pole_condition_grade"] == "NONE"
    assert walkout["make_ready_flagged_pole_count"] == 0

    fx.add_pole_observation(walkout["id"], headers=surveyor_headers, **fx.CLEAN_POLE)
    fx.submit_walkout(walkout["id"], headers=surveyor_headers)
    fx.review_walkout(walkout["id"], "ACCEPTED", headers=engineer_headers)
    locked = fx.lock_scope(route["id"], headers=engineer_headers)

    application = validate_success(
        api.create_pole_attachment_application(
            create_pole_attachment_application_payload(
                segment["id"], pole_owner="TELCO", pole_count=4
            ),
            headers=coordinator_headers,
        ),
        201,
    )
    assert application["status"] == "DRAFT"
    assert application["submitted_at"] is None
    assert application["revision_round"] == 0
    assert application["committed"] is False
    assert application["make_ready_cost_cents"] is None

    permit = validate_success(
        api.create_permit_application(
            create_permit_application_payload(
                segment["id"],
                authority_type="MUNICIPAL_ROW",
                authority_name="City of Ridgefield DPW",
                work_window_start_on="2026-09-15",
                work_window_end_on="2026-09-20",
            ),
            headers=coordinator_headers,
        ),
        201,
    )
    assert permit["status"] == "DRAFT"
    assert permit["submitted_at"] is None
    assert permit["review_days"] is None
    assert permit["decision_due_at"] is None
    assert permit["revision_round"] == 0
    assert permit["deemed"] is False

    design = validate_success(
        api.create_design_package(
            create_design_package_payload(
                route["id"],
                locked["version"],
                fiber_count_allocated=288,
                express_fiber_count=48,
            ),
            headers=engineer_headers,
        ),
        201,
    )
    assert design["status"] == "DRAFT"
    assert design["revision"] == 1
    assert design["assigned_drop_fiber_count"] == 0
    assert design["reserve_fiber_count"] == 240
    assert design["spare_ratio_bp"] == 8333

    splice = validate_success(
        api.create_splice_point(
            create_splice_point_payload(
                design["id"],
                segment["id"],
                station_feet=0,
                enclosure_type="HANDHOLE",
                fiber_count_dropped=24,
            ),
            headers=engineer_headers,
        ),
        201,
    )
    assert splice["status"] == "PLACED"
    assert splice["voided_at"] is None
