"""Sealing a design revision.

Stamping runs three checks in a pinned order, and two of them are tested here at
their exact edges: the route-wide permit clearance check refuses a route with one
unpermitted leg, and the spare-fibre floor passes at precisely 2,000 basis points
and refuses the very next fibre.
"""

from test_helpers import USER_IDS, fixtures as fx, validate_error, validate_success
from test_helpers.assertions import assert_fiber_invariant, assert_spare_ratio_bp
from test_helpers.factories import return_to_draft_payload

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
_MUNICIPAL_WINDOW = {
    "authority_type": "MUNICIPAL_ROW",
    "authority_name": "City of Ridgefield DPW",
    "work_window_start_on": "2026-09-15",
    "work_window_end_on": "2026-09-25",
}


def _cleared_ridge_ring():
    """A PERMITTING ring route whose single 1250-foot segment is permit-CLEARED."""

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
    permit = fx.create_permit(segment["id"], **_MUNICIPAL_WINDOW)
    fx.submit_permit(permit["id"])
    fx.review_permit(permit["id"], "APPROVED", decision_note="aerial attachment approved")
    return {"route_id": route["id"], "segment_id": segment["id"], "permit_id": permit["id"]}


def _design_in_review_dropping(drops, engineer, allocated=240, express=40):
    """A 240/40 package in review holding one handhole per entry in ``drops``.

    ``drops`` maps a station in feet to the fibre count dropped there, so the
    caller controls the reserve — and therefore ``spare_ratio_bp`` — to the fibre.
    """
    built = _cleared_ridge_ring()
    design = fx.create_design(
        built["route_id"], fiber_count_allocated=allocated, express_fiber_count=express
    )
    for station, dropped in drops:
        fx.place_splice_point(
            design["id"],
            built["segment_id"],
            station_feet=station,
            enclosure_type="HANDHOLE",
            fiber_count_dropped=dropped,
        )
    built["design"] = fx.submit_design(design["id"], headers=engineer)
    built["design_id"] = design["id"]
    return built


_FOUR_HANDHOLES_AT_THE_FLOOR = ((0, 38), (250, 38), (500, 38), (750, 38))
_FOUR_HANDHOLES_ONE_FIBRE_OVER = ((0, 38), (250, 38), (500, 38), (750, 39))


def test_a_spare_ratio_of_exactly_two_thousand_basis_points_may_be_stamped(
    api, engineer_headers, engineer_alt_headers
):
    """152 dropped fibres of a 240-fibre cable leave the reserve exactly at the floor.

    PRD: "A ratio of exactly 2,000 basis points passes; anything below is refused
    with `ERR_SPARE_RATIO_BELOW_MINIMUM`."

    Design: Difficulty/boundary_precision_check/spare_fiber_ratio_exactly_at_minimum_passes_stamp
    """
    built = _design_in_review_dropping(_FOUR_HANDHOLES_AT_THE_FLOOR, engineer_headers)
    in_review = built["design"]
    assert in_review["status"] == "IN_REVIEW"
    assert in_review["assigned_drop_fiber_count"] == 152
    assert in_review["reserve_fiber_count"] == 48
    assert in_review["spare_ratio_bp"] == 2000
    assert_fiber_invariant(in_review)
    assert_spare_ratio_bp(in_review)

    stamped = validate_success(
        api.stamp_design_package(built["design_id"], headers=engineer_alt_headers)
    )
    assert stamped["status"] == "STAMPED"
    assert stamped["stamped_by_user_id"] == USER_IDS["route_engineer_second"]
    assert stamped["stamped_at"] == "2026-08-10T00:00:00Z"
    assert stamped["stamp_voided_at"] is None
    assert stamped["splice_point_count"] == 4
    assert stamped["handhole_count"] == 4


def test_stamping_at_the_floor_carries_the_whole_route_to_construction_ready(
    api, engineer_headers, engineer_alt_headers
):
    """With every segment cleared, the stamp is the event that completes the route.

    PRD: "Finally, if every segment on the route now stands at `CLEARED`, the route
    advances `PERMITTING → CONSTRUCTION_READY`."

    Design: Difficulty/boundary_precision_check/spare_fiber_ratio_exactly_at_minimum_passes_stamp
    """
    built = _design_in_review_dropping(_FOUR_HANDHOLES_AT_THE_FLOOR, engineer_headers)
    before = fx.read_route(built["route_id"])
    assert before["status"] == "PERMITTING"
    assert fx.read_segment(built["segment_id"])["permit_status"] == "CLEARED"

    validate_success(api.stamp_design_package(built["design_id"], headers=engineer_alt_headers))

    assert fx.read_route(built["route_id"])["status"] == "CONSTRUCTION_READY"


def test_dropping_one_more_fibre_falls_below_the_floor_and_blocks_the_stamp(
    api, engineer_headers, engineer_alt_headers
):
    """153 dropped fibres give 1958 basis points, and 1958 is not enough.

    PRD: "Third, the **spare-fibre floor**: the package's `spare_ratio_bp` must be
    at least 2,000 basis points, meaning at least twenty percent of the allocated
    cable must remain in the future-customer reserve after express fibre and all
    placed drops are accounted for."

    Design: Difficulty/boundary_precision_check/spare_fiber_ratio_exactly_at_minimum_passes_stamp
    """
    built = _design_in_review_dropping(_FOUR_HANDHOLES_ONE_FIBRE_OVER, engineer_headers)
    in_review = built["design"]
    assert in_review["assigned_drop_fiber_count"] == 153
    assert in_review["reserve_fiber_count"] == 47
    assert in_review["spare_ratio_bp"] == 1958

    response = api.stamp_design_package(built["design_id"], headers=engineer_alt_headers)
    validate_error(response, "ERR_SPARE_RATIO_BELOW_MINIMUM", 422)

    design = fx.read_design(built["design_id"])
    assert design["status"] == "IN_REVIEW"
    assert design["stamped_by_user_id"] is None
    assert design["stamped_at"] is None
    assert fx.read_route(built["route_id"])["status"] == "PERMITTING"


# ---------------------------------------------------------------------------
# One unpermitted leg is enough to stop the stamp
# ---------------------------------------------------------------------------


def _twin_leg_ring_with_one_permitted_leg(engineer):
    """A two-segment ring route where only the first leg has a permit on file."""

    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(
        name="Twin Leg Ring",
        topology_objective="RING_CLOSURE",
        target_in_service_date="2027-03-01",
        budget_authorized_cents=250000000,
    )
    leg_one = fx.create_segment(route["id"], **_RIDGE_AVE_1250)
    leg_two = fx.create_segment(
        route["id"],
        sequence_index=2,
        street_name="Quarry Lane",
        municipality_code="MUN-014",
        length_feet=400,
        terrain_class="URBAN_UNPAVED",
        planned_work_start_on="2026-09-26",
        planned_work_end_on="2026-10-02",
        existing_conduit_available=False,
    )
    fx.accepted_walkout(
        leg_one["id"],
        [_GRADE_A_POLE],
        walked_on="2026-08-11",
        obstruction_count=0,
        conduit_available_confirmed=False,
        surveyor_note="clear aerial span, no obstructions",
    )
    fx.accepted_walkout(
        leg_two["id"],
        [
            {
                "pole_tag": "P-601",
                "pole_owner": "MUNICIPAL_LIGHT",
                "condition_grade": "B",
                "available_vertical_clearance_in": 44,
                "existing_attachment_count": 1,
            }
        ],
        walked_on="2026-08-11",
        obstruction_count=0,
        conduit_available_confirmed=False,
        surveyor_note="unpaved shoulder, one light pole",
    )
    fx.lock_scope(route["id"])

    permit = fx.create_permit(leg_one["id"], **_MUNICIPAL_WINDOW)
    fx.submit_permit(permit["id"])
    fx.review_permit(permit["id"], "APPROVED", decision_note="leg one approved")

    design = fx.create_design(route["id"], fiber_count_allocated=288, express_fiber_count=48)
    for station in (0, 250):
        fx.place_splice_point(
            design["id"],
            leg_one["id"],
            station_feet=station,
            enclosure_type="HANDHOLE",
            fiber_count_dropped=24,
        )
    submitted = fx.submit_design(design["id"], headers=engineer)
    return {
        "route_id": route["id"],
        "leg_one_id": leg_one["id"],
        "leg_two_id": leg_two["id"],
        "design_id": design["id"],
        "design": submitted,
    }


def test_a_single_unpermitted_segment_refuses_the_stamp_for_the_whole_route(
    api, engineer_headers, engineer_alt_headers
):
    """The second leg has no permit at all, so it sits at NOT_REQUIRED and blocks.

    PRD: "One segment at `NOT_REQUIRED`, `PENDING` or `BLOCKED` refuses the stamp
    with `ERR_PERMIT_NOT_CLEARED`."

    Design: Difficulty/cross_entity_state_dependency/design_stamp_requires_every_segment_permit_cleared
    """
    built = _twin_leg_ring_with_one_permitted_leg(engineer_headers)
    assert fx.read_segment(built["leg_one_id"])["permit_status"] == "CLEARED"
    assert fx.read_segment(built["leg_two_id"])["permit_status"] == "NOT_REQUIRED"

    response = api.stamp_design_package(built["design_id"], headers=engineer_alt_headers)
    validate_error(response, "ERR_PERMIT_NOT_CLEARED", 422)


def test_the_clearance_refusal_is_not_the_spare_fibre_floor_in_disguise(
    api, engineer_headers, engineer_alt_headers
):
    """The package has 6667 basis points of reserve, well clear of the 2000 floor.

    PRD: "Second, **route-wide permit clearance**: every segment whose `route_id`
    matches the package's `route_id` must stand at `CLEARED` in its permit
    dimension."

    Design: Difficulty/cross_entity_state_dependency/design_stamp_requires_every_segment_permit_cleared
    """
    built = _twin_leg_ring_with_one_permitted_leg(engineer_headers)
    in_review = built["design"]
    assert in_review["status"] == "IN_REVIEW"
    assert in_review["spare_ratio_bp"] == 6667
    assert in_review["spare_ratio_bp"] > 2000

    refusal = api.stamp_design_package(built["design_id"], headers=engineer_alt_headers)
    assert refusal.status_code == 422, f"expected a 422 refusal, got {refusal.status_code}"

    design = fx.read_design(built["design_id"])
    assert design["status"] == "IN_REVIEW"
    assert design["stamped_by_user_id"] is None
    assert design["stamped_at"] is None
    assert design["submitted_by_user_id"] == USER_IDS["route_engineer"]

    assert fx.read_route(built["route_id"])["status"] == "PERMITTING"


# ---------------------------------------------------------------------------
# The status gate, the peer-review round trip, and the individual-level bar
# ---------------------------------------------------------------------------

_HARBOR_LOOP = {
    "name": "Harbor Loop",
    "topology_objective": "RING_CLOSURE",
    "target_in_service_date": "2027-03-01",
    "budget_authorized_cents": 250000000,
}
_INLAND_SPUR = {
    "name": "Inland Spur",
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
    "existing_conduit_available": False,
}


def _locked_route_with_a_placed_draft(route_spec, cleared=False, submitter=None):
    """A 288/48 draft design holding one handhole, on a route that may be permitted."""

    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(**route_spec)
    segment = fx.create_segment(route["id"], **_DOCK_STREET_400)
    fx.accepted_walkout(
        segment["id"],
        [_GRADE_A_POLE],
        walked_on="2026-08-11",
        obstruction_count=0,
        conduit_available_confirmed=False,
        surveyor_note="clear aerial span, no obstructions",
    )
    fx.lock_scope(route["id"])
    if cleared:
        fx.cleared_segment_permit(
            segment["id"],
            authority_type="MUNICIPAL_ROW",
            authority_name="City of Ridgefield DPW",
            work_window_start_on="2026-09-15",
            work_window_end_on="2026-09-20",
        )
    design = fx.create_design(route["id"], fiber_count_allocated=288, express_fiber_count=48)
    fx.place_splice_point(
        design["id"],
        segment["id"],
        station_feet=0,
        enclosure_type="HANDHOLE",
        fiber_count_dropped=24,
    )
    built = {
        "route_id": route["id"],
        "segment_id": segment["id"],
        "design_id": design["id"],
    }
    if submitter is not None:
        built["design"] = fx.submit_design(design["id"], headers=submitter)
    return built


def test_a_draft_design_cannot_be_stamped_and_the_status_gate_reports_first(
    api, engineer_alt_headers
):
    """No segment is cleared either, yet the answer is about the package's own status.

    PRD: "Stamping is the act that seals a design, and it is guarded by three checks
    that fire in a fixed order after the status gate has confirmed the package is at
    `IN_REVIEW`."

    Design: Corner/state_machines/design_stamp_from_draft_returns_invalid_design_state
    """
    built = _locked_route_with_a_placed_draft(_HARBOR_LOOP)
    assert fx.read_design(built["design_id"])["status"] == "DRAFT"
    assert fx.read_segment(built["segment_id"])["permit_status"] == "NOT_REQUIRED"

    premature = api.stamp_design_package(built["design_id"], headers=engineer_alt_headers)
    validate_error(premature, "ERR_INVALID_DESIGN_STATE", 409)

    design = fx.read_design(built["design_id"])
    assert design["status"] == "DRAFT"
    assert design["stamped_by_user_id"] is None
    assert design["stamped_at"] is None
    assert fx.read_route(built["route_id"])["status"] == "SCOPE_LOCKED"
    assert fx.read_segment(built["segment_id"])["permit_status"] == "NOT_REQUIRED"


def test_a_cleared_route_still_waits_for_the_stamp_before_it_is_construction_ready(
    api, engineer_headers, engineer_alt_headers
):
    """Permit clearance alone does not advance the route; the stamp is the trigger.

    PRD: "Finally, if every segment on the route now stands at `CLEARED`, the route
    advances `PERMITTING → CONSTRUCTION_READY`."

    Design: Corner/state_machines/route_reaches_construction_ready_only_once_a_design_is_stamped
    """
    built = _locked_route_with_a_placed_draft(
        _INLAND_SPUR, cleared=True, submitter=engineer_headers
    )
    assert fx.read_segment(built["segment_id"])["permit_status"] == "CLEARED"
    assert fx.read_route(built["route_id"])["status"] == "PERMITTING", (
        "every segment is cleared, and that is still not sufficient"
    )

    stamped = validate_success(
        api.stamp_design_package(built["design_id"], headers=engineer_alt_headers)
    )
    assert stamped["status"] == "STAMPED"
    assert stamped["stamped_by_user_id"] == USER_IDS["route_engineer_second"]
    assert stamped["stamped_at"] == "2026-08-10T00:00:00Z"
    assert stamped["stamp_voided_at"] is None
    assert stamped["submitted_by_user_id"] == USER_IDS["route_engineer"]

    assert fx.read_route(built["route_id"])["status"] == "CONSTRUCTION_READY"
    segment = fx.read_segment(built["segment_id"])
    assert segment["permit_status"] == "CLEARED"
    assert segment["engineering_status"] == "WALKED"


def test_sending_a_package_back_to_draft_needs_a_note_and_resets_the_submitter(
    api, engineer_headers, engineer_alt_headers
):
    """An empty body is refused, and the accepted return nulls the submitter.

    PRD: "The return requires the package at `IN_REVIEW`, moves it `IN_REVIEW →
    DRAFT`, stores the text in `return_note`, and **clears `submitted_by_user_id`
    back to null** so that whoever resubmits the edited package becomes the new
    submitter of record — which in turn changes who is barred from stamping it."

    Design: Corner/endpoints/return_to_draft_requires_a_note_and_clears_the_submitter
    """
    built = _locked_route_with_a_placed_draft(_HARBOR_LOOP, submitter=engineer_headers)
    assert built["design"]["status"] == "IN_REVIEW"
    assert built["design"]["submitted_by_user_id"] == USER_IDS["route_engineer"]

    noteless = api.return_design_to_draft(built["design_id"], headers=engineer_alt_headers)
    validate_error(noteless, "ERR_INVALID_REQUEST", 400)
    assert fx.read_design(built["design_id"])["status"] == "IN_REVIEW"

    returned = validate_success(
        api.return_design_to_draft(
            built["design_id"],
            return_to_draft_payload("add a second handhole at station 300"),
            headers=engineer_alt_headers,
        )
    )
    assert returned["status"] == "DRAFT"
    assert returned["return_note"] == "add a second handhole at station 300"
    assert returned["submitted_by_user_id"] is None

    design = fx.read_design(built["design_id"])
    assert design["splice_point_count"] == 1
    assert design["reserve_fiber_count"] == 216
    assert_fiber_invariant(design)
    assert_spare_ratio_bp(design)


def test_the_engineer_who_submitted_a_package_may_not_seal_it(
    api, engineer_headers, engineer_alt_headers
):
    """Both parties are route engineers, so the bar is on the individual.

    PRD: "First, **segregation of duties**: the stamping engineer's `X-User-ID` must
    differ from the package's `submitted_by_user_id`. An engineer who submitted a
    package may not stamp their own work, and the attempt is refused with
    `ERR_SEGREGATION_OF_DUTIES` and HTTP 403."

    Design: Corner/rbac/design_stamp_by_the_submitting_engineer_returns_segregation_of_duties
    """
    built = _locked_route_with_a_placed_draft(
        _INLAND_SPUR, cleared=True, submitter=engineer_headers
    )

    own_work = api.stamp_design_package(built["design_id"], headers=engineer_headers)
    validate_error(own_work, "ERR_SEGREGATION_OF_DUTIES", 403)

    untouched = fx.read_design(built["design_id"])
    assert untouched["status"] == "IN_REVIEW"
    assert untouched["stamped_by_user_id"] is None
    assert untouched["stamped_at"] is None
    assert fx.read_route(built["route_id"])["status"] == "PERMITTING"

    peer_stamped = validate_success(
        api.stamp_design_package(built["design_id"], headers=engineer_alt_headers)
    )
    assert peer_stamped["status"] == "STAMPED"
    assert peer_stamped["stamped_by_user_id"] == USER_IDS["route_engineer_second"]
    assert peer_stamped["stamped_at"] == "2026-08-10T00:00:00Z"
    assert fx.read_route(built["route_id"])["status"] == "CONSTRUCTION_READY"
