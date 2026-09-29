"""The two permitting-complexity indices on a route.

Both indices score the same route and both divide by the same segment count, but
they answer different questions. The planned index scores the authority mix the
terrain implies and is frozen at the lock. The live index scores the permits
actually on file, weighted by how badly each one is going, and moves on every
permit status change. On a mixed-authority route the two numbers diverge sharply.
"""

from test_helpers import fixtures as fx, validate_success
from test_helpers.factories import permit_review_payload

_TRIDENT_BACKBONE = {
    "name": "Trident Backbone",
    "topology_objective": "EXPRESS_BACKBONE",
    "target_in_service_date": "2027-06-01",
    "budget_authorized_cents": 400000000,
}

_SEGMENT_SPECS = (
    {
        "sequence_index": 1,
        "street_name": "Ridge Ave",
        "municipality_code": "MUN-014",
        "length_feet": 250,
        "terrain_class": "URBAN_PAVED",
        "planned_work_start_on": "2026-09-15",
        "planned_work_end_on": "2026-09-20",
        "existing_conduit_available": True,
    },
    {
        "sequence_index": 2,
        "street_name": "Depot Street",
        "municipality_code": "MUN-014",
        "length_feet": 300,
        "terrain_class": "RAIL_CROSSING",
        "planned_work_start_on": "2026-09-21",
        "planned_work_end_on": "2026-09-25",
        "existing_conduit_available": False,
    },
    {
        "sequence_index": 3,
        "street_name": "Highway 9 Shoulder",
        "municipality_code": "MUN-014",
        "length_feet": 400,
        "terrain_class": "HIGHWAY_CROSSING",
        "planned_work_start_on": "2026-09-26",
        "planned_work_end_on": "2026-10-02",
        "existing_conduit_available": False,
    },
)

_OBSERVATIONS = (
    {
        "pole_tag": "P-101",
        "pole_owner": "TELCO",
        "condition_grade": "A",
        "available_vertical_clearance_in": 48,
        "existing_attachment_count": 1,
    },
    {
        "pole_tag": "P-201",
        "pole_owner": "ELECTRIC_UTILITY",
        "condition_grade": "B",
        "available_vertical_clearance_in": 44,
        "existing_attachment_count": 3,
    },
    {
        "pole_tag": "P-301",
        "pole_owner": "MUNICIPAL_LIGHT",
        "condition_grade": "A",
        "available_vertical_clearance_in": 50,
        "existing_attachment_count": 0,
    },
)

_PERMIT_SPECS = (
    {
        "authority_type": "MUNICIPAL_ROW",
        "authority_name": "City of Ridgefield DPW",
        "work_window_start_on": "2026-09-15",
        "work_window_end_on": "2026-09-20",
    },
    {
        "authority_type": "RAILROAD",
        "authority_name": "Northern Line Railway",
        "work_window_start_on": "2026-09-21",
        "work_window_end_on": "2026-09-25",
    },
    {
        "authority_type": "STATE_HIGHWAY",
        "authority_name": "State DOT District 4",
        "work_window_start_on": "2026-09-26",
        "work_window_end_on": "2026-10-02",
    },
)


def _three_authority_route_with_three_filings():
    """A three-segment backbone route with one municipal, one rail and one highway
    permit all sitting under review.
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(**_TRIDENT_BACKBONE)
    segments = [fx.create_segment(route["id"], **spec) for spec in _SEGMENT_SPECS]
    for segment, observation in zip(segments, _OBSERVATIONS):
        fx.accepted_walkout(
            segment["id"],
            [observation],
            walked_on="2026-08-11",
            obstruction_count=0,
            conduit_available_confirmed=False,
            surveyor_note="leg walked and sketched",
        )
    locked = fx.lock_scope(route["id"])

    permits = []
    for segment, spec in zip(segments, _PERMIT_SPECS):
        permit = fx.create_permit(segment["id"], **spec)
        permits.append(fx.submit_permit(permit["id"]))

    return {
        "route_id": route["id"],
        "route_at_lock": locked,
        "segment_ids": [segment["id"] for segment in segments],
        "permit_ids": [permit["id"] for permit in permits],
    }


def test_the_planned_index_scores_the_terrain_mix_and_never_moves_again(
    api, coordinator_headers, engineer_headers, rail_reviewer_headers, highway_reviewer_headers
):
    """Municipal 10 plus railroad 40 plus highway 25 over three segments is 2500.

    PRD: "For a three-segment route made of one `URBAN_PAVED`, one `RAIL_CROSSING`
    and one `HIGHWAY_CROSSING` segment, the weights are 10, 40 and 25 for a sum of
    75, giving 7,500 centipoints over three segments and a
    `planned_complexity_index` of 2500."

    Design: Difficulty/dual_variant_calc/route_complexity_planned_versus_live_authority_mix
    """
    built = _three_authority_route_with_three_filings()
    at_lock = built["route_at_lock"]
    assert at_lock["planned_complexity_index"] == 2500
    assert at_lock["live_complexity_index"] == 2500, "the live index is seeded at the lock"

    validate_success(
        api.review_permit_application(
            built["permit_ids"][1],
            permit_review_payload(
                "DENIED", decision_note="flagging plan does not meet crossing standard"
            ),
            headers=rail_reviewer_headers,
        )
    )
    validate_success(
        api.review_permit_application(
            built["permit_ids"][2],
            permit_review_payload("APPROVED", decision_note="shoulder bore approved"),
            headers=highway_reviewer_headers,
        )
    )

    route = fx.read_route(built["route_id"])
    assert route["planned_complexity_index"] == 2500, (
        "two permit decisions must not disturb the planned figure"
    )
    assert route["segment_count"] == 3


def test_the_live_index_weights_each_filed_permit_by_how_badly_it_is_going(
    api, coordinator_headers, engineer_headers, rail_reviewer_headers, highway_reviewer_headers
):
    """A denial and an approval push the live index from 2500 to 3208.

    PRD: "The integer sum is 9,625, which over three segments gives 3,208.33 and a
    `live_complexity_index` of 3208."

    Design: Difficulty/dual_variant_calc/route_complexity_planned_versus_live_authority_mix
    """
    built = _three_authority_route_with_three_filings()

    validate_success(
        api.review_permit_application(
            built["permit_ids"][1],
            permit_review_payload(
                "DENIED", decision_note="flagging plan does not meet crossing standard"
            ),
            headers=rail_reviewer_headers,
        )
    )
    validate_success(
        api.review_permit_application(
            built["permit_ids"][2],
            permit_review_payload("APPROVED", decision_note="shoulder bore approved"),
            headers=highway_reviewer_headers,
        )
    )

    route = fx.read_route(built["route_id"])
    assert route["live_complexity_index"] == 3208
    assert route["live_complexity_index"] != route["planned_complexity_index"]
    assert route["status"] == "PERMITTING"

    assert fx.read_permit(built["permit_ids"][0])["status"] == "UNDER_REVIEW"
    statuses = [fx.read_segment(sid)["permit_status"] for sid in built["segment_ids"]]
    assert statuses == ["PENDING", "BLOCKED", "CLEARED"]


# ---------------------------------------------------------------------------
# The lock is where the planned index is born and the live index is seeded
# ---------------------------------------------------------------------------

_HARBOR_LOOP = {
    "name": "Harbor Loop",
    "topology_objective": "RING_CLOSURE",
    "target_in_service_date": "2027-03-01",
    "budget_authorized_cents": 250000000,
}
_MIXED_AUTHORITY_RING = {
    "name": "Mixed Authority Ring",
    "topology_objective": "RING_CLOSURE",
    "target_in_service_date": "2027-03-01",
    "budget_authorized_cents": 250000000,
}
_MIXED_AUTHORITY_SPUR = {
    "name": "Mixed Authority Spur",
    "topology_objective": "SPUR",
    "target_in_service_date": "2027-06-01",
    "budget_authorized_cents": 250000000,
}
_DOCK_STREET_400 = {
    "sequence_index": 1,
    "street_name": "Dock Street",
    "municipality_code": "MUN-014",
    "length_feet": 400,
    "terrain_class": "URBAN_PAVED",
    "planned_work_start_on": "2026-09-15",
    "planned_work_end_on": "2026-09-20",
}
_RAIL_YARD_CUT_600 = {
    "sequence_index": 2,
    "street_name": "Rail Yard Cut",
    "municipality_code": "MUN-014",
    "length_feet": 600,
    "terrain_class": "RAIL_CROSSING",
    "planned_work_start_on": "2026-09-21",
    "planned_work_end_on": "2026-09-25",
}
_CLEAN_POLE = {
    "pole_tag": "P-001",
    "pole_owner": "TELCO",
    "condition_grade": "B",
    "available_vertical_clearance_in": 45,
    "existing_attachment_count": 2,
}


def _walked_route(route_spec, segment_specs):
    """A PLANNING route whose every segment has an ACCEPTED walkout behind it."""

    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(**route_spec)
    segments = []
    for spec in segment_specs:
        segment = fx.create_segment(route["id"], **spec)
        fx.accepted_walkout(
            segment["id"],
            [dict(_CLEAN_POLE, pole_tag="P-%03d" % spec["sequence_index"])],
            walked_on="2026-08-11",
            obstruction_count=0,
            conduit_available_confirmed=False,
            surveyor_note="leg walked and sketched",
        )
        segments.append(segment)
    return {"route": route, "segments": segments}


def test_the_lock_writes_the_status_the_instant_and_both_indices_at_once(
    api, engineer_headers
):
    """One municipal leg weighs 10 points, which is 1000 centipoints over one segment.

    PRD: "On success the route moves `PLANNING → SCOPE_LOCKED`, `scope_locked_at` is
    stamped from the logical clock, the planned permitting-complexity index is
    computed and written to `planned_complexity_index`, `live_complexity_index` is
    seeded with that identical value, and the route's `version` increments."

    Design: Corner/state_machines/lock_scope_side_effects_stamp_the_instant_and_seed_the_live_complexity_index
    """
    built = _walked_route(_HARBOR_LOOP, (_DOCK_STREET_400,))
    before = fx.read_route(built["route"]["id"])
    assert before["status"] == "PLANNING"
    assert before["planned_complexity_index"] is None
    assert before["live_complexity_index"] is None

    locked = validate_success(
        api.lock_route_scope(built["route"]["id"], headers=engineer_headers)
    )
    assert locked["status"] == "SCOPE_LOCKED"
    assert locked["scope_locked_at"] == "2026-08-10T00:00:00Z"
    assert locked["planned_complexity_index"] == 1000
    assert locked["live_complexity_index"] == 1000, (
        "seeded from the planned variant even though no permit exists yet"
    )
    assert locked["segment_count"] == 1
    assert locked["design_total_length_feet"] == 400
    assert locked["version"] == before["version"] + 1


def test_the_lock_response_already_carries_what_a_later_read_reports(
    api, engineer_headers, coordinator_headers
):
    """The write computes both indices in its own transaction, not on the next read.

    PRD: "Except where a specific narrative in section 3 says otherwise, a write
    returns the created or modified resource in the envelope's `data` field; the
    clock-setting capability instead returns an object carrying `current_utc`."

    Design: Corner/consistency_model/lock_scope_response_already_carries_the_recomputed_complexity_indexes
    """
    built = _walked_route(_MIXED_AUTHORITY_RING, (_DOCK_STREET_400, _RAIL_YARD_CUT_600))

    written = validate_success(
        api.lock_route_scope(built["route"]["id"], headers=engineer_headers)
    )
    assert written["status"] == "SCOPE_LOCKED"
    assert written["planned_complexity_index"] == 2500, (
        "a municipal weight of 10 plus a railroad weight of 40, over two segments"
    )
    assert written["live_complexity_index"] == 2500
    assert written["scope_locked_at"] == "2026-08-10T00:00:00Z"

    read = validate_success(api.get_route(built["route"]["id"], headers=coordinator_headers))
    assert read["planned_complexity_index"] == written["planned_complexity_index"]
    assert read["live_complexity_index"] == written["live_complexity_index"]
    assert read["scope_locked_at"] == written["scope_locked_at"]
    assert read["status"] == "SCOPE_LOCKED"

    assert fx.read_segment(built["segments"][0]["id"])["required_authority_type"] == (
        "MUNICIPAL_ROW"
    )
    assert fx.read_segment(built["segments"][1]["id"])["required_authority_type"] == "RAILROAD"


def test_a_permit_still_in_draft_contributes_nothing_to_the_live_index(
    api, coordinator_headers, reviewer_headers
):
    """Three permits on file, and only the two that were actually filed are scored.

    PRD: "Its input set is every permit application whose `segment_id` belongs to a
    segment of this route and whose status is one of `UNDER_REVIEW`,
    `REVISION_REQUESTED`, `APPROVED` or `DENIED`; permits still in `DRAFT` are
    excluded."

    Design: Corner/calculations/live_complexity_index_excludes_draft_permit_applications
    """
    built = _walked_route(_MIXED_AUTHORITY_SPUR, (_DOCK_STREET_400, _RAIL_YARD_CUT_600))
    municipal_leg, rail_leg = built["segments"]
    locked = fx.lock_scope(built["route"]["id"])
    assert locked["planned_complexity_index"] == 2500

    municipal = fx.filed_permit(
        municipal_leg["id"],
        authority_type="MUNICIPAL_ROW",
        authority_name="City of Ridgefield DPW",
        work_window_start_on="2026-09-15",
        work_window_end_on="2026-09-20",
    )
    rail_filed = fx.filed_permit(
        rail_leg["id"],
        authority_type="RAILROAD",
        authority_name="Eastern Rail Holdings",
        work_window_start_on="2026-09-21",
        work_window_end_on="2026-09-25",
    )
    rail_draft = fx.create_permit(
        rail_leg["id"],
        authority_type="RAILROAD",
        authority_name="Eastern Rail Holdings",
        work_window_start_on="2026-10-01",
        work_window_end_on="2026-10-05",
    )

    validate_success(
        api.review_permit_application(
            municipal["id"],
            permit_review_payload("APPROVED", decision_note="approved as filed"),
            headers=reviewer_headers,
        )
    )

    assert fx.read_permit(rail_draft["id"])["status"] == "DRAFT"
    assert fx.read_permit(rail_filed["id"])["status"] == "UNDER_REVIEW"

    route = fx.read_route(built["route"]["id"])
    assert route["live_complexity_index"] == 2125, (
        "a term of 250 for the approved municipal row plus 4000 for the railroad "
        "under review, over two segments"
    )
    assert route["live_complexity_index"] != 4125, "the draft row is not scored"
    assert route["planned_complexity_index"] == 2500

    assert fx.read_segment(municipal_leg["id"])["permit_status"] == "CLEARED"
    assert fx.read_segment(rail_leg["id"])["permit_status"] == "PENDING"
